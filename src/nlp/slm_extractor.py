"""
Ekstraksi entitas bebas (nama kegiatan) & deteksi perintah "SKIP".
Tanggung jawab: Person 3 (NLP & Intelligence Lead) — Sprint 3

Desain: tanggal & jam SENGAJA tidak diserahkan ke SLM (lihat date_time_parser.py).
SLM hanya mengurus satu hal: nama kegiatan, yang formatnya bebas.

Perubahan dari Sprint 2:
1. Deteksi SKIP diperketat — dulu "ada apa aja aja" salah terdeteksi skip.
   Sekarang pola generik dibuang dan kata skip harus berdiri sebagai penolakan,
   bukan kebetulan muncul di tengah kalimat.
2. Ada ekstraksi kegiatan berbasis regex DULU (gratis, instan). SLM hanya
   dipanggil kalau regex gagal — memangkas 1-2 detik dari mayoritas perintah.
3. Model bisa diganti lewat config (qwen2.5:3b, llama3.2:3b, dst) tanpa ubah kode.
"""
import json
import re

import ollama
from loguru import logger

DEFAULT_MODEL = "qwen3:4b"

# Qwen3 punya mode "thinking" yang membungkus penalaran dalam <think>...</think>
# sebelum jawaban sebenarnya. Blok itu harus dibuang, kalau tidak parsing JSON
# dan klasifikasi intent selalu gagal.
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
THINK_TERBUKA = re.compile(r"<think>.*", re.DOTALL)


def _buang_thinking(raw: str) -> str:
    """Bersihkan blok penalaran Qwen3 dari output."""
    bersih = THINK_BLOCK.sub("", raw)
    bersih = THINK_TERBUKA.sub("", bersih)   # kalau terpotong num_predict

    # Qwen3 kadang menalar TANPA tag <think> sama sekali, langsung dalam bahasa
    # Inggris ("Okay, let's tackle this problem..."). Kalau ada JSON di
    # belakangnya, ambil JSON-nya saja dan buang narasi di depannya.
    kurung = re.search(r"\{.*\}", bersih, re.DOTALL)
    if kurung and not bersih.lstrip().startswith("{"):
        return kurung.group(0).strip()

    return bersih.strip()

# Prompt klasifikasi aksi. Sengaja dipisah dari prompt ekstraksi kegiatan
# supaya masing-masing pendek — SLM kecil jauh lebih patuh pada prompt pendek
# dengan contoh konkret daripada satu prompt panjang yang mengerjakan dua hal.
INTENT_PROMPT = """Kamu mesin klasifikasi perintah asisten jadwal Bahasa Indonesia.
Balas HANYA JSON satu baris: {"aksi": "<pilihan>"}

Pilihan yang sah:

catat       - user ingin MEMBUAT jadwal baru
baca        - user ingin MELIHAT / menanyakan jadwal yang sudah ada
hapus       - user ingin MENGHAPUS jadwal
reschedule  - user ingin MEMINDAHKAN jadwal ke waktu lain
edit        - user ingin MENGUBAH ISI jadwal (nama, catatan) tanpa memindah waktunya
reminder    - user ingin MENGATUR PENGINGAT untuk jadwal yang sudah ada
              ("ingatkan saya 1 jam sebelum meeting")
waktu       - user menanyakan jam atau tanggal SEKARANG, bukan tentang jadwal
lain        - bukan salah satu di atas

Contoh:
"ciptakan jadwal meeting besok" -> catat
"create jadwal rapat jam 3" -> catat
"tolong masukin agenda kuliah senin" -> catat
"jadwal saya hari ini apa aja ya" -> baca
"besok saya sibuk nggak" -> baca
"coba lihat agenda minggu depan" -> baca
"buang jadwal rapat divisi" -> hapus
"gak jadi yang meeting besok, batalin" -> hapus
"undur rapat ke hari kamis" -> reschedule
"ingatkan saya sejam sebelum rapat" -> reminder
"pasang pengingat buat meeting besok" -> reminder
"sekarang jam berapa" -> waktu
"hari ini tanggal berapa" -> waktu
"halo apa kabar" -> lain

Contoh balasan yang benar: {"aksi": "baca"}
/no_think
"""

