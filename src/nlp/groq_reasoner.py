"""
Penalaran berbasis Groq: memahami perintah user sebelum NLP aturan memproses.
Tanggung jawab: Person 3 (NLP & Intelligence Lead) — Sprint 3.10

Masalah yang diselesaikan:
- qwen3:4b (lokal) terlalu kecil untuk menalar perintah ambigu. "Saya ada
  kondangan tanggal X" diklasifikasi 'baca' padahal harusnya 'catat'.
- Tanggal mustahil ("32 Januari") lolos tanpa ditegur — user cuma ditanya
  ulang "Tanggal berapa?" tanpa tahu kenapa ditolak.

Solusi: pakai model Groq (20B-27B) sebagai "otak penalar". Groq dipanggil
HANYA saat aturan keyword tidak bisa memutuskan (akurasi keyword sudah >80%),
jadi latensi mayoritas perintah tidak bertambah.

Modul ini dipakai oleh:
- intent_classifier.py — sebagai fallback pengganti classify_intent_slm
- state_machine.py — untuk menjelaskan kenapa tanggal ditolak
"""
import json
import os
import re

from loguru import logger

VALID_AKSI = {"catat", "baca", "hapus", "reschedule", "reminder", "edit", "waktu"}

# Prompt yang sama dengan PROMPT_REKONSILIASI di ensemble.py — tapi tujuannya
# beda: di sini bukan memilih transkripsi, tapi MEMAHAMI maksud user.
INTENT_PROMPT = """Kamu menentukan MAKSUD user dari perintah suara Bahasa Indonesia
untuk AKIRA, asisten jadwal.

Perintah yang dikenali AKIRA:
- catat       : user ingin MEMBUAT jadwal baru, TERMASUK kalimat pernyataan
                "saya ada X tanggal Y", "besok aku ada Y jam Z"
- baca        : user ingin MELIHAT/menanyakan jadwal yang sudah ada
- hapus       : user ingin MENGHAPUS jadwal
- reschedule  : user ingin MEMINDAHKAN jadwal ke waktu lain
- edit        : user ingin MENGUBAH ISI jadwal (nama, catatan) tanpa pindah waktu
- reminder    : user ingin MENGATUR PENGINGAT sebelum jadwal
- waktu       : user menanyakan jam atau tanggal SEKARANG
- lain        : bukan perintah jadwal

PENTING:
- Kalimat "saya ada X", "aku punya X", "besok ada X" = user MEMBERITAHU
  jadwalnya, artinya CATAT, bukan BACA.
- "ada jadwal apa besok?" (bertanya) = BACA. "besok saya ada rapat" (memberitahu) = CATAT.
- Kalau ada tanggal yang mustahil (misal 32 Januari, 30 Februari), sebutkan
  di field "peringatan".

Balas HANYA JSON:
{"aksi": "<pilihan>", "peringatan": "<pesan singkat atau null>"}

Contoh:
"saya ada kondangan tanggal 5 Januari" -> {"aksi": "catat", "peringatan": null}
"besok saya ada meeting jam 3" -> {"aksi": "catat", "peringatan": null}
"cek jadwal besok" -> {"aksi": "baca", "peringatan": null}
"buatkan jadwal tanggal 32 Januari" -> {"aksi": "catat", "peringatan": "32 Januari tidak valid, Januari maksimal tanggal 31"}
"saya ada kondangan tanggal 32 Januari 2027" -> {"aksi": "catat", "peringatan": "32 Januari tidak valid"}
"halo apa kabar" -> {"aksi": "lain", "peringatan": null}

/no_think
"""

# Reuse infrastruktur model cadangan dari ensemble
_MODEL_BERHASIL = {}


def _daftar_model() -> list:
    """Model Groq untuk penalaran, urut dari paling cepat."""
    from src.stt.ensemble import MODEL_CADANGAN

    berhasil = _MODEL_BERHASIL.get("groq")
    cadangan = MODEL_CADANGAN.get("groq", [])
    if berhasil:
        return [berhasil] + [m for m in cadangan if m != berhasil]
    return list(cadangan)


def _panggil_groq(system_prompt: str, user_msg: str) -> str | None:
    """Panggil Groq LLM dengan fallback model."""
    import requests

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        logger.debug("GROQ_API_KEY kosong, Groq reasoner dilewati")
        return None

    for model in _daftar_model():
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0,
                    "max_tokens": 150,
                    "response_format": {"type": "json_object"},
                },
                timeout=8,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"].strip()
            _MODEL_BERHASIL["groq"] = model
            return raw
        except Exception as e:
            logger.debug(f"Groq model {model} gagal: {e}")
            continue

    logger.warning("Semua model Groq gagal untuk penalaran")
    return None


