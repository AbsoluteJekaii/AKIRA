"""
Unit test untuk intent_classifier.py — Sprint 2
Jalankan: pytest tests/test_intent_classifier.py -v
"""
from src.nlp.intent_classifier import classify_intent_keyword, score_intents


def test_catat():
    assert classify_intent_keyword("catat jadwal meeting besok jam 3") == "catat"


def test_catat_variasi():
    assert classify_intent_keyword("tolong tambahkan meeting dengan klien") == "catat"


def test_baca():
    assert classify_intent_keyword("ada jadwal apa hari ini") == "baca"


def test_hapus():
    assert classify_intent_keyword("hapus jadwal rapat divisi") == "hapus"


def test_hapus_variasi():
    assert classify_intent_keyword("batalkan yang jam 2 siang") == "hapus"


def test_reschedule():
    assert classify_intent_keyword("geser jadwal rapat ke jam 5 sore") == "reschedule"


def test_no_intent():
    assert classify_intent_keyword("halo apa kabar") is None


def test_scoring_prioritas_frasa_spesifik():
    """Frasa spesifik ('hapus jadwal') harus menang atas keyword tunggal."""
    scores = score_intents("hapus jadwal rapat")
    assert scores["hapus"] >= 3


# ---- Sprint 3.10: deteksi pernyataan jadwal + Groq reasoner ----

from src.nlp.intent_classifier import deteksi_pernyataan_jadwal


def test_pernyataan_tanggal_valid():
    """'saya ada kondangan besok' = pernyataan, harus True."""
    assert deteksi_pernyataan_jadwal("saya ada kondangan besok jam 1 siang") is True


def test_pernyataan_tanggal_mustahil():
    """'saya ada kondangan tanggal 32 Januari' = tetap pernyataan meskipun tanggal mustahil."""
    assert deteksi_pernyataan_jadwal("saya ada kondangan tanggal 32 Januari 2027") is True


def test_pernyataan_tanpa_waktu():
    """'saya ada uang' = BUKAN pernyataan jadwal (tidak ada petunjuk waktu)."""
    assert deteksi_pernyataan_jadwal("saya ada uang") is False


def test_pertanyaan_bukan_pernyataan():
    """'besok ada kegiatan ga?' = pertanyaan, bukan pernyataan."""
    assert deteksi_pernyataan_jadwal("besok ada kegiatan ga?") is False


# ---- groq_reasoner: deteksi tanggal mustahil ----

from src.nlp.groq_reasoner import deteksi_tanggal_mustahil, ada_pola_tanggal


def test_tanggal_mustahil_32_januari():
    p = deteksi_tanggal_mustahil("buatkan jadwal tanggal 32 Januari 2027")
    assert p is not None
    assert "31" in p  # harus bilang maks 31


def test_tanggal_mustahil_30_februari():
    p = deteksi_tanggal_mustahil("catat tanggal 30 Februari")
    assert p is not None
    assert "29" in p  # Februari maks 29


def test_tanggal_valid_tidak_dipanggil():
    assert deteksi_tanggal_mustahil("catat tanggal 15 Januari") is None


def test_ada_pola_tanggal_eksplisit():
    assert ada_pola_tanggal("tanggal 32 Januari 2027") is True


def test_ada_pola_tanggal_relatif():
    assert ada_pola_tanggal("besok saya ada meeting") is True


def test_tidak_ada_pola_tanggal():
    assert ada_pola_tanggal("saya ada uang") is False
