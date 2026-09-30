"""
Fasad NLP: normalizer + intent_classifier + date_time_parser + slm_extractor
jadi satu skema JSON resmi (lihat docs/data_schema.md).
Tanggung jawab: Person 3 (NLP & Intelligence Lead) — Sprint 3

Modul lain (state_machine, app) HANYA memanggil parse_command() dari sini.

Skema hasil:
{
  "aksi": "catat" | "baca" | "hapus" | "reschedule" | "waktu" | None,
  "tanggal": "YYYY-MM-DD" | None,
  "jam": "HH:MM" | None,
  "kegiatan": str | None,
  "tanggal_mulai": "YYYY-MM-DD" | None,   # hanya untuk permintaan rentang
  "tanggal_akhir": "YYYY-MM-DD" | None,
  "label_rentang": str | None,
  "teks_asli": str
}
"""
import re

from loguru import logger

from src.nlp.date_time_parser import (
    parse_date_id,
    parse_date_range_id,
    parse_time_id,
    parse_lead_time,
    parse_jam_per_tanggal,
    parse_multi_dates,
    parse_time_range_id,
    pisah_asal_tujuan,
)
from src.nlp.intent_classifier import classify_intent, hanya_kata_benda
from src.nlp.slm_extractor import extract_entities
from src.nlp.text_normalizer import normalize

DEFAULT_MODEL = "qwen2.5:3b"


