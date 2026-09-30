"""
Memahami KOREKSI dari user saat konfirmasi.
Tanggung jawab: Person 3 (NLP Lead) — Sprint 3.16

Masalah yang diselesaikan:
AKIRA membacakan ringkasan, user bilang "tidak", dan seluruh perintah dibatalkan.
Padahal biasanya cuma SATU field yang salah. Mengulang dari nol untuk mengganti
satu angka itu menyebalkan.

Dua lapis, seperti pola di modul NLP lain:

1. **Aturan** — cepat, gratis, deterministik. Menangani bentuk yang jelas:
   "jamnya jadi 12", "tanggalnya 3 September", "kegiatannya futsal".
2. **LLM** — hanya dipanggil kalau aturan menyerah. Menangani kalimat bebas:
   "bukan berenang, aku mau futsal aja sore harinya".

Yang penting: hasil LLM SELALU divalidasi. Field yang tidak dikenal dibuang,
format jam dan tanggal dicek, dan nilai yang tidak masuk akal ditolak. LLM
boleh menebak, tapi tidak boleh menulis apa pun ke kalender tanpa pemeriksaan.
"""
import json
import re

from loguru import logger

# Field yang boleh dikoreksi, beserta kata yang dipakai user untuk menyebutnya.
FIELD_ALIAS = {
    "jam": ["jam", "jamnya", "waktu", "waktunya", "pukul", "mulai", "mulainya"],
    "jam_selesai": ["selesai", "selesainya", "berakhir", "sampai", "kelar"],
    "tanggal": ["tanggal", "tanggalnya", "hari", "harinya", "tgl"],
    "kegiatan": ["kegiatan", "kegiatannya", "acara", "acaranya", "nama", "namanya",
                 "judul", "judulnya", "agendanya"],
    "deskripsi": ["deskripsi", "deskripsinya", "catatan", "catatannya", "keterangan"],
}

# "bukan X, tapi Y" / "ganti jadi Y" / "harusnya Y"
POLA_KOREKSI = [
    r"bukan\s+.+?[,\s]+\s*(?:tapi|melainkan)\s+(.+)",
    r"(?:ganti|ubah|ralat|betulin|perbaiki)\s+(?:jadi|menjadi|ke)\s+(.+)",
    r"harusnya\s+(.+)",
    r"seharusnya\s+(.+)",
    r"maksud(?:nya|ku)\s+(.+)",
]

PROMPT_KOREKSI = """Kamu mesin koreksi data jadwal Bahasa Indonesia.

User sedang mengoreksi satu atau beberapa field dari jadwal yang dibacakan.
Balas HANYA JSON berisi field yang BERUBAH. Field yang tidak disebut user
JANGAN dimasukkan.

Field yang boleh diubah:
  "kegiatan"    : nama kegiatan (teks singkat)
  "tanggal"     : format YYYY-MM-DD
  "jam"         : format HH:MM (24 jam)
  "jam_selesai" : format HH:MM (24 jam)
  "deskripsi"   : catatan tambahan (teks)

Contoh (data sekarang: kegiatan=berenang, tanggal=2026-09-02, jam=12:00):
"bukan berenang, tapi futsal" -> {"kegiatan": "futsal"}
"jamnya jadi 3 sore" -> {"jam": "15:00"}
"tanggalnya 3 september" -> {"tanggal": "2026-09-03"}
"kegiatannya futsal jam 4 sore" -> {"kegiatan": "futsal", "jam": "16:00"}
"catatannya bawa handuk" -> {"deskripsi": "bawa handuk"}
"sudah benar" -> {}

/no_think
"""


def _cari_field(text: str) -> list:
    """Field mana saja yang disebut user di kalimat koreksi."""
    t = text.lower()
    ketemu = []
    for field, alias in FIELD_ALIAS.items():
        if any(re.search(rf"\b{a}\b", t) for a in alias):
            ketemu.append(field)
    return ketemu


