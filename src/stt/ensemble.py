"""
Ensemble STT: beberapa mesin transkripsi, satu kesimpulan.
Tanggung jawab: Person 2 & 3 (Audio + NLP Lead) — Sprint 3.23

Ide dasarnya: tiap mesin salah di tempat yang berbeda. Whisper salah dengar
"setelkan" jadi "setelah", model Groq mungkin benar di situ tapi meleset di
nama bulan. Menjalankan ketiganya lalu memilih yang paling masuk akal
menghasilkan transkripsi yang lebih baik daripada mesin mana pun sendirian.

Alurnya berlapis, dan lapisan yang murah dicoba lebih dulu:

1. **Jalankan paralel.** Tiga mesin bersamaan di thread terpisah, bukan
   berurutan. Total waktunya = mesin paling lambat, bukan jumlah ketiganya.
2. **Voting.** Kalau dua mesin atau lebih sepakat (setelah dinormalkan),
   hasil itu langsung dipakai — tanpa memanggil LLM sama sekali. Ini kasus
   yang paling sering, dan gratis.
3. **Rekonsiliasi LLM.** Hanya kalau ketiganya berbeda. LLM diberi semua
   kandidat dan diminta memilih/menggabungkan yang paling masuk akal sebagai
   perintah jadwal Bahasa Indonesia.
4. **Validasi.** Hasil LLM diperiksa: harus benar-benar berasal dari kandidat,
   bukan kalimat karangan. Kalau menyimpang jauh, dipakai kandidat terbaik
   hasil voting.

Kalau semuanya gagal, yang dipakai kandidat pertama yang berhasil. Sistem ini
menambah akurasi; ia tidak boleh menambah titik kegagalan baru.
"""
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from loguru import logger

# Nama model LLM berubah cukup sering di kedua penyedia — model yang kemarin
# ada bisa dihentikan hari ini, dan gejalanya berupa 404 yang membingungkan.
# Karena itu tiap penyedia punya DAFTAR, dicoba berurutan sampai ada yang
# menjawab. Yang berhasil diingat supaya panggilan berikutnya langsung tepat.
MODEL_CADANGAN = {
    # Diverifikasi hidup lewat scripts/cek_model_llm.py
    "groq": [
        "openai/gpt-oss-20b",       # cepat, cukup untuk memilih kalimat
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",      # paling teliti, paling lambat
    ],
    # Sengaja model dari keluarga berbeda dengan "groq": dua model sekeluarga
    # cenderung salah dengan cara yang sama.
    "groq2": [
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ],
}

# Model yang terbukti jalan, diisi saat runtime.
_MODEL_BERHASIL = {}

# Mesin yang benar-benar menghasilkan kandidat di panggilan terakhir.
# Dipakai transcriber.py untuk label log — sebelumnya label memakai daftar
# CONFIG, sehingga log menyebut mesin yang sebenarnya dilewati.
_TERPAKAI: list = []


def mesin_terpakai() -> list:
    """Mesin yang benar-benar berhasil di panggilan ensemble terakhir."""
    return list(_TERPAKAI)


def _daftar_model(penyedia: str, model: str | list | None) -> list:
    """Susun urutan model yang akan dicoba untuk satu penyedia."""
    if isinstance(model, str) and model.strip():
        pilihan = [model.strip()]
    elif isinstance(model, (list, tuple)) and model:
        pilihan = list(model)
    else:
        pilihan = []

    # Yang sudah terbukti jalan didahulukan
    berhasil = _MODEL_BERHASIL.get(penyedia)
    if berhasil:
        pilihan = [berhasil] + [m for m in pilihan if m != berhasil]

    for cadangan in MODEL_CADANGAN.get(penyedia, []):
        if cadangan not in pilihan:
            pilihan.append(cadangan)
    return pilihan