def parse_command(text: str, use_slm: bool = True, model: str = DEFAULT_MODEL) -> dict:
    """
    Ubah teks mentah hasil STT jadi skema JSON standar.

    use_slm=False -> lewati Ollama sepenuhnya (unit test cepat & mode darurat
    kalau Ollama bermasalah saat demo).
    """
    logger.info(f"Parsing perintah mentah: '{text}'")
    clean = normalize(text)

    aksi = classify_intent(clean, slm_fallback=use_slm, model=model)

    # "jadwal 3 hari ke depan" tidak punya kata kerja perintah sama sekali,
    # tapi menyebut rentang waktu — maksudnya jelas ingin dibacakan.
    if aksi is None and parse_date_range_id(clean):
        logger.info("Rentang waktu tanpa kata perintah, dianggap permintaan baca")
        aksi = "baca"

    # Satu kata benda tanpa kata kerja bukan perintah. Ini menyaring salah
    # dengar seperti "Selamat tinggal" yang direkonsiliasi jadi "Jadwal",
    # yang tanpa penjagaan ini membuat AKIRA membacakan agenda tanpa diminta.
    if hanya_kata_benda(clean):
        logger.info(f"Diabaikan, hanya kata benda tanpa perintah: '{clean}'")
        aksi = None

    result = {
        "aksi": aksi,
        "tanggal": None,
        "jam": None,
        "kegiatan": None,
        "jam_selesai": None,
        "deskripsi": None,
        "tanggal_asal": None,
        "lead_menit": None,
        "tanggal_lain": [],
        "jam_per_tanggal": {},
        "hapus_semua": False,
        "tanggal_mulai": None,
        "tanggal_akhir": None,
        "label_rentang": None,
        "teks_asli": text,
    }

    result["lead_menit"] = parse_lead_time(clean)

    # "tanggal 9, 10 dan 11 buat meeting" — semua tanggalnya dicatat, bukan
    # cuma yang pertama.
    #
    # Dihitung SEBELUM cabang aksi 'baca' keluar lebih awal, karena kalimat
    # pernyataan seperti "saya bakal ada jadwal tanggal 9, 10 dan 11" sering
    # diklasifikasi 'baca' dulu, lalu diubah jadi 'catat' oleh app setelah
    # user menyetujui tawaran pencatatan.
    semua = parse_multi_dates(clean)
    if len(semua) > 1:
        result["tanggal_lain"] = semua

    per_tanggal = parse_jam_per_tanggal(clean)
    if per_tanggal:
        result["jam_per_tanggal"] = per_tanggal
        result["tanggal_lain"] = sorted(set(result["tanggal_lain"]) | set(per_tanggal))

    # Aksi "waktu" tidak butuh parsing tanggal/kegiatan sama sekali
    if aksi == "waktu":
        logger.info(f"Hasil parsing: {result}")
        return result

    # Perintah reschedule menyebut DUA waktu: jadwal lama dan tujuan barunya.
    # Bagian setelah kata "jadi"/"ke tanggal" adalah tujuan — itu yang dipakai.
    teks_waktu = clean
    teks_kegiatan = clean
    if aksi == "reschedule":
        asal, tujuan = pisah_asal_tujuan(clean)
        if tujuan:
            teks_waktu = tujuan
            teks_kegiatan = asal
            # Tanggal di bagian ASAL menunjukkan jadwal MANA yang mau dipindah
            # ("meeting saya hari ini menjadi tanggal 31"). Dipakai untuk
            # menyaring kandidat, bukan sebagai tujuan.
            tanggal_asal = parse_date_id(asal)
            if tanggal_asal:
                result_tanggal_asal = tanggal_asal.strftime("%Y-%m-%d")
                logger.info(f"Tanggal jadwal asal: {result_tanggal_asal}")
            else:
                result_tanggal_asal = None
        else:
            result_tanggal_asal = None
    else:
        result_tanggal_asal = None

    # Rentang tanggal dicek DULU. "tahun 2026" adalah rentang, bukan satu tanggal —
    # ini yang dulu bikin AKIRA salah membacakan satu hari acak.
    # "hapus SELURUH jadwal saya" — sasarannya semua, bukan satu event
    if aksi == "hapus" and re.search(
        r"\b(?:seluruh|semua|semuanya|semua nya|keseluruhan|total)\b", clean
    ):
        result["hapus_semua"] = True
        logger.info("Permintaan hapus SEMUA jadwal terdeteksi")

    rentang = parse_date_range_id(clean)
    # Rentang berlaku untuk baca DAN hapus: "hapus jadwal minggu depan"
    if rentang and aksi in ("baca", "hapus"):
        result["tanggal_mulai"], result["tanggal_akhir"], result["label_rentang"] = rentang
        logger.info(f"Permintaan rentang terdeteksi: {rentang[2]}")
    else:
        parsed_date = parse_date_id(teks_waktu)
        result["tanggal"] = parsed_date.strftime("%Y-%m-%d") if parsed_date else None

    mulai, selesai = parse_time_range_id(teks_waktu)
    result["jam"] = mulai
    result["jam_selesai"] = selesai
    result["tanggal_asal"] = result_tanggal_asal

    # Aksi "baca" tidak perlu nama kegiatan — jangan buang waktu manggil SLM
    if aksi == "baca":
        logger.info(f"Hasil parsing: {result}")
        return result

    # Kalimat yang jelas merujuk ke jadwal yang barusan dibahas ("hapus jadwal
    # tersebut") tidak punya nama untuk diambil — namanya diisi belakangan dari
    # konteks percakapan. Memanggil SLM di sini hanya menambah jeda 10-20 detik.
    if aksi in ("hapus", "reschedule", "reminder"):
        from src.dialog.context import mengandung_rujukan

        if mengandung_rujukan(clean):
            logger.info("Perintah memakai kata rujukan, ekstraksi nama dilewati")
            logger.info(f"Hasil parsing: {result}")
            return result

    if use_slm:
        entities = extract_entities(teks_kegiatan, model=model)
        result["kegiatan"] = entities.get("kegiatan")
        skipped = entities.get("skip", False)
    else:
        from src.nlp.slm_extractor import detect_skip, extract_kegiatan_regex

        skipped = detect_skip(clean)
        result["kegiatan"] = None if skipped else extract_kegiatan_regex(teks_kegiatan)

    if skipped:
        result["_kegiatan_skipped"] = True

    logger.info(f"Hasil parsing: {result}")
    return result