def classify_intent_groq(text: str) -> tuple[str | None, str | None]:
    """
    Klasifikasi intent menggunakan Groq.

    Return (aksi, peringatan).
    - aksi: salah satu VALID_AKSI, atau None kalau Groq juga gagal.
    - peringatan: pesan tentang data yang bermasalah (mis. tanggal mustahil),
      atau None kalau tidak ada masalah.
    """
    raw = _panggil_groq(INTENT_PROMPT, text)
    if not raw:
        return None, None

    try:
        parsed = json.loads(raw)
        aksi = (parsed.get("aksi") or "").strip().lower()
        peringatan = parsed.get("peringatan") or None

        if aksi == "lain":
            logger.info(f"Groq menilai '{text}' bukan perintah jadwal")
            return None, peringatan
        if aksi in VALID_AKSI:
            logger.info(f"Groq mengklasifikasi '{text}' sebagai '{aksi}'")
            return aksi, peringatan

        logger.warning(f"Groq balas aksi tidak dikenal: '{aksi}'")
        return None, peringatan
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning(f"Groq balas bukan JSON valid: '{raw[:80]}' ({e})")
        return None, None


# ---- Validasi tanggal ----

# Pola tanggal eksplisit: "tanggal 32 Januari", "32 Januari 2027"
_TANGGAL_EKSPLISIT = re.compile(
    r"\b(?:tanggal\s+)?(\d{1,2})\s+"
    r"(januari|februari|maret|april|mei|juni|juli|agustus|september|"
    r"oktober|november|desember)\b",
    re.IGNORECASE,
)

_MAX_HARI = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}

_BULAN_KE_ANGKA = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
    "september": 9, "oktober": 10, "november": 11, "desember": 12,
}


SAPAAN_PROMPT = """Kamu menentukan apakah sebuah kalimat DITUJUKAN kepada AKIRA,
asisten jadwal berbasis suara, dan apakah user MENGINGINKAN sesuatu darinya.

Konteks: mikrofon menyala terus di ruangan. Kebanyakan yang terdengar adalah
obrolan biasa yang TIDAK ditujukan ke AKIRA. Nama "AKIRA" sering salah
tertranskripsi jadi "Kira", "Akhirnya", "Akhir ya", "Akira", atau "Kira-kira".

Jawab true HANYA kalau KEDUANYA terpenuhi:
1. Kalimat menyapa/menyebut AKIRA (termasuk versi salah dengar di atas)
2. User meminta sesuatu — perintah, pertanyaan, atau permintaan bantuan

Jawab false kalau:
- Kalimat itu obrolan antar-orang yang kebetulan memuat kata mirip "akira"
- "akhirnya" dipakai sebagai kata keterangan biasa ("akhirnya selesai juga")
- Tidak ada permintaan apa pun, hanya menyebut nama

Balas HANYA JSON: {"untuk_akira": true/false, "alasan": "<singkat>"}

Contoh:
"Kira tolong bantu saya" -> {"untuk_akira": true, "alasan": "menyapa dan minta bantuan"}
"Akira, jadwal saya besok apa?" -> {"untuk_akira": true, "alasan": "pertanyaan jadwal"}
"Akhirnya bisa juga nih" -> {"untuk_akira": false, "alasan": "kata keterangan biasa"}
"kira-kira dia jadi datang nggak ya" -> {"untuk_akira": false, "alasan": "obrolan antar-orang"}
"Akira" -> {"untuk_akira": false, "alasan": "hanya menyebut nama, tidak minta apa-apa"}
"Kira aku butuh bantuan dong" -> {"untuk_akira": true, "alasan": "minta bantuan"}

/no_think
"""


