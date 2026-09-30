"""
Normalisasi teks hasil STT sebelum masuk ke NLP.
Tanggung jawab: Person 3 (NLP & Intelligence Lead) — Sprint 3

Kenapa modul ini ada:
Whisper `small` sering salah eja kata Indonesia ("jadual", "cata", "bahsok")
dan kadang menulis angka sebagai kata ("dua ribu dua puluh enam").
Kalau teks mentah langsung dilempar ke intent classifier & dateparser,
kesalahan kecil ini bikin seluruh pipeline gagal.

Membersihkan di satu tempat JAUH lebih murah daripada menaikkan ukuran model Whisper.
"""
import re

from loguru import logger

# --- 1. Koreksi salah eja umum dari Whisper Indonesia ---------------------
# Kunci = pola regex, nilai = pengganti. Semua dicek pada teks lowercase.
SPELLING_FIXES = {
    r"\bjadual\b": "jadwal",
    r"\bjadwalku\b": "jadwal saya",
    r"\bjadwalnya\b": "jadwal",
    r"\bjadwal2\b": "jadwal",
    r"\bcata\b": "catat",
    r"\bcatet\b": "catat",
    r"\bsatap\b": "catat",
    r"\bbahsok\b": "besok",
    r"\bbesuk\b": "besok",
    r"\bbsk\b": "besok",
    r"\bmuting\b": "meeting",
    r"\bmiting\b": "meeting",
    r"\bmeting\b": "meeting",
    r"\bhapusin\b": "hapus",
    r"\bilangin\b": "hapus",
    r"\bbatalin\b": "batalkan",
    r"\bgeserin\b": "geser",
    r"\bpindahin\b": "pindah",
    r"\bbacain\b": "bacakan",
    r"\bcekin\b": "cek",
    r"\bliat\b": "lihat",
    r"\bngecek\b": "cek",
    r"\bmau tau\b": "cek",
    r"\bpukul\b": "jam",
    r"\btgl\b": "tanggal",
    r"\bthn\b": "tahun",
    r"\bskrg\b": "sekarang",
    r"\bskrng\b": "sekarang",
    r"\bgmn\b": "gimana",
    r"\bapa aja\b": "apa saja",
    r"\bkedepan\b": "ke depan",
    # Akhiran -kan/-in pada kata perintah. Tanpa ini "buatkan jadwal" tidak
    # cocok dengan frasa "buat jadwal" dan salah terbaca sebagai perintah BACA.
    r"\bbuatkan\b": "buat",
    r"\bbuatin\b": "buat",
    r"\bbikinkan\b": "bikin",
    r"\bbikinin\b": "bikin",
    r"\bcatatkan\b": "catat",
    # Ditemukan saat menguji contoh untuk panduan: "tambahin jadwal kuliah
    # lusa" tidak dikenali sama sekali, padahal bentuk santai ini yang paling
    # sering diucapkan.
    r"\btambahin\b": "tambah",
    r"\bnambahin\b": "tambah",
    r"\bcatetin\b": "catat",
    r"\bcatatin\b": "catat",
    r"\bapusin\b": "hapus",
    r"\bingetin\b": "ingatkan",
    r"\bjadwalin\b": "jadwalkan",
    r"\bsetkan\b": "set",
    r"\baturkan\b": "atur",
    r"\bmasukin\b": "masukkan",
    r"\bgeserkan\b": "geser",
    r"\bundurkan\b": "undur",
    r"\bmajuin\b": "majukan",
    r"\bgantiin\b": "ganti",
    r"\bubahin\b": "ubah",
    r"\bceknya\b": "cek",
    # Whisper rutin salah dengar kata perintah ini
    r"\bsetelah\s+(pengingat|alarm|reminder|timer)\b": r"setel \1",
    r"\bsetelahkan\b": "setel",
    r"\bsetelkan\b": "setel",
    r"\bsetting\b": "setel",
    r"\bminit\b": "menit",
    r"\b(?:katatan|catetan|cattan)(?:nya)?\b": "catatan",
    r"\b(?:kegiatanya|kegiatanny)\b": "kegiatan",
    r"\bmenitnya\b": "menit",
    r"\bdetiknya\b": "detik",
    r"\bjamnya\s+lagi\b": "jam lagi",
    # --- Slang & singkatan percakapan sehari-hari -----------------------
    # Dinormalkan ke bentuk baku supaya keyword dan SLM sama-sama mengenalinya.
    r"\b(?:gue|gua|gw|aye|ane)\b": "saya",
    r"\b(?:lu|lo|elu|elo)\b": "kamu",
    r"\b(?:kagak|kaga|ogah)\b": "tidak",
    r"\b(?:udh|udah|dah|wes|uda)\b": "sudah",
    r"\b(?:blm|belom|blom)\b": "belum",
    r"\b(?:ntar|entar|ntr|bentar|sbentar)\b": "nanti",
    r"\b(?:gimana|gmn|piye)\b": "bagaimana",
    r"\b(?:kalo|klo|kl)\b": "kalau",
    r"\b(?:aja|doang|doangan)\b": "saja",
    r"\b(?:banget|bgt|pisan)\b": "sekali",
    r"\b(?:emang|emg|mang)\b": "memang",
    r"\b(?:tp|tapi doang)\b": "tapi",
    r"\b(?:trs|trus|terus aja)\b": "terus",
    r"\b(?:bkn)\b": "bukan",
    r"\b(?:sm|ama|sama2)\b": "sama",
    r"\b(?:dgn|dg)\b": "dengan",
    r"\b(?:krn|karna|coz)\b": "karena",
    r"\b(?:jd|jadinya)\b": "jadi",
    r"\b(?:sblm)\b": "sebelum",
    r"\b(?:stlh|abis|habis itu)\b": "setelah",
    r"\b(?:tgl\.)\b": "tanggal",
    r"\b(?:acaranya|eventnya)\b": "acara",
    r"\b(?:senggang|luang|leluasa)\b": "kosong",
    r"\b(?:free|fri|freetime|free time)\b": "kosong",
    r"\b(?:busy)\b": "sibuk",
    r"\b(?:meet|mit)\b": "meeting",
    r"\b(?:apa aja|apa2)\b": "apa saja",
    r"\b(?:kapan2|kapan aja)\b": "kapan saja",
    # Whisper kadang memecah kata berimbuhan jadi dua ("Baca kan jadwal ku")
    r"\bbaca\s+kan\b": "bacakan",
    r"\bbuat\s+kan\b": "buat",
    r"\bcatat\s+kan\b": "catat",
    r"\bjadwal\s+ku\b": "jadwal saya",
    r"\bjadwal\s+nya\b": "jadwal",
    r"\bke\s+depan\s+nya\b": "ke depan",
}