def merge_answer(data: dict, field: str, answer_text: str) -> dict:
    """
    Gabungkan jawaban susulan user ke data yang sudah ada.
    Dipakai state_machine saat AKIRA nanya ulang field kosong, supaya jawaban
    "jam 3 sore" mengisi field 'jam' tanpa menimpa field lain.
    """
    from src.nlp.slm_extractor import detect_skip

    clean = normalize(answer_text)

    if detect_skip(clean):
        data[field] = None
        data[f"_{field}_skipped"] = True
        logger.info(f"Field '{field}' di-skip lewat jawaban susulan")
        return data

    if field == "tanggal":
        parsed = parse_date_id(clean)
        data["tanggal"] = parsed.strftime("%Y-%m-%d") if parsed else None
    elif field == "lead_menit":
        data[field] = parse_lead_time(clean) or parse_lead_time(clean + " sebelum")
    elif field == "jam" and data.get("tanggal_lain"):
        # Jawaban bisa menyebut jam berbeda untuk tiap tanggal:
        # "tanggal 10 jam 2 siang, tanggal 12 jam 12 siang"
        per_tanggal = parse_jam_per_tanggal(clean)
        if per_tanggal:
            data["jam_per_tanggal"] = per_tanggal
            data["jam"] = per_tanggal[sorted(per_tanggal)[0]]
            logger.info(f"Jam berbeda per tanggal: {per_tanggal}")
        else:
            data["jam"] = parse_time_id(clean)
        # Simpan kalimat asal jam. Pemeriksaan pagi/malam harus melihat
        # kalimat INI, bukan perintah awal yang mungkin tidak menyebut jam.
        data["_jam_sumber"] = clean
    elif field in ("jam", "jam_selesai"):
        # Jawaban "jam 11" maupun "sampai jam 11" sama-sama diterima
        data[field] = parse_time_id(clean.replace("sampai", " ").replace("selesai", " "))
        if field == "jam":
            data["_jam_sumber"] = clean
    elif field == "deskripsi":
        # Deskripsi bebas — jangan diproses macam-macam, cukup dirapikan
        from src.nlp.text_normalizer import strip_fillers

        data[field] = strip_fillers(answer_text.strip(" .,!?")) or None
    elif field == "kegiatan":
        # Jawaban lisan biasanya mengulang pertanyaannya: "kegiatannya meeting".
        # Kata pembuka itu harus dibuang, kalau tidak judul event jadi
        # "kegiatannya meeting" dan pencarian untuk hapus/reschedule meleset.
        from src.nlp.slm_extractor import extract_kegiatan_regex

        data[field] = extract_kegiatan_regex(clean) or clean.strip() or None
    else:
        data[field] = clean.strip() or None

    logger.info(f"Field '{field}' diisi dari jawaban: {data.get(field)}")
    return data


if __name__ == "__main__":
    # Test tanpa Ollama:  python -m src.nlp.parser
    tests = [
        "catat jadwal meeting besok jam 3 sore",
        "Catat jadwal tanggal 30 Agustus jam 9 pagi",
        "Bacakan jadwal saya untuk tahun 2026",
        "coba cek dong jadwal besok",
        "sekarang jam berapa ya akira",
        "hapus jadwal rapat divisi",
        "geser jadwal rapat ke jam 5 sore",
        "catat jadwal lusa jam 9 pagi, kegiatannya skip aja",
    ]
    for t in tests:
        print(f"\n{t!r}\n  -> {parse_command(t, use_slm=False)}")

    print("\n=== Test merge_answer ===")
    data = {"aksi": "catat", "tanggal": None, "jam": "15:00", "kegiatan": None}
    print("Sebelum:", data)
    print("Sesudah jawab 'besok':", merge_answer(data, "tanggal", "besok"))