def _ada_petunjuk_tanggal(text: str) -> bool:
    from src.nlp.date_time_parser import BULAN_PATTERN, HARI_PATTERN

    return bool(
        re.search(
            rf"\b(?:tanggal|besok|lusa|kemarin|hari ini|minggu depan|bulan depan|"
            rf"{BULAN_PATTERN}|{HARI_PATTERN})\b|\b\d{{1,2}}[/-]\d{{1,2}}\b",
            text.lower(),
        )
    )


def koreksi_rule_based(data: dict, text: str) -> dict:
    """
    Coba pahami koreksi tanpa LLM. Return dict field yang berubah.

    Menangani bentuk yang paling sering: user menyebut nama field lalu
    nilai barunya.
    """
    from src.nlp.date_time_parser import parse_date_id, parse_time_id
    from src.nlp.text_normalizer import normalize

    bersih = normalize(text)
    perubahan = {}
    field_disebut = _cari_field(bersih)

    # --- Waktu
    jam_baru = parse_time_id(bersih)
    if jam_baru:
        # "selesainya jam 5 sore" menyebut kata "jam" DAN "selesai" sekaligus.
        # Yang menentukan adalah kata penanda akhir, bukan sekadar ada tidaknya
        # kata "jam" — kecuali user eksplisit bilang "mulai".
        akhir = "jam_selesai" in field_disebut
        mulai = bool(re.search(r"\b(?:mulai|mulainya|dimulai)\b", bersih))
        target = "jam_selesai" if akhir and not mulai else "jam"
        if jam_baru != data.get(target):
            perubahan[target] = jam_baru

    if _ada_petunjuk_tanggal(bersih):
        tgl = parse_date_id(bersih)
        if tgl:
            tgl_str = tgl.strftime("%Y-%m-%d")
            if tgl_str != data.get("tanggal"):
                perubahan["tanggal"] = tgl_str

    # --- Nama kegiatan & deskripsi (field bebas teks)
    for field in ("kegiatan", "deskripsi"):
        if field not in field_disebut:
            continue
        nilai = _ambil_nilai_teks(bersih, field)
        if nilai and nilai != data.get(field):
            perubahan[field] = nilai

    # --- "bukan X tapi Y" tanpa menyebut nama field: anggap nama kegiatan
    if not perubahan and not field_disebut:
        for pola in POLA_KOREKSI:
            m = re.search(pola, bersih)
            if m:
                nilai = _bersihkan_nilai(m.group(1))
                if nilai:
                    perubahan["kegiatan"] = nilai
                break

    if perubahan:
        logger.info(f"Koreksi (aturan) dari '{text}': {perubahan}")
    return perubahan


def _ambil_nilai_teks(text: str, field: str) -> str | None:
    """Ambil nilai setelah nama field: 'kegiatannya futsal' -> 'futsal'."""
    alias = "|".join(FIELD_ALIAS[field])
    m = re.search(
        rf"\b(?:{alias})\b\s*(?:itu|adalah|jadi|menjadi|ganti\s+jadi|nya)?\s*(.+)", text
    )
    if not m:
        return None
    return _bersihkan_nilai(m.group(1))


# Kata kerja perubahan yang BUKAN nilai baru. "catatannya diganti" berarti
# user ingin mengubah, bukan mengisi catatan dengan kata "diganti".
KATA_PERUBAHAN = {
    "diganti", "ganti", "diubah", "ubah", "dirubah", "salah", "keliru",
    "diperbaiki", "perbaiki", "diralat", "ralat", "beda", "berbeda",
}


