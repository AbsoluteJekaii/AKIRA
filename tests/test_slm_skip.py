"""
Unit test untuk deteksi SKIP (tidak butuh Ollama jalan) — Sprint 2
Jalankan: pytest tests/test_slm_skip.py -v
"""
import pytest

from src.nlp.slm_extractor import detect_skip


@pytest.mark.parametrize("text", [
    "kegiatannya skip aja",
    "gak usah diisi",
    "gausah",
    "ga usah",
    "nggak usah",
    "tidak usah",
    "lewatin aja",
    "lewati",
    "kosongin",
    "kosongkan",
])
def test_skip_terdeteksi(text):
    assert detect_skip(text) is True


@pytest.mark.parametrize("text", [
    "meeting dengan klien",
    "rapat divisi marketing",
    "catat jadwal besok jam 3",
])
def test_bukan_skip(text):
    assert detect_skip(text) is False
