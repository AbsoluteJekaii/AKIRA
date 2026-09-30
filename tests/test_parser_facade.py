"""
Unit test untuk parser.py fasad NLP (mode use_slm=False, tanpa Ollama) — Sprint 2
Jalankan: pytest tests/test_parser_facade.py -v
"""
from src.nlp.parser import merge_answer, parse_command


def test_parse_catat_lengkap():
    result = parse_command("catat jadwal meeting besok jam 3 sore", use_slm=False)
    assert result["aksi"] == "catat"
    assert result["jam"] == "15:00"
    assert result["tanggal"] is not None


def test_parse_baca():
    result = parse_command("ada jadwal apa hari ini", use_slm=False)
    assert result["aksi"] == "baca"


def test_parse_skip_terdeteksi():
    result = parse_command("catat jadwal lusa jam 9 pagi, kegiatannya skip aja", use_slm=False)
    assert result.get("_kegiatan_skipped") is True


def test_merge_answer_tanggal():
    data = {"aksi": "catat", "tanggal": None, "jam": "15:00", "kegiatan": None}
    result = merge_answer(data, "tanggal", "besok")
    assert result["tanggal"] is not None
    assert result["jam"] == "15:00"  # field lain tidak tertimpa


def test_merge_answer_jam():
    data = {"aksi": "catat", "tanggal": "2026-09-10", "jam": None, "kegiatan": None}
    result = merge_answer(data, "jam", "jam 5 sore")
    assert result["jam"] == "17:00"


def test_merge_answer_skip():
    data = {"aksi": "catat", "tanggal": "2026-09-10", "jam": "15:00", "kegiatan": None}
    result = merge_answer(data, "kegiatan", "gak usah")
    assert result["_kegiatan_skipped"] is True
