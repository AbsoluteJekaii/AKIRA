"""
Dialog state machine: validasi field wajib + alur tanya-ulang (slot filling).
Tanggung jawab: Person 4 (Voice Output, Dialog UX & QA Lead) — Sprint 2 versi lengkap

Skema data (lihat docs/data_schema.md):
{"aksi": "catat", "tanggal": "2026-09-10", "jam": "15:00", "kegiatan": "meeting"}
"""
import re

from loguru import logger

# Field wajib berbeda per aksi — 'baca' tidak butuh tanggal/jam, 'hapus' butuh nama kegiatan.
REQUIRED_BY_ACTION = {
    # 'kegiatan' ditaruh PALING DEPAN dan jadi wajib sejak Sprint 3.2.
    # Sebelumnya opsional, hasilnya event masuk kalender dengan judul
    # "Jadwal tanpa nama" — tidak ada gunanya buat user. Kalau memang tidak
    # mau mengisi, user tinggal bilang "skip" dan tetap dilewati.
    "catat": ["kegiatan", "tanggal", "jam"],
    "baca": [],
    # 'hapus' TIDAK lagi mewajibkan nama kegiatan sejak Sprint 3.5:
    # "hapus jadwal saya tanggal 30" cukup, karena AKIRA akan membacakan
    # kandidatnya dan meminta konfirmasi sebelum menghapus apa pun.
    # Validasi "ada kegiatan ATAU tanggal" ditangani check_missing_fields().
    "hapus": [],
    # 'jam' TIDAK wajib untuk reschedule: kalau user cuma bilang "pindahkan rapat
    # ke tanggal 31", jam aslinya dipertahankan. Bertanya "jam berapa?" padahal
    # jamnya tidak berubah cuma bikin percakapan panjang tanpa guna.
    "reschedule": ["kegiatan", "tanggal"],
    # 'reminder' butuh tahu jadwal MANA dan berapa lama sebelumnya.
    # Nama kegiatan boleh kosong kalau konteks percakapan sudah jelas
    # (ditangani check_missing_fields, seperti 'hapus').
    "reminder": ["lead_menit"],
    # 'edit' tidak butuh field apa pun di awal: AKIRA mencari jadwalnya dulu,
    # baru bertanya apa yang mau diubah.
    "edit": [],
    "waktu": [],   # pertanyaan jam/tanggal — tidak butuh field apa pun
}

OPTIONAL_FIELDS = ["kegiatan"]

# Field TAMBAHAN yang ditanyakan setelah field wajib lengkap — khusus aksi catat.
# Semuanya boleh dilewati: user tinggal bilang "skip" / "gausah" / "lewati".
OPTIONAL_BY_ACTION = {
    "catat": ["jam_selesai", "deskripsi"],
}

FIELD_QUESTIONS = {
    "tanggal": "Tanggal berapa, Bos?",
    "jam": "Jam berapa mulainya, Bos?",
    "kegiatan": "Kegiatannya apa, Bos?",
    "lead_menit": "Berapa lama sebelum acara saya ingatkan, Bos? Misalnya satu jam sebelum.",
    "periode": "Jam segitu pagi atau malam, Bos?",
    "jam_selesai": "Selesai jam berapa, Bos? Kalau tidak perlu, bilang saja lewati.",
    "deskripsi": "Ada catatan atau deskripsi tambahan, Bos? Kalau tidak ada, bilang saja lewati.",
}

# Field wajib yang tetap boleh di-skip user secara eksplisit ("skip", "gausah").
SKIPPABLE_FIELDS = ["kegiatan", "jam_selesai", "deskripsi"]

# Kata yang membatalkan seluruh perintah di tengah slot filling.
# Sebelumnya "batalkan deh" diperlakukan sebagai jawaban yang gagal diparse,
# lalu AKIRA mengulang pertanyaan yang sama sampai batas percobaan habis.
KATA_BATAL = [
    "batal", "batalkan", "gajadi", "gak jadi", "nggak jadi", "tidak jadi",
    "udahlah", "sudahlah", "lupakan", "cancel", "stop", "berhenti", "keluar",
]

_BATAL_RE = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in KATA_BATAL) + r")\b")


