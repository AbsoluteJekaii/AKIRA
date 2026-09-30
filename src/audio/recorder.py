"""
Modul rekam audio setelah wake word terdeteksi, dengan VAD (auto-stop saat diam).
Tanggung jawab: Person 2 (Audio Pipeline Lead)
"""
import array
import math
import queue
import wave

import sounddevice as sd
import webrtcvad
from loguru import logger

SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)

# Ambang energi (RMS 0-32767) untuk membedakan suara sungguhan dari noise latar.
# WebRTC VAD saja tidak cukup: kipas laptop, AC, dan dengung mikrofon sering
# lolos sebagai "speech", sehingga rekaman tidak pernah berhenti sendiri.
RMS_AMBANG = 320

# Rekaman yang terlalu pendek hampir pasti bukan perintah — biasanya batuk,
# ketukan meja, atau sisa suara AKIRA sendiri.
# Minimum frame bicara agar rekaman dianggap ucapan sungguhan.
#
# Dinaikkan dari 10: pada nilai lama, dengungan kipas dan suara dari speaker
# sendiri kadang lolos, lalu STT dipaksa menebak dari derau dan menghasilkan
# kalimat yang terdengar masuk akal. Satu frame = 30 ms, jadi 18 frame
# berarti sekitar setengah detik suara sungguhan — di bawah itu, ucapan
# manusia yang bermakna praktis tidak ada.
MIN_FRAME_BICARA = 10   # ~0,3 detik — untuk perintah bebas

# Jawaban atas pertanyaan AKIRA boleh jauh lebih pendek. "Ya", "boleh",
# "iya" hanya 4-8 frame; memakai batas perintah bebas membuat jawaban
# satu kata dibuang sebagai derau — AKIRA lalu bertanya ulang padahal
# sudah dijawab. Di titik ini user memang sedang ditanya, jadi risiko
# derau jauh lebih kecil, dan lapis deteksi derau di ensemble tetap aktif.
MIN_FRAME_JAWABAN = 4


def hitung_rms(frame: bytes) -> float:
    """Energi rata-rata satu frame audio 16-bit."""
    sampel = array.array("h", frame)
    if not sampel:
        return 0.0
    return math.sqrt(sum(s * s for s in sampel) / len(sampel))


def record_with_vad(
    max_silence_frames: int = 18,
    aggressiveness: int = 3,
    max_duration_s: int = 10,
    initial_timeout_s: float | None = None,
    rms_ambang: float = RMS_AMBANG,
    interupsi=None,
    min_frame_bicara: int = MIN_FRAME_BICARA,
) -> bytes:
    """
    Rekam audio dari mic, otomatis berhenti setelah `max_silence_frames`
    frame diam berturut-turut (default ~0.9 detik diam).

    max_duration_s     : batas keamanan kalau VAD gagal mendeteksi diam.
    initial_timeout_s  : kalau user TIDAK mulai bicara dalam sekian detik,
                         kembalikan bytes kosong. Dipakai mode percakapan:
                         AKIRA menunggu perintah lanjutan sebentar, lalu
                         balik standby sendiri tanpa harus dipanggil ulang.
    rms_ambang         : energi minimum agar sebuah frame dihitung sebagai
                         suara. Naikkan kalau ruangan berisik, turunkan kalau
                         suaramu pelan atau mic-nya kurang sensitif.
    interupsi          : fungsi tanpa argumen; kalau mengembalikan True,
                         perekaman dihentikan dan hasilnya kosong. Dipakai
                         antarmuka: menekan pintasan saat AKIRA sedang
                         mendengar tidak perlu menunggu rekaman selesai —
                         tanpa ini, penundaannya bisa belasan detik.

    Frame dianggap bicara hanya kalau VAD DAN energi sama-sama setuju.
    Dua lapis ini yang membuat rekaman berhenti tepat waktu di ruangan berisik.
    """
    vad = webrtcvad.Vad(aggressiveness)
    q = queue.Queue()
    frames = []
    silence_count = 0
    speech_started = False
    frame_bicara = 0
    max_frames = int((max_duration_s * 1000) / FRAME_DURATION_MS)
    initial_limit = (
        int((initial_timeout_s * 1000) / FRAME_DURATION_MS) if initial_timeout_s else None
    )
    leading_frames = 0

    def callback(indata, frames_count, time_info, status):
        q.put(bytes(indata))

    logger.info("Merekam... (bicara sekarang)")
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=FRAME_SIZE,
        dtype="int16",
        channels=1,
        callback=callback,
    ):
        while len(frames) < max_frames:
            # Diperiksa SEBELUM pengambilan frame, yang memblokir sampai
            # potongan audio berikutnya tersedia.
            if interupsi is not None and not speech_started:
                try:
                    if interupsi():
                        logger.info("Perekaman dihentikan oleh pemicu antarmuka")
                        return b""
                except Exception as e:
                    logger.warning(f"Pemeriksa interupsi error: {e}")

            frame = q.get()
            # Dua syarat: VAD mengenali pola suara DAN energinya cukup.
            is_speech = vad.is_speech(frame, SAMPLE_RATE) and hitung_rms(frame) >= rms_ambang

            if not speech_started:
                leading_frames += 1
                if is_speech:
                    speech_started = True
                elif initial_limit and leading_frames > initial_limit:
                    logger.info("Tidak ada suara dalam batas waktu, berhenti mendengar")
                    return b""
                # Simpan sedikit frame sebelum bicara supaya suku kata awal tidak terpotong
                frames.append(frame)
                if len(frames) > 10 and not speech_started:
                    frames.pop(0)
                continue

            frames.append(frame)
            if is_speech:
                silence_count = 0
                frame_bicara += 1
            else:
                silence_count += 1
            if silence_count > max_silence_frames and len(frames) > 10:
                break

    durasi = len(frames) * FRAME_DURATION_MS / 1000

    # Buang rekaman yang isinya hampir seluruhnya noise. Tanpa ini, Whisper
    # dipaksa menebak dari keheningan dan menghasilkan halusinasi seperti
    # "Terima kasih kerana menonton".
    if frame_bicara < min_frame_bicara:
        logger.info(f"Rekaman diabaikan: hanya {frame_bicara} frame suara dari noise")
        return b""

    logger.info(f"Rekaman selesai ({durasi:.1f} detik, {frame_bicara} frame suara)")
    return b"".join(frames)


def save_wav(audio_bytes: bytes, path: str = "temp_recording.wav"):
    """Simpan hasil rekaman ke file .wav (dibutuhkan Whisper untuk transkripsi)."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_bytes)
    return path


if __name__ == "__main__":
    # Test manual:
    #   python -m src.audio.recorder
    audio = record_with_vad()
    path = save_wav(audio)
    print(f"Tersimpan di {path}")
