"""
Modul Text-to-Speech AKIRA.
Tanggung jawab: Person 4 (Voice Output, Dialog UX & QA Lead) — Sprint 3

Strategi 3 lapis (otomatis jatuh ke bawah kalau gagal):
1. Edge TTS  — suara neural Indonesia (Gadis), paling natural, BUTUH INTERNET
2. Piper     — suara Indonesia offline, jaga-jaga internet mati saat demo
3. pyttsx3   — suara Windows bawaan, aksen Inggris, pilihan terakhir

Tiga perbaikan besar di Sprint 3:

A. LATENSI. Dulu tiap kalimat: buat file mp3 -> panggil ffmpeg (proses baru) ->
   baca file wav -> putar. ffmpeg saja makan ratusan milidetik.
   Sekarang audio disintesis ke MEMORI dan didekode langsung oleh soundfile;
   ffmpeg cuma dipakai kalau soundfile menolak mp3-nya.

B. PIPELINING. Teks panjang dipecah per kalimat. Kalimat berikutnya disintesis
   di thread lain SAMBIL kalimat sekarang diputar, jadi user mendengar suara
   pertama jauh lebih cepat.

C. BISA DIPOTONG (barge-in). Saat AKIRA membacakan daftar jadwal, tekan
   ENTER / spasi / Ctrl+C untuk memotong. Tidak perlu mendengarkan sampai habis.
"""
import asyncio
import io
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

from loguru import logger

# Suara Edge TTS. Bisa ditimpa lewat .env (EDGE_VOICE / EDGE_RATE / EDGE_PITCH)
# tanpa mengubah kode — berguna untuk mencoba-coba sebelum demo.
#   id-ID-GadisNeural  - perempuan, hangat (default)
#   id-ID-ArdiNeural   - laki-laki, lebih berwibawa
EDGE_VOICE = os.getenv("EDGE_VOICE", "id-ID-GadisNeural")

# +35% (versi lama) menghilangkan jeda antar kata — terdengar seperti
# pengumuman stasiun. +18% terasa gesit seperti orang bicara cepat tapi
# artikulasinya masih utuh. Ubah lewat .env kalau ingin lebih lambat.
EDGE_RATE = os.getenv("EDGE_RATE", "+18%")
EDGE_PITCH = os.getenv("EDGE_PITCH", "+0Hz")

PIPER_VOICE = "models/id_ID-news_tts-medium.onnx"

# Kalimat pendek yang sering diulang (sapaan, konfirmasi) disimpan di memori
# supaya pemutaran kedua dan seterusnya nyaris instan.
_AUDIO_CACHE: dict[str, tuple] = {}
_CACHE_MAX_CHARS = 120
_CACHE_MAX_ITEMS = 40

# Event global: di-set kalau ada yang minta AKIRA berhenti bicara.
_stop_speaking = threading.Event()


class SpeechInterrupted(Exception):
    """Dilempar saat user memotong pembacaan (barge-in)."""


# ------------------------------------------------------- event loop persisten
class _AsyncRunner:
    """
    Satu event loop asyncio yang hidup terus di background thread.

    asyncio.run() bikin loop baru tiap panggilan — untuk edge-tts itu berarti
    setup koneksi dari nol setiap kalimat. Dengan loop persisten, koneksi
    dan resource-nya bisa dipakai ulang.
    """

    def __init__(self):
        self._loop = None
        self._thread = None
        self._lock = threading.Lock()

    def _ensure(self):
        with self._lock:
            if self._loop and self._loop.is_running():
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._thread.start()

    def run(self, coro, timeout: float = 20.0):
        self._ensure()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)


_runner = _AsyncRunner()


# ------------------------------------------------------------------ utilitas
def perhalus_prosodi(text: str) -> str:
    """
    Sisipkan tanda baca yang memandu jeda TTS.

    Mesin TTS neural memakai tanda baca untuk menentukan jeda dan intonasi.
    Kalimat AKIRA banyak yang dirakit dari potongan tanpa koma, sehingga
    dibacakan datar dalam satu tarikan napas. Menambahkan koma di tempat yang
    tepat memberi efek jauh lebih besar daripada mengganti mesin TTS-nya.
    """
    if not text:
        return text

    out = text
    # Jeda sebelum sapaan di ujung kalimat
    out = re.sub(r"\s+(Bos)([.?!])", r", \1\2", out)
    # Jeda setelah pembuka — tapi jangan kalau sudah diikuti koma
    out = re.sub(r"^(Baik|Siap|Oke|Permisi|Maaf|Halo)\s+(?![A-Za-z]+,)", r"\1, ", out)
    # Jam dibaca lebih rapi dengan titik daripada titik dua
    out = re.sub(r"\b(\d{1,2}):(\d{2})\b", r"\1.\2", out)
    # Jangan sampai koma bertumpuk
    out = re.sub(r",\s*,+", ",", out)
    return out