PROMPT_REKONSILIASI = """Kamu memilih transkripsi yang paling masuk akal.

Beberapa mesin speech-to-text mentranskripsi SATU ucapan Bahasa Indonesia yang
sama, tapi hasilnya berbeda. Ucapan itu adalah perintah atau jawaban untuk
AKIRA, asisten jadwal berbasis suara. Tugasmu: tentukan kalimat yang paling
mungkin BENAR-BENAR diucapkan.

== PERINTAH YANG DIKENALI AKIRA ==
1. CATAT jadwal   — "catat meeting besok jam 3 sore"
2. BACA jadwal    — "cek jadwal besok", "hari ini saya kosong ga?"
3. HAPUS jadwal   — "hapus jadwal meeting", "hapus seluruh jadwal"
4. RESCHEDULE     — "geser rapat ke tanggal 5 jam 2 siang"
5. EDIT           — "edit jadwal saya"
6. PENGINGAT      — "ingatkan 1 jam sebelum meeting"
7. ALARM/TIMER    — "timer 30 detik", "matikan timernya"
8. TANYA WAKTU    — "sekarang jam berapa", "617 hari lagi itu hari apa"
9. KONFIRMASI     — "ya", "sudah benar", "oke"
10. KOREKSI       — "tanggalnya 3 Januari", "kegiatannya futsal"
11. PEMBATALAN    — "batalkan", "tidak jadi"
12. SELF DESTRUCT — "AKIRA destroy yourself"

== JAWABAN SAAT KONFIRMASI ==
Saat pertanyaan asisten = "Sudah benar?", user biasanya menjawab:
ya/oke/betul/benar/sudah (setuju) ATAU salah/tidak/bukan/batalkan (tolak)
ATAU koreksi langsung: "tanggalnya X", "kegiatannya Y", "jamnya Z"

== VALIDASI ANGKA ==
- Tanggal harus valid: Januari maks 31, Februari maks 28/29, April/Juni/
  September/November maks 30. "32 Januari" MUSTAHIL — cari angka terdekat
  dari kandidat lain (misal "3 Januari" atau "2 Januari").
- Jam: 0-23 (atau 1-12 + pagi/siang/sore/malam). "jam 7.60" mustahil.
- Kalau angka tidak masuk akal, pilih kandidat yang punya angka VALID,
  atau perbaiki ke angka terdekat yang valid dari kandidat-kandidat yang ada.

== ATURAN ==
- Kalau ada "Pertanyaan asisten", pilih kandidat yang paling NYAMBUNG sebagai
  jawaban atas pertanyaan itu. Ini petunjuk terkuat.
- Cocokkan kandidat ke salah satu perintah di atas — pilih yang paling mirip
  dengan pola perintah yang dikenali.
- Boleh menggabungkan bagian dari beberapa kandidat.
- JANGAN menambah informasi yang tidak ada di kandidat mana pun.
- Pertahankan angka yang VALID dari kandidat yang paling masuk akal.
- Balas HANYA JSON: {"teks": "<kalimat final>"}

Contoh:
Pertanyaan asisten: "Sudah benar?"
Kandidat: 1. "Kalim, betalkan"  2. "Salim, batalkan"  3. "Batalkan!"
-> {"teks": "Batalkan"}

Pertanyaan asisten: "Jam berapa mulainya?"
Kandidat: 1. "jam duo siang"  2. "jam 2 siang"  3. "jam dua siang"
-> {"teks": "jam 2 siang"}

Pertanyaan asisten: "Sudah benar?"
Kandidat: 1. "Anggalnya 32 Januari 2007"  2. "Tanggalnya 32 Januari 2027"  3. "Tanggalnya 32 Januari 2027"
Reasoning: 32 Januari mustahil. Kandidat 2&3 sepakat "Januari 2027". Angka "32" kemungkinan salah dengar "3" + "2" terpisah, atau "3 Februari". Tidak bisa ditentukan pasti, tapi "Tanggalnya" + angka + bulan = pola koreksi tanggal. Pertahankan apa adanya agar sistem hilir yang memvalidasi.
-> {"teks": "Tanggalnya 3 Januari 2027"}

/no_think
"""