SYSTEM_PROMPT = """Kamu mesin ekstraksi nama kegiatan dari perintah jadwal Bahasa Indonesia.
Balas HANYA JSON satu baris, tanpa penjelasan, tanpa markdown.

Format: {"kegiatan": "<nama singkat>" atau null}

/no_think

Aturan:
- Ambil NAMA KEGIATAN saja. Buang kata perintah (catat, jadwalkan, hapus, cek),
  buang keterangan waktu (besok, jam 3 sore, tanggal 17 november), buang kata sopan.
- Maksimal 4 kata. Jangan mengarang kalau tidak disebut: isi null.

Contoh:
"catat jadwal meeting besok jam 3 sore" -> {"kegiatan": "meeting"}
"jadwalkan rapat divisi hari kamis" -> {"kegiatan": "rapat divisi"}
"hapus jadwal makan siang dengan klien" -> {"kegiatan": "makan siang dengan klien"}
"cek jadwal saya besok" -> {"kegiatan": null}
"jadwalkan jam 2 siang" -> {"kegiatan": null}
"""

# Pola SKIP diperketat: harus jelas berupa penolakan mengisi field.
# Pola longgar seperti r"\bgak\s*ada\b" DIBUANG karena bikin "ada apa aja"
# salah terdeteksi sebagai skip.
SKIP_PATTERNS = [
    r"\bskip\b",
    r"\b(?:lewat|lewati|lewatin)\s+(?:aja|saja|dulu)\b",
    # Jawaban satu kata saat AKIRA bertanya balik — aman karena harus berdiri sendiri,
    # bukan kebetulan muncul di tengah kalimat panjang.
    # Jawaban satu kata, boleh diulang ("lewati", "lewati-lewati", "skip skip")
    r"\A\s*(?:lewat|lewati|lewatin|skip|kosong|kosongin)"
    r"(?:[\s,.-]+(?:lewat|lewati|lewatin|skip|kosong|kosongin))*\s*\Z",
    r"\b(?:gak|ga|nggak|tidak|enggak)\s*usah\b",
    r"\bgausah\b",
    r"\bkosong(?:in|kan|i)\s*(?:aja|saja|dulu)?\b",
    r"\b(?:gak|ga|nggak|tidak)\s+(?:perlu|penting)\b",
    r"\blanjut\s+(?:aja|saja)\b",
    r"\bterserah\b",
]

_COMPILED_SKIP = [re.compile(p) for p in SKIP_PATTERNS]

# Kata yang harus dibuang saat menebak nama kegiatan lewat regex.
_STOPWORDS = r"""
catat|catatkan|tambah|tambahkan|buat|bikin|simpan|jadwalkan|masukkan|daftarkan|set|atur|
ciptakan|create|susun|input|masukin|bikinin|buatin|jadwalin|
hapus|batalkan|hilangkan|cancel|buang|delete|
ubah|ganti|pindah|pindahkan|geser|undur|majukan|reschedule|
lihat|cek|baca|bacakan|sebutkan|tampilkan|tunjukkan|periksa|
ingatkan|ingetin|ingatin|peringatkan|pengingat|reminder|setel|setelkan|setelah|
pasang|bangunkan|timer|alarm|untuk|
sebelum|sebelumnya|sblm|mulai|dimulai|kasih|tau|tahu|
menit|detik|sejam|sehari|semenit|seminggu|setengah|seperempat|
jadwal|jadwalku|jadwalnya|agenda|agendanya|acara|acaranya|kegiatan|kegiatannya|
kesibukan|urusan|janji|namanya|judulnya|perihal|soal|tentang|
saya|aku|punya|untuk|buat|di|pada|ke|dan|yang|
tolong|coba|dong|deh|ya|nih|sih|aja|saja|itu|ini|nya|jadi|menjadi|dengan|dari|
sampai|dan|atau|apakah|apa|adalah|ada|punya|milik|
nggak|enggak|engga|gak|ga|tidak|bukan|belum|bisa|boleh|mau|ingin|pengen|bakal|akan|
diganti|dirubah|diubah|diralat|diperbaiki|salah|keliru|
kah|deh|kok|kan|lah|pun|dong|sih|ya|
itu|tersebut|tadi|barusan|berikut|berikutnya|sebelumnya|
kesatu|kedua|ketiga|keempat|kelima|keenam|ketujuh|
pertama|terakhir|masing|masing2|semua|semuanya|seluruh|seluruhnya|
keseluruhan|total|tiap|setiap|
besok|lusa|kemarin|hari|ini|minggu|bulan|tahun|depan|lagi|nanti|sekarang|
pagi|siang|sore|malam|jam|tanggal|pukul|setengah|
senin|selasa|rabu|kamis|jumat|sabtu|ahad|
januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember
"""
_STOPWORD_RE = re.compile(rf"\b(?:{_STOPWORDS.strip().replace(chr(10), '')})\b")


