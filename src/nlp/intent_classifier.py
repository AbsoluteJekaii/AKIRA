"""
Klasifikasi aksi: catat / baca / hapus / reschedule / waktu.
Tanggung jawab: Person 3 (NLP & Intelligence Lead) — Sprint 3

Perubahan dari Sprint 2:
1. Pencocokan frasa jadi LONGGAR (tidak harus berdampingan).
   "coba cek dong jadwal besok" sekarang cocok dengan frasa "cek jadwal",
   karena di antara kedua kata boleh ada maksimal 3 kata lain.
   Ini penyebab utama AKIRA dulu cuma paham kalimat kaku.
2. Daftar keyword diperluas ke bahasa sehari-hari.
3. Aksi baru "waktu" untuk pertanyaan "sekarang jam berapa" / "tanggal berapa".
4. Kalau skor imbang, pemenang ditentukan urutan prioritas — tidak lagi
   langsung menyerah ke SLM (yang lambat dan kadang meleset).
"""
import re

from loguru import logger

# Bobot: frasa lebih spesifik dapat skor lebih tinggi supaya menang
# saat satu kalimat mengandung beberapa keyword sekaligus.
INTENT_KEYWORDS = {
    "waktu": {
        4: ["jam berapa", "tanggal berapa", "hari apa", "pukul berapa",
            "tahun berapa", "bulan apa"],
        2: ["waktu sekarang", "jam sekarang", "tanggal hari ini"],
    },
    "reminder": {
        4: ["ingatkan sebelum", "ingetin sebelum", "kasih tau sebelum",
            "peringatkan sebelum", "bangunkan sebelum"],
        3: ["setel pengingat", "atur pengingat", "pasang pengingat",
            "set reminder", "atur reminder", "buat pengingat", "ubah pengingat"],
        2: ["pengingat", "reminder"],
    },
    "edit": {
        4: ["edit jadwal", "ubah isi jadwal", "ganti nama jadwal",
            "ubah nama jadwal", "perbaiki jadwal", "koreksi jadwal",
            "ganti judul jadwal", "ubah detail"],
        3: ["edit", "sunting", "perbarui jadwal", "update jadwal"],
    },
    "catat": {
        3: ["catat jadwal", "tambah jadwal", "buat jadwal", "bikin jadwal",
            "masukkan jadwal", "set jadwal", "atur jadwal", "jadwalkan",
            "tambah acara", "buat acara", "bikin acara", "buat agenda",
            "ciptakan jadwal", "create jadwal", "bikin acara", "masukin jadwal",
            "susun jadwal", "pasang jadwal", "input jadwal"],
        2: ["catat", "tambahkan", "simpan", "daftarkan"],
        1: ["tambah", "buat", "bikin", "atur", "set", "daftar", "ciptakan", "create"],
    },
    "baca": {
        3: ["jadwal apa", "agenda apa", "acara apa", "ada jadwal apa", "ada jadwal", "punya jadwal", "ada acara", "ada agenda",
            "apakah ada", "apa ada", "lihat jadwal", "cek jadwal", "baca jadwal",
            "bacakan jadwal", "sebutkan jadwal", "tampilkan jadwal",
            "kasih tau jadwal", "info jadwal", "jadwal apa saja",
            "apa saja jadwal", "jadwal saya apa", "cek agenda", "lihat agenda",
            "ada acara apa", "ada apa saja", "gimana jadwal", "bagaimana jadwal",
            "review jadwal", "periksa jadwal",
            # Cara orang bertanya sehari-hari — tidak menyebut kata "jadwal" sama sekali
            "ada kerjaan", "ada kesibukan", "ada kegiatan", "sibuk nggak", "sibuk gak",
            "sibuk ga", "kosong nggak", "kosong gak", "free nggak", "free gak",
            "ngapain aja", "ada apa aja", "lagi ada apa", "ada urusan"],
        2: ["bacakan", "sebutkan", "tampilkan", "tunjukkan", "kasih tau",
            "beritahu", "ada apa"],
        # CATATAN: kata "jadwal"/"agenda" telanjang SENGAJA tidak dimasukkan.
        # Hampir semua perintah mengandung kata itu ("buat jadwal", "hapus jadwal"),
        # jadi memberinya skor bikin 'baca' ikut menang di perintah yang bukan baca.
        1: ["lihat", "cek", "baca", "periksa"],
    },
    "hapus": {
        3: ["hapus jadwal", "batalkan jadwal", "cancel jadwal", "hilangkan jadwal",
            "buang jadwal", "hapus acara", "batalkan acara"],
        2: ["hapus", "batalkan", "hilangkan", "cancel", "delete"],
        1: ["buang"],
    },
    "reschedule": {
        3: ["ubah jadwal", "pindah jadwal", "geser jadwal", "ganti jadwal",
            "reschedule", "undur jadwal", "majukan jadwal", "pindahkan jadwal",
            "ubah waktu", "ganti waktu"],
        2: ["undur", "majukan", "pindahkan", "geser", "reschedule"],
        1: ["ubah", "ganti", "pindah"],
    },
}