def _bersihkan_nilai(teks: str) -> str | None:
    """Rapikan nilai hasil tangkapan: buang keterangan waktu dan kata pengisi."""
    from src.nlp.slm_extractor import extract_kegiatan_regex

    nilai = extract_kegiatan_regex(teks)
    if nilai:
        return nilai
    if not nilai:
        nilai = re.sub(r"[^\w\s]", " ", teks).strip()
        nilai = " ".join(nilai.split()[:5])

    if not nilai:
        return None

    # Kalau yang tersisa cuma kata kerja perubahan, berarti user belum
    # menyebutkan nilai barunya — jangan simpan kata itu sebagai isi field.
    sisa = [k for k in nilai.split() if k.lower() not in KATA_PERUBAHAN]
    if not sisa:
        return None
    return " ".join(sisa)


def _valid(field: str, nilai) -> bool:
    """Periksa nilai dari LLM sebelum dipakai. LLM boleh menebak, tidak boleh ngawur."""
    if nilai is None or nilai == "":
        return False
    if field in ("jam", "jam_selesai"):
        return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(nilai)))
    if field == "tanggal":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(nilai)):
            return False
        from datetime import datetime

        try:
            datetime.strptime(nilai, "%Y-%m-%d")
            return True
        except ValueError:
            return False
    if field in ("kegiatan", "deskripsi"):
        return isinstance(nilai, str) and 0 < len(nilai.strip()) <= 100
    return False


def koreksi_via_llm(data: dict, text: str, model: str = None) -> dict:
    """
    Serahkan kalimat koreksi ke LLM. Dipanggil HANYA kalau aturan menyerah.

    Hasilnya divalidasi ketat: field tak dikenal dibuang, format jam dan
    tanggal dicek. Kalau LLM balas ngawur, hasilnya kosong dan AKIRA
    bertanya lagi — bukan menulis data salah ke kalender.
    """
    from datetime import datetime

    from src.nlp.slm_extractor import DEFAULT_MODEL, _chat, _clean_json_response

    model = model or DEFAULT_MODEL
    konteks = {
        k: data.get(k)
        for k in ("kegiatan", "tanggal", "jam", "jam_selesai", "deskripsi")
        if data.get(k)
    }

    pesan = (
        f"Hari ini {datetime.now():%Y-%m-%d}.\n"
        f"Data jadwal sekarang: {json.dumps(konteks, ensure_ascii=False)}\n"
        f"Koreksi user: {text}"
    )

    # Groq lebih dulu: model di sana jauh lebih besar daripada qwen3:4b lokal,
    # dan memahami koreksi bebas adalah tugas penalaran — persis yang
    # dibutuhkan di sini. Sebelumnya jalur ini SELALU memakai model lokal,
    # sehingga penalaran terbaik yang tersedia tidak pernah dipakai untuk
    # memahami koreksi. Model lokal tetap jadi cadangan saat luring.
    mentah = None
    try:
        from src.nlp.groq_reasoner import _panggil_groq

        mentah = _panggil_groq(PROMPT_KOREKSI, pesan)
        if mentah:
            logger.debug("Koreksi dipahami lewat Groq")
    except Exception as e:
        logger.debug(f"Groq tidak tersedia untuk koreksi: {e}")

    try:
        if not mentah:
            response = _chat(
                model,
                [
                    {"role": "system", "content": PROMPT_KOREKSI},
                    {"role": "user", "content": pesan},
                ],
                {"temperature": 0.0, "num_predict": 200, "top_k": 10},
            )
            mentah = _clean_json_response(response["message"]["content"])
        hasil = json.loads(mentah)
    except json.JSONDecodeError:
        # Sering terjadi dan tidak berbahaya: hasilnya kosong, AKIRA bertanya lagi.
        logger.info("LLM tidak membalas JSON valid untuk koreksi, diabaikan")
        return {}
    except Exception as e:
        logger.warning(f"Koreksi via LLM gagal: {e}")
        return {}

    if not isinstance(hasil, dict):
        return {}

    perubahan = {}
    for field, nilai in hasil.items():
        if field not in FIELD_ALIAS:
            logger.debug(f"Field '{field}' dari LLM tidak dikenal, diabaikan")
            continue
        if not _valid(field, nilai):
            logger.warning(f"Nilai '{nilai}' untuk field '{field}' tidak valid, ditolak")
            continue
        if nilai != data.get(field):
            perubahan[field] = nilai

    if perubahan:
        logger.info(f"Koreksi (LLM) dari '{text}': {perubahan}")
    return perubahan


