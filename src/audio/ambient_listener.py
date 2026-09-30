"""
Pendengar ambient: satu stream mikrofon, dua tugas sekaligus.
Tanggung jawab: Person 2 (Audio Pipeline Lead) — Sprint 3.22

Masalah yang diselesaikan:
Mode ambient merekam kalimat penuh lalu mentranskripsinya dengan Whisper.
Selama itu berlangsung, mikrofon dipegang penuh — model wake word tidak
pernah mendapat giliran mendengar. Akibatnya perintah rahasia hanya bisa
dideteksi dari TEKS hasil Whisper, dan Whisper rutin salah dengar
("destrui diri sendiri", "Akhirnya"). Untuk perintah yang menghapus sistem,
bergantung pada tebakan Whisper itu pilihan yang buruk.

Solusinya: satu loop yang membaca mikrofon sekali, lalu memberi potongan
audio yang sama ke DUA pemroses:

1. **openWakeWord** — tiap potongan 80 ms langsung dinilai. Murah, deterministik,
   dan sama sekali tidak melibatkan Whisper. Ini yang menangkap
   "AKIRA DESTROY YOURSELF".
2. **VAD** — mendeteksi kapan ada orang bicara, lalu merekam sampai diam.
   Hasil rekamannya baru dikirim ke Whisper. Kalau ruangan sepi, Whisper
   tidak pernah dipanggil.

Jadi wake word tidak lagi bergantung pada akurasi transkripsi.
"""
import array
import math
import time

import numpy as np
import pyaudio
import webrtcvad
from loguru import logger

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280          # 80 ms — ukuran yang diharapkan openWakeWord
VAD_FRAME_SAMPLES = 320       # 20 ms — ukuran yang diterima webrtcvad
VAD_FRAMES_PER_CHUNK = CHUNK_SAMPLES // VAD_FRAME_SAMPLES   # 4


def _rms(frame_bytes: bytes) -> float:
    sampel = array.array("h", frame_bytes)
    if not sampel:
        return 0.0
    return math.sqrt(sum(s * s for s in sampel) / len(sampel))