def untuk_akira_groq(text: str) -> tuple[bool, str | None]:
    """
    Tanyakan ke Groq apakah kalimat ambient ditujukan kepada AKIRA.

    Dipakai HANYA saat pemeriksaan kata kunci tidak bisa memutuskan: nama
    AKIRA terdengar, tapi tidak ada kata perintah jadwal. Contoh nyata dari
    log: "Kira tolong bantu saya" — jelas ditujukan ke AKIRA, tapi tidak
    memuat satu pun kata seperti "jadwal" atau "catat".

    Return (untuk_akira, alasan). Kegagalan mengembalikan (False, None) —
    lebih baik AKIRA diam daripada menyahut obrolan orang lain.
    """
    if not text or not text.strip():
        return False, None

    balasan = _panggil_groq(SAPAAN_PROMPT, text.strip())
    if not balasan:
        return False, None

    try:
        hasil = json.loads(balasan)
    except Exception as e:
        logger.warning(f"Balasan sapaan bukan JSON: {e}")
        return False, None

    untuk_akira = bool(hasil.get("untuk_akira"))
    alasan = hasil.get("alasan")
    logger.info(
        f"Groq menilai '{text[:45]}' "
        f"{'DITUJUKAN' if untuk_akira else 'bukan'} untuk AKIRA"
        f"{f' ({alasan})' if alasan else ''}"
    )
    return untuk_akira, alasan


JAWABAN_PROMPT = """Kamu menafsirkan JAWABAN user atas pertanyaan dari
asisten jadwal berbasis suara Bahasa Indonesia.

Jawaban berasal dari pengenalan suara, jadi bisa berisi salah dengar,
pengulangan, atau kata tambahan. Nilai MAKSUD-nya, bukan ejaannya.

Tentukan salah satu:
- "ya"     : user menyetujui / mengiyakan
- "tidak"  : user menolak / membatalkan
- "lain"   : user menyebut hal lain (koreksi, perintah baru, pertanyaan balik)
- "kosong" : jawaban tidak bermakna atau tidak bisa ditafsirkan

Balas HANYA JSON: {"maksud": "ya|tidak|lain|kosong", "alasan": "<singkat>"}

Contoh:
Pertanyaan: "Mau saya catat jadwal itu ke kalender?"
Jawaban: "Ya, catat, catat, catat" -> {"maksud": "ya", "alasan": "mengiyakan dan meminta dicatat"}

Pertanyaan: "Mau saya catat jadwal itu ke kalender?"
Jawaban: "gas aja" -> {"maksud": "ya", "alasan": "ungkapan setuju"}

Pertanyaan: "Mau saya catat jadwal itu ke kalender?"
Jawaban: "nanti aja deh" -> {"maksud": "tidak", "alasan": "menunda, berarti tidak sekarang"}

Pertanyaan: "Hapus rapat divisi? Ini tidak bisa dibatalkan."
Jawaban: "hapus aja" -> {"maksud": "ya", "alasan": "mengulang perintah hapus"}

Pertanyaan: "Sudah benar?"
Jawaban: "jamnya jadi jam 3" -> {"maksud": "lain", "alasan": "koreksi jam"}

Pertanyaan: "Sudah benar?"
Jawaban: "Selamat tinggal kuala" -> {"maksud": "kosong", "alasan": "tidak nyambung dengan pertanyaan"}

/no_think
"""


def tafsir_jawaban_groq(pertanyaan: str, jawaban: str) -> bool | None:
    """
    Minta Groq menafsirkan jawaban ya/tidak yang tidak tertangkap aturan.

    Dipanggil HANYA ketika aturan kata kunci menyerah. Contoh nyata dari log:
    ditanya "Mau saya catat?", user menjawab dan STT menghasilkan
    "Ya, catat, catat, catat". Aturan bisa saja menangkapnya, tapi bentuk
    lain seperti "gas aja", "hajar", atau "nanti aja deh" tidak akan pernah
    habis didaftar — di situlah penalaran dibutuhkan.

    Return True (ya), False (tidak), atau None (lain / tidak jelas / gagal).

    Kegagalan mengembalikan None, BUKAN True. Untuk konfirmasi, keraguan
    harus berujung pada bertanya ulang atau membatalkan — tidak pernah pada
    menjalankan aksi yang tidak jelas disetujui.
    """
    if not jawaban or not jawaban.strip():
        return None

    pesan = f'Pertanyaan: "{(pertanyaan or "").strip()}"\nJawaban: "{jawaban.strip()}"'
    balasan = _panggil_groq(JAWABAN_PROMPT, pesan)
    if not balasan:
        return None

    try:
        hasil = json.loads(balasan)
    except Exception as e:
        logger.warning(f"Balasan tafsir jawaban bukan JSON: {e}")
        return None

    maksud = str(hasil.get("maksud", "")).lower().strip()
    logger.info(
        f"Groq menafsirkan jawaban '{jawaban[:40]}' sebagai '{maksud}'"
        f"{' (' + hasil['alasan'] + ')' if hasil.get('alasan') else ''}"
    )

    if maksud == "ya":
        return True
    if maksud == "tidak":
        return False
    return None