# --- 2. Kata pengisi yang tidak membawa arti (dibuang setelah intent dinilai) --
# Sengaja TIDAK dibuang sebelum intent scoring; hanya untuk logging/debug.
FILLER_WORDS = [
    "coba", "tolong", "dong", "deh", "ya", "yah", "nih", "sih", "kok",
    "eh", "hmm", "emm", "gitu", "loh", "lah", "kan",
]

# --- 3. Angka dalam bentuk kata --------------------------------------------
UNITS = {
    # "kosong" SENGAJA tidak di sini: dalam percakapan jadwal, "hari ini saya
    # kosong" berarti tidak ada acara, bukan angka nol. Memasukkannya bikin
    # kalimat itu berubah jadi "hari ini saya 0".
    "nol": 0, "satu": 1, "se": 1, "dua": 2, "tiga": 3, "empat": 4,
    "lima": 5, "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9,
    "sepuluh": 10, "sebelas": 11,
}
def _words_to_number(tokens: list[str]) -> int | None:
    """
    Konversi rangkaian kata angka Indonesia jadi integer.
    Contoh: ['dua','ribu','dua','puluh','enam'] -> 2026
            ['tiga','puluh'] -> 30
            ['tujuh','belas'] -> 17
    Return None kalau rangkaian tidak valid.
    """
    total = 0
    current = 0
    seen_any = False
    after_scale = False  # True setelah 'puluh'/'ratus'/'belas' -> angka berikutnya DITAMBAH

    for tok in tokens:
        if tok in UNITS:
            # 'dua puluh enam': enam ditambahkan ke 20, bukan menimpa jadi 6
            current = current + UNITS[tok] if after_scale else UNITS[tok]
            after_scale = False
            seen_any = True
        elif tok == "belas":
            current = 10 + (current if current else 0)
            after_scale = True
            seen_any = True
        elif tok == "puluh":
            current = (current if current else 1) * 10
            after_scale = True
            seen_any = True
        elif tok == "ratus":
            current = (current if current else 1) * 100
            after_scale = True
            seen_any = True
        elif tok == "ribu":
            total += (current if current else 1) * 1000
            current = 0
            after_scale = False
            seen_any = True
        else:
            return None

    if not seen_any:
        return None
    return total + current


NUMBER_WORD = r"(?:nol|kosong|satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|sebelas|belas|puluh|ratus|ribu)"
NUMBER_PHRASE = rf"\b{NUMBER_WORD}(?:\s+{NUMBER_WORD})*\b"


