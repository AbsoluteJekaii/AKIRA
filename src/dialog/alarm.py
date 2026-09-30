"""
Alarm & timer — pengingat berbasis WAKTU, bukan jadwal kalender.
Tanggung jawab: Person 4 (Dialog UX Lead) — Sprint 3.15

Beda dengan `reminder.py`:
- `reminder.py` mengingatkan sebelum EVENT di Google Calendar
- modul ini mengingatkan pada WAKTU tertentu, tanpa event apa pun
  ("timer 30 detik", "ingetin nanti jam 3 sore")

Sengaja disimpan di memori proses saja, tidak ke Google Calendar. Timer 30
detik bukan agenda — mengotori kalender dengan hal seperti itu justru
merepotkan user. Konsekuensinya: alarm hilang kalau AKIRA di-restart, dan itu
memang perilaku yang wajar untuk timer.
"""
import re
import threading
import time
from datetime import datetime, timedelta

from loguru import logger

_alarms: list = []
_lock = threading.Lock()
_thread = None

SATUAN_DETIK = {"detik": 1, "menit": 60, "jam": 3600}

ANGKA_KATA = {
    "se": 1, "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
    "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
    "lima belas": 15, "dua puluh": 20, "tiga puluh": 30, "empat puluh lima": 45,
    "enam puluh": 60,
}

# "timer 30 detik", "hitung mundur 5 menit", "ingetin 10 menit lagi"
POLA_TIMER = re.compile(
    r"\b(?:timer|hitung\s*mundur|countdown|alarm)?\s*"
    r"(\d{1,4})\s*(detik|menit|jam)\b"
    r"(?:\s+(?:lagi|dari sekarang|ke depan|kedepan))?"
)

KATA_TIMER = re.compile(r"\b(?:timer|hitung\s*mundur|countdown|stopwatch)\b")

# "lagi" / "dari sekarang" menandakan durasi dihitung dari SEKARANG,
# bukan jeda sebelum suatu acara.
DARI_SEKARANG = re.compile(r"\b(?:lagi|dari sekarang|mulai sekarang)\b")

KATA_ALARM = re.compile(r"\b(?:alarm|bangunkan|ingatkan|ingetin|kasih\s*tau)\b")


def parse_durasi(text: str) -> int | None:
    """
    Ambil durasi timer dalam DETIK.
    "timer 30 detik" -> 30 | "5 menit lagi" -> 300 | "dua jam lagi" -> 7200
    """
    if not text:
        return None
    t = text.lower()

    m = POLA_TIMER.search(t)
    if m:
        return int(m.group(1)) * SATUAN_DETIK[m.group(2)]

    kata_pat = "|".join(sorted(ANGKA_KATA, key=len, reverse=True))
    m = re.search(rf"\b({kata_pat})\s+(detik|menit|jam)\b", t)
    if m:
        return ANGKA_KATA[m.group(1)] * SATUAN_DETIK[m.group(2)]

    m = re.search(r"\bse(detik|menit|jam)\b", t)
    if m:
        return SATUAN_DETIK[m.group(1)]

    return None


TANYA_WAKTU = re.compile(
    r"\b(?:jam|pukul)\s+berapa\b|\bhari\s+apa\b|\btanggal\s+berapa\b"
)


def is_permintaan_timer(text: str) -> bool:
    """True untuk 'timer 30 detik', 'ingetin 5 menit lagi'."""
    if not text:
        return False
    t = text.lower()
    if parse_durasi(t) is None:
        return False

    # "1 jam sebelum meeting" itu pengingat event kalender, bukan timer
    if re.search(r"\bsebelum(?:nya)?\b", t):
        return False

    # "15 menit lagi jam berapa" adalah PERTANYAAN, bukan permintaan timer.
    # Durasi dan kata "lagi" membuatnya mirip timer, dan sebelumnya pendeteksi
    # ini diperiksa lebih dulu dan menang — user bertanya jam, AKIRA
    # memasang timer.
    if TANYA_WAKTU.search(t):
        return False

    # Harus ada kata pemicu atau penanda "dari sekarang",
    # supaya "rapat 30 menit" (durasi acara) tidak ikut jadi timer
    return bool(KATA_TIMER.search(t) or DARI_SEKARANG.search(t))