def minta_batal(text: str) -> bool:
    """
    True kalau user ingin membatalkan perintah yang sedang diisi.
    Dibatasi jawaban pendek supaya "batalkan jadwal rapat besok" —
    yang justru sebuah perintah — tidak ikut tertangkap.
    """
    if not text:
        return False
    t = text.lower().strip(" .,!?")

    # "batalkan jadwal rapat besok" itu PERINTAH hapus, bukan pembatalan
    # pengisian. Kalau menyebut objek jadwal, jangan diperlakukan sebagai batal.
    if re.search(r"\b(?:jadwal|acara|agenda|kegiatan|meeting|rapat)\b", t):
        return False

    # Bentuk berulang karena user menegaskan: "batalkan, batalkan semuanya"
    kata = [k for k in t.split() if k not in ("semua", "semuanya", "aja", "saja", "dong", "deh", "ya")]
    if len(kata) > 3:
        return False
    return bool(_BATAL_RE.search(t))

MAX_RETRY_PER_FIELD = 3


def get_required_fields(data: dict) -> list:
    """Ambil daftar field wajib sesuai aksi yang terdeteksi."""
    aksi = data.get("aksi")
    return REQUIRED_BY_ACTION.get(aksi, ["tanggal", "jam"])


def check_missing_fields(data: dict) -> list:
    """Cek field wajib mana yang masih kosong (field yang di-skip user tidak dihitung kosong)."""
    required = get_required_fields(data)
    missing = []
    for field in required:
        if data.get(f"_{field}_skipped"):
            continue
        if not data.get(field):
            missing.append(field)

    # 'hapus' butuh SALAH SATU dari nama kegiatan atau tanggal — bukan keduanya.
    # Kalau dua-duanya kosong, tanyakan nama kegiatan.
    if data.get("aksi") in ("hapus", "reminder") and not data.get("kegiatan") and not data.get("tanggal"):
        missing.append("kegiatan")

    return missing


def is_complete(data: dict) -> bool:
    return len(check_missing_fields(data)) == 0


def get_next_question(data: dict) -> tuple[str, str] | None:
    """
    Return (nama_field, pertanyaan) untuk field kosong berikutnya.
    Return None kalau semua field wajib sudah lengkap.
    """
    missing = check_missing_fields(data)
    if not missing:
        return None
    field = missing[0]

    # Kalau field tanggal kosong dan ada peringatan dari Groq (misal "32 Januari
    # tidak valid"), sampaikan ke user supaya dia tahu kenapa tanggalnya ditolak.
    if field == "tanggal":
        from src.nlp.intent_classifier import ambil_peringatan
        from src.nlp.groq_reasoner import deteksi_tanggal_mustahil

        # Cek peringatan dari Groq (diisi saat classify_intent)
        peringatan = ambil_peringatan()
        if peringatan:
            return field, f"{peringatan}. Tanggal berapa yang benar, Bos?"

        # Cek juga dari teks_asli (kalau keyword berhasil tapi tanggal mustahil)
        teks_asli = data.get("teks_asli", "")
        if teks_asli:
            peringatan = deteksi_tanggal_mustahil(teks_asli)
            if peringatan:
                return field, f"{peringatan}. Tanggal berapa yang benar, Bos?"

    return field, FIELD_QUESTIONS.get(field, f"Tolong sebutkan {field}-nya, Bos.")


def perlu_perjelas_jam(data: dict) -> bool:
    """
    True kalau jam yang tertangkap ambigu — bisa pagi atau malam.
    Lebih baik bertanya sekali daripada membuat jadwal 12 jam meleset.
    """
    from src.nlp.date_time_parser import jam_ambigu

    if data.get("aksi") not in ("catat", "reschedule"):
        return False
    if not data.get("jam") or data.get("_periode_dikonfirmasi"):
        return False

    # Periksa kalimat tempat jam itu DISEBUT. Sebelumnya selalu memeriksa
    # perintah awal — kalau jamnya baru disebut di jawaban ("jam 7"),
    # perintah awal tidak memuat jam sama sekali, dianggap tidak ambigu,
    # dan "makan malam jam 7" tersimpan pukul 07.00.
    sumber = data.get("_jam_sumber") or data.get("teks_asli", "")
    if not jam_ambigu(sumber):
        return False

    # Nama kegiatan sering sudah menjawab pertanyaannya sendiri.
    # "makan malam" + "jam 7" jelas 19.00 — bertanya justru terdengar bodoh.
    if tebak_periode_dari_kegiatan(data):
        return False
    return True