class PendengarAmbient:
    """
    Membuka mikrofon sekali, lalu melayani wake word dan perekaman suara
    dari stream yang sama.

    Dipakai sebagai context manager supaya stream selalu ditutup rapi:

        with PendengarAmbient(model_paths, ...) as pendengar:
            jenis, isi = pendengar.dengar(batas_detik=3)
    """

    def __init__(
        self,
        model_paths,
        threshold: float = 0.6,
        threshold_per_model: dict = None,
        confirm_frames: int = 2,
        vad_aggressiveness: int = 3,
        rms_ambang: float = 320,
        max_silence_frames: int = 18,
        max_duration_s: int = 10,
    ):
        from src.wakeword.detector import load_model

        self.oww = load_model(model_paths, threshold)
        self.nama_model = list(self.oww.models.keys())
        self.threshold = threshold
        self.threshold_per_model = threshold_per_model or {}
        self.confirm_frames = confirm_frames
        self.vad = webrtcvad.Vad(vad_aggressiveness)
        self.rms_ambang = rms_ambang
        self.max_silence_frames = max_silence_frames
        self.max_duration_s = max_duration_s

        self._pa = None
        self._stream = None
        self._hits = 0
        self._model_terpicu = None

    # ------------------------------------------------------------ context
    def __enter__(self):
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SAMPLES,
        )
        try:
            self.oww.reset()
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        for tutup in (
            lambda: self._stream.stop_stream(),
            lambda: self._stream.close(),
            lambda: self._pa.terminate(),
        ):
            try:
                tutup()
            except Exception:
                pass
        return False

    # ------------------------------------------------------------ helper
    def _ambang(self, nama: str) -> float:
        for kunci, nilai in self.threshold_per_model.items():
            if kunci in nama:
                return nilai
        return self.threshold

    def _baca_chunk(self) -> bytes:
        return self._stream.read(CHUNK_SAMPLES, exception_on_overflow=False)

    def _cek_wakeword(self, chunk: bytes) -> str | None:
        """Nilai satu potongan dengan openWakeWord. Return nama model kalau terpicu."""
        audio = np.frombuffer(chunk, dtype=np.int16)
        prediksi = self.oww.predict(audio)

        terbaik = max(self.nama_model, key=lambda n: prediksi.get(n, 0.0) - self._ambang(n))
        skor = prediksi.get(terbaik, 0.0)

        if skor <= self._ambang(terbaik):
            self._hits = 0
            self._model_terpicu = None
            return None

        if self._model_terpicu and terbaik != self._model_terpicu:
            self._hits = 0
        self._model_terpicu = terbaik
        self._hits += 1

        if self._hits < self.confirm_frames:
            return None

        logger.info(f"Wake word '{terbaik}' terdeteksi di mode ambient (skor {skor:.3f})")
        self._hits = 0
        self._model_terpicu = None
        return terbaik

    def _ada_suara(self, chunk: bytes) -> bool:
        """True kalau potongan ini berisi suara orang (VAD + energi)."""
        if _rms(chunk) < self.rms_ambang:
            return False
        for i in range(VAD_FRAMES_PER_CHUNK):
            awal = i * VAD_FRAME_SAMPLES * 2       # 2 byte per sampel
            frame = chunk[awal:awal + VAD_FRAME_SAMPLES * 2]
            if len(frame) == VAD_FRAME_SAMPLES * 2 and self.vad.is_speech(frame, SAMPLE_RATE):
                return True
        return False

    # ------------------------------------------------------------ utama
    def dengar(self, batas_detik: float = 3.0):
        """
        Dengarkan sampai salah satu terjadi:

        - wake word terdeteksi  -> ("wakeword", nama_model)
        - ada orang bicara      -> ("suara", bytes audio)
        - batas waktu habis     -> ("sepi", None)

        Wake word dicek pada SETIAP potongan, termasuk saat sedang merekam
        kalimat. Jadi mengucapkan frasa rahasia di tengah kalimat lain tetap
        tertangkap, dan tidak sekali pun melewati Whisper.
        """
        batas = time.time() + batas_detik
        frames = []
        merekam = False
        diam = 0
        frame_bicara = 0
        max_chunk = int(self.max_duration_s * SAMPLE_RATE / CHUNK_SAMPLES)

        while True:
            chunk = self._baca_chunk()

            terpicu = self._cek_wakeword(chunk)
            if terpicu:
                return "wakeword", terpicu

            bicara = self._ada_suara(chunk)

            if not merekam:
                if bicara:
                    merekam = True
                    frames = [chunk]
                    frame_bicara = 1
                    diam = 0
                elif time.time() > batas:
                    return "sepi", None
                continue

            frames.append(chunk)
            if bicara:
                frame_bicara += 1
                diam = 0
            else:
                # 1 chunk = 80 ms; max_silence_frames dihitung dalam frame 30 ms
                diam += VAD_FRAMES_PER_CHUNK

            if diam > self.max_silence_frames or len(frames) >= max_chunk:
                durasi = len(frames) * CHUNK_SAMPLES / SAMPLE_RATE
                if frame_bicara < 2:
                    logger.debug("Rekaman ambient diabaikan: isinya noise")
                    return "sepi", None
                logger.info(f"Rekaman ambient selesai ({durasi:.1f} detik)")
                return "suara", b"".join(frames)


if __name__ == "__main__":
    # python -m src.audio.ambient_listener
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    model_utama = cfg["wakeword"]["model_path"]
    model_rahasia = cfg.get("self_destruct", {}).get("model_path")

    paths = [model_utama]
    ambang = {}
    if model_rahasia:
        import os

        if os.path.exists(model_rahasia):
            paths.append(model_rahasia)
            nama = os.path.splitext(os.path.basename(model_rahasia))[0]
            ambang[nama] = cfg["self_destruct"].get("threshold", 0.7)

    print(f"Mendengarkan {len(paths)} wake word. Coba ucapkan salah satunya,")
    print("atau bicara biasa untuk melihat deteksi suara. Ctrl+C untuk berhenti.\n")

    with PendengarAmbient(paths, cfg["wakeword"]["threshold"], ambang) as p:
        try:
            while True:
                jenis, isi = p.dengar(batas_detik=5)
                if jenis == "wakeword":
                    print(f"  >> WAKE WORD: {isi}")
                elif jenis == "suara":
                    print(f"  >> suara terekam ({len(isi) / 32000:.1f} detik)")
        except KeyboardInterrupt:
            print("\nSelesai.")
