"""
Jembatan antara antarmuka grafis dan mesin AKIRA.
Tanggung jawab: Person 1 (Integrator utama) — Sprint 4

Masalah yang diselesaikan:
`app.run()` adalah loop tak berujung yang memblokir. Kalau dipanggil langsung
dari Tkinter, jendela akan membeku total — tidak bisa diklik, tidak bisa
ditutup, dan Windows menandainya "Not Responding".

Modul ini menjalankan AKIRA di thread terpisah dan menyalurkan seluruh
keluaran log ke antrean yang dibaca antarmuka setiap 200 ms. Antarmuka tidak
pernah memanggil fungsi AKIRA yang memblokir secara langsung.
"""
import queue
import threading

from loguru import logger

# Antrean log: diisi thread AKIRA, dibaca thread antarmuka.
# maxsize mencegah kebocoran memori kalau antarmuka sempat tidak membaca.
antrean_log: "queue.Queue[str]" = queue.Queue(maxsize=2000)

_thread: threading.Thread | None = None
_berjalan = threading.Event()
_sink_id: int | None = None


def _kirim_ke_antrean(pesan):
    """Sink loguru: salin tiap baris log ke antrean antarmuka."""
    try:
        antrean_log.put_nowait(str(pesan).rstrip())
    except queue.Full:
        # Antrean penuh berarti antarmuka tertinggal jauh. Buang yang terlama
        # supaya log terbaru tetap masuk — kehilangan baris lama lebih baik
        # daripada kehilangan baris yang sedang terjadi.
        try:
            antrean_log.get_nowait()
            antrean_log.put_nowait(str(pesan).rstrip())
        except queue.Empty:
            pass


def pasang_sink():
    """Sambungkan log AKIRA ke antarmuka. Aman dipanggil berkali-kali."""
    global _sink_id
    if _sink_id is not None:
        return
    _sink_id = logger.add(
        _kirim_ke_antrean,
        format="{time:HH:mm:ss} | {level: <7} | {message}",
        level="INFO",
    )


def sedang_berjalan() -> bool:
    return _berjalan.is_set() and _thread is not None and _thread.is_alive()


def mulai() -> bool:
    """
    Jalankan AKIRA di thread latar. Return False kalau sudah berjalan.

    Thread dibuat daemon agar ikut mati saat jendela ditutup — tanpa itu,
    proses Python tetap hidup di latar meski jendelanya sudah hilang.
    """
    global _thread

    if sedang_berjalan():
        logger.warning("AKIRA sudah berjalan")
        return False

    pasang_sink()
    _berjalan.set()

    def jalan():
        try:
            from src.app import run

            run()
        except SystemExit:
            logger.info("AKIRA berhenti (self destruct)")
        except KeyboardInterrupt:
            logger.info("AKIRA dihentikan")
        except Exception as e:
            logger.error(f"AKIRA berhenti karena error: {e}")
            logger.exception("Detail:")
        finally:
            _berjalan.clear()

    _thread = threading.Thread(target=jalan, daemon=True, name="akira-engine")
    _thread.start()
    return True


def baca_log(maks: int = 200) -> list:
    """Ambil baris log yang menumpuk sejak pembacaan terakhir."""
    baris = []
    for _ in range(maks):
        try:
            baris.append(antrean_log.get_nowait())
        except queue.Empty:
            break
    return baris