def detect_skip(text: str) -> bool:
    """Deteksi perintah SKIP secara deterministik (dicek sebelum memanggil SLM)."""
    text_lower = text.lower()
    for pattern in _COMPILED_SKIP:
        if pattern.search(text_lower):
            logger.info(f"Perintah SKIP terdeteksi (pola: {pattern.pattern})")
            return True
    return False


# Nama kegiatan yang MEMUAT kata keterangan waktu. Tanpa perlindungan,
# "siang" dibuang sebagai penanda jam dan "makan siang" tersimpan sebagai
# "makan" — judul yang kehilangan maknanya.
KEGIATAN_BERWAKTU = [
    "makan pagi", "makan siang", "makan malam", "makan sore",
    "sarapan pagi", "minum pagi", "ngopi pagi", "ngopi sore",
    "olahraga pagi", "olahraga sore", "senam pagi", "jalan pagi",
    "jalan sore", "lari pagi", "lari sore", "bersepeda pagi",
    "kuliah pagi", "kuliah malam", "kelas malam", "kelas pagi",
    "shift pagi", "shift siang", "shift malam", "jaga malam",
    "belajar malam", "sholat subuh", "sholat maghrib", "sholat isya",
    "tidur siang", "istirahat siang",
]
_KEGIATAN_BERWAKTU_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(KEGIATAN_BERWAKTU, key=len, reverse=True)) + r")\b"
)


def extract_kegiatan_regex(text: str) -> str | None:
    """
    Tebak nama kegiatan tanpa SLM: buang kata perintah, keterangan waktu, dan angka.
    Kalau sisanya masuk akal (1-4 kata), pakai itu dan lewati Ollama sama sekali.

    Ini memangkas 1-2 detik dari mayoritas perintah — SLM cuma dipanggil
    untuk kalimat yang benar-benar rumit.
    """
    t = text.lower()

    # Lindungi nama kegiatan yang memuat "pagi/siang/sore/malam" sebelum
    # kata-kata itu disaring sebagai keterangan waktu.
    terlindung = {}
    def _simpan(m):
        kunci = f"zzkeg{len(terlindung)}zz"
        terlindung[kunci] = m.group(1)
        return f" {kunci} "
    t = _KEGIATAN_BERWAKTU_RE.sub(_simpan, t)

    t = re.sub(r"\b\d+([:.]\d+)?\b", " ", t)     # angka (jam, tanggal, tahun)
    t = _STOPWORD_RE.sub(" ", t)
    for kunci, asli in terlindung.items():
        t = t.replace(kunci, asli)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    if not t:
        return None
    words = t.split()
    if len(words) > 4:
        return None  # terlalu ramai, serahkan ke SLM

    logger.debug(f"Kegiatan via regex: '{t}'")
    return t


