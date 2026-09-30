"""
Reminder proaktif: AKIRA yang mulai bicara duluan.
Tanggung jawab: Person 4 (Voice Output, Dialog UX & QA Lead) — Sprint 3

Perubahan dari Sprint 2:
1. LANGSUNG BEKERJA SAAT DINYALAKAN. Dulu loop tidur 60 detik dulu, jadi
   user harus menunggu tanpa tanda apa pun. Sekarang begitu AKIRA hidup,
   dia langsung membacakan agenda beberapa hari ke depan — ada jadwal
   atau tidak, tetap melapor.
2. Reminder berjenjang: H-60 menit, H-15 menit, dan saat acara dimulai.
3. Tidak menyela saat AKIRA sedang melayani perintah user (pakai busy flag),
   supaya suara reminder tidak menabrak percakapan yang sedang berjalan.
"""
import threading
import time
from datetime import datetime, timedelta

from loguru import logger

CHECK_INTERVAL_SECONDS = 60          # cek kalender tiap 1 menit
LEAD_TIERS = [30, 15, 5]             # default; ditimpa config reminder.lead_tiers_minutes
BRIEFING_DAYS = 7                    # cakupan briefing saat startup

_reminded: set[tuple] = set()        # (event_id, tier) — satu tier sekali saja
_busy = threading.Event()            # True saat AKIRA sedang melayani user


def set_busy(value: bool):
    """Dipanggil app.py: True saat sesi percakapan mulai, False saat selesai."""
    _busy.set() if value else _busy.clear()


def is_busy() -> bool:
    return _busy.is_set()


def pengingat_khusus(event: dict) -> list:
    """
    Menit pengingat khusus milik event (diatur user lewat suara).
    Kosong kalau event memakai pengingat default kalender.

    Sengaja membaca dict event langsung, bukan lewat API — datanya sudah ikut
    terbawa saat read_events(), jadi tidak perlu permintaan jaringan tambahan.
    """
    reminders = event.get("reminders") or {}
    if reminders.get("useDefault", True):
        return []
    return [
        o.get("minutes")
        for o in reminders.get("overrides", [])
        if isinstance(o.get("minutes"), int)
    ]


def parse_event_start(event: dict) -> datetime | None:
    """Ambil waktu mulai event dari struktur Google Calendar."""
    start = event.get("start", {})
    dt_str = start.get("dateTime")
    if not dt_str:
        return None  # event all-day, tidak perlu reminder berbasis jam
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        logger.warning(f"Format waktu tidak dikenali: {dt_str}")
        return None


def build_reminder_message(event: dict, start_dt: datetime) -> str:
    """
    Susun kalimat pengingat. Jam acara ikut disebut supaya user bisa mengecek
    sendiri kalau angka "menit lagi" terdengar meleset.
    """
    judul = event.get("summary", "jadwal tanpa nama")
    menit_lagi = int((start_dt - datetime.now().astimezone()).total_seconds() / 60)
    jam = start_dt.strftime("%H:%M")

    if menit_lagi <= 1:
        return f"Permisi Bos, {judul} dimulai sekarang."
    return f"Permisi Bos, pengingat: Anda ada {judul} {menit_lagi} menit lagi, jam {jam}."


def check_all_tiers(say_fn, lead_tiers: list[int] | None = None):
    """
    Cek semua tier dalam SATU kali ambil data.

    Versi sebelumnya memanggil find_upcoming_events() per tier, jadi tiap menit
    ada 3 permintaan ke Google Calendar untuk data yang sama persis
    (terlihat di log sebagai "Ditemukan 20 event" tiga kali berturut-turut).
    Sekarang data diambil sekali, lalu dicocokkan ke tiap tier di memori.
    """
    if is_busy():
        logger.debug("AKIRA sedang melayani user, reminder ditunda satu siklus")
        return

    from src.calendar_service.crud import read_events

    try:
        events = read_events(max_results=20)
    except Exception as e:
        logger.error(f"Gagal ambil kalender untuk reminder: {e}")
        return

    tiers_default = sorted(lead_tiers or LEAD_TIERS)
    now = datetime.now().astimezone()

    for event in events:
        event_id = event.get("id")
        start_dt = parse_event_start(event)
        if not start_dt:
            continue

        menit_lagi = (start_dt - now).total_seconds() / 60
        if menit_lagi < 0:
            continue

        # Pengingat khusus milik event ini (diatur user lewat suara) MENGGANTIKAN
        # tier default. Kalau user minta diingatkan sejam sebelum, dia tidak
        # ingin juga diingatkan di menit 30, 15, dan 5.
        khusus = pengingat_khusus(event)
        tiers = sorted(khusus) if khusus else tiers_default

        # Pilih tier paling dekat yang sudah terlewati ambangnya dan belum diucapkan
        for lead in tiers:
            if menit_lagi <= max(lead, 1) and (event_id, lead) not in _reminded:
                message = build_reminder_message(event, start_dt)
                logger.info(f"Trigger reminder (tier H-{lead}): {message}")
                say_fn(message)

                # Tandai tier ini DAN semua tier yang lebih jauh sebagai selesai.
                # Kalau AKIRA baru menyala saat acara tinggal 14 menit lagi, dia
                # mengucapkan H-15 — tier H-30 sudah terlewat dan tidak boleh
                # ikut bunyi di siklus berikutnya sebagai pengingat basi.
                for lebih_jauh in tiers:
                    if lebih_jauh >= lead:
                        _reminded.add((event_id, lebih_jauh))
                break


def announce_startup_briefing(say_fn, days: int = BRIEFING_DAYS):
    """
    Laporan agenda begitu AKIRA dinyalakan — tanpa menunggu wake word,
    tanpa menunggu siklus 60 detik pertama.
    """
    from src.calendar_service.executor import get_briefing

    try:
        message = get_briefing(days=days)
        logger.info(f"Briefing startup: {message}")
        say_fn(message)
    except Exception as e:
        logger.error(f"Gagal menyusun briefing startup: {e}")


def start_reminder_loop(
    say_fn,
    interval: int = CHECK_INTERVAL_SECONDS,
    run_immediately: bool = True,
    lead_tiers: list[int] | None = None,
):
    """
    Jalankan loop reminder di background thread (daemon, ikut mati saat app ditutup).

    lead_tiers  : daftar menit sebelum acara untuk mengingatkan, mis. [30, 15, 5].
                  Diisi app.py dari config/settings.yaml -> reminder.lead_tiers_minutes.
    run_immediately=True -> cek sekali SEKARANG, tidak menunggu interval pertama.
    """
    tiers = sorted(lead_tiers or LEAD_TIERS)

    def loop():
        logger.info(f"Reminder aktif (cek tiap {interval} detik, ingatkan H-{tiers} menit)")
        if run_immediately:
            check_all_tiers(say_fn, tiers)
        while True:
            time.sleep(interval)
            check_all_tiers(say_fn, tiers)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    # Test logika tanpa API Google — pakai event palsu:
    #   python -m src.dialog.reminder
    now = datetime.now().astimezone()
    fake_event = {
        "id": "test123",
        "summary": "Meeting dengan klien",
        "start": {"dateTime": (now + timedelta(minutes=10)).isoformat()},
    }
    start_dt = parse_event_start(fake_event)
    print("Parsed start:", start_dt)
    print("Pesan reminder:", build_reminder_message(fake_event, start_dt))

    fake_now = {
        "id": "test456",
        "summary": "Rapat divisi",
        "start": {"dateTime": (now + timedelta(seconds=30)).isoformat()},
    }
    print("Pesan saat mulai:", build_reminder_message(fake_now, parse_event_start(fake_now)))