# ------------------------------------------------------------ pemeriksaan
def cek_komponen(config: dict) -> list:
    """
    Periksa kesiapan tiap komponen tanpa menjalankan AKIRA.

    Return daftar (nama, status, keterangan) dengan status:
    "ok" | "peringatan" | "gagal".

    Dipakai tab Status. Pemeriksaan sengaja tidak melempar exception —
    satu komponen yang gagal tidak boleh menghentikan pemeriksaan lainnya.
    """
    import os

    hasil = []

    # --- Model wake word
    for label, kunci in [
        ("Wake word utama", ("wakeword", "model_path")),
        ("Wake word rahasia", ("self_destruct", "model_path")),
    ]:
        path = config
        for k in kunci:
            path = (path or {}).get(k) if isinstance(path, dict) else None
        if not path:
            hasil.append((label, "peringatan", "tidak diatur di config"))
        elif os.path.exists(path):
            ukuran = os.path.getsize(path) / 1024
            hasil.append((label, "ok", f"{os.path.basename(path)} ({ukuran:.0f} KB)"))
        else:
            tingkat = "gagal" if "utama" in label else "peringatan"
            hasil.append((label, tingkat, f"tidak ditemukan: {path}"))

    # --- Kredensial Google
    if os.path.exists("config/credentials.json"):
        if os.path.exists("config/token.json"):
            hasil.append(("Google Calendar", "ok", "credentials + token tersedia"))
        else:
            hasil.append(("Google Calendar", "peringatan",
                          "token belum ada — login saat pertama jalan"))
    else:
        hasil.append(("Google Calendar", "gagal", "config/credentials.json tidak ada"))

    # --- GPU
    try:
        import torch

        if torch.cuda.is_available():
            hasil.append(("GPU (CUDA)", "ok", torch.cuda.get_device_name(0)))
        else:
            hasil.append(("GPU (CUDA)", "peringatan",
                          "tidak terdeteksi — STT lokal akan lambat"))
    except ImportError:
        hasil.append(("GPU (CUDA)", "peringatan", "PyTorch belum terpasang"))

    # --- Mesin STT
    try:
        from src.stt.backends import cek_kesiapan

        status_stt = cek_kesiapan()
        daftar = config.get("stt", {}).get("engine", "whisper")
        daftar = daftar if isinstance(daftar, (list, tuple)) else [daftar]

        for mesin in daftar:
            ket = status_stt.get(str(mesin).replace("groq-whisper", "groq"), "tidak dikenal")
            hasil.append((f"STT: {mesin}", "ok" if ket == "siap" else "peringatan", ket))
    except Exception as e:
        hasil.append(("Mesin STT", "gagal", str(e)[:60]))

    # --- Ollama
    try:
        import ollama

        model = config.get("nlp", {}).get("ollama_model", "qwen3:4b")
        ollama.chat(model=model, messages=[{"role": "user", "content": "ping"}],
                    options={"num_predict": 1})
        hasil.append(("Ollama (LLM lokal)", "ok", model))
    except Exception as e:
        hasil.append(("Ollama (LLM lokal)", "peringatan", str(e)[:60]))

    # --- Perekonsiliasi lapis 2
    try:
        from src.stt.ensemble import _perekonsiliasi_siap

        diminta = (config.get("stt", {}).get("ensemble", {}) or {}).get(
            "perekonsiliasi", []
        )
        if diminta:
            siap = _perekonsiliasi_siap(list(diminta))
            hasil.append((
                "Rekonsiliasi lapis 2",
                "ok" if set(siap) == set(diminta) else "peringatan",
                ", ".join(siap),
            ))
    except Exception:
        pass

    # --- Mikrofon
    try:
        import sounddevice as sd

        masuk = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        if masuk:
            hasil.append(("Mikrofon", "ok", masuk[0]["name"][:50]))
        else:
            hasil.append(("Mikrofon", "gagal", "tidak ada perangkat input"))
    except Exception as e:
        hasil.append(("Mikrofon", "peringatan", str(e)[:60]))

    return hasil


def uji_mikrofon(durasi: float = 3.0) -> tuple:
    """
    Rekam beberapa detik lalu laporkan tingkat energinya.

    Berguna saat suara "tidak terdengar": memisahkan masalah mikrofon dari
    masalah pengenalan suara. Return (berhasil, pesan).
    """
    try:
        import numpy as np
        import sounddevice as sd

        rekaman = sd.rec(int(durasi * 16000), samplerate=16000, channels=1, dtype="int16")
        sd.wait()
        rms = float(np.sqrt(np.mean(rekaman.astype(float) ** 2)))

        if rms < 50:
            return False, f"Nyaris tidak ada suara (RMS {rms:.0f}). Cek mikrofon aktif?"
        if rms < 320:
            return False, (
                f"Suara terlalu pelan (RMS {rms:.0f}, ambang 320). "
                f"Dekatkan mikrofon atau turunkan audio.rms_ambang."
            )
        return True, f"Mikrofon baik (RMS {rms:.0f})."
    except Exception as e:
        return False, f"Gagal menguji mikrofon: {e}"
