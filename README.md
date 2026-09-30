# AKIRA

**A**udio-driven **K**alendar & **I**nteractive **R**eminder **A**ssistant

Asisten jadwal berbasis suara untuk Bahasa Indonesia lisan. Panggil dengan
suara, bicara seperti biasa, dan AKIRA mengelola Google Calendar-mu —
menanyakan sendiri detail yang kurang, menerima koreksi tanpa mengulang
perintah, dan mengingatkan sebelum acara dimulai.

> Dibuat untuk **KOMPRES 16 Informatika Universitas Gunadarma 2026** —
> kategori AI Innovation.

```
Kamu  : "AKIRA WAKE UP"
AKIRA : "Selamat pagi. Ada yang bisa dibantu?"
Kamu  : "Besok gue sibuk ga?"
AKIRA : "Besok ada rapat divisi jam 09.00."
Kamu  : "Catat presentasi besok jam 10"
AKIRA : "Jam segitu pagi atau malam?"
Kamu  : "Pagi"
AKIRA : "Selesai jam berapa? Kalau tidak perlu, bilang saja lewati."
Kamu  : "Lewati"
AKIRA : "Ada catatan tambahan?"
Kamu  : "Lewati"
AKIRA : "...kegiatan presentasi, besok jam 10.00. Sudah benar?"
Kamu  : "Jamnya jadi jam 2 siang"
AKIRA : "Baik, saya ubah jamnya jadi 14.00. Sudah benar?"
Kamu  : "Benar"
AKIRA : "Sudah saya catat."
```

---

## Fitur

**Manajemen jadwal**
- Mencatat, membaca, memindahkan, mengedit, dan menghapus agenda Google Calendar
- Beberapa tanggal sekaligus, dengan jam berbeda per tanggal
- Hapus massal: seluruhnya, per tanggal, atau per rentang waktu
- Deteksi jadwal bertabrakan, dengan pilihan tetap simpan / ganti jam / batal

**Pengingat & waktu**
- Pengingat otomatis 30, 15, dan 5 menit sebelum acara
- Pengingat khusus yang tersimpan di Google Calendar (ikut muncul di ponsel)
- Alarm dan timer, termasuk membatalkan dan menanyakan sisa waktu

**Percakapan**
- Satu wake word untuk banyak perintah berturut-turut
- Mode ambient: 15 menit setelahnya, cukup sebut *"Akira, ..."* di kalimat biasa
- Koreksi satu bagian saat konfirmasi — *"kegiatannya futsal"* — tanpa mengulang
- Kata rujukan: *"hapus jadwal tersebut"*
- Memahami bahasa santai: *"besok gue sibuk ga?"*, *"tambahin jadwal kuliah lusa"*
- Kalimat bebas diterjemahkan penalaran LLM ke perintah baku, lalu diverifikasi aturan
- Hapus atau ubah tanpa ingat nama: sebut harinya, pilih dari daftar
- Jam diucapkan sehari-hari: "jam 8 malam", bukan "jam dua puluh"

**Aplikasi desktop**
- Pemeriksaan kesiapan komponen sebelum dipakai
- Kalender langsung di jendela aplikasi, log aktivitas langsung
- Pintasan keyboard dan tombol aksi cepat — tanpa perlu bicara
- Perintah bisa diketik, tetap melewati dialog dan konfirmasi yang sama

---

## Cara Kerja

```
Mikrofon
   │
   ▼
Wake word ──────────── openWakeWord, model dilatih sendiri
   │
   ▼
Perekaman ──────────── WebRTC VAD + gerbang energi
   │
   ▼
LAPIS 1  Speech-to-Text, 3 mesin PARALEL
         Whisper lokal │ whisper-large-v3-turbo │ whisper-large-v3
         → pemungutan suara
         → kandidat saling asing = derau, dibuang
   │
   ▼  (hanya bila mesin tidak sepakat)
LAPIS 2  Rekonsiliasi, 2 LLM PARALEL
         gpt-oss-20b │ qwen3.8-27b  — dari keluarga model berbeda
         + konteks: pertanyaan terakhir AKIRA
         + validasi: hasil harus berasal dari kandidat asli
         + terjemahan maksud → perintah baku, diverifikasi parser
   │
   ▼
LAPIS 3  Pemahaman
         maksud    : kata kunci → LLM → Qwen3 4B lokal
         tanggal   : ATURAN DETERMINISTIK, tidak lewat LLM
   │
   ▼
Dialog ─────────────── slot filling, konfirmasi, koreksi, bentrok
   │
   ▼
Google Calendar API
   │
   ▼
Text-to-Speech ─────── Edge TTS → Piper (luring) → pyttsx3
```

