"""
Unit test untuk konversi waktu di executor.py (tidak menyentuh API Google) — Sprint 2
Jalankan: pytest tests/test_executor.py -v
"""
from src.calendar_service.executor import compute_end_time, to_iso_datetime


def test_to_iso_datetime():
    assert to_iso_datetime("2026-09-10", "15:00") == "2026-09-10T15:00:00"


def test_compute_end_default_1_jam():
    assert compute_end_time("2026-09-10", "15:00") == "2026-09-10T16:00:00"


def test_compute_end_lintas_tengah_malam():
    """Kasus penting: acara jam 23:30 harus berakhir di hari berikutnya."""
    assert compute_end_time("2026-09-10", "23:30") == "2026-09-11T00:30:00"


def test_compute_end_durasi_kustom():
    assert compute_end_time("2026-09-10", "15:00", duration_minutes=30) == "2026-09-10T15:30:00"


# --- Test tambahan: helper pembacaan jadwal ---

def test_event_date_str_berjam():
    from src.calendar_service.executor import _event_date_str
    ev = {"start": {"dateTime": "2026-11-17T15:00:00+07:00"}}
    assert _event_date_str(ev) == "2026-11-17"


def test_event_date_str_seharian():
    from src.calendar_service.executor import _event_date_str
    ev = {"start": {"date": "2026-11-17"}}
    assert _event_date_str(ev) == "2026-11-17"


def test_event_time_str():
    from src.calendar_service.executor import _event_time_str
    assert _event_time_str({"start": {"dateTime": "2026-11-17T15:00:00+07:00"}}) == "15:00"
    assert _event_time_str({"start": {"date": "2026-11-17"}}) is None


def test_ucapkan_tanggal():
    """Sejak Sprint 3.6 tahun ikut disebut secara default (dulu dihilangkan)."""
    from src.calendar_service.executor import _ucapkan_tanggal
    assert _ucapkan_tanggal("2026-11-17") == "17 November 2026"
    assert _ucapkan_tanggal("2026-11-17", sebut_tahun=False) == "17 November"


def test_ringkas_event():
    from src.calendar_service.executor import _ringkas_event
    ev = {"summary": "Meeting klien", "start": {"dateTime": "2026-11-17T15:00:00+07:00"}}
    assert "Meeting klien" in _ringkas_event(ev)
    assert "15:00" in _ringkas_event(ev)