# Urutan prioritas saat skor imbang. Aksi yang lebih spesifik menang,
# 'baca' paling akhir karena kata "jadwal" saja sering ikut ke kalimat lain.
PRIORITY = ["waktu", "reminder", "edit", "reschedule", "hapus", "catat", "baca"]


VALID_INTENTS = set(INTENT_KEYWORDS.keys())

# Maksimal kata sisipan yang diizinkan di antara kata-kata satu frasa.
MAX_GAP_WORDS = 3


# Intent yang frasanya harus PERSIS berdampingan, tanpa sisipan kata.
# 'waktu' masuk sini karena pola longgar bikin "jadwal saya hari ini apa aja ya"
# cocok dengan frasa "hari apa" (lewat sisipan "ini ... aja"), sehingga
# pertanyaan tentang jadwal salah dijawab dengan jam dinding.
INTENT_TANPA_SISIPAN = {"waktu"}


def _phrase_regex(phrase: str, max_gap: int = MAX_GAP_WORDS) -> str:
    """
    Ubah frasa jadi regex: kata-katanya harus muncul berurutan, boleh disisipi
    sampai `max_gap` kata lain.

    "cek jadwal" -> cocok dengan "cek dong jadwal", "cek lah jadwal saya"
    max_gap=0    -> harus persis berdampingan
    """
    words = [re.escape(w) for w in phrase.split()]
    if max_gap == 0:
        return r"\b" + r"\s+".join(words) + r"\b"
    gap = rf"(?:\s+\w+){{0,{max_gap}}}\s+"
    return r"\b" + gap.join(words) + r"\b"


# Precompile sekali saat import — jangan compile ulang tiap perintah masuk.
_COMPILED = {
    intent: {
        weight: [
            re.compile(
                _phrase_regex(kw, 0 if intent in INTENT_TANPA_SISIPAN else MAX_GAP_WORDS)
            )
            for kw in keywords
        ]
        for weight, keywords in weighted.items()
    }
    for intent, weighted in INTENT_KEYWORDS.items()
}


def score_intents(text: str) -> dict:
    """Hitung skor tiap intent berdasarkan keyword yang muncul di kalimat."""
    text_lower = text.lower()
    scores = {intent: 0 for intent in INTENT_KEYWORDS}

    for intent, weighted in _COMPILED.items():
        for weight, patterns in weighted.items():
            for pattern in patterns:
                if pattern.search(text_lower):
                    scores[intent] += weight
                    break  # satu frasa per bobot sudah cukup, hindari skor menggelembung
    return scores


# Pertanyaan KETERSEDIAAN: "hari ini saya kosong ga?", "besok sibuk nggak?".
# Kalimat begini tidak menyebut kata "jadwal" sama sekali dan tidak punya kata
# kerja perintah, jadi penilaian keyword biasa selalu meleset.
KETERSEDIAAN = re.compile(
    r"\b(?:kosong|sibuk|padat|penuh|santai|lowong|available|bebas)\b"
)


def _tanya_ketersediaan(text: str) -> bool:
    """
    True untuk pertanyaan seperti "hari ini saya kosong ga?".
    Harus berupa PERTANYAAN — "kosongin aja" (perintah skip) tidak boleh ikut.
    """
    t = text.lower()
    if not KETERSEDIAAN.search(t):
        return False
    # Bentuk perintah, bukan pertanyaan
    if re.search(r"\bkosong(?:in|kan|i)\b", t):
        return False
    return bool(
        re.search(r"\b(?:ga|gak|nggak|enggak|engga|tidak|kah|apa|apakah)\b|\?", t)
    )