# Pertanyaan yang baru saja diucapkan AKIRA. Diisi app.py sebelum mendengarkan.
_KONTEKS_PERTANYAAN = ""


def set_konteks_pertanyaan(pertanyaan: str):
    """
    Simpan pertanyaan terakhir AKIRA sebagai konteks rekonsiliasi.

    Tanpa ini, LLM menilai kandidat tanpa tahu sedang menjawab apa —
    "Kalim, betalkan" dan "Salim, batalkan" sama-sama terdengar masuk akal.
    Begitu tahu pertanyaannya "Sudah benar?", pilihannya jadi jelas.
    """
    global _KONTEKS_PERTANYAAN
    _KONTEKS_PERTANYAAN = (pertanyaan or "").strip()


def _normalkan(teks: str) -> str:
    """Bentuk banding untuk voting: huruf kecil, tanpa tanda baca & spasi ganda."""
    t = (teks or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


# Kata yang ejaannya beda tapi maknanya sama, disatukan SEBELUM dibandingkan.
#
# Jaccard menghitung kata apa adanya. Pada kalimat pendek, satu perbedaan
# ejaan sudah menjatuhkan skor: "Ya, catat" dan "Iya catat" hanya 0,33 —
# dan jawaban yang jelas-jelas sama terbuang sebagai derau. Penyatuan ini
# hanya dipakai untuk MENGUKUR kemiripan; teks yang dipilih tidak berubah.
SINONIM = {
    "iya": "ya", "iyaa": "ya", "yaa": "ya", "yap": "ya", "yup": "ya",
    "yes": "ya", "yoi": "ya", "oke": "ya", "ok": "ya", "okay": "ya",
    "okey": "ya", "boleh": "ya", "betul": "ya", "benar": "ya", "sip": "ya",
    "tidak": "tidak", "nggak": "tidak", "ngga": "tidak", "gak": "tidak",
    "ga": "tidak", "enggak": "tidak", "engga": "tidak", "no": "tidak",
    "catetin": "catat", "catatkan": "catat", "catatin": "catat",
}


def _kata_bermakna(teks: str) -> set:
    """Himpunan kata setelah ejaan disatukan ke bentuk dasarnya."""
    return {SINONIM.get(k, k) for k in _normalkan(teks).split()}


def _mirip(a: str, b: str) -> float:
    """Kemiripan 0-1 berdasarkan kata yang sama (Jaccard), setelah sinonim disatukan."""
    ka, kb = _kata_bermakna(a), _kata_bermakna(b)
    if not ka or not kb:
        return 0.0
    return len(ka & kb) / len(ka | kb)


def jalankan_paralel(audio_path: str, mesin: list, timeout_s: float = 12.0, **kwargs) -> dict:
    """
    Jalankan beberapa mesin STT bersamaan.

    Return {nama_mesin: teks}. Mesin yang gagal atau kehabisan waktu tidak
    masuk hasil — kegagalan satu mesin tidak boleh menahan yang lain.
    """
    from src.stt.backends import get_backend

    hasil = {}
    with ThreadPoolExecutor(max_workers=max(1, len(mesin))) as pool:
        futures = {
            pool.submit(get_backend(nama), audio_path, **kwargs): nama for nama in mesin
        }
        for future, nama in futures.items():
            try:
                teks = (future.result(timeout=timeout_s) or "").strip()
                if teks:
                    hasil[nama] = teks
                    logger.info(f"  [{nama}] '{teks}'")
                else:
                    logger.debug(f"  [{nama}] kosong")
            except FutureTimeout:
                logger.warning(f"  [{nama}] kehabisan waktu ({timeout_s}s)")
            except Exception as e:
                logger.warning(f"  [{nama}] gagal: {e}")

    return hasil


# Ambang kesepakatan minimum antar-mesin. Di bawah ini, rekamannya hampir
# pasti derau: tiap mesin menebak sesuatu yang berbeda dari suara yang sama.
AMBANG_DERAU = 0.35
AMBANG_DERAU_JAWABAN = 0.20     # saat AKIRA baru saja bertanya


def tingkat_kesepakatan(kandidat: dict) -> float:
    """
    Seberapa mirip kandidat satu sama lain (0-1), dirata-ratakan atas
    SEMUA pasangan.

    Rata-rata, bukan pasangan termirip. Dua mesin yang kebetulan berbagi
    satu kata ("jadwal") sudah cukup membuat nilai maksimum terlihat tinggi,
    padahal mesin ketiga mendengar sesuatu yang sama sekali lain — tanda
    khas derau.

    Ucapan sungguhan menghasilkan kandidat yang berdekatan: mesin boleh
    salah satu-dua kata, tapi kerangka kalimatnya sama.
    """
    daftar = list(kandidat.values())
    if len(daftar) < 2:
        return 1.0

    pasangan = [
        _mirip(daftar[i], daftar[j])
        for i in range(len(daftar))
        for j in range(i + 1, len(daftar))
    ]
    return sum(pasangan) / len(pasangan)


def kemungkinan_derau(kandidat: dict) -> bool:
    """
    True kalau kandidat terlalu berbeda satu sama lain untuk dipercaya.

    Ini memakai ensemble sebagai DETEKTOR DERAU, bukan hanya sebagai
    pemilih transkripsi. Contoh nyata dari log, saat tidak ada yang bicara:

        [whisper]    'Selamat tinggal.'
        [groq-turbo] 'Perniatra, jadwal, jadwal.'
        [groq-v3]    'Jadwal.'

    Ketiganya saling asing. Merekonsiliasinya menghasilkan kata yang
    terdengar masuk akal — dan AKIRA bertindak atas sesuatu yang tidak
    pernah diucapkan. Lebih baik dibuang.
    """
    if len(kandidat) < 2:
        return False

    # Saat AKIRA baru saja bertanya, user hampir pasti sedang menjawab —
    # dan jawaban cenderung pendek, sehingga satu kata berbeda saja sudah
    # menurunkan skor drastis. Ambang dilonggarkan, bukan dimatikan:
    # derau yang saling asing tetap tertangkap.
    ambang = AMBANG_DERAU_JAWABAN if _KONTEKS_PERTANYAAN else AMBANG_DERAU

    skor = tingkat_kesepakatan(kandidat)
    if skor >= ambang:
        return False

    logger.warning(
        f"Kandidat saling asing (kesepakatan {skor:.2f} < {ambang}), "
        f"kemungkinan derau — rekaman dibuang"
    )
    for nama, teks in kandidat.items():
        logger.debug(f"  [{nama}] '{teks}'")
    return True


def voting(kandidat: dict, ambang_mirip: float = 0.8) -> str | None:
    """
    Cari kandidat yang didukung minimal dua mesin.

    Tidak menuntut sama persis — "jam 3 sore." dan "jam 3 sore" seharusnya
    dihitung sepakat. Kemiripan 0.8 ke atas sudah dianggap satu suara.

    Return teks pemenang, atau None kalau tidak ada yang sepakat.
    """
    if len(kandidat) < 2:
        return None

    daftar = list(kandidat.items())
    skor = {}

    for nama_a, teks_a in daftar:
        dukungan = sum(
            1 for nama_b, teks_b in daftar
            if nama_b != nama_a and _mirip(teks_a, teks_b) >= ambang_mirip
        )
        skor[nama_a] = dukungan

    terbaik = max(skor, key=skor.get)
    if skor[terbaik] >= 1:
        logger.info(f"Voting: '{kandidat[terbaik]}' didukung {skor[terbaik] + 1} mesin")
        return kandidat[terbaik]
    return None


def _valid_hasil_llm(teks: str, kandidat: dict, ambang: float = 0.5) -> bool:
    """
    Hasil LLM harus benar-benar berasal dari kandidat.

    Tanpa pemeriksaan ini, LLM bisa "memperbaiki" kalimat jadi sesuatu yang
    tidak pernah diucapkan — dan itu jauh lebih berbahaya daripada salah
    dengar biasa, karena kalimatnya terdengar masuk akal.
    """
    if not teks or not teks.strip():
        return False
    return any(_mirip(teks, k) >= ambang for k in kandidat.values())


def _satu_rekonsiliasi(nama: str, kandidat: dict, model=None) -> str | None:
    """
    Jalankan SATU perekonsiliasi dan validasi hasilnya.

    Kalau nama model ditolak penyedia (404 / model_not_found), model berikutnya
    di daftar cadangan dicoba. Ini penting karena nama model di Groq berubah
    cukup sering, dan gejalanya berupa 404 yang tidak menjelaskan apa pun.
    """
    import json

    fungsi = PEREKONSILIASI.get(nama)
    if not fungsi:
        logger.warning(f"Perekonsiliasi '{nama}' tidak dikenal")
        return None

    daftar = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(kandidat.values()))
    pesan = f"Kandidat transkripsi:\n{daftar}"
    if _KONTEKS_PERTANYAAN:
        pesan = f'Pertanyaan asisten: "{_KONTEKS_PERTANYAAN}"\n{pesan}'

    if nama == "lokal":
        model_dicoba = [model]
    else:
        model_dicoba = _daftar_model(nama, model)[:4]

    mentah = None
    for kandidat_model in model_dicoba:
        try:
            mentah = fungsi(PROMPT_REKONSILIASI, pesan, kandidat_model)
            if nama != "lokal":
                _MODEL_BERHASIL[nama] = kandidat_model
            break
        except Exception as e:
            pesan_error = str(e)
            # 402 = akun tanpa kredit. Ganti model hanya menolong kalau
            # model berikutnya berakhiran ":free", jadi tetap dilanjutkan.
            if "402" in pesan_error or "payment" in pesan_error.lower():
                logger.warning(
                    f"{nama} menolak '{kandidat_model}': akun tanpa kredit. "
                    f"Mencoba model gratis berikutnya"
                )
                continue

            if any(t in pesan_error for t in ("404", "400", "not found", "not_found",
                                              "decommissioned", "does not exist")):
                logger.warning(f"Model '{kandidat_model}' ditolak {nama}, coba berikutnya")
                continue
            logger.warning(f"Perekonsiliasi '{nama}' gagal: {e}")
            return None

    if mentah is None:
        logger.warning(f"Perekonsiliasi '{nama}': semua model ditolak")
        return None

    try:
        teks = json.loads(_bersihkan_json(mentah)).get("teks", "").strip()
    except Exception as e:
        logger.warning(f"Perekonsiliasi '{nama}' balas bukan JSON: {e}")
        return None

    if not _valid_hasil_llm(teks, kandidat):
        logger.warning(f"Hasil '{nama}' ('{teks}') tidak mirip kandidat, ditolak")
        return None

    logger.info(f"Perekonsiliasi '{nama}' memilih: '{teks}'")
    return teks