KOREKSI_BANYAK_PROMPT = """Kamu mengoreksi BEBERAPA jadwal sekaligus berdasarkan
ucapan user dalam Bahasa Indonesia.

Kamu diberi daftar jadwal (satu per tanggal) dan kalimat user. Tentukan jadwal
MANA yang ingin diubah dan APA perubahannya.

Aturan:
- "tanggal" pada hasil WAJIB salah satu tanggal di daftar, atau "semua".
- Hari disebut dengan nama ("minggunya", "yang sabtu", "hari minggu") —
  cocokkan dengan nama hari di daftar.
- Hanya isi field yang BERUBAH: "kegiatan" (teks singkat) dan/atau "jam"
  (HH:MM, 24 jam). Jangan mengarang nilai yang tidak diucapkan.
- Kalau user menyebut hari mana yang berbeda TAPI belum menyebut nilai
  barunya ("yang minggunya beda"), jangan menebak. Isi "tanya" dengan
  tanggal-tanggal itu dan biarkan "ubah" kosong.
- Kalau kalimat bukan koreksi sama sekali, kembalikan keduanya kosong.

Balas HANYA JSON:
{"ubah": [{"tanggal": "YYYY-MM-DD"|"semua", "kegiatan": "...", "jam": "HH:MM"}],
 "tanya": ["YYYY-MM-DD"]}

Contoh (daftar: Sabtu 2026-10-03 makan malam 19:00, Minggu 2026-10-04 makan malam 19:00):
"yang minggunya beda"
-> {"ubah": [], "tanya": ["2026-10-04"]}
"minggunya futsal jam 8 pagi"
-> {"ubah": [{"tanggal": "2026-10-04", "kegiatan": "futsal", "jam": "08:00"}], "tanya": []}
"sabtu jamnya jadi jam 8 malam"
-> {"ubah": [{"tanggal": "2026-10-03", "jam": "20:00"}], "tanya": []}
"semuanya jam 6 sore aja"
-> {"ubah": [{"tanggal": "semua", "jam": "18:00"}], "tanya": []}

/no_think
"""


