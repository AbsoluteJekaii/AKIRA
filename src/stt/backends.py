"""
Mesin Speech-to-Text.
Tanggung jawab: Person 2 (Audio Pipeline Lead)

Empat nama mesin, dipilih lewat `stt.engine` di config/settings.yaml:

    whisper     Whisper lokal (small). Gratis, offline, selalu jadi cadangan.
    groq-turbo  whisper-large-v3-turbo di Groq. Cepat.
    groq-v3     whisper-large-v3 di Groq. Sedikit lebih teliti.
    groq        sama dengan groq-turbo (nama lama, dipertahankan)

Semua mengembalikan string, jadi modul lain tidak perlu tahu mana yang dipakai.

Kalau mesin pilihan gagal (internet putus, kuota habis), sistem jatuh ke
Whisper lokal — perbedaan antara "agak meleset" dan "bisu total" saat demo.
"""
import os

from loguru import logger

INITIAL_PROMPT = (
    "Perintah asisten jadwal berbahasa Indonesia. "
    "Kosakata umum: catat jadwal, cek jadwal, bacakan jadwal, hapus jadwal, "
    "geser jadwal, reschedule, meeting, rapat divisi, presentasi, kuliah, "
    "besok, lusa, minggu depan, bulan depan, hari Senin sampai Minggu, "
    "Januari Februari Maret April Mei Juni Juli Agustus September Oktober "
    "November Desember, tahun 2026, jam 3 sore, jam setengah 8 pagi, "
    "sekarang jam berapa."
)


# ------------------------------------------------------------ Whisper lokal
_model_cache = {}


def _muat_whisper(model_size: str, device: str):
    import whisper

    kunci = (model_size, device)
    if kunci not in _model_cache:
        logger.info(f"Loading Whisper model '{model_size}' di {device}...")
        _model_cache[kunci] = whisper.load_model(model_size, device=device)
    return _model_cache[kunci]


def transcribe_whisper(audio_path: str, model_size="small", device="cuda", language="id") -> str:
    model = _muat_whisper(model_size, device)
    hasil = model.transcribe(
        audio_path,
        language=language,
        fp16=(device == "cuda"),
        initial_prompt=INITIAL_PROMPT,
        temperature=0.0,
        condition_on_previous_text=False,
        beam_size=int(os.getenv("WHISPER_BEAM_SIZE", "1")),
        no_speech_threshold=0.6,
        compression_ratio_threshold=2.4,
    )
    return hasil["text"].strip()


# --------------------------------------------------------------------- Groq
# Groq menjalankan whisper-large-v3-turbo di perangkat kerasnya sendiri.
# Untuk AKIRA ini menarik karena dua hal sekaligus: modelnya JAUH lebih besar
# daripada `small` yang muat di RTX 3050, tapi latensinya justru lebih rendah
# karena tidak dijalankan di laptop.
GROQ_MODEL_DEFAULT = "whisper-large-v3-turbo"


def transcribe_groq(audio_path: str, language="id", timeout_s: int = 30,
                    groq_model: str = None, **_) -> str:
    """
    Transkripsi lewat Groq (whisper-large-v3-turbo).

    Butuh `GROQ_API_KEY` di .env. Satu panggilan saja — tidak perlu unggah
    lalu polling seperti layanan transkripsi lain, jadi biasanya paling cepat
    di antara mesin cloud.

    Melempar exception kalau gagal; pemanggil yang memutuskan cadangannya.
    """
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY belum diisi di .env")

    model = groq_model or os.getenv("GROQ_STT_MODEL", GROQ_MODEL_DEFAULT)

    try:
        from groq import Groq

        client = Groq(api_key=api_key, timeout=timeout_s)
        with open(audio_path, "rb") as f:
            hasil = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model=model,
                language=language,
                temperature=0,
                # prompt mengarahkan kosakata, sama seperti initial_prompt Whisper lokal
                prompt=INITIAL_PROMPT,
                response_format="verbose_json",
            )
        return (hasil.text or "").strip()

    except ImportError:
        # SDK belum terpasang — pakai HTTP langsung supaya tetap jalan
        logger.debug("SDK groq tidak ada, memakai HTTP langsung")
        return _groq_via_http(audio_path, api_key, model, language, timeout_s)


def _groq_via_http(audio_path: str, api_key: str, model: str, language: str, timeout_s: int) -> str:
    """Jalur cadangan tanpa SDK groq — hanya butuh `requests`."""
    import requests

    with open(audio_path, "rb") as f:
        response = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (os.path.basename(audio_path), f, "audio/wav")},
            data={
                "model": model,
                "language": language,
                "temperature": "0",
                "prompt": INITIAL_PROMPT,
                "response_format": "json",
            },
            timeout=timeout_s,
        )
    response.raise_for_status()
    return (response.json().get("text") or "").strip()