# Kata benda yang berdiri sendiri BUKAN perintah. "Jadwal" saja tidak
# menyatakan apakah user ingin melihat, membuat, atau menghapus — dan di log
# kata itu muncul dari salah dengar "Selamat tinggal", lalu AKIRA
# membacakan agenda tanpa diminta.
KATA_BENDA_SENDIRIAN = {
    "jadwal", "jadwalnya", "agenda", "agendanya", "acara", "acaranya",
    "kegiatan", "kegiatannya", "kalender", "waktu", "jam", "tanggal",
    "hari", "besok", "sekarang", "nanti",
}


def hanya_kata_benda(text: str) -> bool:
    """
    True kalau kalimat cuma satu kata benda tanpa kata kerja.

    Ucapan sependek ini hampir selalu hasil salah dengar. Memperlakukannya
    sebagai perintah membuat AKIRA bertindak atas sesuatu yang tidak pernah
    diucapkan user.
    """
    kata = [k for k in re.findall(r"\w+", (text or "").lower()) if k]
    if len(kata) != 1:
        return False
    return kata[0] in KATA_BENDA_SENDIRIAN


def classify_intent_keyword(text: str) -> str | None:
    """
    Klasifikasi berbasis keyword.
    Return None HANYA kalau tidak ada keyword sama sekali.
    Skor imbang diselesaikan lewat urutan PRIORITY, bukan menyerah ke SLM.
    """
    from src.nlp.date_time_parser import parse_lead_time

    # Kalimat yang menyebut jeda "X sebelum acara" hampir pasti pengaturan
    # pengingat, bukan pembuatan jadwal baru — "ingatkan saya 1 jam sebelum
    # meeting" dulu terbaca 'catat' dan bikin event duplikat.
    if parse_lead_time(text) is not None:
        logger.info(f"Jeda pengingat terdeteksi, intent 'reminder': '{text}'")
        return "reminder"

    if _tanya_ketersediaan(text):
        logger.info(f"Pertanyaan ketersediaan terdeteksi, intent 'baca': '{text}'")
        return "baca"

    scores = score_intents(text)
    max_score = max(scores.values())

    if max_score == 0:
        logger.debug(f"Tidak ada keyword intent yang cocok di: '{text}'")
        return None

    winners = [intent for intent, s in scores.items() if s == max_score]
    if len(winners) > 1:
        winner = min(winners, key=lambda i: PRIORITY.index(i))
        logger.info(f"Skor imbang {winners}, dipilih '{winner}' lewat prioritas")
        return winner

    logger.debug(f"Intent '{winners[0]}' (skor {max_score}) dari: '{text}'")
    return winners[0]


def classify_intent(text: str, slm_fallback: bool = True, model: str = "qwen2.5:3b") -> str | None:
    """
    Klasifikasi utama yang dipakai pipeline.
    Keyword dulu; Groq (bisa nalar) kalau keyword menyerah; SLM terakhir.
    """
    intent = classify_intent_keyword(text)
    if intent:
        return intent

    if not slm_fallback:
        return None

    # Groq lebih dulu — model 20B+ jauh lebih pintar nalar daripada qwen3:4b.
    # Contoh: "saya ada kondangan tanggal 5 Januari" → Groq paham ini 'catat',
    # qwen3:4b salah klasifikasi jadi 'baca'.
    logger.info("Tidak ada keyword cocok, fallback ke Groq untuk klasifikasi intent")
    try:
        from src.nlp.groq_reasoner import classify_intent_groq

        groq_intent, peringatan = classify_intent_groq(text)
        if peringatan:
            # Simpan peringatan (misal "32 Januari tidak valid") agar dialog
            # bisa menyampaikannya ke user, bukan cuma diam-diam bertanya ulang.
            _PERINGATAN_TERAKHIR["teks"] = peringatan
            logger.info(f"Groq peringatan: {peringatan}")
        if groq_intent in VALID_INTENTS:
            return groq_intent
    except Exception as e:
        logger.warning(f"Groq fallback gagal: {e}")

    # Jaring terakhir: SLM lokal (qwen3:4b). Lebih lambat dan kurang pintar,
    # tapi tidak butuh internet.
    logger.info("Groq tidak berhasil, coba SLM lokal")
    try:
        from src.nlp.slm_extractor import classify_intent_slm

        slm_intent = classify_intent_slm(text, model=model)
        if slm_intent in VALID_INTENTS:
            return slm_intent
    except Exception as e:
        logger.error(f"SLM fallback gagal: {e}")

    return None