def _bersihkan_json(mentah: str) -> str:
    """Buang blok <think> dan pembungkus markdown dari balasan LLM."""
    import re as _re

    bersih = _re.sub(r"<think>.*?</think>", "", mentah, flags=_re.DOTALL)
    bersih = _re.sub(r"<think>.*", "", bersih, flags=_re.DOTALL).strip()
    kurung = _re.search(r"\{.*\}", bersih, _re.DOTALL)
    return kurung.group(0) if kurung else bersih


def rekonsiliasi_ganda(kandidat: dict, perekonsiliasi: list, model_per_nama: dict = None) -> str | None:
    """
    Jalankan BEBERAPA perekonsiliasi lalu bandingkan hasilnya.

    Kenapa lebih dari satu: satu LLM bisa salah menebak sama seperti satu
    mesin STT bisa salah dengar. Kalau dua LLM dari penyedia berbeda sampai
    pada kalimat yang sama, keyakinannya jauh lebih tinggi daripada satu
    LLM yang kebetulan percaya diri.

    Aturan keputusan:
    - Dua atau lebih sepakat  -> pakai itu
    - Semua beda             -> pakai yang paling dekat dengan kandidat STT
    - Semua gagal            -> None (pemanggil pakai jaring terakhir)
    """
    model_per_nama = model_per_nama or {}
    hasil = {}

    with ThreadPoolExecutor(max_workers=max(1, len(perekonsiliasi))) as pool:
        futures = {
            pool.submit(_satu_rekonsiliasi, nama, kandidat, model_per_nama.get(nama)): nama
            for nama in perekonsiliasi
        }
        for future, nama in futures.items():
            try:
                teks = future.result(timeout=20)
                if teks:
                    hasil[nama] = teks
            except Exception as e:
                logger.warning(f"Perekonsiliasi '{nama}' error: {e}")

    if not hasil:
        return None

    if len(hasil) == 1:
        satu = next(iter(hasil.values()))
        logger.info(f"Hanya satu perekonsiliasi berhasil: '{satu}'")
        return satu

    sepakat = voting(hasil, ambang_mirip=0.85)
    if sepakat:
        logger.info(f"Perekonsiliasi sepakat: '{sepakat}'")
        return sepakat

    # Tidak sepakat: pilih yang paling dekat dengan apa yang benar-benar
    # didengar mesin STT. Yang menyimpang jauh biasanya hasil mengarang.
    def kedekatan(teks):
        return max(_mirip(teks, k) for k in kandidat.values())

    terbaik = max(hasil.values(), key=kedekatan)
    logger.info(f"Perekonsiliasi berbeda, dipilih yang terdekat ke kandidat: '{terbaik}'")
    return terbaik


