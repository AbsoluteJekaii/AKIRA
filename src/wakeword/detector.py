"""
Modul deteksi wake word "AKIRA WAKE UP" pakai openWakeWord.
Tanggung jawab: Person 2 (Audio Pipeline Lead) — Sprint 3.1

PENTING: file model .onnx (akira_wake_up.onnx) harus sudah hasil training
via notebook Colab (lihat docs/wakeword_training.md), taruh di models/.

Perbaikan Sprint 3.1 — wake word suka aktif sendiri:

1. KONFIRMASI BEBERAPA FRAME. Satu frame melewati ambang tidak cukup.
   Skor harus bertahan di atas ambang selama `confirm_frames` frame
   berturut-turut (default 2 = 160 ms). Suara sesaat — batuk, pintu,
   kursi bergeser — biasanya hanya memicu satu frame.

2. COOLDOWN. Setelah wake word dikenali, detektor menolak deteksi baru
   selama `cooldown_s` detik. Ini mencegah sisa gema atau suara AKIRA
   sendiri langsung memicu sesi berikutnya.

3. BUANG AUDIO BASI. Buffer mic dikosongkan saat mulai mendengar, supaya
   audio yang menumpuk selama sesi sebelumnya tidak ikut dinilai.
"""
import time

import numpy as np
import pyaudio
from loguru import logger
from openwakeword.model import Model

CHUNK_SIZE = 1280  # openWakeWord expects 80ms chunks at 16kHz (1280 samples)
SAMPLE_RATE = 16000

DEFAULT_THRESHOLD = 0.6      # dinaikkan dari 0.5 — 0.5 terlalu mudah kepicu
DEFAULT_CONFIRM_FRAMES = 2   # 2 frame = 160 ms skor harus bertahan tinggi
DEFAULT_COOLDOWN_S = 3.0     # abaikan deteksi sekian detik setelah sesi selesai

_model_cache = {}
_last_detection_time = 0.0


def load_model(model_paths, threshold: float = DEFAULT_THRESHOLD) -> Model:
    """
    Load model wake word custom dari file .onnx, dengan cache.

    Cache penting: app.py memanggil listen_for_wakeword() lagi setiap kali satu
    sesi selesai. Tanpa cache, model di-load ulang tiap kali dan ada jeda
    beberapa detik di mana AKIRA tuli terhadap panggilan.
    """
    if isinstance(model_paths, str):
        model_paths = [model_paths]

    kunci = "|".join(sorted(model_paths))
    if kunci not in _model_cache:
        logger.info(f"Loading wakeword model: {', '.join(model_paths)}")
        _model_cache[kunci] = Model(wakeword_models=list(model_paths))
    return _model_cache[kunci]