### Tiga keputusan desain

**AI hanya di tempat yang membutuhkannya.** Tanggal dan jam sengaja tidak
diserahkan ke LLM. Kesalahan tanggal berakibat langsung dan tidak terlihat —
jadwal tersimpan di waktu yang salah tanpa tanda apa pun. Aturan eksplisit
tidak berhalusinasi dan bisa diuji menyeluruh.

**Ketidaksepakatan adalah sinyal.** Ucapan sungguhan menghasilkan transkripsi
yang berdekatan di ketiga mesin. Derau menghasilkan tebakan yang saling asing.
Ensemble tidak hanya memilih transkripsi terbaik, tetapi juga mendeteksi
kapan sebenarnya tidak ada yang berbicara.

**Setiap komponen punya jalur mundur.** Tanpa internet, AKIRA tetap berjalan
dengan Whisper lokal, Qwen3 lokal, dan suara Piper — akurasinya turun, tapi
tidak pernah bisu.

---

## Kebutuhan

| | |
|---|---|
| Sistem operasi | Windows 10/11 |
| Python | 3.10 – 3.12 (bukan 3.13) |
| GPU | NVIDIA dengan CUDA — disarankan, tidak wajib |
| RAM | 16 GB |
| Lainnya | Mikrofon, akun Google, [Ollama](https://ollama.com) |
| API | Kunci [Groq](https://console.groq.com) — gratis, untuk akurasi penuh |

---

## Memulai Cepat

```powershell
python -m venv venv
venv\Scripts\activate

# PyTorch versi CUDA WAJIB dipasang lebih dulu
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt

python -c "import openwakeword; openwakeword.utils.download_models()"
ollama pull qwen3:4b

Copy-Item .env.example .env      # lalu isi GROQ_API_KEY
```

Taruh `credentials.json` dari Google Cloud Console di folder `config/`, lalu:

```powershell
python akira_app.py
```

Tekan **Periksa Komponen**, lalu **Jalankan AKIRA**, dan ucapkan
**"AKIRA WAKE UP"**.

**Panduan lengkap langkah demi langkah — termasuk pengaturan Google Calendar
dan jebakan yang sering terjadi — ada di [SETUP.md](SETUP.md).**

---

## Contoh Perintah

| Ucapkan | Hasil |
|---|---|
| "Cek jadwal besok" | Membacakan jadwal besok |
| "Hari ini saya kosong ga?" | Sama, dengan bahasa santai |
| "Catat meeting besok jam 3 sore" | Mencatat, lalu meminta konfirmasi |
| "Catat rapat tanggal 10, 12, dan 15 Oktober" | Tiga jadwal sekaligus |
| "Hapus jadwal rapat divisi" | Mencari, lalu meminta konfirmasi |
| "Hapus semua jadwal minggu depan" | Hapus massal dalam rentang |
| "Geser rapat ke tanggal 5 jam 2 siang" | Memindahkan jadwal |
| "Edit jadwal saya" | Mengubah nama atau catatan |
| "Ingatkan saya 1 jam sebelum meeting" | Pengingat khusus |
| "Timer 15 menit buat minum obat" | Timer dengan keperluan |
| "617 hari lagi itu hari apa?" | Menghitung tanggal |
| "Panggil saya Dzaky" | Mengganti nama panggilan |

Setiap penyimpanan, penghapusan, pemindahan, dan pengeditan **selalu melewati
konfirmasi**. Diam atau jawaban tidak jelas berarti batal.

---

## Pintasan Keyboard

| Kombinasi | Aksi |
|---|---|
| `Ctrl+Alt+A` | Dengarkan sekarang, tanpa wake word |
| `Ctrl+Alt+B` | Panggil AKIRA — untuk ruangan bising |
| `Ctrl+Alt+H` | Bacakan jadwal hari ini |
| `Ctrl+Alt+C` | Mulai catat jadwal |
| `Ctrl+Alt+W` | Tampilkan jendela AKIRA |

Bisa diubah di tab **Pintasan**. Untuk pintasan yang berfungsi dari aplikasi
lain, pasang `pip install keyboard`.

---

## Struktur Proyek

```
akira/
├── akira_app.py              antarmuka grafis
├── run.py                    mode terminal
├── SETUP.md                  panduan pemasangan
├── config/settings.yaml      seluruh pengaturan
├── models/                   model wake word + suara Piper
├── scripts/                  auto-start & alat diagnosa
├── src/
│   ├── app.py                orkestrator
│   ├── wakeword/             deteksi frasa aktivasi
│   ├── audio/                perekaman, VAD, pendengar ambient
│   ├── stt/                  3 mesin + ensemble + penyaring
│   ├── nlp/                  normalisasi, maksud, tanggal, koreksi
│   ├── calendar_service/     Google Calendar
│   ├── dialog/               slot filling, konfirmasi, alarm, pengingat
│   ├── gui/                  jendela, tema, pintasan
│   ├── tts/                  suara berlapis
│   └── utils/                sapaan, log, preferensi
└── tests/                    898 test
```

Dua fasad menjadi satu-satunya pintu masuk ke logika inti:
`nlp/parser.py` untuk pemahaman bahasa, dan `calendar_service/executor.py`
untuk eksekusi kalender. Modul lain tidak memanggil sub-modul secara langsung.

---

## Pengujian

```powershell
pytest tests/ -q
```

**898 test**, berjalan ±3 detik tanpa mikrofon, GPU, maupun internet.

Termasuk **47 simulasi percakapan utuh** (`tests/test_alur_percakapan.py`)
yang menjalankan sesi AKIRA sungguhan dengan mikrofon, speaker, dan kalender
diganti tiruan — dari ucapan pertama sampai jadwal masuk kalender. Pengujian
ini menemukan kesalahan integrasi yang lolos dari ratusan unit test, karena
setiap bagiannya benar secara terpisah dan yang keliru adalah sambungannya.

Ditambah pemeriksa otomatis untuk kelas kesalahan yang lolos dari
`py_compile`, serta analisis statis `pyflakes` dan `vulture`.

### Alat diagnosa

```powershell
python scripts\cek_api_key.py       # API key mana yang terbaca
python scripts\cek_model_llm.py     # model LLM Groq mana yang hidup
python -m src.stt.backends          # mesin STT mana yang siap
python -m src.nlp.parser            # uji penguraian perintah tanpa mikrofon
```

---

## Privasi

| Data | Ke mana |
|---|---|
| Suara saat siaga | **Tidak ke mana pun** — wake word diproses lokal |
| Potongan audio perintah (±2–5 detik) | Groq, untuk transkripsi |
| Teks perintah | Groq, hanya bila mesin tidak sepakat atau maksud tidak jelas |
| Teks yang diucapkan AKIRA | Microsoft (Edge TTS) |
| Jadwal | Akun Google Calendar-mu sendiri |

Rekaman tidak diarsipkan — setiap rekaman menimpa yang sebelumnya.
Transkripsi tercatat di log lokal untuk analisis kesalahan dan tidak dikirim
ke mana pun.

**Mode luring penuh:** kosongkan `GROQ_API_KEY` dan set `USE_ONLINE_TTS=false`
di `.env`. Akurasi turun, tapi tidak ada data suara yang meninggalkan laptop.

**Jangan pernah mengunggah** `.env`, `config/credentials.json`, atau
`config/token.json`. Ketiganya sudah ada di `.gitignore`.

---

## Keterbatasan

- Akurasi puncak butuh internet; tanpa itu hanya Whisper `small` yang berjalan
- Model Whisper lokal dibatasi `small` karena VRAM 4 GB pada perangkat pengembangan
- Wake word dilatih pada data sintetis, belum diuji sistematis lintas penutur
- Dirancang untuk satu pengguna per instalasi
- Ambang deteksi derau ditetapkan dari pengamatan, belum dari eksperimen terkontrol
- Auto-start bersifat khusus Windows

---

## Teknologi

[openWakeWord](https://github.com/dscripka/openWakeWord) ·
[Whisper](https://github.com/openai/whisper) ·
[Groq](https://console.groq.com) ·
[Ollama](https://ollama.com) + Qwen3 ·
[Edge TTS](https://github.com/rany2/edge-tts) ·
[Piper](https://github.com/rhasspy/piper) ·
WebRTC VAD ·
Google Calendar API ·
Tkinter

---

## Tim

| Nama | Peran |
|---|---|
| Maulana Dzaky Putra Irawan | Integrator — kalender, orkestrasi |
| *[Nama Anggota 2]* | Audio — wake word, perekaman, STT |
| *[Nama Anggota 3]* | NLP — pemahaman bahasa, tanggal |
| *[Nama Anggota 4]* | Dialog & UX — suara, antarmuka, pengujian |

Laboratorium Informatika, Universitas Gunadarma — 2026