def _panggil_groq_llm(system_prompt: str, user_pesan: str, model: str = None) -> str:
    """
    Panggil LLM di Groq untuk rekonsiliasi. Butuh GROQ_API_KEY.

    Beda dengan `transcribe_groq` di backends.py: yang itu Whisper (audio ->
    teks), yang ini LLM (teks -> teks). Keduanya memakai API key yang sama.
    """
    import requests

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY belum diisi di .env")

    model = model or os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile")

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_pesan},
            ],
            "temperature": 0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _panggil_llm_lokal(system_prompt: str, user_pesan: str, model: str = None) -> str:
    """Rekonsiliasi lewat Ollama lokal. Gratis, tanpa internet."""
    from src.nlp.slm_extractor import DEFAULT_MODEL, _chat, _clean_json_response

    response = _chat(
        model or DEFAULT_MODEL,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_pesan},
        ],
        {"temperature": 0.0, "num_predict": 200, "top_k": 10},
    )
    return _clean_json_response(response["message"]["content"])


def transcribe_ensemble(
    audio_path: str,
    mesin: list,
    timeout_s: float = 12.0,
    perekonsiliasi: list = None,
    model_perekonsiliasi: dict = None,
    **kwargs,
) -> str:
    """
    Fasad ensemble. Tiga lapis:

    LAPIS 1 — beberapa mesin STT jalan paralel, menghasilkan kandidat.
    LAPIS 2 — kalau kandidat tidak sepakat, beberapa LLM merekonsiliasi.
    LAPIS 3 — hasilnya diserahkan ke pipeline NLP + qwen3 lokal (di luar
              fungsi ini) untuk dipahami sebagai perintah.

    Voting dicoba lebih dulu di tiap lapis, karena gratis dan paling sering
    berhasil. LLM hanya dipanggil saat benar-benar buntu.
    """
    from src.stt.backends import mesin_siap

    # Mesin yang API key-nya kosong atau library-nya belum terpasang dibuang
    # lebih dulu. Memanggilnya cuma menambah jeda untuk kegagalan yang sudah pasti.
    mesin = mesin_siap(mesin) or ["whisper"]

    logger.info(f"[Lapis 1] STT paralel: {', '.join(mesin)}")
    kandidat = jalankan_paralel(audio_path, mesin, timeout_s=timeout_s, **kwargs)

    if not kandidat:
        logger.error("Semua mesin STT gagal")
        return ""

    _TERPAKAI.clear()
    _TERPAKAI.extend(kandidat)

    if len(kandidat) == 1:
        satu = next(iter(kandidat.values()))
        logger.info(f"Hanya satu mesin berhasil, dipakai apa adanya: '{satu}'")
        return satu

    sepakat = voting(kandidat)
    if sepakat:
        return sepakat

    # Sebelum melibatkan LLM: kalau kandidat saling asing, ini derau.
    # Merekonsiliasi derau selalu menghasilkan sesuatu yang terdengar masuk
    # akal, dan itu justru berbahaya.
    if kemungkinan_derau(kandidat):
        return ""

    # Lapis 2 hanya jalan kalau lapis 1 tidak menghasilkan kesepakatan
    if perekonsiliasi is None:
        perekonsiliasi = ["lokal"]

    perekonsiliasi = _perekonsiliasi_siap(perekonsiliasi)
    logger.info(f"[Lapis 2] Kandidat berbeda, rekonsiliasi lewat: {', '.join(perekonsiliasi)}")

    hasil = rekonsiliasi_ganda(kandidat, perekonsiliasi, model_perekonsiliasi)
    if hasil:
        return hasil

    # Jaring terakhir: kandidat terpanjang. Transkripsi yang terpotong biasanya
    # lebih merugikan daripada yang kelebihan satu kata.
    terpanjang = max(kandidat.values(), key=lambda t: len(_normalkan(t).split()))
    logger.info(f"Rekonsiliasi gagal, memakai kandidat terpanjang: '{terpanjang}'")
    return terpanjang