# Kata dalam nama kegiatan yang memastikan periode waktu.
_PERIODE_DARI_KEGIATAN = {
    "malam": "malam", "dinner": "malam", "isya": "malam", "maghrib": "malam",
    "sore": "sore", "ashar": "sore",
    "pagi": "pagi", "sarapan": "pagi", "subuh": "pagi", "breakfast": "pagi",
    "siang": "siang", "lunch": "siang", "dzuhur": "siang", "zuhur": "siang",
}


def tebak_periode_dari_kegiatan(data: dict) -> bool:
    """
    Kalau nama kegiatan memastikan periodenya, terapkan tanpa bertanya.

    Return True kalau berhasil menebak (dan jam sudah disesuaikan).
    """
    kegiatan = (data.get("kegiatan") or "").lower()
    for kata, periode in _PERIODE_DARI_KEGIATAN.items():
        if re.search(rf"\b{kata}\b", kegiatan):
            perjelas_periode(data, periode)
            logger.info(f"Periode '{periode}' disimpulkan dari kegiatan '{kegiatan}'")
            return True
    return False


def perjelas_periode(data: dict, jawaban: str) -> dict:
    """
    Terapkan jawaban "pagi"/"malam" ke jam yang sudah tertangkap.
    "jam 10" + "malam" -> 22:00
    """
    from src.nlp.date_time_parser import _adjust_period, _cari_periode

    periode = _cari_periode((jawaban or "").lower())
    data["_periode_dikonfirmasi"] = True

    if not periode or not data.get("jam"):
        logger.info("Periode tidak jelas, jam dibiarkan seperti tertangkap")
        return data

    jam, menit = (int(x) for x in data["jam"].split(":"))
    jam_baru = _adjust_period(jam % 12, periode)
    data["jam"] = f"{jam_baru:02d}:{menit:02d}"
    logger.info(f"Jam diperjelas jadi {data['jam']} ({periode})")
    return data


def get_optional_fields(data: dict) -> list:
    """Field tambahan yang perlu ditanyakan untuk aksi ini (boleh dilewati)."""
    return OPTIONAL_BY_ACTION.get(data.get("aksi"), [])


def get_next_optional_question(data: dict) -> tuple[str, str] | None:
    """
    Field opsional berikutnya yang belum ditanyakan.
    Field yang sudah terisi atau sudah di-skip tidak ditanya lagi.
    """
    for field in get_optional_fields(data):
        if data.get(field) or data.get(f"_{field}_skipped"):
            continue
        return field, FIELD_QUESTIONS.get(field, f"Isi {field}-nya, Bos?")
    return None


def apply_skip(data: dict, field: str) -> dict:
    """Tandai field sebagai di-skip secara eksplisit."""
    if field in OPTIONAL_FIELDS or field in SKIPPABLE_FIELDS:
        data[field] = None
        data[f"_{field}_skipped"] = True
        logger.info(f"Field '{field}' di-skip")
    else:
        logger.warning(f"Field '{field}' wajib, tidak bisa di-skip")
    return data


def build_confirmation(data: dict) -> str:
    """Kalimat konfirmasi sebelum eksekusi (dibacakan TTS)."""
    aksi_label = {
        "catat": "mencatat",
        "hapus": "menghapus",
        "reschedule": "memindahkan",
        "baca": "membacakan",
        "waktu": "mengecek waktu",
    }.get(data.get("aksi"), "memproses")

    kegiatan = data.get("kegiatan") or "jadwal tanpa nama"

    if data.get("aksi") in ("baca", "waktu"):
        return "Baik Bos."
    if data.get("aksi") in ("hapus", "reminder", "edit"):
        return "Baik Bos, saya cek dulu jadwalnya."
    from src.nlp.date_time_parser import ucapkan_tanggal

    tanggal = (
        ucapkan_tanggal(data["tanggal"], sebut_hari=True)
        if data.get("tanggal")
        else "tanggal yang disebutkan"
    )

    # Jam boleh kosong untuk reschedule — jam asli event dipertahankan.
    if data.get("jam"):
        waktu = f"{tanggal} jam {data['jam']}"
    else:
        waktu = f"{tanggal}, jam tetap seperti semula"

    return f"Baik Bos, saya akan {aksi_label} {kegiatan} ke {waktu}." \
        if data.get("aksi") == "reschedule" \
        else f"Baik Bos, saya akan {aksi_label} {kegiatan} pada {waktu}."