def is_permintaan_alarm(text: str) -> bool:
    """
    True untuk 'ingetin nanti jam 3 sore', 'alarm jam 5 pagi'.
    Harus menyebut jam absolut, bukan durasi.
    """
    if not text:
        return False
    from src.nlp.date_time_parser import parse_time_id

    t = text.lower()
    if not KATA_ALARM.search(t):
        return False
    if parse_durasi(t) is not None:
        return False           # itu timer, bukan alarm
    if re.search(r"\bsebelum(?:nya)?\b", t):
        return False           # itu pengingat event kalender
    return parse_time_id(t) is not None


# Kata yang menandai keperluan alarm, tapi BUKAN keperluannya itu sendiri.
# "timer 1 menit dengan catatan" -> tidak ada keperluan; kata "catatan" cuma
# pembuka yang tidak diikuti apa-apa. Tanpa penjagaan ini AKIRA berteriak
# "waktunya catatan".
PEMBUKA_LABEL = r"(?:dengan|buat|untuk|namanya|labelnya|catatan(?:nya)?|keterangan(?:nya)?|judul(?:nya)?)"

KATA_BUKAN_LABEL = {
    "catatan", "catatannya", "keterangan", "keterangannya", "label", "labelnya",
    "judul", "judulnya", "nama", "namanya", "timer", "alarm", "pengingat",
    "reminder", "menit", "detik", "jam", "hari", "lagi", "sekarang", "nanti",
    "dengan", "buat", "untuk", "ya", "dong", "aja", "saja",
    # Kata perintah pemasang timer — bukan keperluannya
    "hitung", "mundur", "countdown", "stopwatch", "pasang", "setel", "set",
    "bikin", "buatkan", "bikinin", "tolong",
}


def _label_dari_teks(text: str) -> str | None:
    """
    Ambil keperluan alarm: 'ingetin minum obat jam 3' -> 'minum obat'.

    Return None kalau yang tersisa cuma kata pembuka — lebih baik AKIRA
    bilang "timernya sudah selesai" daripada "waktunya catatan".
    """
    from src.nlp.slm_extractor import extract_kegiatan_regex

    t = (text or "").lower()

    # Kalau ada pembuka eksplisit, ambil yang SETELAHNYA
    m = re.search(rf"\b{PEMBUKA_LABEL}\s+(.+)", t)
    kandidat = m.group(1) if m else t

    try:
        hasil = extract_kegiatan_regex(kandidat)
    except Exception:
        hasil = None

    if not hasil:
        return None

    sisa = [k for k in hasil.split() if k not in KATA_BUKAN_LABEL]
    if not sisa:
        logger.info(f"Label alarm kosong setelah dibersihkan: '{hasil}'")
        return None
    return " ".join(sisa)


def tambah_timer(detik: int, label: str = None, say_fn=None) -> dict:
    """Pasang timer relatif dari sekarang."""
    return _tambah(datetime.now() + timedelta(seconds=detik), label, say_fn, "timer")


def tambah_alarm(jam: str, tanggal: str = None, label: str = None, say_fn=None) -> dict:
    """
    Pasang alarm pada jam tertentu (format HH:MM).
    Kalau jamnya sudah lewat hari ini, otomatis dipasang untuk besok.
    """
    now = datetime.now()
    hh, mm = (int(x) for x in jam.split(":"))

    if tanggal:
        target = datetime.strptime(f"{tanggal} {jam}", "%Y-%m-%d %H:%M")
    else:
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
            logger.info("Jam sudah lewat hari ini, alarm dipasang untuk besok")

    return _tambah(target, label, say_fn, "alarm")