# Peringatan dari Groq tentang data yang bermasalah (misal tanggal mustahil).
# Diakses state_machine.py untuk disampaikan ke user.
_PERINGATAN_TERAKHIR = {"teks": None}


def ambil_peringatan() -> str | None:
    """Ambil dan hapus peringatan terakhir dari Groq. Sekali pakai."""
    peringatan = _PERINGATAN_TERAKHIR.get("teks")
    _PERINGATAN_TERAKHIR["teks"] = None
    return peringatan


# Penanda kalimat TANYA. Kalau salah satu muncul, kalimatnya bukan pernyataan.
PENANDA_TANYA = re.compile(
    r"\b(?:apa|apakah|berapa|kapan|mana|gimana|bagaimana|kah)\b"
    r"|\b(?:ga|gak|nggak|enggak|engga|tidak|belum)\s*\??\s*$"
    r"|\?"
)

# "saya ada X", "aku punya X", "besok saya ada X"
POLA_PERNYATAAN = re.compile(
    r"\b(?:saya|aku|gue|gua)\s+(?:ada|punya|mau|akan|harus|bakal|mesti)\b"
)


def deteksi_pernyataan_jadwal(text: str) -> bool:
    """
    True kalau kalimatnya MEMBERITAHU adanya kegiatan, bukan MENANYAKAN.

    "besok saya ada kondangan jam 1 siang"  -> True  (user memberi tahu)
    "saya ada kondangan tanggal 32 Januari" -> True  (tanggal mustahil, tapi
                                                       polanya tetap pernyataan)
    "besok ada kegiatan ga?"                -> False (user bertanya)
    "cek jadwal besok"                      -> False (perintah)

    Dipakai app.py untuk menawarkan: "Mau saya catatkan?" — jauh lebih natural
    daripada memperlakukan pernyataan sebagai perintah baca.
    """
    if not text:
        return False
    t = text.lower().strip()

    if PENANDA_TANYA.search(t):
        return False
    if not POLA_PERNYATAAN.search(t):
        return False

    # Harus ada petunjuk waktu — tanpa itu, kalimatnya terlalu kabur untuk
    # ditawarkan sebagai jadwal ("saya ada uang", "saya mau makan").
    # Cek dua hal: parse_date_id (tanggal valid) DAN ada_pola_tanggal (pola
    # yang terlihat seperti tanggal, termasuk yang mustahil seperti "32 Januari").
    from src.nlp.date_time_parser import parse_date_id, parse_time_id
    from src.nlp.groq_reasoner import ada_pola_tanggal

    if parse_time_id(t) is not None:
        logger.info(f"Kalimat terdeteksi sebagai pernyataan jadwal: '{text}'")
        return True
    if parse_date_id(t) is not None:
        logger.info(f"Kalimat terdeteksi sebagai pernyataan jadwal: '{text}'")
        return True
    if ada_pola_tanggal(t):
        logger.info(f"Kalimat terdeteksi sebagai pernyataan jadwal (pola tanggal): '{text}'")
        return True

    return False


if __name__ == "__main__":
    tests = [
        "catat jadwal meeting besok jam 3",
        "hapus jadwal rapat divisi",
        "ada jadwal apa hari ini",
        "coba cek dong jadwal besok",
        "bacakan jadwal saya untuk tahun 2026",
        "sekarang jam berapa ya akira",
        "sekarang tanggal berapa",
        "geser jadwal rapat ke jam 5 sore",
        "tolong tambahkan meeting dengan klien",
        "gimana jadwal saya minggu ini",
        "halo apa kabar",
    ]
    for t in tests:
        print(f"{t!r}\n  -> {classify_intent_keyword(t)} | skor: {score_intents(t)}\n")