# Jawaban yang jelas TIDAK berisi koreksi — tidak perlu dibawa ke LLM.
# Termasuk bentuk yang diulang-ulang: "nah, nah, nah" / "hmm hmm"
TIDAK_INFORMATIF = re.compile(
    r"\A\s*(?:nah|hah|hmm+|eh|em+|anu|apa|ya|iya|oh|oke|ok|"
    r"terima\s*kasih|makasih|halo|hai)"
    r"(?:[\s,.!?]+(?:nah|hah|hmm+|eh|em+|anu|apa|ya|iya|oh|oke|ok))*"
    r"[\s,.!?]*\Z"
)


def layak_ke_llm(text: str) -> bool:
    """
    Apakah kalimat ini pantas dibawa ke LLM?

    Memanggil LLM untuk jawaban kosong atau "nah, nah, nah" cuma membuang
    2-3 detik per putaran — dan di log terlihat sebagai error JSON berulang
    yang bikin panik padahal masalahnya cuma tidak ada yang bisa diproses.
    """
    if not text or not text.strip():
        return False
    if TIDAK_INFORMATIF.match(text.strip().lower()):
        return False
    # Satu kata tanpa angka hampir tidak pernah berisi koreksi yang bisa dipakai
    kata = re.findall(r"\w+", text)
    return len(kata) >= 2 or any(k.isdigit() for k in kata)


def parse_koreksi(data: dict, text: str, use_llm: bool = True, model: str = None) -> dict:
    """
    Fasad: pahami koreksi user. Aturan dulu, LLM sebagai cadangan.
    Return dict field yang berubah (kosong kalau tidak ada koreksi terdeteksi).
    """
    perubahan = koreksi_rule_based(data, text)
    if perubahan or not use_llm:
        return perubahan

    if not layak_ke_llm(text):
        logger.debug(f"Jawaban '{text}' tidak berisi koreksi, LLM dilewati")
        return {}

    return koreksi_via_llm(data, text, model)


def terapkan(data: dict, perubahan: dict) -> list:
    """Terapkan perubahan ke data. Return daftar nama field yang berubah."""
    for field, nilai in perubahan.items():
        data[field] = nilai
    return list(perubahan)


def ucapkan_perubahan(perubahan: dict) -> str:
    """Kalimat konfirmasi singkat: 'kegiatannya jadi futsal dan jamnya jadi 16.00'."""
    from src.nlp.date_time_parser import ucapkan_tanggal

    label = {
        "kegiatan": "kegiatannya", "tanggal": "tanggalnya", "jam": "jamnya",
        "jam_selesai": "jam selesainya", "deskripsi": "catatannya",
    }
    bagian = []
    for field, nilai in perubahan.items():
        tampil = ucapkan_tanggal(nilai) if field == "tanggal" else nilai
        bagian.append(f"{label.get(field, field)} jadi {tampil}")
    return " dan ".join(bagian)


if __name__ == "__main__":
    # python -m src.nlp.correction   (tanpa LLM)
    data = {
        "aksi": "catat", "kegiatan": "berenang",
        "tanggal": "2026-09-02", "jam": "12:00",
    }
    print(f"Data awal: {data}\n")
    for kalimat in [
        "jamnya jadi 3 sore",
        "tanggalnya 3 september",
        "kegiatannya futsal",
        "bukan berenang, tapi futsal",
        "selesainya jam 5 sore",
        "catatannya bawa handuk",
        "sudah benar",
    ]:
        hasil = parse_koreksi(dict(data), kalimat, use_llm=False)
        ucap = ucapkan_perubahan(hasil) if hasil else "(tidak ada koreksi)"
        print(f"  {kalimat!r:34} -> {hasil}\n{'':38}{ucap}")