def _tambah(waktu: datetime, label, say_fn, jenis: str) -> dict:
    alarm = {
        "waktu": waktu,
        "label": label,
        "say_fn": say_fn,
        "jenis": jenis,
        "aktif": True,
    }
    with _lock:
        _alarms.append(alarm)
    logger.info(f"{jenis.capitalize()} dipasang untuk {waktu:%H:%M:%S} (label: {label})")
    _pastikan_loop()
    return alarm


def daftar_aktif() -> list:
    """Alarm & timer yang belum berbunyi."""
    with _lock:
        return [a for a in _alarms if a["aktif"]]


def batalkan_semua() -> int:
    """Matikan semua alarm & timer. Return jumlah yang dibatalkan."""
    with _lock:
        aktif = [a for a in _alarms if a["aktif"]]
        for a in aktif:
            a["aktif"] = False
    logger.info(f"{len(aktif)} alarm/timer dibatalkan")
    return len(aktif)


# --- Membatalkan & menanyakan sisa waktu ---------------------------------
BATAL_TIMER = re.compile(
    r"\b(?:batal(?:kan|in)?|matikan|hentikan|stop|hapus|cancel|off)\b"
    r".{0,20}?\b(?:timer(?:nya)?|alarm(?:nya)?|pengingat(?:nya)?|hitung\s*mundur)\b"
    r"|\b(?:timer(?:nya)?|alarm(?:nya)?|pengingat(?:nya)?)\b.{0,20}?"
    r"\b(?:batal(?:kan|in)?|matikan|hentikan|stop|dihapus|dimatikan)\b"
)

TANYA_TIMER = re.compile(
    r"\b(?:timer|alarm|pengingat|hitung\s*mundur)\w*\b.{0,30}?"
    r"\b(?:berapa|sisa|lama|kapan|masih|tinggal)\b"
    r"|\b(?:berapa|sisa|masih|tinggal)\b.{0,30}?\b(?:timer|alarm|pengingat)\w*\b"
)


def is_batal_timer(text: str) -> bool:
    """True untuk 'matikan timernya', 'batalkan alarm'."""
    return bool(BATAL_TIMER.search((text or "").lower()))


def is_tanya_timer(text: str) -> bool:
    """True untuk 'timernya berapa lama lagi', 'sisa timer berapa'."""
    return bool(TANYA_TIMER.search((text or "").lower()))


def sisa_detik(alarm: dict, sekarang: datetime = None) -> int:
    """Berapa detik lagi alarm ini berbunyi (minimal 0)."""
    sekarang = sekarang or datetime.now()
    return max(0, int((alarm["waktu"] - sekarang).total_seconds()))


def ucapkan_sisa(sekarang: datetime = None) -> str:
    """Kalimat laporan sisa waktu semua timer & alarm yang aktif."""
    aktif = daftar_aktif()
    if not aktif:
        return "Tidak ada timer atau alarm yang aktif, Bos."

    bagian = []
    for a in sorted(aktif, key=lambda x: x["waktu"]):
        sisa = ucapkan_sisa_kasar(sisa_detik(a, sekarang))
        nama = f" untuk {a['label']}" if a["label"] else ""
        jenis = "timer" if a["jenis"] == "timer" else "alarm"
        bagian.append(f"{jenis}{nama} tinggal {sisa} lagi")

    return "Bos, " + ", dan ".join(bagian) + "."


def pesan_bunyi(alarm: dict) -> str:
    """Kalimat yang diucapkan saat alarm berbunyi."""
    if alarm["label"]:
        return f"Bos, waktunya {alarm['label']}."
    if alarm["jenis"] == "timer":
        return "Bos, timernya sudah selesai."
    return f"Bos, ini alarm yang Anda minta. Sekarang jam {alarm['waktu']:%H:%M}."


