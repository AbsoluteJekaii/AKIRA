"""
Konfigurasi bersama untuk seluruh pengujian.

Pengujian TIDAK BOLEH memanggil layanan sungguhan — Groq, maupun Ollama lokal.

Ditemukan dari laptop pengembang: di sana ada GROQ_API_KEY di .env dan Ollama
menyala, sehingga test yang melewati jalur penalaran benar-benar memanggil
API. Akibatnya tiga:

1. Hasil test bergantung pada jawaban LLM saat itu — test yang lolos di satu
   mesin gagal di mesin lain.
2. Seluruh test butuh 26 detik, bukan 3.
3. Setiap `pytest` memakan kuota API pengguna.

Fixture di bawah memutus semua jalur keluar. Test yang memang perlu perilaku
LLM tertentu memasang tiruannya sendiri, yang otomatis menimpa pemutus ini.
"""
import pytest


class JaringanDiblokir(RuntimeError):
    """Dilempar bila kode mencoba menghubungi layanan sungguhan saat pengujian."""


def _tolak(*_a, **_k):
    raise JaringanDiblokir("pemanggilan layanan sungguhan diblokir saat pengujian")


@pytest.fixture(autouse=True)
def _putus_layanan_luar(monkeypatch):
    # Kunci dari .env tidak boleh terbaca oleh kode yang diuji
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    import src.nlp.groq_reasoner as groq_reasoner
    import src.nlp.slm_extractor as slm_extractor
    import src.stt.backends as backends
    import src.stt.ensemble as ensemble

    # Groq: penalaran (tafsir, terjemahan, koreksi) dan rekonsiliasi.
    # Mengembalikan None meniru "Groq tidak dapat dihubungi" — jalur yang
    # memang harus ditangani kode dengan aman.
    monkeypatch.setattr(groq_reasoner, "_panggil_groq", lambda *a, **k: None)
    monkeypatch.setattr(ensemble, "_panggil_groq_llm", _tolak)
    monkeypatch.setattr(backends, "transcribe_groq", _tolak)

    # Ollama lokal
    monkeypatch.setattr(slm_extractor, "_chat", _tolak)
