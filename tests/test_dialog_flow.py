"""
Unit test untuk state_machine.py
Jalankan: pytest tests/test_dialog_flow.py -v
"""
from src.dialog.state_machine import check_missing_fields, is_complete, get_next_question, apply_skip


def test_complete_data():
    data = {"aksi": "catat", "tanggal": "2026-09-10", "jam": "15:00", "kegiatan": "meeting"}
    assert is_complete(data) is True
    assert check_missing_fields(data) == []
    assert get_next_question(data) is None


def test_missing_tanggal():
    data = {"aksi": "catat", "tanggal": None, "jam": "15:00", "kegiatan": None}
    assert is_complete(data) is False
    assert "tanggal" in check_missing_fields(data)
    assert get_next_question(data) is not None


def test_missing_jam():
    data = {"aksi": "catat", "tanggal": "2026-09-10", "jam": None, "kegiatan": None}
    assert "jam" in check_missing_fields(data)


def test_missing_both():
    """Sejak Sprint 3.2 'kegiatan' ikut wajib untuk aksi catat."""
    data = {"aksi": "catat", "tanggal": None, "jam": None, "kegiatan": None}
    missing = check_missing_fields(data)
    assert "tanggal" in missing
    assert "jam" in missing
    assert "kegiatan" in missing
    assert len(missing) == 3


def test_apply_skip():
    data = {"aksi": "catat", "tanggal": "2026-09-10", "jam": "15:00", "kegiatan": "belum diisi"}
    result = apply_skip(data, "kegiatan")
    assert result["kegiatan"] is None
    assert result["_kegiatan_skipped"] is True
