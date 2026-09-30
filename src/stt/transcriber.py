"""
Fasad Speech-to-Text: memilih mesin, lalu menyaring hasilnya.
Tanggung jawab: Person 2 (Audio Pipeline Lead)

Mesinnya sendiri ada di backends.py, penggabungan beberapa mesin di
ensemble.py. Modul ini hanya meneruskan dan menyaring — penyaring halusinasi
dan pengulangan sengaja dipasang DI SINI supaya berlaku untuk mesin apa pun.
"""
import os
import re

from loguru import logger


# Konteks yang diberikan ke Whisper sebelum transkripsi.
# Ini cara termurah menaikkan akurasi: model jadi condong ke kosakata jadwal
# dan format tanggal Indonesia, tanpa perlu ganti ke model yang lebih besar.
INITIAL_PROMPT = (
    "Perintah asisten jadwal berbahasa Indonesia. "
    "Kosakata umum: catat jadwal, cek jadwal, bacakan jadwal, hapus jadwal, "
    "geser jadwal, reschedule, meeting, rapat divisi, presentasi, kuliah, "
    "besok, lusa, minggu depan, bulan depan, hari Senin sampai Minggu, "
    "Januari Februari Maret April Mei Juni Juli Agustus September Oktober November Desember, "
    "tahun 2026, tahun 2027, jam 3 sore, jam setengah 8 pagi, sekarang jam berapa."
)


# Opsi ensemble, diisi app.py saat startup supaya transcribe() tidak perlu
# menerima config penuh di setiap panggilan.
_ENSEMBLE_OPSI = {}


def set_opsi_ensemble(timeout_s=12.0, perekonsiliasi=None, model_perekonsiliasi=None):
    """Dipanggil sekali dari app.py setelah config dibaca."""
    _ENSEMBLE_OPSI.update({
        "timeout_s": timeout_s,
        "perekonsiliasi": perekonsiliasi,
        "model_perekonsiliasi": model_perekonsiliasi or {},
    })


# Kalimat yang SERING dihalusinasikan Whisper saat inputnya sunyi atau cuma
# noise. Ini artefak data latih Whisper (banyak subtitle YouTube), bukan hasil
# dengar sungguhan. Di log terlihat sebagai transkripsi seperti
# "Terima kasih kerana menonton!" padahal user tidak bicara apa-apa.
HALUSINASI_UMUM = [
    "terima kasih kerana menonton",
    "terima kasih telah menonton",
    "terima kasih sudah menonton",
    "jangan lupa like dan subscribe",
    "jangan lupa subscribe",
    "sampai jumpa di video berikutnya",
    "sampai jumpa di video selanjutnya",
    "subtitle by",
    "sub by",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "amara.org",
]


def _terjebak_mengulang(text: str, min_kata: int = 12, ambang: float = 0.35) -> bool:
    """
    True kalau Whisper terjebak mengulang frasa yang sama.

    Gejala khas decoder yang macet: "Kuala Lumpur, Kuala Lumpur, Kuala Lumpur..."
    sampai batas token habis. Hasilnya bukan transkripsi, dan kalau diteruskan
    ke parser bisa memicu aksi yang tidak diinginkan.

    Ambang: kalau kata unik kurang dari 35% dari total kata, teks dianggap macet.
    """
    kata = re.findall(r"\w+", text.lower())
    if len(kata) < min_kata:
        return False
    return (len(set(kata)) / len(kata)) < ambang


def _is_halusinasi(text: str) -> bool:
    """True kalau teks hanya berisi frasa halusinasi khas Whisper."""
    t = text.lower().strip(" .!?,")
    if not t:
        return False
    return any(frasa in t for frasa in HALUSINASI_UMUM)


def transcribe(
    audio_path: str,
    model_size: str = "small",
    device: str = "cuda",
    language: str = "id",
    engine: str = None,
) -> str:
    """
    Transkripsi file audio (.wav) jadi teks.

    Mesin yang dipakai ditentukan `engine` (atau env STT_ENGINE, default
    "whisper"). Apa pun mesinnya, hasilnya lewat penyaring yang sama:
    halusinasi khas dan output yang terjebak mengulang tetap dibuang.

    Penyaring itu sengaja dipasang DI SINI, bukan di tiap backend — supaya
    mengganti mesin tidak berarti kehilangan perlindungan yang sudah ada.
    """
    from src.stt.backends import transcribe_dengan_cadangan

    engine = engine or os.getenv("STT_ENGINE", "whisper")

    if isinstance(engine, (list, tuple)):
        # Beberapa mesin sekaligus -> ensemble
        from src.stt.ensemble import transcribe_ensemble

        text = transcribe_ensemble(
            audio_path,
            list(engine),
            timeout_s=_ENSEMBLE_OPSI.get("timeout_s", 12.0),
            perekonsiliasi=_ENSEMBLE_OPSI.get("perekonsiliasi"),
            model_perekonsiliasi=_ENSEMBLE_OPSI.get("model_perekonsiliasi"),
            model_size=model_size,
            device=device,
            language=language,
        )
    else:
        text = transcribe_dengan_cadangan(
            audio_path,
            engine=engine,
            model_size=model_size,
            device=device,
            language=language,
        )

    if not text:
        return ""

    if _is_halusinasi(text):
        logger.warning(f"Transkripsi diabaikan (halusinasi): '{text}'")
        return ""

    if _terjebak_mengulang(text):
        logger.warning(f"Transkripsi diabaikan (terjebak mengulang): '{text[:70]}...'")
        return ""

    if isinstance(engine, (list, tuple)):
        # Sebutkan mesin yang BENAR-BENAR berhasil, bukan daftar dari config.
        from src.stt.ensemble import mesin_terpakai

        label = "+".join(mesin_terpakai()) or "tidak ada"
    else:
        label = engine
    logger.info(f"Transkripsi [{label}]: '{text}'")
    return text


def warmup(model_size: str = "small", device: str = "cuda", engine: str = None):
    """
    Muat model STT saat startup.
    Tanpa ini, perintah PERTAMA user selalu kena beban loading model.
    """
    from src.stt.backends import warmup_backend

    engine = engine or os.getenv("STT_ENGINE", "whisper")
    if isinstance(engine, (list, tuple)):
        # Yang perlu dipanaskan hanya mesin lokal; yang cloud tidak punya
        # model untuk dimuat.
        for nama in engine:
            if "whisper" in nama and nama != "groq-whisper":
                warmup_backend(nama, model_size, device)
        return

    warmup_backend(engine, model_size, device)


if __name__ == "__main__":
    # Test manual (butuh file audio hasil recorder.py dulu):
    #   python -m src.stt.transcriber
    text = transcribe("temp_recording.wav", model_size="small")
    print("Hasil:", text)