def koreksi_banyak_groq(jadwal: list, kalimat: str) -> dict | None:
    """
    Minta Groq menentukan jadwal mana yang dikoreksi dan apa perubahannya.

    jadwal: [{"tanggal": "YYYY-MM-DD", "hari": "Minggu", "kegiatan": ..., "jam": ...}]

    Return {"ubah": [...], "tanya": [...]} yang SUDAH DIVALIDASI, atau None
    kalau gagal. Validasi penting di sini: tanggal hasil harus benar-benar
    ada di daftar, dan jam harus berformat benar. LLM boleh menalar, tapi
    tidak boleh menciptakan tanggal baru atau jam yang mustahil.
    """
    if not kalimat or not kalimat.strip() or not jadwal:
        return None

    daftar = "\n".join(
        f"- {j['hari']} {j['tanggal']}: {j.get('kegiatan') or '(belum ada)'} "
        f"jam {j.get('jam') or '(belum ada)'}"
        for j in jadwal
    )
    pesan = f"Daftar jadwal:\n{daftar}\n\nKalimat user: {kalimat.strip()}"

    balasan = _panggil_groq(KOREKSI_BANYAK_PROMPT, pesan)
    if not balasan:
        return None
    try:
        hasil = json.loads(balasan)
    except Exception as e:
        logger.warning(f"Balasan koreksi-banyak bukan JSON: {e}")
        return None

    sah = {j["tanggal"] for j in jadwal}
    ubah = []
    for item in hasil.get("ubah") or []:
        if not isinstance(item, dict):
            continue
        tgl = item.get("tanggal")
        if tgl != "semua" and tgl not in sah:
            logger.warning(f"Groq menyebut tanggal di luar daftar: {tgl}, diabaikan")
            continue
        bersih = {"tanggal": tgl}
        keg = item.get("kegiatan")
        if isinstance(keg, str) and 0 < len(keg.strip()) <= 60:
            bersih["kegiatan"] = keg.strip()
        jam = item.get("jam")
        if isinstance(jam, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", jam):
            bersih["jam"] = jam
        if len(bersih) > 1:
            ubah.append(bersih)

    tanya = [t for t in (hasil.get("tanya") or []) if t in sah]
    logger.info(f"Groq menalar koreksi '{kalimat[:40]}': ubah={ubah} tanya={tanya}")
    return {"ubah": ubah, "tanya": tanya}


# Katalog SELURUH kemampuan AKIRA dalam bentuk kalimat baku yang pasti
# dipahami parser berbasis aturan. Groq menerjemahkan maksud user ke salah
# satunya — pemahaman bahasa di Groq, perhitungan tanggal & jam tetap di
# aturan deterministik.
KATALOG_PERINTAH = """
| aksi          | bentuk baku                                          |
|---------------|------------------------------------------------------|
| catat         | catat <kegiatan> <hari/tanggal> jam <jam> <periode>   |
| baca          | cek jadwal <hari/tanggal/rentang>                     |
| hapus         | hapus jadwal <kegiatan> <hari/tanggal>                |
| hapus         | hapus jadwal                (belum tahu yang mana)    |
| reschedule    | pindahkan jadwal <kegiatan> ke <tanggal> jam <jam>    |
| edit          | edit jadwal <kegiatan>                                |
| reminder      | ingatkan <N> menit sebelum <kegiatan>                 |
| waktu         | sekarang jam berapa                                   |
| waktu         | hari ini tanggal berapa                               |
| waktu         | <N> hari lagi itu hari apa                            |
| waktu         | <N> menit lagi jam berapa                             |
| timer         | timer <N> menit untuk <keperluan>                     |
| alarm         | setel alarm jam <jam> <periode>                       |
| batal_timer   | matikan timer                                         |
| ganti_nama    | panggil saya <nama>                                   |
| penutup       | terima kasih                                          |
"""

MAKSUD_PROMPT = f"""Kamu adalah lapis pemahaman AKIRA, asisten jadwal berbasis suara
Bahasa Indonesia. Kalimat user tidak dikenali oleh aturan kata kunci, jadi
tugasmu memahami MAKSUD-nya dan menuliskannya ulang dalam bentuk baku.

Kalimat berasal dari pengenalan suara: bisa berisi salah dengar, bahasa
santai, singkatan, atau kata yang terulang. Nilai MAKSUD-nya.

Daftar kemampuan AKIRA:
{KATALOG_PERINTAH}

Aturan WAJIB:
1. Tulis ulang HANYA dengan bentuk baku di atas.
2. JANGAN menghitung tanggal. Salin kata waktu apa adanya ("besok",
   "sabtu", "tanggal 10", "minggu depan") — sistem lain yang menghitungnya.
3. Rapikan ungkapan jam santai: "jam 7an" -> "jam 7", "setengah 8 malem"
   -> "jam 7.30 malam", "ntar malem" -> "nanti malam".
4. JANGAN mengarang detail yang tidak diucapkan. Tanpa nama kegiatan,
   jangan menambahkannya.
5. Kalau kalimat jelas bukan untuk AKIRA atau tidak bermakna, isi
   "perintah" dengan null.

Balas HANYA JSON:
{{"perintah": "<kalimat baku>" | null, "aksi": "<aksi dari tabel>" | null, "alasan": "<singkat>"}}

Contoh:
"ntar malem gue ada dinner sama klien jam 7an masukin ya"
-> {{"perintah": "catat dinner sama klien nanti malam jam 7 malam", "aksi": "catat", "alasan": "minta dicatat"}}
"besok aku free gak sih"
-> {{"perintah": "cek jadwal besok", "aksi": "baca", "alasan": "menanyakan kesibukan besok"}}
"yang futsal sabtu itu gak jadi"
-> {{"perintah": "hapus jadwal futsal sabtu", "aksi": "hapus", "alasan": "membatalkan acara"}}
"tolong undur rapat ke kamis ya"
-> {{"perintah": "pindahkan jadwal rapat ke kamis", "aksi": "reschedule", "alasan": "menggeser waktu"}}
"bangunin aku jam setengah 6 pagi"
-> {{"perintah": "setel alarm jam 5.30 pagi", "aksi": "alarm", "alasan": "minta dibangunkan"}}
"udah dulu ya"
-> {{"perintah": "terima kasih", "aksi": "penutup", "alasan": "pamit"}}
"hmm kucing tetangga lucu"
-> {{"perintah": null, "aksi": null, "alasan": "bukan untuk AKIRA"}}

/no_think
"""

AKSI_DIKENAL = {
    "catat", "baca", "hapus", "reschedule", "edit", "reminder", "waktu",
    "timer", "alarm", "batal_timer", "ganti_nama", "penutup",
}


def pahami_maksud_groq(kalimat: str, pertanyaan_terakhir: str = None) -> dict | None:
    """
    Terjemahkan maksud user ke salah satu perintah baku AKIRA.

    Dipanggil HANYA ketika seluruh aturan menyerah — perintah yang dikenali
    aturan tidak pernah melewati sini, jadi jalur umum tetap instan.

    Return {"perintah": str, "aksi": str}, {"bukan": True} kalau Groq menilai
    kalimat itu bukan perintah, atau None kalau Groq tidak dapat dihubungi.
    Hasil WAJIB diproses
    ulang oleh parser berbasis aturan, dan pemanggil memeriksa bahwa parser
    sampai pada aksi yang sama. Kalau berbeda, hasil Groq dibuang: Groq
    hanya boleh MENERJEMAHKAN, tidak boleh memutuskan sendiri.
    """
    if not kalimat or not kalimat.strip():
        return None

    pesan = kalimat.strip()
    if pertanyaan_terakhir:
        pesan = f'(AKIRA baru saja bertanya: "{pertanyaan_terakhir}")\nKalimat user: {pesan}'

    balasan = _panggil_groq(MAKSUD_PROMPT, pesan)
    if not balasan:
        return None
    try:
        hasil = json.loads(balasan)
    except Exception as e:
        logger.warning(f"Balasan pemahaman maksud bukan JSON: {e}")
        return None

    perintah = hasil.get("perintah")
    aksi = hasil.get("aksi")
    if not perintah or aksi not in AKSI_DIKENAL:
        logger.info(f"Groq: '{kalimat[:40]}' bukan perintah ({hasil.get('alasan')})")
        # Dibedakan dari None (gagal menghubungi): kalau Groq sudah menilai
        # ini bukan perintah, pengklasifikasi lain tidak boleh memaksakan label.
        return {"bukan": True}

    perintah = " ".join(str(perintah).split())
    if len(perintah.split()) > 20:
        logger.warning("Terjemahan Groq terlalu panjang, diabaikan")
        return None

    logger.info(f"Groq memahami '{kalimat[:40]}' sebagai '{perintah}' ({aksi})")
    return {"perintah": perintah, "aksi": aksi}


def deteksi_tanggal_mustahil(text: str) -> str | None:
    """
    Cek apakah teks mengandung tanggal yang mustahil (misal 32 Januari).

    Return pesan peringatan, atau None kalau tidak ada masalah.
    Fungsi ini deterministik (tanpa LLM) dan sangat cepat.
    """
    m = _TANGGAL_EKSPLISIT.search(text)
    if not m:
        return None

    hari = int(m.group(1))
    bulan_nama = m.group(2).lower()
    bulan = _BULAN_KE_ANGKA.get(bulan_nama)
    if not bulan:
        return None

    maks = _MAX_HARI[bulan]
    if hari > maks:
        return f"{hari} {bulan_nama.title()} tidak ada — {bulan_nama.title()} maksimal tanggal {maks}"
    if hari < 1:
        return f"Tanggal {hari} tidak valid"
    return None


def ada_pola_tanggal(text: str) -> bool:
    """
    True kalau teks mengandung pola yang TERLIHAT seperti tanggal, valid atau tidak.

    Dipakai oleh deteksi_pernyataan_jadwal sebagai pengganti parse_date_id
    untuk kasus tanggal mustahil — "saya ada kondangan tanggal 32 Januari"
    tetap terdeteksi sebagai pernyataan jadwal meskipun 32 Januari bukan
    tanggal valid.
    """
    t = text.lower()
    # "tanggal X bulan", "X Januari", "besok", "lusa", dsb.
    if _TANGGAL_EKSPLISIT.search(t):
        return True
    if re.search(r"\b(?:besok|lusa|hari\s+ini|minggu\s+depan|bulan\s+depan)\b", t):
        return True
    if re.search(r"\btanggal\s+\d{1,2}\b", t):
        return True
    # "hari senin", "kamis depan"
    if re.search(r"\b(?:senin|selasa|rabu|kamis|jumat|sabtu|ahad|minggu)\b", t):
        return True
    return False