def split_sentences(text: str, max_chars: int = 140) -> list[str]:
    """
    Pecah teks jadi potongan enak diucapkan.
    Potongan pertama sengaja dibuat pendek supaya suara keluar cepat.
    """
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        while len(part) > max_chars:
            cut = part.rfind(",", 0, max_chars)
            if cut < 40:
                cut = max_chars
            chunks.append(part[:cut].strip())
            part = part[cut:].lstrip(", ").strip()
        if part:
            chunks.append(part)
    return chunks or [text]


def _decode_audio(raw: bytes):
    """
    Ubah bytes mp3/wav jadi (numpy array, samplerate) tanpa menyentuh disk.
    soundfile (libsndfile >= 1.1) sudah bisa baca mp3 langsung — ini yang
    menghilangkan pemanggilan ffmpeg dan memangkas latensi.
    """
    import soundfile as sf

    try:
        data, sr = sf.read(io.BytesIO(raw), dtype="float32")
        return data, sr
    except Exception as e:
        logger.debug(f"soundfile tidak bisa dekode langsung ({e}), pakai ffmpeg")

    tmp_in = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_in.write(raw)
    tmp_in.close()
    tmp_out = tmp_in.name.replace(".mp3", ".wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "quiet", "-i", tmp_in.name, tmp_out],
            check=True,
        )
        data, sr = sf.read(tmp_out, dtype="float32")
        return data, sr
    finally:
        for p in (tmp_in.name, tmp_out):
            try:
                os.remove(p)
            except OSError:
                pass


def _key_pressed() -> bool:
    """Cek apakah user menekan tombol (untuk memotong pembacaan)."""
    if os.name == "nt":
        try:
            import msvcrt

            if msvcrt.kbhit():
                msvcrt.getch()
                return True
        except Exception:
            return False
        return False

    try:
        import select

        if sys.stdin and sys.stdin.isatty():
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if ready:
                sys.stdin.readline()
                return True
    except Exception:
        return False
    return False


def _play_array(data, samplerate, interruptible: bool = True):
    """
    Putar audio dan pantau permintaan berhenti.
    Pemutaran non-blocking + polling, supaya tombol dan Ctrl+C tetap direspons
    di tengah pembacaan — bukan setelah selesai.
    """
    import sounddevice as sd

    sd.play(data, samplerate)
    try:
        while True:
            if not sd.get_stream().active:
                break
            if interruptible and (_stop_speaking.is_set() or _key_pressed()):
                sd.stop()
                logger.info("Pembacaan dipotong oleh user")
                raise SpeechInterrupted()
            time.sleep(0.05)
    except KeyboardInterrupt:
        sd.stop()
        logger.info("Pembacaan dihentikan (Ctrl+C)")
        raise SpeechInterrupted()


def _cache_get(key: str):
    return _AUDIO_CACHE.get(key)


def _cache_put(key: str, value):
    if len(key) > _CACHE_MAX_CHARS:
        return
    if len(_AUDIO_CACHE) >= _CACHE_MAX_ITEMS:
        _AUDIO_CACHE.pop(next(iter(_AUDIO_CACHE)))
    _AUDIO_CACHE[key] = value


# --------------------------------------------------------------- mesin suara
def _synth_edge(text: str):
    """Sintesis lewat Edge TTS, hasilkan (array, samplerate). Butuh internet."""
    import edge_tts

    async def _generate() -> bytes:
        communicate = edge_tts.Communicate(
            text, EDGE_VOICE, rate=EDGE_RATE, pitch=EDGE_PITCH
        )
        buffer = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.extend(chunk["data"])
        return bytes(buffer)

    raw = _runner.run(_generate())
    if not raw:
        raise RuntimeError("Edge TTS mengembalikan audio kosong")
    return _decode_audio(raw)