def build_ringkasan(data: dict) -> str:
    """
    Ringkasan lengkap sebelum benar-benar dieksekusi, untuk dikonfirmasi user.
    Beda dengan build_confirmation() yang cuma menyatakan niat, ini membacakan
    SEMUA detail yang terkumpul — termasuk field opsional — supaya salah dengar
    ketahuan sebelum masuk kalender, bukan sesudah.
    """
    from src.nlp.date_time_parser import ucapkan_tanggal

    bagian = [f"kegiatan {data.get('kegiatan') or 'tanpa nama'}"]

    # Beberapa tanggal sekaligus — sebutkan semuanya supaya user bisa
    # mengoreksi sebelum tiga event terlanjur dibuat.
    banyak = data.get("tanggal_lain") or []
    per_tanggal = data.get("jam_per_tanggal") or {}

    if len(banyak) > 1:
        # Nama hari selalu disebut, dan jam per tanggal kalau berbeda-beda.
        # Kalau jamnya digabung jadi satu, user tidak punya kesempatan
        # menyadari yang salah sebelum beberapa jadwal terlanjur dibuat.
        from src.nlp.date_time_parser import gabung_tanggal

        keg_per = data.get("kegiatan_per_tanggal") or {}
        if keg_per:
            # Kegiatan berbeda tiap hari: sebut pasangan hari-kegiatan-jam
            rincian = gabung_tanggal(banyak, per_tanggal, keg_per)
            return f"Saya rangkum dulu ya Bos: {rincian}. Sudah benar?"

        bagian.append(f"pada {gabung_tanggal(banyak, per_tanggal)}")
        if per_tanggal:
            return "Saya rangkum dulu ya Bos: " + ", ".join(bagian) + ". Sudah benar?"
    elif data.get("tanggal"):
        bagian.append(f"pada {ucapkan_tanggal(data['tanggal'], sebut_hari=True)}")
    if data.get("jam"):
        waktu = f"jam {data['jam']}"
        if data.get("jam_selesai"):
            waktu += f" sampai {data['jam_selesai']}"
        bagian.append(waktu)
    if data.get("deskripsi"):
        bagian.append(f"dengan catatan {data['deskripsi']}")

    return "Saya rangkum dulu ya Bos: " + ", ".join(bagian) + ". Sudah benar?"


def run_optional_filling(data: dict, ask_fn, listen_fn, merge_fn) -> dict | None:
    """
    Tanyakan field opsional satu per satu.

    Jawaban kosong atau tidak terparse dianggap dilewati — field opsional
    tidak boleh menghambat user menyelesaikan perintah.

    Tapi PEMBATALAN tetap dihormati. Sebelumnya tidak, dan akibatnya fatal:
    user berkata "batalkan semuanya", kalimat itu gagal diparse sebagai jam,
    lalu dianggap "lewati" dan perintahnya tetap berjalan sampai tersimpan.
    Perintah yang diminta batal justru diteruskan.

    Return data, atau None kalau user membatalkan.
    """
    while True:
        next_q = get_next_optional_question(data)
        if next_q is None:
            return data

        field, question = next_q
        ask_fn(question)
        answer = listen_fn()

        if minta_batal(answer):
            logger.info(f"User membatalkan saat mengisi '{field}' (opsional)")
            ask_fn("Baik Bos, saya batalkan.")
            return None

        if not answer or not answer.strip():
            logger.info(f"Field opsional '{field}' dilewati (tidak dijawab)")
            data = apply_skip(data, field)
            continue

        data = merge_fn(data, field, answer)
        if not data.get(field) and not data.get(f"_{field}_skipped"):
            logger.info(f"Field opsional '{field}' dilewati (jawaban tidak terparse)")
            data = apply_skip(data, field)