def listen_for_wakeword(
    model_path,
    threshold: float = DEFAULT_THRESHOLD,
    confirm_frames: int = DEFAULT_CONFIRM_FRAMES,
    cooldown_s: float = DEFAULT_COOLDOWN_S,
    threshold_per_model: dict = None,
    interupsi=None,
) -> str | None:
    """
    Loop blocking: dengarkan mic sampai salah satu wake word terdeteksi.

    model_path boleh berupa satu path atau daftar path — beberapa wake word
    bisa didengarkan sekaligus dalam satu stream mic.

    threshold_per_model: ambang khusus untuk model tertentu, mis.
    {"akira_destroy": 0.8}. Model yang tidak disebut memakai `threshold` biasa.
    Berguna saat dua frasa mirip — yang berisiko diberi ambang lebih tinggi.

    interupsi: fungsi tanpa argumen yang dipanggil tiap siklus. Bila
    mengembalikan True, pendengaran dihentikan dan fungsi mengembalikan None.
    Dipakai antarmuka untuk membangunkan AKIRA lewat tombol atau pintasan
    keyboard — tanpa ini, permintaan dari antarmuka tidak akan pernah terbaca
    karena loop ini memblokir selamanya.

    Return NAMA model yang memicu (string, truthy), atau None kalau dihentikan.
    Nama inilah yang dipakai app.py untuk membedakan "AKIRA WAKE UP" dari
    wake word lain seperti perintah rahasia.

    "Benar-benar terdeteksi" berarti skor bertahan di atas `threshold` selama
    `confirm_frames` frame berturut-turut, dan cooldown sejak deteksi terakhir
    sudah lewat.
    """
    global _last_detection_time

    oww_model = load_model(model_path, threshold)
    nama_model = list(oww_model.models.keys())
    threshold_per_model = threshold_per_model or {}

    def ambang(nama: str) -> float:
        """Ambang yang berlaku untuk satu model."""
        for kunci, nilai in threshold_per_model.items():
            if kunci in nama:
                return nilai
        return threshold

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE,
    )

    logger.info("Menunggu wake word 'AKIRA WAKE UP'...")
    try:
        try:
            oww_model.reset()  # buang skor sisa sesi sebelumnya
        except Exception:
            pass

        # Buang audio yang menumpuk di buffer selama sesi sebelumnya berjalan
        for _ in range(int(SAMPLE_RATE / CHUNK_SIZE)):
            try:
                stream.read(CHUNK_SIZE, exception_on_overflow=False)
            except Exception:
                break

        hits = 0
        skor_tertinggi = 0.0
        model_terpicu = None

        while True:
            if interupsi is not None:
                try:
                    if interupsi():
                        logger.debug("Pendengaran wake word dihentikan oleh interupsi")
                        return None
                except Exception as e:
                    logger.warning(f"Pemeriksa interupsi error: {e}")

            audio_chunk = np.frombuffer(
                stream.read(CHUNK_SIZE, exception_on_overflow=False), dtype=np.int16
            )
            prediksi = oww_model.predict(audio_chunk)

            # Ambil model yang skornya paling jauh MELAMPAUI ambangnya sendiri.
            # Membandingkan skor mentah tidak adil kalau ambangnya berbeda.
            def margin(n):
                return prediksi.get(n, 0.0) - ambang(n)

            terbaik = max(nama_model, key=margin)
            score = prediksi.get(terbaik, 0.0)

            if score > ambang(terbaik):
                # Kalau model yang memicu berganti, hitungan konfirmasi diulang
                if model_terpicu and terbaik != model_terpicu:
                    hits = 0
                    skor_tertinggi = 0.0
                model_terpicu = terbaik
                hits += 1
                skor_tertinggi = max(skor_tertinggi, score)
            else:
                if hits:
                    logger.debug(f"Deteksi sesaat diabaikan ({hits} frame, skor {skor_tertinggi:.3f})")
                hits = 0
                skor_tertinggi = 0.0
                model_terpicu = None
                continue

            if hits < confirm_frames:
                continue

            sejak_terakhir = time.time() - _last_detection_time
            if sejak_terakhir < cooldown_s:
                logger.debug(f"Deteksi diabaikan, masih cooldown ({sejak_terakhir:.1f}s)")
                hits = 0
                skor_tertinggi = 0.0
                continue

            _last_detection_time = time.time()
            logger.info(
                f"Wake word '{model_terpicu}' terdeteksi! "
                f"(skor {skor_tertinggi:.3f} / ambang {ambang(model_terpicu):.2f}, "
                f"bertahan {hits} frame)"
            )
            return model_terpicu
    except KeyboardInterrupt:
        # Ctrl+C saat menunggu wake word = permintaan mematikan AKIRA.
        # Diteruskan ke run() yang menutupnya dengan rapi.
        logger.info("Dihentikan saat menunggu wake word")
        raise
    finally:
        # Penutupan stream tidak boleh melempar error baru dan menutupi
        # penyebab aslinya — ini yang bikin traceback muncul saat Ctrl+C.
        try:
            stream.stop_stream()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass
        try:
            pa.terminate()
        except Exception:
            pass


def tandai_deteksi_sekarang():
    """
    Setel ulang penanda waktu deteksi ke sekarang.
    Dipanggil app.py saat sesi SELESAI, supaya cooldown dihitung dari akhir sesi —
    bukan dari awal — dan suara AKIRA sendiri tidak memicu sesi baru.
    """
    global _last_detection_time
    _last_detection_time = time.time()


if __name__ == "__main__":
    # Test manual:  python -m src.wakeword.detector
    # Coba juga bikin suara berisik (tepuk tangan, batuk) — seharusnya TIDAK memicu.
    print("Ucapkan 'AKIRA WAKE UP'. Coba juga suara berisik untuk cek false trigger.")
    detected = listen_for_wakeword("models/akira_wake_up.onnx")
    print("Terdeteksi:", detected)