def cek_sekali(sekarang: datetime = None) -> list:
    """
    Satu siklus pengecekan. Dipisah dari loop supaya bisa diuji tanpa menunggu.
    Return daftar alarm yang baru saja berbunyi.
    """
    sekarang = sekarang or datetime.now()
    bunyi = []

    with _lock:
        for a in _alarms:
            if a["aktif"] and a["waktu"] <= sekarang:
                a["aktif"] = False
                bunyi.append(a)

    for a in bunyi:
        pesan = pesan_bunyi(a)
        logger.info(f"Alarm berbunyi: {pesan}")
        if a["say_fn"]:
            try:
                a["say_fn"](pesan)
            except Exception as e:
                logger.error(f"Gagal mengucapkan alarm: {e}")

    return bunyi


def _pastikan_loop(interval: float = 1.0):
    """
    Jalankan thread pengecek kalau belum ada.

    Interval 1 detik — jauh lebih rapat daripada loop reminder kalender
    (30 detik), karena "timer 30 detik" harus akurat. Bebannya nol: cuma
    membandingkan waktu di memori, tidak ada panggilan jaringan.
    """
    global _thread
    if _thread and _thread.is_alive():
        return

    def loop():
        while True:
            time.sleep(interval)
            try:
                cek_sekali()
            except Exception as e:
                logger.error(f"Loop alarm error: {e}")

    _thread = threading.Thread(target=loop, daemon=True)
    _thread.start()
    logger.info("Loop alarm aktif (cek tiap 1 detik)")


def ucapkan_sisa_kasar(detik: int) -> str:
    """
    Sisa waktu dalam bentuk yang enak didengar, dibulatkan.

    Beda dengan ucapkan_durasi() yang tepat: "89 detik" benar tapi janggal
    diucapkan. Untuk laporan sisa waktu, "sekitar 1 menit" lebih berguna.
    """
    if detik < 60:
        return f"{detik} detik"
    if detik < 3600:
        menit = round(detik / 60)
        return "sekitar 1 menit" if menit == 1 else f"sekitar {menit} menit"
    jam = detik / 3600
    if abs(jam - round(jam)) < 0.1:
        n = round(jam)
        return "sekitar 1 jam" if n == 1 else f"sekitar {n} jam"
    return f"sekitar {jam:.1f} jam".replace(".", ",")


def ucapkan_durasi(detik: int) -> str:
    """30 -> '30 detik', 300 -> '5 menit', 7200 -> '2 jam'."""
    if detik % 3600 == 0 and detik >= 3600:
        n = detik // 3600
        return "satu jam" if n == 1 else f"{n} jam"
    if detik % 60 == 0 and detik >= 60:
        n = detik // 60
        return "satu menit" if n == 1 else f"{n} menit"
    return f"{detik} detik"


if __name__ == "__main__":
    # python -m src.dialog.alarm
    print("=== Deteksi timer ===")
    for t in ["timer 30 detik", "ingetin 5 menit lagi", "hitung mundur 2 menit",
              "dua jam lagi ingatkan saya", "rapat 30 menit", "catat meeting besok"]:
        print(f"  {t!r:34} timer={is_permintaan_timer(t)!s:6} durasi={parse_durasi(t)}")

    print("\n=== Deteksi alarm ===")
    for t in ["ingetin nanti jam 3 sore", "alarm jam 5 pagi", "bangunkan saya jam 6",
              "ingatkan 1 jam sebelum meeting", "timer 30 detik"]:
        print(f"  {t!r:34} alarm={is_permintaan_alarm(t)}")

    print("\n=== Uji timer 2 detik (loop background) ===")
    tambah_timer(2, "minum obat", say_fn=lambda p: print(f"  >> BUNYI: {p}"))
    for i in range(4):
        time.sleep(1)
        print(f"  detik {i+1}: {len(daftar_aktif())} timer masih menunggu")