def convert_number_words(text: str) -> str:
    """
    Ganti rangkaian kata angka jadi digit.
    'tahun dua ribu dua puluh enam' -> 'tahun 2026'
    'tanggal tujuh belas november' -> 'tanggal 17 november'
    """

    def repl(match):
        tokens = match.group(0).split()
        value = _words_to_number(tokens)
        return str(value) if value is not None else match.group(0)

    return re.sub(NUMBER_PHRASE, repl, text)


# --- 4. Perbaikan tahun yang salah dengar ----------------------------------
# Whisper sering menulis "2026" jadi "2006" / "2020" / "20 26" / "2 0 2 6".
YEAR_SPACED = re.compile(r"\btahun\s+(\d)\s*(\d)\s*(\d)\s*(\d)\b")
YEAR_SPLIT = re.compile(r"\btahun\s+(\d{2})\s+(\d{2})\b")
YEAR_SHORT = re.compile(r"\btahun\s+'?(\d{2})\b(?!\d)")


def normalize_year(text: str) -> str:
    """
    Rapikan penulisan tahun agar selalu jadi 4 digit yang utuh.
    'tahun 2 0 2 6' -> 'tahun 2026'
    'tahun 20 26'   -> 'tahun 2026'
    'tahun 26'      -> 'tahun 2026'
    """
    text = YEAR_SPACED.sub(lambda m: f"tahun {m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}", text)
    text = YEAR_SPLIT.sub(lambda m: f"tahun {m.group(1)}{m.group(2)}", text)
    text = YEAR_SHORT.sub(lambda m: f"tahun 20{m.group(1)}", text)
    return text


# --- 5. Fasad --------------------------------------------------------------
def normalize(text: str) -> str:
    """
    Bersihkan teks hasil STT. Dipanggil SEKALI di parser.parse_command(),
    modul lain tidak perlu memanggil ini lagi.
    """
    if not text:
        return ""

    original = text
    out = text.lower().strip()

    # Buang tanda baca yang mengganggu regex, sisakan titik dua & titik desimal jam
    out = re.sub(r"[!?,;\"'`]", " ", out)
    out = re.sub(r"\.(?!\d)", " ", out)

    out = convert_number_words(out)
    out = normalize_year(out)

    # Whisper kadang menulis kata "kosong" sebagai angka 0 ("hari ini saya 0 nggak").
    # Hanya untuk 0 yang berdiri sendiri, bukan bagian jam/tanggal — dan harus
    # SETELAH convert_number_words, kalau tidak hasilnya diubah balik jadi angka.
    out = re.sub(r"(?<!jam )(?<!pukul )(?<![\d:.\-/])\b0\b(?![\d:.\-/])", "kosong", out)

    for pattern, replacement in SPELLING_FIXES.items():
        out = re.sub(pattern, replacement, out)

    out = re.sub(r"\s+", " ", out).strip()

    if out != original.lower().strip():
        logger.debug(f"Normalisasi: '{original}' -> '{out}'")
    return out


# Kata benda yang mungkin dipakai user untuk menyebut isi kalendernya.
# AKIRA sebaiknya membalas dengan kata yang SAMA — kalau user bertanya
# "ada kegiatan ga", menjawab "tidak ada jadwal" terasa tidak nyambung.
SEBUTAN = ["kegiatan", "acara", "agenda", "kesibukan", "urusan", "janji", "jadwal"]


def deteksi_sebutan(text: str, default: str = "jadwal") -> str:
    """
    Ambil kata benda yang dipakai user untuk menyebut isi kalendernya.
    "besok ada kegiatan ga?" -> "kegiatan"
    "cek jadwal besok"       -> "jadwal"
    """
    if not text:
        return default
    t = text.lower()
    for kata in SEBUTAN:
        if re.search(rf"\b{kata}\b", t):
            return kata
    return default


def strip_fillers(text: str) -> str:
    """Buang kata pengisi. Dipakai untuk mencari nama kegiatan, bukan untuk intent."""
    out = text
    for word in FILLER_WORDS:
        out = re.sub(rf"\b{word}\b", " ", out)
    return re.sub(r"\s+", " ", out).strip()


if __name__ == "__main__":
    tests = [
        "Bacakan jadwal saya untuk tahun dua ribu dua puluh enam",
        "bacakan jadual saya untuk tahun 20 26",
        "Coba cek dong jadual besok",
        "Cata jadual meting bahsok jam tiga sore",
        "catat jadwal tanggal tiga puluh agustus",
        "sekarang jam berapa ya akira",
        "tanggal tujuh belas november tahun 2 0 2 6",
    ]
    for t in tests:
        print(f"{t!r}\n  -> {normalize(t)!r}\n")