def run_slot_filling(data: dict, ask_fn, listen_fn, merge_fn) -> dict | None:
    """
    Loop tanya-ulang sampai semua field wajib terisi.

    Parameter berupa fungsi supaya modul ini bisa diuji tanpa mic/speaker asli
    (dependency injection) — saat produksi diisi speaker.speak / recorder+STT / parser.merge_answer.

    ask_fn(text)         -> ucapkan pertanyaan ke user
    listen_fn()          -> rekam & transkripsi jawaban user, return str
    merge_fn(data, field, answer) -> gabungkan jawaban ke data, return data

    Return data lengkap, atau None kalau user gagal menjawab berulang kali.
    """
    while True:
        next_q = get_next_question(data)
        if next_q is None:
            logger.info("Semua field wajib lengkap")
            return data

        field, question = next_q
        filled = False

        for attempt in range(1, MAX_RETRY_PER_FIELD + 1):
            ask_fn(question)
            answer = listen_fn()

            if not answer or not answer.strip():
                logger.warning(f"Jawaban kosong untuk '{field}' (percobaan {attempt})")
                continue

            if minta_batal(answer):
                logger.info(f"User membatalkan saat mengisi '{field}'")
                ask_fn("Baik Bos, saya batalkan.")
                return None

            data = merge_fn(data, field, answer)

            if data.get(field) or data.get(f"_{field}_skipped"):
                filled = True
                break

            # Kalau field tanggal gagal diparse, cek apakah jawabannya
            # mengandung tanggal mustahil — sampaikan ke user supaya dia
            # tahu KENAPA ditolak, bukan cuma ditanya ulang.
            if field == "tanggal":
                from src.nlp.groq_reasoner import deteksi_tanggal_mustahil

                peringatan = deteksi_tanggal_mustahil(answer)
                if peringatan:
                    question = f"{peringatan}. Tanggal berapa yang benar, Bos?"
                    logger.info(f"Tanggal mustahil di jawaban: {peringatan}")
                    continue

            logger.warning(f"Gagal parse jawaban '{answer}' untuk field '{field}' (percobaan {attempt})")

        if not filled:
            ask_fn(f"Maaf Bos, saya belum menangkap {field}-nya. Perintah dibatalkan.")
            logger.error(f"Slot filling gagal untuk field '{field}' setelah {MAX_RETRY_PER_FIELD} percobaan")
            return None


if __name__ == "__main__":
    # Test tanpa mic/speaker — simulasi jawaban user pakai fungsi dummy:
    #   python -m src.dialog.state_machine
    from src.nlp.parser import merge_answer

    print("=== Test validasi per aksi ===")
    cases = [
        {"aksi": "catat", "tanggal": "2026-09-10", "jam": "15:00", "kegiatan": "meeting"},
        {"aksi": "catat", "tanggal": None, "jam": "15:00", "kegiatan": None},
        {"aksi": "baca", "tanggal": None, "jam": None, "kegiatan": None},
        {"aksi": "hapus", "tanggal": None, "jam": None, "kegiatan": "rapat"},
        {"aksi": "hapus", "tanggal": None, "jam": None, "kegiatan": None},
    ]
    for c in cases:
        print(f"{c}\n  missing: {check_missing_fields(c)} | complete: {is_complete(c)} | next: {get_next_question(c)}\n")

    print("=== Simulasi slot filling (jawaban user dipalsukan) ===")
    data = {"aksi": "catat", "tanggal": None, "jam": None, "kegiatan": "meeting"}
    fake_answers = iter(["besok", "jam 3 sore"])

    result = run_slot_filling(
        data,
        ask_fn=lambda q: print(f"  AKIRA: {q}"),
        listen_fn=lambda: next(fake_answers, ""),
        merge_fn=merge_answer,
    )
    print(f"  Hasil akhir: {result}")
    print(f"  Konfirmasi: {build_confirmation(result)}")