def _perekonsiliasi_siap(daftar: list) -> list:
    """
    Saring perekonsiliasi yang API key-nya kosong.
    Selalu menyisakan minimal "lokal", yang tidak butuh apa pun.
    """
    butuh_key = {
        "groq": "GROQ_API_KEY",
        "groq2": "GROQ_API_KEY",
    }
    siap = []

    for nama in daftar:
        key = butuh_key.get(nama)
        if key and not os.getenv(key, "").strip():
            logger.warning(f"Perekonsiliasi '{nama}' dilewati: {key} kosong")
            continue
        siap.append(nama)

    return siap or ["lokal"]


PEREKONSILIASI = {
    "groq": _panggil_groq_llm,
    # Perekonsiliasi kedua, tetap di Groq tapi dengan model dari keluarga
    # berbeda — pendapat kedua yang independen tanpa perlu penyedia lain.
    "groq2": _panggil_groq_llm,
    "lokal": _panggil_llm_lokal,
}


if __name__ == "__main__":
    # python -m src.stt.ensemble   (uji logika tanpa audio & tanpa jaringan)
    print("=== Voting ===")
    kasus = [
        ("dua sepakat", {
            "whisper": "catat jadwal meeting besok jam 3 sore",
            "groq-turbo": "Catat jadwal meeting besok jam 3 sore.",
            "groq-v3": "catat jadwal miting besok jam 3",
        }),
        ("semua beda", {
            "whisper": "setelah pengingat untuk 30 minit lagi",
            "groq-turbo": "setelkan pengingat untuk 30 menit lagi",
            "groq-v3": "setel pengingat 30 menit lagi ya",
        }),
        ("satu mesin saja", {"whisper": "cek jadwal besok"}),
    ]
    for label, k in kasus:
        print(f"\n  {label}:")
        for nama, teks in k.items():
            print(f"    {nama:12} {teks!r}")
        print(f"    -> voting: {voting(k)!r}")

    print("\n=== Validasi hasil LLM ===")
    kandidat = {
        "a": "setel pengingat 30 menit lagi",
        "b": "setelkan pengingat untuk 30 menit lagi",
    }
    for teks in [
        "setel pengingat untuk 30 menit lagi",     # gabungan wajar
        "hapus semua jadwal saya",                 # karangan
        "",
    ]:
        print(f"  {teks!r:44} -> valid={_valid_hasil_llm(teks, kandidat)}")