def _synth_piper(text: str):
    """Sintesis lewat Piper (offline), hasilkan (array, samplerate)."""
    import soundfile as sf

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    result = subprocess.run(
        [sys.executable, "-m", "piper", "--model", PIPER_VOICE,
         "--output-file", tmp_path, text],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise RuntimeError(result.stderr.strip()[:200])

    try:
        data, sr = sf.read(tmp_path, dtype="float32")
        return data, sr
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _speak_pyttsx3(text: str):
    """Suara bawaan Windows — pilihan terakhir, aksen Inggris, tidak bisa dipotong."""
    import pyttsx3

    engine = pyttsx3.init()
    voices = engine.getProperty("voices")

    chosen = None
    for v in voices:
        if "indone" in v.name.lower() or "id-id" in v.id.lower():
            chosen = v.id
            break
    if not chosen:
        for v in voices:
            if "zira" in v.name.lower():
                chosen = v.id
                break
    if chosen:
        engine.setProperty("voice", chosen)
    engine.setProperty("rate", 185)
    engine.say(text)
    engine.runAndWait()


def _synthesize(text: str, use_online: bool):
    """Sintesis satu potongan teks dengan fallback berlapis."""
    cache_key = f"{'on' if use_online else 'off'}::{text}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if use_online:
        try:
            result = _synth_edge(text)
            _cache_put(cache_key, result)
            return result
        except Exception as e:
            logger.warning(f"Edge TTS gagal ({e}), fallback ke Piper offline")

    result = _synth_piper(text)
    _cache_put(cache_key, result)
    return result


# -------------------------------------------------------------------- fasad
def speak(text: str, use_online: bool = True, interruptible: bool = True) -> bool:
    """
    Ucapkan teks lewat speaker.

    Return True kalau selesai penuh, False kalau dipotong user.
    Teks panjang dipecah per kalimat; kalimat berikutnya disintesis di thread
    lain sambil kalimat sekarang diputar.
    """
    if not text or not text.strip():
        return True

    _stop_speaking.clear()
    # "jam 20:00" diucapkan "jam 8 malam". Dipasang di sini — satu-satunya
    # pintu keluar suara — supaya berlaku untuk SEMUA ucapan: ringkasan,
    # pengingat, alarm, dan jawaban waktu. Teks di log tetap 24 jam.
    from src.nlp.date_time_parser import ucapkan_jam_alami

    chunks = split_sentences(perhalus_prosodi(ucapkan_jam_alami(text)))

    next_result: dict = {}

    def prefetch(idx: int):
        try:
            next_result[idx] = _synthesize(chunks[idx], use_online)
        except Exception as e:
            next_result[idx] = e

    try:
        current = _synthesize(chunks[0], use_online)
    except Exception as e:
        logger.warning(f"Sintesis gagal total ({e}), fallback ke pyttsx3")
        _speak_pyttsx3(text)
        return True

    for i, _ in enumerate(chunks):
        worker = None
        if i + 1 < len(chunks):
            worker = threading.Thread(target=prefetch, args=(i + 1,), daemon=True)
            worker.start()

        try:
            data, sr = current
            _play_array(data, sr, interruptible=interruptible)
        except SpeechInterrupted:
            _stop_speaking.clear()
            return False

        if worker:
            worker.join(timeout=15)
            nxt = next_result.get(i + 1)
            if isinstance(nxt, Exception) or nxt is None:
                logger.warning(f"Potongan ke-{i+1} gagal disintesis, sisa teks dilewati")
                return True
            current = nxt

    return True


def warmup(use_online: bool = True):
    """
    Panaskan jalur TTS saat startup: buka event loop, resolve DNS, load libsndfile.
    Tanpa ini, sapaan PERTAMA selalu terasa lambat padahal teksnya sudah muncul.
    """
    try:
        _synthesize("Siap.", use_online)
        logger.info("Jalur TTS sudah dipanaskan")
    except Exception as e:
        logger.warning(f"Warmup TTS gagal: {e}")


if __name__ == "__main__":
    # Test manual:  python -m src.tts.speaker
    print("Warmup...")
    t0 = time.time()
    warmup(use_online=True)
    print(f"  selesai dalam {time.time() - t0:.2f} detik")

    print("Tes Edge TTS (online)...")
    t0 = time.time()
    speak("Halo Bos, Selamat Malam. Bagaimana kabar Anda?", use_online=True)
    print(f"  selesai dalam {time.time() - t0:.2f} detik")

    print("Tes teks panjang — tekan ENTER untuk memotong:")
    speak(
        "Hari ini Anda punya tiga jadwal. Rapat divisi jam sembilan pagi. "
        "Makan siang dengan klien jam dua belas siang. "
        "Presentasi proposal jam tiga sore. Jangan sampai terlambat ya Bos.",
        use_online=True,
    )

    print("Tes Piper (offline)...")
    speak("Ini suara cadangan kalau internet bermasalah.", use_online=False)