# ------------------------------------------------------------------ fasad
BACKEND = {
    "whisper": transcribe_whisper,
    "groq": transcribe_groq,
    # Dua model Whisper berbeda di Groq, dipakai sebagai dua "mesin" terpisah.
    # turbo lebih cepat, v3 (non-turbo) sedikit lebih teliti — keduanya salah
    # di tempat yang berbeda, dan itulah gunanya untuk voting.
    "groq-turbo": lambda path, **kw: transcribe_groq(
        path, groq_model="whisper-large-v3-turbo", **kw
    ),
    "groq-v3": lambda path, **kw: transcribe_groq(
        path, groq_model="whisper-large-v3", **kw
    ),
}


def get_backend(nama: str):
    """Ambil fungsi transkripsi sesuai nama mesin. Tidak dikenal -> Whisper lokal."""
    nama = (nama or "whisper").lower().strip()
    if nama not in BACKEND:
        logger.warning(f"Mesin STT '{nama}' tidak dikenal, memakai Whisper lokal")
        return BACKEND["whisper"]
    return BACKEND[nama]


def transcribe_dengan_cadangan(
    audio_path: str,
    engine: str = "whisper",
    model_size: str = "small",
    device: str = "cuda",
    language: str = "id",
) -> str:
    """
    Transkripsi dengan mesin pilihan; jatuh ke Whisper lokal kalau gagal.

    Cadangan ini bukan basa-basi: Groq butuh internet, dan wifi kampus
    saat final adalah hal yang tidak bisa kamu kendalikan. Lebih baik
    transkripsi agak meleset daripada AKIRA bisu di depan juri.
    """
    fungsi = get_backend(engine)

    try:
        teks = fungsi(audio_path, model_size=model_size, device=device, language=language)
        if teks:
            return teks
        logger.info(f"Mesin '{engine}' mengembalikan teks kosong")
        return ""
    except Exception as e:
        if fungsi is BACKEND["whisper"]:
            logger.error(f"Whisper lokal gagal: {e}")
            return ""
        logger.warning(f"Mesin '{engine}' gagal ({e}), jatuh ke Whisper lokal")

    try:
        return transcribe_whisper(audio_path, model_size, device, language)
    except Exception as e:
        logger.error(f"Whisper cadangan juga gagal: {e}")
        return ""


def warmup_backend(engine: str, model_size: str, device: str):
    """
    Muat model lokal lebih awal supaya perintah pertama tidak kena beban
    loading. Mesin Groq tidak punya model untuk dimuat, tapi Whisper lokal
    tetap disiapkan sebagai cadangan saat internet mati.
    """
    engine = (engine or "whisper").lower()
    try:
        if engine.startswith("groq") and not os.getenv("GROQ_API_KEY", "").strip():
            logger.warning("GROQ_API_KEY kosong — akan selalu jatuh ke Whisper lokal")
        _muat_whisper(model_size, device)
        logger.info(f"Model STT lokal ({model_size}) dimuat")
    except Exception as e:
        logger.warning(f"Warmup mesin STT gagal: {e}")

def cek_kesiapan() -> dict:
    """
    Status tiap mesin STT: terpasang? API key terisi? Dipakai skrip diagnosa
    dan saat startup, supaya masalah konfigurasi ketahuan sebelum demo.
    """
    status = {}

    for nama, modul, env_key in [
        ("whisper", "whisper", None),
        ("groq", "requests", "GROQ_API_KEY"),
        ("groq-turbo", "requests", "GROQ_API_KEY"),
        ("groq-v3", "requests", "GROQ_API_KEY"),
    ]:
        try:
            __import__(modul)
        except ImportError:
            status[nama] = "library belum terpasang"
            continue

        if env_key and not os.getenv(env_key, "").strip():
            status[nama] = f"{env_key} KOSONG"
        else:
            status[nama] = "siap"

    return status


def mesin_siap(daftar: list) -> list:
    """Saring daftar mesin, sisakan yang benar-benar bisa dipakai."""
    status = cek_kesiapan()
    siap = [m for m in daftar if status.get(m.replace("groq-whisper", "groq")) == "siap"]

    dilewati = [m for m in daftar if m not in siap]
    if dilewati:
        logger.warning(f"Mesin STT dilewati (belum siap): {', '.join(dilewati)}")
    return siap


if __name__ == "__main__":
    # python -m src.stt.backends
    print("Status mesin STT:\n")
    for nama, keterangan in cek_kesiapan().items():
        tanda = "OK " if keterangan == "siap" else "-  "
        print(f"  [{tanda}] {nama:16} {keterangan}")
