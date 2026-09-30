"""
Unit test untuk date_time_parser.py
Jalankan: pytest tests/test_date_time_parser.py -v
"""
from datetime import datetime, timedelta

from src.nlp.date_time_parser import parse_date_id, parse_time_id


def test_besok():
    now = datetime(2026, 9, 10)
    result = parse_date_id("besok", reference_time=now)
    assert result.date() == (now + timedelta(days=1)).date()


def test_lusa():
    now = datetime(2026, 9, 10)
    result = parse_date_id("lusa", reference_time=now)
    assert result.date() == (now + timedelta(days=2)).date()


def test_jam_sore():
    result = parse_time_id("jam 3 sore")
    assert result == "15:00"


def test_jam_pagi():
    result = parse_time_id("jam 8 pagi")
    assert result == "08:00"


def test_jam_setengah():
    result = parse_time_id("jam setengah 8 pagi")
    assert result == "07:30"


def test_jam_malam():
    result = parse_time_id("jam 10 malam")
    assert result == "22:00"


def test_jam_invalid():
    result = parse_time_id("kapan-kapan aja")
    assert result is None


# --- Test tambahan: tanggal eksplisit di dalam kalimat (bug dari demo pertama) ---

def test_tanggal_eksplisit_lengkap():
    """'17 November 2026' di tengah kalimat harus terbaca, bukan diabaikan."""
    result = parse_date_id("Cek jadwal pada tanggal 17 November 2026")
    assert result is not None
    assert result.month == 11
    assert result.day == 17
    assert result.year == 2026


def test_tanggal_eksplisit_tanpa_tahun():
    result = parse_date_id("cek jadwal 17 november")
    assert result is not None
    assert result.month == 11
    assert result.day == 17


def test_tanggal_dan_jam_bersamaan():
    """Kata 'jam' tidak boleh mengacaukan pembacaan tanggal."""
    tanggal = parse_date_id("catat meeting 5 september jam 3 sore")
    jam = parse_time_id("catat meeting 5 september jam 3 sore")
    assert tanggal is not None
    assert tanggal.month == 9
    assert tanggal.day == 5
    assert jam == "15:00"


def test_tanggal_mustahil_tidak_fallback():
    """Tanggal 32 Januari mustahil — harus return None, bukan tanggal ngaco dari dateparser."""
    assert parse_date_id("tanggalnya 32 januari 2027") is None
    assert parse_date_id("tanggal 32 januari") is None
    # Februari maks 28/29
    assert parse_date_id("tanggal 30 februari 2027") is None


def test_tanggal_valid_tetap_berhasil():
    """Pastikan tanggal valid tidak ikut terdampak."""
    result = parse_date_id("tanggal 31 januari 2027")
    assert result is not None
    assert result.day == 31
    assert result.month == 1