def _tidak_ada_kandidat_nama(text: str) -> bool:
    """
    True kalau kalimat sama sekali tidak menyisakan kata yang mungkin jadi
    nama kegiatan setelah kata perintah dan keterangan waktu dibuang.
    """
    t = re.sub(r"\b\d+([:.]\d+)?\b", " ", text.lower())
    t = _STOPWORD_RE.sub(" ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return not t.strip()


def _clean_json_response(raw: str) -> str:
    """Bersihkan output SLM dari markdown fence / teks pembungkus."""
    cleaned = _buang_thinking(raw)
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    return match.group(0) if match else cleaned


def extract_entities(
    text: str,
    model: str = DEFAULT_MODEL,
    max_retries: int = 1,
    allow_regex_shortcut: bool = True,
) -> dict:
    """
    Ekstrak {"kegiatan", "skip"} dari kalimat user.
    Urutan: cek SKIP (regex) -> tebak kegiatan (regex) -> baru SLM.
    """
    result = {"kegiatan": None, "skip": detect_skip(text), "error": None}

    if result["skip"]:
        return result

    if allow_regex_shortcut:
        guess = extract_kegiatan_regex(text)
        if guess:
            result["kegiatan"] = guess
            result["source"] = "regex"
            return result

        # Kalau setelah semua kata perintah & keterangan waktu dibuang tidak
        # tersisa apa pun ("hapus jadwal tersebut"), memang TIDAK ADA nama
        # kegiatan di kalimat itu. Memanggil SLM cuma membuang 10-20 detik
        # untuk hasil yang sudah pasti kosong — dan nama kegiatannya nanti
        # diisi dari konteks percakapan.
        if _tidak_ada_kandidat_nama(text):
            logger.info("Tidak ada kandidat nama kegiatan, SLM dilewati")
            result["source"] = "regex-kosong"
            return result

    raw = ""
    for attempt in range(1, max_retries + 1):
        try:
            response = _chat(
                model,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                # Qwen3 kadang tetap menalar panjang meski diminta tidak.
                # Ruang output dilebihkan supaya JSON-nya tidak terpotong di tengah.
                {"temperature": 0.0, "num_predict": 200, "top_k": 10},
            )
            raw = response["message"]["content"]
            parsed = json.loads(_clean_json_response(raw))

            kegiatan = parsed.get("kegiatan")
            if isinstance(kegiatan, str):
                kegiatan = kegiatan.strip() or None
            result["kegiatan"] = kegiatan
            result["skip"] = bool(parsed.get("skip", False))
            result["source"] = "slm"
            logger.info(f"SLM ekstrak (percobaan {attempt}): {result}")
            return result

        except json.JSONDecodeError:
            logger.warning(f"Percobaan {attempt}: SLM tidak balas JSON valid -> '{raw[:100]}'")
            if attempt == max_retries:
                result["error"] = "invalid_json"
        except Exception as e:
            logger.error(f"Percobaan {attempt}: gagal panggil Ollama: {e}")
            result["error"] = str(e)
            break

    return result


VALID_AKSI = {"catat", "baca", "hapus", "reschedule", "reminder", "edit", "waktu"}


def _chat(model: str, messages: list, options: dict, format_json: bool = True):
    """
    Panggil Ollama dengan think=False dan format="json".

    `format="json"` adalah kuncinya: Ollama memaksa model mengeluarkan JSON
    valid, sehingga penalaran prosa ("Okay, let's tackle this problem...")
    tidak muncul sama sekali. Tanpa ini Qwen3 menghabiskan 10 detik menalar
    dalam bahasa Inggris sebelum menjawab — dua kali, karena percobaan
    pertama selalu gagal diparse.

    Parameter yang tidak dikenal versi ollama-python lama diabaikan dengan
    aman lewat fallback bertingkat.
    """
    kwargs = {"model": model, "messages": messages, "options": options}
    if format_json:
        kwargs["format"] = "json"

    for percobaan in (
        dict(kwargs, think=False),
        kwargs,
        {"model": model, "messages": messages, "options": options},
    ):
        try:
            return ollama.chat(**percobaan)
        except TypeError:
            continue
        except Exception as e:
            if "think" in str(e).lower() or "format" in str(e).lower():
                continue
            raise
    raise RuntimeError("Semua variasi pemanggilan Ollama gagal")


def classify_intent_slm(text: str, model: str = DEFAULT_MODEL) -> str | None:
    """
    Minta SLM menebak aksi dari kalimat bebas.

    Ini yang bikin AKIRA tidak perlu didaftari tata bahasanya satu per satu:
    "ciptakan jadwal", "create jadwal", "tolong masukin agenda" tidak ada di
    daftar keyword mana pun, tapi SLM paham maksudnya.

    Keyword tetap dicoba lebih dulu (instan, tanpa biaya) — SLM baru dipanggil
    kalau keyword menyerah. Jadi perintah umum tetap cepat, perintah tak terduga
    tetap dimengerti.

    Return None kalau SLM juga tidak yakin.
    """
    try:
        response = _chat(
            model,
            [
                {"role": "system", "content": INTENT_PROMPT},
                # "/no_think" harus ada di pesan USER — di system prompt sering
                # diabaikan Qwen3. Ruang output juga dilebihkan: kalau model
                # tetap menalar, jawabannya masih sempat keluar di belakang.
                {"role": "user", "content": f"{text}\n/no_think"},
            ],
            {"temperature": 0.0, "num_predict": 160, "top_k": 5},
        )
        raw = _buang_thinking(response["message"]["content"]).lower()
    except Exception as e:
        logger.error(f"Gagal klasifikasi intent via SLM: {e}")
        return None

    # Jalur utama: JSON. Jauh lebih tegas daripada menebak dari teks bebas.
    try:
        aksi = json.loads(_clean_json_response(raw)).get("aksi", "").strip().lower()
        if aksi in VALID_AKSI:
            logger.info(f"SLM mengklasifikasi '{text}' sebagai '{aksi}'")
            return aksi
        if aksi == "lain":
            logger.info(f"SLM menilai '{text}' bukan perintah jadwal")
            return None
    except (json.JSONDecodeError, AttributeError):
        pass

    kata_valid = [k for k in re.findall(r"[a-z]+", raw) if k in VALID_AKSI or k == "lain"]

    if not kata_valid:
        logger.warning(f"SLM balas di luar daftar: '{raw[:70]}'")
        return None

    # Ambil kata TERAKHIR, bukan pertama. Qwen3 sering menalar dulu dalam
    # bahasa Inggris ("...the user is asking about their schedule, so baca")
    # dan menaruh kesimpulannya di ujung. Mengambil yang pertama berarti
    # menangkap kata yang muncul di tengah penalaran, bukan jawabannya.
    kata = kata_valid[-1]

    if kata == "lain":
        logger.info(f"SLM menilai '{text}' bukan perintah jadwal")
        return None

    logger.info(f"SLM mengklasifikasi '{text}' sebagai '{kata}'")
    return kata


def check_ollama_ready(model: str = DEFAULT_MODEL) -> bool:
    """
    Cek Ollama hidup & model ter-pull. Dipanggil app.py saat startup
    supaya error ketahuan sebelum user bicara.
    """
    try:
        ollama.chat(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            options={"num_predict": 1},
        )
        logger.info(f"Ollama siap (model: {model})")
        return True
    except Exception as e:
        logger.error(f"Ollama TIDAK siap: {e}")
        logger.error(f"Pastikan Ollama jalan & 'ollama pull {model}' sudah dilakukan")
        return False


def warmup(model: str = DEFAULT_MODEL):
    """
    Panggilan kosong untuk memaksa Ollama memuat model ke memori.
    Tanpa ini, perintah PERTAMA user selalu terasa lambat (~3 detik)
    karena model baru di-load saat itu juga.
    """
    try:
        ollama.chat(
            model=model,
            messages=[{"role": "user", "content": "hai"}],
            options={"num_predict": 1},
        )
        logger.info(f"Model SLM '{model}' sudah dipanaskan")
    except Exception as e:
        logger.warning(f"Warmup SLM gagal: {e}")


if __name__ == "__main__":
    print("=== Deteksi SKIP (offline) ===")
    for t, expected in [
        ("kegiatannya skip aja", True),
        ("gak usah diisi", True),
        ("gausah", True),
        ("lewatin aja", True),
        ("kosongin aja", True),
        ("ada apa aja aja", False),      # bug Sprint 2 — harus False
        ("meeting dengan klien", False),
        ("cek jadwal saya besok ada apa saja", False),
    ]:
        got = detect_skip(t)
        status = "OK " if got == expected else "GAGAL"
        print(f"  [{status}] '{t}' -> {got}")

    print("\n=== Ekstraksi kegiatan via regex (tanpa Ollama) ===")
    for t in [
        "catat jadwal meeting besok jam 3 sore",
        "jadwalkan rapat divisi hari kamis",
        "hapus jadwal seminar",
        "cek jadwal saya besok",
        "catat jadwal presentasi proposal kompres lomba minggu depan jam 9 pagi",
    ]:
        print(f"  '{t}' -> {extract_kegiatan_regex(t)!r}")
