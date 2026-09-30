"""
Orkestrator utama AKIRA — merangkai semua modul jadi satu alur end-to-end.
Tanggung jawab: Person 1 (Integrator utama) — Sprint 3

Alur baru (MODE PERCAKAPAN):
  wake word -> sapaan + briefing -> [ perintah -> eksekusi -> perintah -> ... ]
                                     ^                                     |
                                     +--- tanpa perlu wake word lagi ------+
  Sesi berakhir kalau user diam beberapa detik atau bilang "makasih/cukup/udah".

Ini memperbaiki keluhan terbesar: dulu tiap satu perintah harus dibuka
dengan "AKIRA WAKE UP" lagi.
"""
import os
import re
import sys
import time

import yaml
from dotenv import load_dotenv

from src.utils import trigger
from src.utils.logger_config import setup_logger

load_dotenv()
logger = setup_logger()

CONFIG_PATH = "config/settings.yaml"

# Kata penutup — user bilang salah satu ini, AKIRA balik standby.
KATA_PENUTUP = [
    # Ucapan terima kasih dalam berbagai ejaan. "terimakasih" (menyambung)
    # paling sering muncul dari jalur KETIK dan sempat tidak dikenali sama
    # sekali, karena daftar hanya memuat versi berspasi.
    "makasih", "makasi", "terima kasih", "terimakasih", "trimakasih",
    "trims", "thanks", "thank you", "tengkyu", "tq",
    # Menyatakan cukup
    "udah", "udahan", "sudah cukup", "udah cukup", "cukup", "cukup sekian",
    "itu saja", "itu aja", "segitu saja", "segitu aja",
    "tidak ada lagi", "nggak ada lagi", "gak ada lagi", "ga ada lagi",
    # Pamit
    "selesai", "keluar", "stop", "berhenti", "dah", "bye", "sampai jumpa",
    "istirahat", "tidur",
]

# Jawaban menolak. Hanya dihitung sebagai penutup kalau AKIRA baru saja
# bertanya "masih ada yang bisa saya bantu?" — di luar konteks itu, kata
# "tidak" bisa saja bagian dari perintah biasa.
# Mode ambient: setelah dibangunkan sekali, AKIRA terus mendengar. Supaya
# tidak menanggapi obrolan yang bukan untuknya, kalimat harus menyebut namanya.
# Perintah yang menunggu giliran diproses (dipakai mode input beruntun)
_antrean_perintah: list = []

# Variasi salah dengar Whisper untuk kata "AKIRA". Daftar ini tumbuh dari
# log demo — "akhirnya" muncul berkali-kali padahal yang diucapkan "akira".
# Variasi salah dengar "AKIRA", dikumpulkan dari log demo — bukan karangan.
# Whisper dan Groq sama-sama sering menuliskannya sebagai kata Indonesia
# yang mirip: "akhirnya", "kira-kira", "akhir ya".
VARIAN_AKIRA = [
    "akira", "akhira", "akhirah", "akiro", "akyra", "akira h",
    "aquila", "okira", "agira", "akirah", "akiranya", "akira nya",
    "akhirnya", "akhirny", "akhirnya", "akhir ya", "akhir nya",
    "kira", "kirana", "kira kira", "akir", "akhir",
]

PANGGILAN_AKIRA = re.compile(
    r"\b(?:" + "|".join(sorted(set(VARIAN_AKIRA), key=len, reverse=True)).replace(" ", r"\s*") + r")\b"
)

# Kata perintah yang menandakan kalimat memang ditujukan ke AKIRA.
# "akhirnya" adalah kata Indonesia yang wajar ("akhirnya selesai juga"),
# jadi memasukkannya ke daftar panggilan berisiko salah picu. Karena itu
# kalimat harus JUGA mengandung niat perintah sebelum sesi dibuka.
NIAT_PERINTAH = re.compile(
    r"\b(?:jadwal|agenda|acara|kegiatan|catat|catatkan|buat|buatkan|bikin|"
    r"tambah|tambahkan|tambahin|hapus|batalkan|geser|pindah|reschedule|"
    r"ingatkan|ingetin|pengingat|reminder|alarm|timer|setel|"
    r"cek|lihat|bacakan|baca|sebutkan|tampilkan|jam berapa|tanggal berapa|"
    r"kosong|sibuk|free)\b"
)


def disapa_akira(text: str) -> bool:
    """
    True kalau kalimat menyebut nama AKIRA (toleran salah dengar Whisper).

    Dipakai mode ambient. Karena daftar variasinya memuat kata yang juga
    sah dalam Bahasa Indonesia ("akhirnya"), pemanggilan saja tidak cukup —
    lihat juga perintah_untuk_akira().
    """
    return bool(PANGGILAN_AKIRA.search((text or "").lower()))


# Frasa self destruct versi TEKS. Diperlukan karena selama mode ambient
# berjalan, mikrofon dipakai untuk merekam kalimat penuh — model wake word
# tidak pernah mendapat giliran mendengar. Tanpa deteksi teks ini, perintah
# rahasia jadi tidak bisa dipanggil sama sekali saat ambient aktif.
FRASA_DESTRUCT = re.compile(
    r"\b(?:destroy|destrui|destruy|distroy|destruksi|hancurkan|musnahkan)\b"
    r".{0,20}?\b(?:yourself|your\s*self|diri|dirimu|diri\s*sendiri|sendiri)\b"
)


def minta_self_destruct(text: str) -> bool:
    """
    True untuk "AKIRA DESTROY YOURSELF" dan variasi salah dengarnya
    ("akira destrui diri sendiri", "akhirnya destroy yourself").

    Tetap menuntut nama AKIRA disebut — konfirmasi berlapis di alur
    penghancuran yang jadi pengaman sebenarnya, tapi tidak ada gunanya
    membuka alur itu untuk kalimat yang jelas bukan ditujukan ke AKIRA.
    """
    if not disapa_akira(text):
        return False
    return bool(FRASA_DESTRUCT.search((text or "").lower()))


# Frasa aktivasi versi TEKS. Saat mode ambient berjalan, model wake word
# tidak selalu menang atas transkripsi — di log, "AKIRA WAKE UP" berkali-kali
# tertulis "Akhirnya wake up" dan tidak memicu apa pun karena "wake up"
# bukan kata perintah jadwal.
FRASA_BANGUN = re.compile(r"\bwake\s*up\b|\bbangun\b|\bhalo\b|\bhai\b")


def minta_bangun(text: str) -> bool:
    """
    True untuk "AKIRA WAKE UP" dan variasi salah dengarnya.

    Dipakai mode ambient: kalimat yang menyebut nama AKIRA dan frasa bangun
    membuka sesi, meski tidak mengandung perintah jadwal apa pun.
    """
    if not disapa_akira(text):
        return False
    return bool(FRASA_BANGUN.search((text or "").lower()))


def perintah_untuk_akira(text: str, pakai_llm: bool = True) -> bool:
    """
    True kalau kalimat menyebut AKIRA DAN user menginginkan sesuatu.

    Dua lapis, yang murah lebih dulu:

    1. **Kata kunci.** Nama AKIRA + kata perintah jadwal. Cepat dan gratis,
       menangani mayoritas kasus.
    2. **Penalaran Groq.** Dipakai hanya kalau nama terdengar tapi tidak ada
       kata perintah. Contoh nyata dari log: "Kira tolong bantu saya" —
       jelas ditujukan ke AKIRA, tapi tidak memuat satu pun kata seperti
       "jadwal" atau "catat", sehingga lapis pertama menyerah.

    Nama saja tidak pernah cukup. "Akira" tanpa permintaan apa pun, dan
    "akhirnya selesai juga", dua-duanya tetap diabaikan.
    """
    if not disapa_akira(text):
        return False

    if NIAT_PERINTAH.search((text or "").lower()):
        return True

    if not pakai_llm:
        return False

    try:
        from src.nlp.groq_reasoner import untuk_akira_groq

        untuk_akira, _ = untuk_akira_groq(text)
        return untuk_akira
    except Exception as e:
        logger.warning(f"Penalaran sapaan gagal: {e}")
        return False


KATA_NEGATIF = [
    "tidak", "nggak", "enggak", "engga", "gak", "ga", "nope", "no",
    "belum", "kosong", "gausah", "gak usah",
]


def _pesan_penutup(config: dict) -> str:
    """
    Kalimat saat sesi berakhir.

    Setelah sesi selesai, AKIRA otomatis masuk mode ambient. Pengguna perlu
    tahu itu — kalau tidak, ia akan mengucapkan "AKIRA WAKE UP" lagi padahal
    cukup menyebut namanya saja.
    """
    if _get(config, "ambient", "enabled", default=True):
        menit = _get(config, "ambient", "timeout_menit", default=15)
        return (
            f"Baik Bos, saya standby. Selama {menit} menit ke depan, "
            f"cukup panggil Akira kalau butuh."
        )
    return "Baik Bos. Panggil saya lagi kalau butuh."


def is_negatif(text: str) -> bool:
    """True kalau jawaban singkat user berarti 'tidak ada lagi'."""
    t = text.lower().strip(" .,!?")
    if len(t.split()) > 3:
        return False
    return any(t == k or t.startswith(k + " ") for k in KATA_NEGATIF)


def load_config(path: str = CONFIG_PATH) -> dict:
    if not os.path.exists(path):
        logger.error(f"Config '{path}' tidak ditemukan")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get(config: dict, *keys, default=None):
    """Ambil nilai nested dari config dengan aman."""
    node = config
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node


def preflight_check(config: dict) -> bool:
    """
    Cek semua dependency eksternal SEBELUM masuk listening loop.
    Kalau Ollama belum nyala atau model wake word hilang, lebih baik ketahuan
    sekarang daripada saat user sudah bicara di depan juri.
    """
    ok = True

    wakeword_path = config["wakeword"]["model_path"]
    if not os.path.exists(wakeword_path):
        logger.error(f"Model wake word tidak ada: {wakeword_path}")
        logger.error("Training dulu via Colab, lihat docs/wakeword_training.md")
        ok = False
    else:
        logger.info(f"Model wake word ditemukan: {wakeword_path}")

    if not os.path.exists("config/credentials.json"):
        logger.error("config/credentials.json tidak ada — setup OAuth dulu di Google Cloud Console")
        ok = False
    else:
        logger.info("Credentials Google Calendar ditemukan")

    engine = _get(config, "stt", "engine", default="whisper")
    daftar = engine if isinstance(engine, (list, tuple)) else [engine]
    try:
        from src.stt.backends import cek_kesiapan

        status = cek_kesiapan()
        siap = [m for m in daftar if status.get(str(m).replace("groq-whisper", "groq")) == "siap"]
        for m in daftar:
            ket = status.get(str(m).replace("groq-whisper", "groq"), "tidak dikenal")
            (logger.info if ket == "siap" else logger.warning)(f"Mesin STT '{m}': {ket}")
        if not siap:
            logger.warning("Tidak ada mesin STT pilihan yang siap — akan memakai Whisper lokal")
    except Exception as e:
        logger.warning(f"Tidak bisa cek mesin STT: {e}")

    try:
        from src.nlp.slm_extractor import check_ollama_ready

        if not check_ollama_ready(config["nlp"]["ollama_model"]):
            logger.warning("Ollama tidak siap — sistem tetap jalan, ekstraksi nama kegiatan pakai regex saja")
    except Exception as e:
        logger.warning(f"Tidak bisa cek Ollama: {e}")

    return ok


def warmup_all(config: dict, use_online_tts: bool):
    """
    Panaskan semua komponen berat sebelum wake word pertama.
    Tanpa ini, perintah pertama terasa lambat: Whisper loading model,
    Ollama loading bobot, dan Edge TTS membuka koneksi — semuanya sekaligus.
    """
    logger.info("Memanaskan komponen (STT, Ollama, TTS)...")

    # Opsi ensemble dipasang sekali di sini supaya transcribe() tidak perlu
    # menerima config penuh di setiap panggilan.
    try:
        from src.stt.transcriber import set_opsi_ensemble

        ens = _get(config, "stt", "ensemble", default={}) or {}
        set_opsi_ensemble(
            timeout_s=ens.get("timeout_s", 12),
            perekonsiliasi=ens.get("perekonsiliasi"),
            model_perekonsiliasi=ens.get("model_perekonsiliasi") or {},
        )
    except Exception as e:
        logger.warning(f"Gagal memasang opsi ensemble: {e}")

    try:
        from src.stt.transcriber import warmup as warmup_stt

        warmup_stt(
            config["stt"]["model_size"],
            config["stt"]["device"],
            engine=_get(config, "stt", "engine", default="whisper"),
        )
    except Exception as e:
        logger.warning(f"Warmup Whisper gagal: {e}")

    try:
        from src.nlp.slm_extractor import warmup as warmup_slm

        warmup_slm(config["nlp"]["ollama_model"])
    except Exception as e:
        logger.warning(f"Warmup SLM gagal: {e}")

    try:
        from src.tts.speaker import warmup as warmup_tts

        warmup_tts(use_online=use_online_tts)
    except Exception as e:
        logger.warning(f"Warmup TTS gagal: {e}")

    logger.info("Semua komponen siap.")


_PENUTUP_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in KATA_PENUTUP) + r")\b"
)


def is_penutup(text: str) -> bool:
    """
    Cek apakah user ingin mengakhiri sesi percakapan.

    Pencocokan WAJIB memakai batas kata. Versi sebelumnya memakai substring,
    sehingga kata "dipindahkan" mengandung "dah" dan seluruh perintah
    reschedule berubah jadi perintah menutup sesi — tanpa pesan galat apa pun.
    Kata pendek seperti "dah", "stop", dan "cukup" sangat rawan pada
    pencocokan substring.

    Dibatasi juga pada kalimat pendek: "makasih ya, sekarang catat rapat
    besok" jelas bukan pamit.
    """
    t = text.lower().strip(" .,!?")
    if not t:
        return False

    # Kalimat panjang yang menyebut kata perintah bukan pamit
    if len(t.split()) > 4 and NIAT_PERINTAH.search(t):
        return False

    return bool(_PENUTUP_RE.search(t))


def _proses_aksi_berisiko(data: dict, ask, dengar, say, konteks=None) -> bool:
    """
    Alur untuk aksi yang menghapus atau memindahkan jadwal.

    Dipakai untuk hapus, reschedule, dan pengaturan pengingat.
    Tiga langkah:
    1. Cari kandidat (bisa lewat nama kegiatan, tanggal, atau keduanya)
    2. Kalau lebih dari satu, bacakan daftarnya dan minta user memilih nomor
    3. Konfirmasi eksplisit sebelum benar-benar dieksekusi

    Sebelumnya AKIRA langsung menghapus begitu ada satu yang cocok. Untuk operasi
    yang tidak bisa dibatalkan, itu terlalu berani.
    """
    from src.calendar_service.executor import (
        atur_pengingat,
        cari_kandidat,
        deskripsi_kandidat,
        hapus_banyak,
        hapus_event,
        pindah_event,
        ubah_event,
    )
    from src.dialog.confirmation import (
        SEMUA_KANDIDAT,
        konfirmasi,
        konfirmasi_dengan_koreksi,
        pilih_kandidat,
    )
    from src.nlp.date_time_parser import ucapkan_tanggal

    try:
        # Jadwal yang sudah dipilih dari daftar harinya tidak dicari ulang —
        # pencarian nama bisa menemukan jadwal lain yang judulnya mirip.
        kandidat = data.get("_event_terpilih") or cari_kandidat(data)
    except Exception as e:
        logger.error(f"Gagal mencari kandidat: {e}")
        say("Maaf Bos, saya gagal mengambil data kalender.")
        return False

    if not kandidat and konteks is not None and konteks.event_terakhir:
        logger.info("Pencarian kosong, memakai jadwal yang barusan dibahas sebagai kandidat")
        kandidat = list(konteks.event_terakhir)

    if not kandidat:
        patokan = data.get("kegiatan") or (
            ucapkan_tanggal(data["tanggal"]) if data.get("tanggal") else "itu"
        )
        say(f"Saya tidak menemukan jadwal {patokan}, Bos.")
        return False

    # Hapus massal: jangan minta memilih satu dari 20 — konfirmasi jumlahnya.
    massal = data["aksi"] == "hapus" and (
        data.get("hapus_semua") or data.get("tanggal_mulai")
    )
    if massal and len(kandidat) > 1:
        label = data.get("label_rentang") or "seluruhnya"
        contoh = ", ".join(deskripsi_kandidat(e) for e in kandidat[:3])
        say(f"Ada {len(kandidat)} jadwal, Bos. Contohnya: {contoh}.")

        if not konfirmasi(
            f"Hapus SEMUA {len(kandidat)} jadwal {label}? "
            f"Ini tidak bisa dibatalkan, Bos.",
            ask, dengar,
        ):
            say("Baik Bos, tidak jadi dihapus.")
            return False

        hasil = hapus_banyak(kandidat)
        if konteks is not None:
            konteks.bersihkan()
        say(hasil["message"])
        return True

    indeks = pilih_kandidat(kandidat, deskripsi_kandidat, ask, dengar)
    if indeks is None:
        say("Baik Bos, saya batalkan.")
        return False

    # "dua-duanya" / "semuanya" — hanya masuk akal untuk penghapusan
    if indeks == SEMUA_KANDIDAT:
        if data["aksi"] != "hapus":
            say("Untuk yang ini saya perlu satu jadwal saja, Bos. Sebutkan nomornya.")
            return False

        if not konfirmasi(
            f"Hapus semua {len(kandidat)} jadwal itu? Ini tidak bisa dibatalkan, Bos.",
            ask, dengar,
        ):
            say("Baik Bos, tidak jadi dihapus.")
            return False

        hasil = hapus_banyak(kandidat)
        if konteks is not None:
            konteks.bersihkan()
        say(hasil["message"])
        return True

    event = kandidat[indeks]
    ringkas = deskripsi_kandidat(event)

    if data["aksi"] == "hapus":
        if not konfirmasi(f"Hapus {ringkas}? Ini tidak bisa dibatalkan, Bos.", ask, dengar):
            say("Baik Bos, tidak jadi dihapus.")
            return False
        hasil = hapus_event(event)
    elif data["aksi"] == "edit":
        # `terapkan` sengaja tidak dipakai: perubahan diterapkan langsung ke
        # Google Calendar oleh ubah_event(), bukan ke dict lokal.
        from src.nlp.correction import parse_koreksi, ucapkan_perubahan

        # Salin detail event ke data supaya koreksi punya nilai pembanding
        acuan = {
            "kegiatan": event.get("summary"),
            "deskripsi": event.get("description"),
            "tanggal": _tanggal_event(event),
            "jam": _jam_event(event),
        }

        ask(f"{ringkas}. Mau ubah apanya, Bos?")
        jawaban = dengar()
        perubahan = parse_koreksi(acuan, jawaban, use_llm=True)

        if not perubahan:
            say("Maaf Bos, saya belum menangkap apa yang mau diubah.")
            return False

        if not konfirmasi(f"Ubah {ucapkan_perubahan(perubahan)}?", ask, dengar):
            say("Baik Bos, tidak jadi diubah.")
            return False

        hasil = ubah_event(event, perubahan)

    elif data["aksi"] == "reminder":
        from src.nlp.date_time_parser import ucapkan_lead_time

        menit = data.get("lead_menit") or 15
        if not konfirmasi(
            f"Ingatkan {ucapkan_lead_time(menit)} sebelum {ringkas}?", ask, dengar
        ):
            say("Baik Bos, pengingatnya tidak jadi diatur.")
            return False
        hasil = atur_pengingat(event, menit)
    else:
        # Konfirmasi yang menerima koreksi: kalau user menjawab "jamnya jadi
        # jam 12", waktunya langsung diperbarui dan pertanyaannya diulang
        # dengan detail baru — tanpa perlu mengulang seluruh perintah.
        def pertanyaan():
            tujuan = ucapkan_tanggal(data["tanggal"])
            jam_teks = (
                f" jam {data['jam']}" if data.get("jam") else ", jam tetap seperti semula"
            )
            return f"Pindahkan {ringkas} ke {tujuan}{jam_teks}?"

        if not konfirmasi_dengan_koreksi(data, pertanyaan, ask, dengar):
            say("Baik Bos, tidak jadi dipindah.")
            return False
        hasil = pindah_event(event, data["tanggal"], data.get("jam"))

    if konteks is not None:
        konteks.catat_event(hasil.get("data"))

    say(hasil["message"])
    return True


# "beberapa kegiatan", "banyak jadwal", "tambahin semua"
MINTA_BANYAK = re.compile(
    r"\b(?:beberapa|banyak|sekaligus|semua(?:nya)?|satu per satu|"
    r"beberapa kali|rutin|tiap minggu|setiap minggu)\b"
)


def _minta_banyak_jadwal(text: str) -> bool:
    """
    True untuk "aku ada beberapa kegiatan bulan ini, tambahin ya".

    Harus disertai niat mencatat — kalau tidak, "cek beberapa jadwal"
    ikut tertangkap dan AKIRA malah masuk mode input.
    """
    t = (text or "").lower()
    if not MINTA_BANYAK.search(t):
        return False
    return bool(
        re.search(r"\b(?:tambah|tambahin|tambahkan|catat|catatin|buat|bikin|masukin|input)\b", t)
    )


def _lanjut_tambah_jadwal(config, ask, dengar, say, konteks, model) -> bool:
    """
    Tanya jadwal berikutnya dalam mode input beruntun.
    Return True kalau masih lanjut, False kalau user bilang cukup.
    """
    ask("Ada lagi, Bos?")
    jawaban = dengar()

    if not jawaban.strip():
        say("Baik Bos, saya sudahi dulu.")
        return False

    if is_penutup(jawaban) or is_negatif(jawaban):
        say("Siap Bos, semua sudah saya catat.")
        return False

    # Jawaban diproses di putaran berikutnya lewat antrean sederhana
    _antrean_perintah.append(jawaban)
    return True


def _dengar_ambient(config: dict, model_paths: list, ambang_khusus: dict):
    """
    Dengarkan sekali dalam mode ambient.

    Return ("wakeword", nama_model) | ("suara", bytes) | ("sepi", None).

    Wake word dinilai langsung dari audio oleh openWakeWord — Whisper baru
    dipanggil terpisah lewat _transkripsi_ambient(), dan hanya untuk kalimat
    biasa. Perintah rahasia tidak pernah melewati Whisper sama sekali.
    """
    from src.audio.ambient_listener import PendengarAmbient

    try:
        with PendengarAmbient(
            model_paths,
            threshold=config["wakeword"]["threshold"],
            threshold_per_model=ambang_khusus,
            confirm_frames=_get(config, "wakeword", "confirm_frames", default=2),
            vad_aggressiveness=config["audio"]["vad_aggressiveness"],
            rms_ambang=_get(config, "audio", "rms_ambang", default=320),
            max_silence_frames=config["audio"]["max_silence_frames"],
            max_duration_s=_get(config, "audio", "max_duration_s", default=10),
        ) as pendengar:
            return pendengar.dengar(
                batas_detik=_get(config, "ambient", "cek_tiap_detik", default=3)
            )
    except Exception as e:
        logger.error(f"Pendengar ambient error: {e}")
        time.sleep(1)
        return "sepi", None


def _catat_konteks(pertanyaan: str):
    """Simpan kalimat terakhir AKIRA supaya lapis 2 tahu sedang menjawab apa."""
    try:
        from src.stt.ensemble import set_konteks_pertanyaan

        set_konteks_pertanyaan(pertanyaan)
    except Exception:
        pass


def _transkripsi_ambient(config: dict, audio: bytes) -> str:
    """
    Transkripsi audio hasil rekaman ambient. Dipanggil hanya kalau ada suara.

    `engine` WAJIB diteruskan. Tanpa itu transcribe() jatuh ke default
    "whisper" — dan mode ambient diam-diam berjalan dengan satu mesin saja,
    tanpa ensemble maupun rekonsiliasi. Gejalanya persis seperti yang terlihat
    di log: sesi biasa memakai tiga mesin, ambient cuma satu.
    """
    if not audio:
        return ""

    from src.audio.recorder import save_wav
    from src.stt.transcriber import transcribe

    return transcribe(
        save_wav(audio),
        model_size=config["stt"]["model_size"],
        device=config["stt"]["device"],
        language=config["stt"]["language"],
        engine=_get(config, "stt", "engine", default="whisper"),
    )


def _terjemahkan_maksud(text: str, sudah: set) -> tuple[str, str | None]:
    """
    Minta Groq menerjemahkan kalimat yang tidak dikenali ke perintah baku,
    lalu PASTIKAN parser berbasis aturan sampai pada aksi yang sama.

    Groq hanya boleh menerjemahkan, tidak boleh memutuskan. Kalau terjemahan
    "catat ..." ternyata tidak dibaca parser sebagai perintah catat, hasilnya
    dibuang — lebih baik bilang "belum mengerti" daripada menjalankan
    sesuatu yang tidak bisa dibuktikan.

    Return (status, kalimat_baku):
        ("ok", kalimat)   terjemahan terbukti sah
        ("bukan", None)   Groq menilai ini bukan perintah — jangan dipaksakan
        ("gagal", None)   Groq tak terhubung / tak bisa dipakai — boleh cadangan lokal
    """
    from src.dialog.alarm import is_batal_timer, is_permintaan_alarm, is_permintaan_timer
    from src.nlp.intent_classifier import hanya_kata_benda
    from src.nlp.parser import parse_command
    from src.utils.user_settings import deteksi_ganti_nama

    if text in sudah or len((text or "").split()) < 2 or hanya_kata_benda(text):
        return ("bukan", None)

    try:
        from src.nlp.groq_reasoner import pahami_maksud_groq
        from src.stt import ensemble

        hasil = pahami_maksud_groq(text, getattr(ensemble, "_KONTEKS_PERTANYAAN", None))
    except Exception as e:
        logger.warning(f"Pemahaman maksud gagal: {e}")
        return ("gagal", None)
    if not hasil:
        return ("gagal", None)
    if hasil.get("bukan"):
        return ("bukan", None)

    kanonik, aksi = hasil["perintah"], hasil["aksi"]
    pemeriksa = {
        "timer": is_permintaan_timer,
        "alarm": is_permintaan_alarm,
        "batal_timer": is_batal_timer,
        "ganti_nama": lambda t: bool(deteksi_ganti_nama(t)),
        "penutup": is_penutup,
    }
    if aksi in pemeriksa:
        sah = pemeriksa[aksi](kanonik)
    else:
        sah = parse_command(kanonik, use_slm=False).get("aksi") == aksi

    if not sah:
        logger.warning(f"Terjemahan Groq '{kanonik}' tidak terbukti sebagai '{aksi}', dibuang")
        return ("bukan", None)
    return ("ok", kanonik)


def _pilih_jadwal_dari_hari(data: dict, ask, dengar, say, konteks=None) -> bool | None:
    """
    Untuk hapus / pindah / edit / pengingat tanpa nama kegiatan: tanyakan
    HARINYA, bacakan jadwal di hari itu, lalu minta user memilih satu.

    Sebelumnya AKIRA langsung bertanya "kegiatannya apa?" — memaksa user
    mengingat judul persis jadwalnya. Orang lebih mudah mengingat KAPAN
    sebuah acara daripada apa judulnya di kalender.

    Return:
        None  -> langkah ini tidak berlaku (nama/rujukan/rentang sudah jelas)
        True  -> jadwal terpilih, disimpan di data["_event_terpilih"]
        False -> dibatalkan atau tidak ada jadwal; alur berhenti
    """
    from src.calendar_service.executor import _ambil_event_rentang, deskripsi_kandidat
    from src.dialog.confirmation import SEMUA_KANDIDAT, pilih_kandidat
    from src.dialog.context import mengandung_rujukan
    from src.dialog.state_machine import minta_batal
    from src.nlp.date_time_parser import parse_date_id, ucapkan_tanggal

    aksi = data.get("aksi")
    if aksi not in ("hapus", "reschedule", "edit", "reminder"):
        return None
    if data.get("kegiatan") or data.get("hapus_semua") or data.get("tanggal_mulai"):
        return None
    if (mengandung_rujukan(data.get("teks_asli", ""))
            and konteks is not None and konteks.event_terakhir):
        return None     # "hapus jadwal tersebut" — sudah jelas yang mana

    kunci = "tanggal_asal" if aksi == "reschedule" else "tanggal"
    sumber = data.get(kunci)

    if not sumber:
        ask("Jadwal pada hari apa, Bos?")
        jawaban = dengar()
        if minta_batal(jawaban):
            say("Baik Bos, saya batalkan.")
            return False
        tgl = parse_date_id(jawaban or "")
        if not tgl:
            say("Maaf Bos, harinya tidak tertangkap. Coba sebut lagi perintahnya.")
            return False
        sumber = tgl.strftime("%Y-%m-%d")

    label = ucapkan_tanggal(sumber, sebut_hari=True, sebut_tahun=False)
    try:
        events = _ambil_event_rentang(sumber, sumber)
    except Exception as e:
        logger.error(f"Gagal membaca jadwal {sumber}: {e}")
        say("Maaf Bos, saya gagal mengambil data kalender.")
        return False

    if not events:
        say(f"Tidak ada jadwal pada {label}, Bos.")
        return False

    if len(events) == 1:
        terpilih = events
        say(f"Pada {label} ada satu jadwal: {deskripsi_kandidat(events[0])}.")
    else:
        indeks = pilih_kandidat(events, deskripsi_kandidat, ask, dengar)
        if indeks is None:
            say("Baik Bos, saya batalkan.")
            return False
        if indeks == SEMUA_KANDIDAT:
            if aksi != "hapus":
                say("Untuk yang ini saya perlu satu jadwal saja, Bos. Coba ulangi.")
                return False
            terpilih = events
            data["hapus_semua"] = True
        else:
            terpilih = [events[indeks]]

    data[kunci] = sumber
    data["_event_terpilih"] = terpilih
    # Nama kegiatan diisi dari jadwal terpilih supaya slot filling tidak
    # menanyakannya lagi dan ringkasan konfirmasi tetap bermakna.
    data["kegiatan"] = terpilih[0].get("summary")
    logger.info(f"Jadwal dipilih dari {sumber}: {[e.get('summary') for e in terpilih]}")
    return True


def _tanya_detail_per_hari(data: dict, ask, dengar) -> dict | None:
    """
    Tanyakan apakah kegiatan dan jamnya sama untuk semua hari yang disebut.

    Sama   -> kembali ke alur biasa: satu kegiatan, satu jam untuk semua.
    Beda   -> tanya kegiatan dan jam untuk TIAP hari, satu per satu.

    Jawaban dipahami dua lapis: kata kunci ("sama", "beda") lebih dulu,
    lalu penalaran Groq untuk jawaban bebas seperti "yang minggu lain".
    Kalau tetap tidak jelas, dianggap sama — itu alur yang paling pendek,
    dan ringkasan di akhir masih memberi kesempatan mengoreksi per hari.

    Return data, atau None kalau user membatalkan.
    """
    from src.dialog.confirmation import tafsir_dengan_penalaran
    from src.dialog.state_machine import minta_batal, perjelas_periode
    from src.nlp.date_time_parser import gabung_tanggal, parse_time_id, ucapkan_tanggal
    from src.nlp.parser import merge_answer

    daftar = data["tanggal_lain"]
    pertanyaan = (
        f"Untuk {gabung_tanggal(daftar)}, kegiatan dan jamnya sama semua, Bos?"
    )
    ask(pertanyaan)
    jawaban = dengar()

    if minta_batal(jawaban):
        ask("Baik Bos, saya batalkan.")
        return None

    t = (jawaban or "").lower()
    if re.search(r"\b(?:beda|berbeda|lain|lainan|nggak sama|gak sama|tidak sama|beda.beda)\b", t):
        sama = False
    elif re.search(r"\b(?:sama|semua sama|sama semua|sama aja|sama saja)\b", t):
        sama = True
    else:
        # "iya sama" -> True; "yang minggu lain" -> False (lewat penalaran)
        sama = tafsir_dengan_penalaran(jawaban, pertanyaan)
        if sama is None:
            logger.info("Jawaban sama/beda tidak jelas, dianggap sama")
            sama = True

    if sama:
        return data

    # --- Beda: kumpulkan detail tiap hari
    kegiatan_per, jam_per = {}, {}
    for tanggal in daftar:
        nama_hari = ucapkan_tanggal(tanggal, sebut_hari=True, sebut_tahun=False)

        ask(f"Untuk {nama_hari}, kegiatannya apa, Bos?")
        jawab_keg = dengar()
        if minta_batal(jawab_keg):
            ask("Baik Bos, saya batalkan.")
            return None
        sementara = merge_answer({"aksi": "catat"}, "kegiatan", jawab_keg)
        if not sementara.get("kegiatan"):
            ask("Maaf Bos, kegiatannya tidak tertangkap. Saya batalkan dulu.")
            return None

        ask("Jam berapa, Bos?")
        jawab_jam = dengar()
        if minta_batal(jawab_jam):
            ask("Baik Bos, saya batalkan.")
            return None
        jam = parse_time_id(jawab_jam or "")
        if not jam:
            ask("Maaf Bos, jamnya tidak tertangkap. Saya batalkan dulu.")
            return None

        # Periode tiap hari diperiksa sendiri: "makan malam jam 7" jelas,
        # "futsal jam 7" perlu ditanya.
        satu = {"aksi": "catat", "jam": jam, "kegiatan": sementara["kegiatan"],
                "_jam_sumber": jawab_jam}
        from src.dialog.state_machine import perlu_perjelas_jam

        if perlu_perjelas_jam(satu):
            ask("Jam segitu pagi atau malam, Bos?")
            satu = perjelas_periode(satu, dengar())

        kegiatan_per[tanggal] = satu["kegiatan"]
        jam_per[tanggal] = satu["jam"]

    data["kegiatan_per_tanggal"] = kegiatan_per
    data["jam_per_tanggal"] = jam_per
    # Isi field umum dengan hari pertama supaya pemeriksaan kelengkapan lolos;
    # yang dipakai saat menyimpan tetap nilai per tanggal.
    data["kegiatan"] = kegiatan_per[daftar[0]]
    data["jam"] = jam_per[daftar[0]]
    data["_periode_dikonfirmasi"] = True
    logger.info(f"Detail per hari: {kegiatan_per} | {jam_per}")
    return data


def _tanggal_event(event: dict) -> str:
    """Tanggal event dalam YYYY-MM-DD."""
    start = event.get("start", {})
    return (start.get("dateTime") or start.get("date", ""))[:10]


def _jam_event(event: dict) -> str | None:
    """Jam event (HH:MM), None kalau seharian penuh."""
    dt = event.get("start", {}).get("dateTime")
    return dt[11:16] if dt else None


def _tangani_bentrok(data: dict, ask, dengar, say) -> bool:
    """
    Cek tabrakan jadwal, lalu TANYAKAN apa yang harus dilakukan.

    Sebelumnya AKIRA hanya memberi tahu lalu tetap lanjut ke konfirmasi —
    user harus menolak, mengulang perintah, dan menyebut ulang semuanya.
    Sekarang tiga pilihan ditawarkan langsung di tempat:

      "tetap"  -> simpan berdampingan (jadwal tumpang tindih kadang disengaja)
      "ganti"  -> sebutkan jam baru saat itu juga, tanpa mengulang perintah
      "batal"  -> tidak jadi

    Return True kalau boleh lanjut, False kalau dibatalkan.
    """
    from src.calendar_service.executor import cari_bentrok, ucapkan_bentrok
    from src.dialog.confirmation import tafsir_ya_tidak
    from src.nlp.correction import parse_koreksi, terapkan, ucapkan_perubahan

    for _ in range(3):     # batas putaran: jam baru pun bisa bentrok lagi
        per_tanggal = data.get("jam_per_tanggal") or {}
        daftar = data.get("tanggal_lain") or (
            [data["tanggal"]] if data.get("tanggal") else []
        )

        semua_bentrok = []
        for tanggal in daftar:
            jam = per_tanggal.get(tanggal, data.get("jam"))
            try:
                bentrok = cari_bentrok(tanggal, jam, data.get("jam_selesai"))
            except Exception as e:
                logger.warning(f"Gagal cek bentrok {tanggal}: {e}")
                continue
            if bentrok:
                semua_bentrok.append((tanggal, bentrok))

        if not semua_bentrok:
            return True

        for tanggal, bentrok in semua_bentrok:
            say(ucapkan_bentrok(bentrok, tanggal))

        ask(
            "Mau tetap saya masukkan berdampingan, ganti jamnya, "
            "atau batalkan, Bos?"
        )
        jawaban = dengar()
        t = (jawaban or "").lower()

        if re.search(r"\b(?:batal|batalkan|jangan|gak jadi|nggak jadi|tidak jadi)\b", t):
            say("Baik Bos, tidak jadi saya catat.")
            return False

        if re.search(r"\b(?:tetap|lanjut|masukkan|masukin|biarkan|gapapa|"
                     r"tidak apa|nggak apa|ya|iya|oke|boleh)\b", t):
            logger.info("User memilih tetap menyimpan meski bentrok")
            return True

        # Selain itu: mungkin user langsung menyebut jam baru
        perubahan = parse_koreksi(data, jawaban, use_llm=False)
        if perubahan:
            terapkan(data, perubahan)
            say(f"Baik Bos, saya ubah {ucapkan_perubahan(perubahan)}.")
            continue

        if tafsir_ya_tidak(jawaban) is False:
            say("Baik Bos, tidak jadi saya catat.")
            return False

        ask("Sebutkan jam barunya, atau bilang tetap saja, Bos.")
        jawaban = dengar()
        perubahan = parse_koreksi(data, jawaban, use_llm=False)
        if perubahan:
            terapkan(data, perubahan)
            say(f"Baik Bos, saya ubah {ucapkan_perubahan(perubahan)}.")
            continue

        if re.search(r"\b(?:tetap|lanjut|gapapa|ya|iya|oke)\b", (jawaban or "").lower()):
            return True

        say("Baik Bos, saya batalkan.")
        return False

    logger.info("Bentrok belum selesai setelah beberapa putaran, tetap dilanjutkan")
    return True


def _catat_banyak_tanggal(data: dict, execute, konteks, say):
    """
    Buat event yang sama untuk beberapa tanggal sekaligus.

    Jam, nama kegiatan, dan deskripsi diambil dari data yang sudah dikonfirmasi;
    yang berbeda hanya tanggalnya. Kegagalan per tanggal dilaporkan sendiri —
    satu tanggal gagal tidak membatalkan sisanya.
    """
    from src.nlp.date_time_parser import ucapkan_tanggal

    tanggal_list = data["tanggal_lain"]
    per_tanggal = data.get("jam_per_tanggal") or {}
    keg_per = data.get("kegiatan_per_tanggal") or {}
    berhasil, gagal = [], []

    for tanggal in tanggal_list:
        satuan = dict(data)
        satuan["tanggal"] = tanggal
        satuan["tanggal_lain"] = []
        # Jam dan kegiatan khusus tanggal ini kalau ada; kalau tidak, yang umum
        satuan["jam"] = per_tanggal.get(tanggal, data.get("jam"))
        satuan["kegiatan"] = keg_per.get(tanggal, data.get("kegiatan"))
        hasil = execute(satuan)

        if hasil.get("success"):
            berhasil.append(tanggal)
            konteks.catat_event(hasil.get("data"))
        else:
            gagal.append(tanggal)
            logger.error(f"Gagal mencatat {tanggal}: {hasil.get('message')}")

    nama = data.get("kegiatan") or "jadwal"
    if berhasil:
        from src.nlp.date_time_parser import gabung_tanggal

        if keg_per:
            rincian = gabung_tanggal(berhasil, per_tanggal, keg_per)
            say(f"Sudah saya catat, Bos. {rincian}.")
        else:
            rincian = gabung_tanggal(berhasil, per_tanggal)
            jam = "" if per_tanggal else f", jam {data.get('jam')}"
            say(f"Sudah saya catat, Bos. {nama.capitalize()} pada {rincian}{jam}.")
    if gagal:
        daftar = ", ".join(ucapkan_tanggal(t, sebut_tahun=False) for t in gagal)
        say(f"Tapi {daftar} gagal saya simpan, Bos.")


def _proses_alarm(text: str, say) -> bool:
    """
    Tangani permintaan alarm atau timer. Return True kalau tertangani.

    Dipisah dari alur kalender karena sifatnya beda: timer 30 detik bukan
    agenda, dan tidak perlu masuk Google Calendar.
    """
    from src.dialog import alarm as modul_alarm
    from src.nlp.date_time_parser import parse_date_id, parse_time_id
    from src.nlp.text_normalizer import normalize

    bersih = normalize(text)

    # Membatalkan & menanyakan sisa waktu dicek DULU: "matikan timernya"
    # mengandung kata "timer" dan bisa salah terbaca sebagai permintaan
    # timer baru kalau urutannya terbalik.
    if modul_alarm.is_batal_timer(bersih):
        jumlah = modul_alarm.batalkan_semua()
        if jumlah:
            say(f"Baik Bos, {jumlah} timer saya matikan.")
        else:
            say("Tidak ada timer yang aktif, Bos.")
        return True

    if modul_alarm.is_tanya_timer(bersih):
        say(modul_alarm.ucapkan_sisa())
        return True

    if modul_alarm.is_permintaan_timer(bersih):
        detik = modul_alarm.parse_durasi(bersih)
        label = modul_alarm._label_dari_teks(bersih)
        modul_alarm.tambah_timer(detik, label, say_fn=say)
        durasi = modul_alarm.ucapkan_durasi(detik)
        say(f"Siap Bos, timer {durasi} dimulai sekarang.")
        return True

    if modul_alarm.is_permintaan_alarm(bersih):
        jam = parse_time_id(bersih)
        tanggal = parse_date_id(bersih)
        label = modul_alarm._label_dari_teks(bersih)
        modul_alarm.tambah_alarm(
            jam,
            tanggal.strftime("%Y-%m-%d") if tanggal else None,
            label,
            say_fn=say,
        )
        keperluan = f" untuk {label}" if label else ""
        say(f"Siap Bos, alarm{keperluan} saya pasang jam {jam}.")
        return True

    return False


def _proses_self_destruct(config: dict, ask, dengar, say) -> bool:
    """
    Perintah rahasia: AKIRA menghapus dirinya sendiri.

    Empat lapis pengaman, sengaja bertele-tele — ini satu-satunya perintah
    yang tidak punya tombol undo:

    1. Wake word terpisah (bukan "AKIRA WAKE UP")
    2. Konfirmasi biasa
    3. Kata kode acak yang harus diucapkan ulang — salah dengar tidak mungkin
       menghasilkan kata yang tepat
    4. Cadangan otomatis sebelum apa pun dihapus

    Return True kalau penghapusan benar-benar dijalankan.
    """
    from src.dialog.confirmation import konfirmasi
    from src.dialog.self_destruct import (
        buat_cadangan,
        cocok_kata_kode,
        hapus_sekarang,
        jadwalkan_hapus_total,
        pilih_kata_kode,
        ringkas_target,
    )

    tingkat = _get(config, "self_destruct", "tingkat", default="data")
    pakai_cadangan = _get(config, "self_destruct", "backup", default=True)

    logger.warning(f"PERINTAH SELF DESTRUCT diterima (tingkat: {tingkat})")

    # Tanpa cadangan, peringatannya harus lebih tegas — tidak ada jalan pulang.
    peringatan = (
        "Tidak ada cadangan yang dibuat. Semuanya hilang permanen."
        if not pakai_cadangan
        else "Tidak bisa dibatalkan."
    )

    if not konfirmasi(
        f"Bos, Anda meminta saya menghancurkan diri. Ini akan menghapus "
        f"{ringkas_target(tingkat)}. {peringatan} Anda yakin?",
        ask,
        dengar,
    ):
        say("Baik Bos, saya batalkan. Saya masih di sini.")
        return False

    # Lapis terakhir: kata kode acak
    kode = pilih_kata_kode()
    ask(
        f"Konfirmasi terakhir. Untuk melanjutkan, ucapkan kata: {kode}. "
        f"Ucapkan hal lain untuk membatalkan."
    )
    jawaban = dengar()

    if not cocok_kata_kode(jawaban, kode):
        logger.info(f"Kata kode salah ('{jawaban}'), self destruct dibatalkan")
        say("Kata kodenya tidak cocok, Bos. Saya batalkan.")
        return False

    if not pakai_cadangan:
        logger.warning("Cadangan dimatikan — penghapusan permanen tanpa jalan pulang")

    if pakai_cadangan:
        say("Baik Bos. Saya buat cadangan dulu.")
        cadangan = buat_cadangan()
        if cadangan:
            say(f"Cadangan tersimpan di folder induk dengan nama {cadangan.name}.")
        else:
            if not konfirmasi(
                "Cadangan gagal dibuat, Bos. Tetap lanjutkan tanpa cadangan?",
                ask,
                dengar,
            ):
                say("Baik Bos, saya batalkan.")
                return False

    if tingkat == "total":
        say(
            "Selamat tinggal, Bos. Terima kasih sudah membangun saya. "
            "Sistem saya akan terhapus setelah proses ini berhenti.",
            interruptible=False,
        )
        jadwalkan_hapus_total()
        logger.warning("Self destruct total dijadwalkan. AKIRA berhenti.")
        raise SystemExit(0)

    terhapus = hapus_sekarang(tingkat)
    say(
        f"Selesai, Bos. {len(terhapus)} bagian sudah saya hapus. "
        f"Saya akan berhenti sekarang.",
        interruptible=False,
    )
    logger.warning(f"Self destruct tingkat '{tingkat}' selesai: {len(terhapus)} item")
    raise SystemExit(0)


def handle_session(config: dict, perintah_awal: str = None):
    """
    Satu SESI percakapan: dibuka wake word, lalu bisa berisi banyak perintah
    berturut-turut tanpa wake word lagi.
    """
    from src.audio.recorder import (
        MIN_FRAME_BICARA,
        MIN_FRAME_JAWABAN,
        record_with_vad,
        save_wav,
    )
    from src.nlp.intent_classifier import classify_intent_keyword
    from src.nlp.text_normalizer import normalize
    from src.calendar_service.executor import execute
    from src.dialog import reminder
    from src.dialog.confirmation import konfirmasi, konfirmasi_dengan_koreksi
    from src.dialog.context import KonteksSesi, resolusi_rujukan
    from src.nlp.intent_classifier import deteksi_pernyataan_jadwal
    from src.nlp.text_normalizer import deteksi_sebutan
    from src.dialog.state_machine import (
        build_confirmation,
        build_ringkasan,
        is_complete,
        perjelas_periode,
        perlu_perjelas_jam,
        run_optional_filling,
        run_slot_filling,
    )
    from src.nlp.parser import merge_answer, parse_command
    from src.stt.transcriber import transcribe
    from src.tts.speaker import speak
    from src.utils.greeting import get_greeting
    from src.utils.session_state import sudah_briefing_hari_ini, tandai_briefing_selesai

    from src.utils.user_settings import deteksi_ganti_nama, get_nama_panggilan, set_nama_panggilan

    use_online_tts = os.getenv("USE_ONLINE_TTS", "false").lower() == "true"
    speaker_name = get_nama_panggilan()

    follow_up_timeout = _get(config, "dialog", "follow_up_timeout_s", default=8)
    max_idle = _get(config, "dialog", "max_idle_turns", default=2)
    briefing_days = _get(config, "dialog", "briefing_days", default=7)
    briefing_sekali_sehari = _get(config, "dialog", "briefing_once_per_day", default=True)
    model = config["nlp"]["ollama_model"]

    def say(text, interruptible=True):
        # Kalimat terakhir AKIRA jadi konteks untuk lapis 2. Sangat membantu
        # saat jawabannya pendek dan ambigu ("betalkan" vs "batalkan").
        _catat_konteks(text)

        # Semua kalimat AKIRA ditulis memakai "Bos" sebagai penanda sapaan.
        # Menggantinya di satu tempat jauh lebih aman daripada menyebar
        # nama panggilan ke puluhan f-string di executor, state machine,
        # dan modul konfirmasi.
        if speaker_name and speaker_name != "Bos":
            text = re.sub(r"\bBos\b", speaker_name, text)
        logger.info(f"AKIRA: {text}")
        return speak(text, use_online=use_online_tts, interruptible=interruptible)

    def listen(timeout: float | None = None, jawaban: bool = False) -> str:
        """
        Dengarkan satu ucapan, atau ambil perintah ketikan kalau ada.

        Perekaman bisa diinterupsi pemicu antarmuka. Ketika itu terjadi,
        teks ketikannya HARUS dikembalikan di sini — kalau tidak, pemanggil
        menerima string kosong dan menganggap user diam. Di log terpantau
        slot filling bertanya tiga kali berturut-turut padahal jawabannya
        sudah diketik setiap kali.
        """
        if trigger.ada_pemicu():
            pemicu = trigger.ambil()
            if pemicu and pemicu.jenis == "perintah":
                logger.info(f"Jawaban dari {pemicu.sumber}: '{pemicu.perintah}'")
                return pemicu.perintah

        audio = record_with_vad(
            max_silence_frames=config["audio"]["max_silence_frames"],
            aggressiveness=config["audio"]["vad_aggressiveness"],
            max_duration_s=_get(config, "audio", "max_duration_s", default=10),
            initial_timeout_s=timeout,
            rms_ambang=_get(config, "audio", "rms_ambang", default=320),
            interupsi=trigger.ada_pemicu,
            # Menjawab pertanyaan AKIRA boleh sependek "ya" — lihat
            # MIN_FRAME_JAWABAN di recorder.py
            min_frame_bicara=MIN_FRAME_JAWABAN if jawaban else MIN_FRAME_BICARA,
        )
        if not audio:
            # Rekaman dihentikan pemicu: ambil teksnya, jangan kembalikan kosong
            if trigger.ada_pemicu():
                pemicu = trigger.ambil()
                if pemicu and pemicu.jenis == "perintah":
                    logger.info(f"Jawaban dari {pemicu.sumber}: '{pemicu.perintah}'")
                    return pemicu.perintah
            return ""
        path = save_wav(audio)
        return transcribe(
            path,
            model_size=config["stt"]["model_size"],
            device=config["stt"]["device"],
            language=config["stt"]["language"],
            engine=_get(config, "stt", "engine", default="whisper"),
        )

    reminder.set_busy(True)
    try:
        # --- Pembuka: sapaan, dan briefing HANYA kalau belum diucapkan hari ini.
        #
        # Dulu briefing diulang setiap wake word. Isinya sama persis sepanjang hari,
        # jadi user mendengar laporan yang sama lima kali dalam sejam.
        # Sekarang statusnya dicatat per tanggal (bertahan walau program di-restart).
        perlu_briefing = briefing_sekali_sehari and not sudah_briefing_hari_ini()

        say(get_greeting(speaker_name, singkat=not perlu_briefing))

        if perlu_briefing:
            try:
                from src.calendar_service.executor import get_briefing

                say(get_briefing(days=briefing_days))
                tandai_briefing_selesai()
            except Exception as e:
                logger.warning(f"Gagal menyusun briefing: {e}")
        else:
            logger.info("Briefing dilewati (sudah diucapkan hari ini)")

        idle_turns = 0
        baru_bertanya = False  # True tepat setelah AKIRA tanya "masih ada lagi?"
        # Terjemahan Groq yang sudah dicoba di sesi ini. Kalau hasil terjemahan
        # pun tidak dipahami, jangan diterjemahkan lagi — cegah putaran tanpa akhir.
        sudah_diterjemahkan = set()
        konteks = KonteksSesi()  # ingatan jangka pendek: jadwal yang barusan dibahas
        mode_banyak = False      # True saat user menambah beberapa jadwal berturut-turut
        _antrean_perintah.clear()

        # Mode ambient: kalimat pemicunya SUDAH berisi perintah, jadi langsung
        # diproses. Menyuruh user mengulang ("ada apa Bos?") justru menyebalkan.
        if perintah_awal:
            _antrean_perintah.append(perintah_awal)

        # --- Loop percakapan: banyak perintah dalam satu sesi
        while True:
            # Perintah yang sudah diucapkan saat mode input beruntun
            # diproses lebih dulu, tanpa mendengarkan lagi.
            if _antrean_perintah:
                text = _antrean_perintah.pop(0)
                logger.info(f"Memproses dari antrean: '{text}'")
            elif trigger.ada_pemicu():
                # Pintasan ditekan SAAT sesi sedang berjalan. Tanpa cabang ini,
                # perintahnya menunggu sampai sesi berakhir karena kehabisan
                # waktu diam — di log terpantau 14 detik, dan terasa seperti
                # tombolnya tidak berfungsi.
                pemicu = trigger.ambil()
                if pemicu and pemicu.jenis == "perintah":
                    text = pemicu.perintah
                    logger.info(f"Perintah dari {pemicu.sumber}: '{text}'")
                else:
                    say("Ya Bos?")
                    text = listen(timeout=follow_up_timeout)
            else:
                text = listen(timeout=follow_up_timeout)

            if not text.strip():
                idle_turns += 1
                if idle_turns >= max_idle:
                    logger.info("User diam, kembali ke standby.")
                    return
                say("Masih ada yang bisa saya bantu, Bos?")
                baru_bertanya = True
                continue

            idle_turns = 0

            def ask(q):
                return say(q)

            def dengar():
                return listen(timeout=12, jawaban=True)

            # Alarm & timer ditangani sebelum parser kalender. "timer 30 detik"
            # bukan agenda — memasukkannya ke Google Calendar justru merepotkan.
            if _proses_alarm(text, say):
                baru_bertanya = False
                continue

            # "panggil saya Dzaky" — diproses sebelum apa pun, karena kalimatnya
            # bukan perintah kalender dan akan membingungkan parser.
            nama_baru = deteksi_ganti_nama(text)
            if nama_baru:
                try:
                    speaker_name = set_nama_panggilan(nama_baru)
                    say(f"Siap, mulai sekarang saya panggil Anda {speaker_name}.")
                except ValueError:
                    say("Maaf, saya tidak menangkap namanya. Coba sebutkan lagi.")
                baru_bertanya = False
                continue

            if is_penutup(text):
                say(_pesan_penutup(config))
                return

            # "Tidak." setelah AKIRA bertanya "masih ada lagi?" berarti selesai,
            # bukan perintah yang gagal dipahami.
            if baru_bertanya and is_negatif(text):
                say(_pesan_penutup(config))
                return

            baru_bertanya = False

            # "aku ada beberapa kegiatan bulan ini, tambahin ya"
            if not mode_banyak and _minta_banyak_jadwal(text):
                mode_banyak = True
                say("Siap Bos, sebutkan satu per satu. Bilang cukup kalau sudah selesai.")
                lanjutan = dengar()
                if not lanjutan.strip():
                    mode_banyak = False
                    continue
                text = lanjutan

            # Kata kunci tidak mengenali kalimatnya: terjemahkan maksud lewat
            # Groq SEBELUM pengklasifikasi label dipakai.
            #
            # Urutan ini penting. Pengklasifikasi label hanya mengenal 7 aksi
            # kalender — ia tidak tahu timer, alarm, atau pamit ada. Diberi
            # "10 menitan lagi kabarin soal jemuran", ia terpaksa memilih
            # label terdekat, "reminder", lalu AKIRA menanyakan "berapa lama
            # sebelum acara?" untuk acara yang tidak pernah ada. Penerjemah
            # memakai katalog LENGKAP dan hasilnya divalidasi.
            use_slm = True
            if text not in sudah_diterjemahkan and not classify_intent_keyword(normalize(text)):
                status, terjemahan = _terjemahkan_maksud(text, sudah_diterjemahkan)
                # Dicatat supaya Groq tidak ditanya dua kali untuk kalimat
                # yang sama bila parser nanti juga menyerah.
                sudah_diterjemahkan.add(text)
                if status == "ok":
                    sudah_diterjemahkan.add(terjemahan)
                    _antrean_perintah.insert(0, terjemahan)
                    continue
                if status == "bukan":
                    # Groq sudah menilai ini bukan perintah — jangan biarkan
                    # pengklasifikasi lain memaksakan label.
                    use_slm = False

            data = parse_command(text, use_slm=use_slm, model=model)

            # "reschedule meeting ITU ke besok" — selesaikan rujukan dari
            # jadwal yang baru saja dibacakan atau dibuat.
            data = resolusi_rujukan(data, konteks)

            # User cuma MEMBERI TAHU ("besok saya ada kondangan jam 1 siang"),
            # bukan bertanya. Menjawabnya dengan membacakan kalender terasa
            # tuli — yang wajar adalah menawarkan mencatatkannya.
            if deteksi_pernyataan_jadwal(text):
                # Aksi 'baca' melewati ekstraksi nama kegiatan, jadi ambil
                # sekarang supaya AKIRA bisa menyebut namanya saat menawarkan
                # dan tidak perlu bertanya ulang setelah user setuju.
                if not data.get("kegiatan"):
                    from src.nlp.slm_extractor import extract_kegiatan_regex
                    from src.nlp.text_normalizer import normalize

                    data["kegiatan"] = extract_kegiatan_regex(normalize(text))

                sebutan = deteksi_sebutan(text, default="jadwal")
                nama = data.get("kegiatan") or sebutan
                if konfirmasi(
                    f"Mau saya catat {nama} itu ke kalender, Bos?", ask, dengar
                ):
                    data["aksi"] = "catat"
                else:
                    say("Baik Bos, tidak saya catat.")
                    baru_bertanya = False
                    continue

            if not data.get("aksi"):
                # Semua aturan menyerah. Sebelum bilang "belum mengerti",
                # minta Groq menerjemahkan maksudnya ke perintah baku, lalu
                # proses ulang lewat jalur yang SAMA dari awal — termasuk
                # timer, alarm, penutup, dan ganti nama.
                if text not in sudah_diterjemahkan:
                    status, terjemahan = _terjemahkan_maksud(text, sudah_diterjemahkan)
                    sudah_diterjemahkan.add(text)
                    if status == "ok":
                        sudah_diterjemahkan.add(terjemahan)
                        _antrean_perintah.insert(0, terjemahan)
                        continue
                say("Maaf Bos, saya belum mengerti. Coba ulangi perintahnya.")
                continue

            # Hapus / pindah / edit tanpa nama: pilih dari daftar jadwal harinya
            pilihan = _pilih_jadwal_dari_hari(data, ask, dengar, say, konteks)
            if pilihan is False:
                continue

            # Beberapa hari disebut tapi detailnya belum: tanyakan dulu apakah
            # kegiatannya sama. "Sabtu dan Minggu" sering berarti dua acara
            # berbeda — mengisinya dengan satu kegiatan tanpa bertanya membuat
            # user harus mengoreksi setelahnya.
            if (data.get("aksi") == "catat"
                    and len(data.get("tanggal_lain") or []) > 1
                    and not data.get("kegiatan")
                    and not data.get("kegiatan_per_tanggal")):
                data = _tanya_detail_per_hari(data, ask, dengar)
                if data is None:
                    continue

            # Slot filling — tanya ulang kalau ada field wajib yang kosong
            if not is_complete(data):
                data = run_slot_filling(data, ask, dengar, merge_answer)
                if data is None:
                    continue

            # Aksi yang MENGUBAH atau MENGHAPUS jadwal butuh langkah tambahan
            if data["aksi"] in ("hapus", "reschedule", "reminder", "edit"):
                if not _proses_aksi_berisiko(data, ask, dengar, say, konteks):
                    continue
                baru_bertanya = False
                continue

            if data["aksi"] == "catat":
                # "jam 10" itu pagi atau malam? Tanya sekali daripada membuat
                # jadwal yang meleset 12 jam.
                if perlu_perjelas_jam(data):
                    ask("Jam segitu pagi atau malam, Bos?")
                    data = perjelas_periode(data, dengar())

                # Tanyakan detail opsional (jam selesai, deskripsi) — boleh dilewati,
                # tapi pembatalan tetap menghentikan perintah.
                data = run_optional_filling(data, ask, dengar, merge_answer)
                if data is None:
                    baru_bertanya = False
                    continue
                # Peringatkan bentrok SEBELUM ringkasan konfirmasi, supaya
                # user memutuskan dengan tahu — bukan menemukan tabrakannya
                # setelah event terlanjur dibuat.
                if not _tangani_bentrok(data, ask, dengar, say):
                    continue

                # Bacakan ulang semuanya sebelum masuk kalender.
                # Jawaban berupa koreksi ("jamnya jadi jam 12") langsung
                # diterapkan, tidak dipaksa jadi ya/tidak.
                if not konfirmasi_dengan_koreksi(
                    data, lambda: build_ringkasan(data), ask, dengar, model=model
                ):
                    say("Baik Bos, saya batalkan.")
                    continue
            elif data["aksi"] not in ("baca", "waktu"):
                say(build_confirmation(data))

            # Beberapa tanggal sekaligus: buat satu event untuk tiap tanggal.
            # Dulu hanya tanggal pertama yang tersimpan, dua sisanya hilang
            # diam-diam — kegagalan yang baru ketahuan saat user cek kalender.
            if data["aksi"] == "catat" and len(data.get("tanggal_lain") or []) > 1:
                _catat_banyak_tanggal(data, execute, konteks, say)
                baru_bertanya = False
                continue

            result = execute(data)

            # Ingat hasilnya supaya perintah berikutnya bisa bilang "jadwal itu"
            if result.get("success"):
                konteks.catat_event(result.get("data"))

            selesai = say(result["message"])
            if not selesai:
                say("Baik Bos, saya hentikan.", interruptible=False)

            # "Aku ada beberapa kegiatan bulan ini" — lanjut tanya satu per satu
            # sampai user bilang cukup. Jauh lebih andal daripada memaksa parser
            # memecah satu kalimat panjang berisi lima jadwal sekaligus.
            if mode_banyak and result.get("success"):
                mode_banyak = _lanjut_tambah_jadwal(
                    config, ask, dengar, say, konteks, model
                )
    finally:
        reminder.set_busy(False)


def _sesi_self_destruct(config: dict):
    """Sesi pendek khusus perintah rahasia — tidak ada briefing, tidak ada basa-basi."""
    from src.audio.recorder import record_with_vad, save_wav
    from src.stt.transcriber import transcribe
    from src.tts.speaker import speak
    from src.utils.user_settings import get_nama_panggilan

    use_online_tts = os.getenv("USE_ONLINE_TTS", "false").lower() == "true"
    speaker_name = get_nama_panggilan()

    def say(text, interruptible=True):
        _catat_konteks(text)
        if speaker_name and speaker_name != "Bos":
            text = re.sub(r"\bBos\b", speaker_name, text)
        logger.info(f"AKIRA: {text}")
        return speak(text, use_online=use_online_tts, interruptible=interruptible)

    def dengar():
        audio = record_with_vad(
            max_silence_frames=config["audio"]["max_silence_frames"],
            aggressiveness=config["audio"]["vad_aggressiveness"],
            max_duration_s=_get(config, "audio", "max_duration_s", default=10),
            initial_timeout_s=12,
            rms_ambang=_get(config, "audio", "rms_ambang", default=320),
        )
        if not audio:
            return ""
        return transcribe(
            save_wav(audio),
            model_size=config["stt"]["model_size"],
            device=config["stt"]["device"],
            language=config["stt"]["language"],
            engine=_get(config, "stt", "engine", default="whisper"),
        )

    _proses_self_destruct(config, say, dengar, say)


def run():
    logger.info("=" * 55)
    logger.info("AKIRA — Audio-driven Kalendar & Interactive Reminder Assistant")
    logger.info("=" * 55)

    config = load_config()

    if not preflight_check(config):
        logger.error("Preflight check gagal. Perbaiki dulu sebelum menjalankan AKIRA.")
        sys.exit(1)

    from src.dialog.reminder import (
        announce_startup_briefing,
        check_all_tiers,
        start_reminder_loop,
    )
    from src.tts.speaker import speak
    from src.wakeword.detector import listen_for_wakeword, tandai_deteksi_sekarang

    from src.utils.session_state import sudah_briefing_hari_ini, tandai_briefing_selesai

    use_online_tts = os.getenv("USE_ONLINE_TTS", "false").lower() == "true"
    briefing_days = _get(config, "dialog", "briefing_days", default=7)
    briefing_saat_start = _get(config, "dialog", "briefing_on_start", default=True)
    briefing_sekali_sehari = _get(config, "dialog", "briefing_once_per_day", default=True)

    warmup_all(config, use_online_tts)

    def say_bg(text):
        speak(text, use_online=use_online_tts)

    # Laporan agenda saat dinyalakan — tapi hanya kalau belum diucapkan hari ini.
    # Kalau AKIRA di-restart siang hari, dia tidak mengulang laporan pagi tadi.
    if briefing_saat_start and not (briefing_sekali_sehari and sudah_briefing_hari_ini()):
        announce_startup_briefing(say_bg, days=briefing_days)
        tandai_briefing_selesai()
    elif briefing_saat_start:
        logger.info("Briefing startup dilewati (sudah diucapkan hari ini)")

    # Reminder jalan di background thread, cek pertama langsung dijalankan.
    start_reminder_loop(
        say_bg,
        interval=_get(config, "reminder", "check_interval_seconds", default=60),
        lead_tiers=_get(config, "reminder", "lead_tiers_minutes", default=[30, 15, 5]),
        run_immediately=True,
    )

    # Wake word kedua (opsional): perintah rahasia self destruct.
    # Kalau file modelnya tidak ada, fiturnya diam-diam tidak aktif —
    # AKIRA tetap jalan normal.
    model_paths = [config["wakeword"]["model_path"]]
    nama_destruct = None
    ambang_khusus = {}
    destruct_path = _get(config, "self_destruct", "model_path")
    destruct_lewat_teks = _get(config, "self_destruct", "aktif_lewat_teks", default=True)

    if destruct_path and os.path.exists(destruct_path):
        model_paths.append(destruct_path)
        nama_destruct = os.path.splitext(os.path.basename(destruct_path))[0]
        ambang_khusus[nama_destruct] = _get(
            config, "self_destruct", "threshold", default=0.8
        )
        logger.info(
            f"Wake word rahasia aktif: {nama_destruct} "
            f"(ambang {ambang_khusus[nama_destruct]})"
        )
    elif destruct_path:
        logger.warning(f"Model self destruct tidak ditemukan: {destruct_path}")

    if destruct_lewat_teks:
        logger.info(
            "Self destruct lewat suara aktif: sebut 'AKIRA DESTROY YOURSELF' "
            "(bekerja juga saat mode ambient, tanpa model wake word)"
        )
    else:
        logger.info("Self destruct lewat teks dimatikan di config")

    ambient_aktif = _get(config, "ambient", "enabled", default=True)
    ambient_menit = _get(config, "ambient", "timeout_menit", default=15)
    pernah_dibangunkan = False
    waktu_aktivitas_terakhir = 0.0

    if ambient_aktif:
        logger.info(
            f"Mode ambient aktif: setelah dibangunkan sekali, cukup sebut "
            f"'AKIRA ...' selama {ambient_menit} menit terakhir"
        )

    logger.info("AKIRA siap. Panggil 'AKIRA WAKE UP' untuk mulai. (Ctrl+C untuk berhenti)")
    logger.info("Saat AKIRA bicara, tekan ENTER untuk memotong pembacaan.")

    try:
        while True:
            # Pemicu dari antarmuka / pintasan keyboard.
            #
            # WAJIB diperiksa paling awal. Blok mode ambient di bawah selalu
            # berakhir dengan `continue`, jadi pemeriksaan yang ditaruh
            # sesudahnya tidak akan PERNAH tercapai selama ambient aktif —
            # dan ambient aktif setiap kali AKIRA baru selesai dipakai.
            # Gejalanya: pintasan tercatat di log tapi tidak terjadi apa-apa.
            if trigger.ada_pemicu():
                pemicu = trigger.ambil()
                if pemicu:
                    logger.info(f"Dibangunkan lewat {pemicu.sumber} ({pemicu.jenis})")
                    try:
                        handle_session(
                            config,
                            perintah_awal=(pemicu.perintah or None
                                           if pemicu.jenis == "perintah" else None),
                        )
                    except KeyboardInterrupt:
                        logger.info("Sesi dipotong.")
                    tandai_deteksi_sekarang()
                    pernah_dibangunkan = True
                    waktu_aktivitas_terakhir = time.time()
                    continue

            # --- Mode ambient: dengar terus tanpa wake word ---
            # Satu stream mikrofon melayani DUA hal sekaligus: openWakeWord
            # menilai tiap potongan 80 ms (murah, tanpa Whisper), dan VAD
            # menangkap kalimat untuk ditranskripsi.
            #
            # Ini yang membuat "AKIRA DESTROY YOURSELF" tidak lagi bergantung
            # pada tebakan Whisper — model wake word tetap mendengar walau
            # AKIRA sedang merekam kalimat lain.
            if ambient_aktif and pernah_dibangunkan:
                sisa = ambient_menit * 60 - (time.time() - waktu_aktivitas_terakhir)
                if sisa > 0:
                    # Di ambient tidak ada pertanyaan yang sedang dijawab
                    _catat_konteks("")
                    jenis, isi = _dengar_ambient(config, model_paths, ambang_khusus)

                    # Pemicu bisa datang saat ambient sedang merekam.
                    # Tanpa pemeriksaan ini, rekaman ambient harus selesai
                    # dulu sebelum pintasan terbaca.
                    if trigger.ada_pemicu():
                        continue

                    if jenis == "wakeword":
                        waktu_aktivitas_terakhir = time.time()
                        try:
                            if nama_destruct and nama_destruct in str(isi):
                                logger.warning("Wake word rahasia terdeteksi di mode ambient")
                                _sesi_self_destruct(config)
                            else:
                                handle_session(config)
                        except KeyboardInterrupt:
                            logger.info("Sesi dipotong.")
                        tandai_deteksi_sekarang()
                        waktu_aktivitas_terakhir = time.time()
                        continue

                    text = _transkripsi_ambient(config, isi) if jenis == "suara" else ""

                    if text and destruct_lewat_teks and minta_self_destruct(text):
                        logger.warning(f"Perintah self destruct lewat teks: '{text}'")
                        waktu_aktivitas_terakhir = time.time()
                        try:
                            _sesi_self_destruct(config)
                        except KeyboardInterrupt:
                            logger.info("Self destruct dibatalkan lewat Ctrl+C")
                        tandai_deteksi_sekarang()
                        waktu_aktivitas_terakhir = time.time()
                        continue

                    if text and minta_bangun(text):
                        logger.info(f"Frasa bangun terdeteksi di teks: '{text}'")
                        waktu_aktivitas_terakhir = time.time()
                        try:
                            handle_session(config)
                        except KeyboardInterrupt:
                            logger.info("Sesi dipotong.")
                        tandai_deteksi_sekarang()
                        waktu_aktivitas_terakhir = time.time()
                        continue

                    if text and perintah_untuk_akira(text):
                        logger.info(f"Disapa tanpa wake word: '{text}'")
                        waktu_aktivitas_terakhir = time.time()
                        try:
                            handle_session(config, perintah_awal=text)
                        except KeyboardInterrupt:
                            logger.info("Sesi dipotong.")
                        tandai_deteksi_sekarang()
                        waktu_aktivitas_terakhir = time.time()
                    elif text:
                        logger.debug(f"Diabaikan (bukan perintah untuk AKIRA): '{text}'")
                    continue

                logger.info(
                    f"Tidak ada aktivitas {ambient_menit} menit, "
                    f"kembali menunggu wake word"
                )
                pernah_dibangunkan = False

            terpicu = listen_for_wakeword(
                model_paths,
                threshold=config["wakeword"]["threshold"],
                confirm_frames=_get(config, "wakeword", "confirm_frames", default=2),
                cooldown_s=_get(config, "wakeword", "cooldown_s", default=3.0),
                threshold_per_model=ambang_khusus,
                interupsi=trigger.ada_pemicu,
            )

            # Wake word rahasia punya alur sendiri, tidak lewat sesi biasa
            if terpicu and nama_destruct and nama_destruct in str(terpicu):
                try:
                    _sesi_self_destruct(config)
                except KeyboardInterrupt:
                    logger.info("Self destruct dibatalkan lewat Ctrl+C")
                tandai_deteksi_sekarang()
                continue

            if terpicu:
                pernah_dibangunkan = True
                waktu_aktivitas_terakhir = time.time()
                try:
                    handle_session(config)
                except KeyboardInterrupt:
                    # Ctrl+C saat sesi = potong sesi ini saja, bukan matikan program
                    logger.info("Sesi dipotong. Kembali ke mode standby...")
                    tandai_deteksi_sekarang()
                    continue
                # Hitung cooldown dari AKHIR sesi, supaya sisa suara AKIRA sendiri
                # atau gema di ruangan tidak langsung memicu sesi baru.
                tandai_deteksi_sekarang()

                # Cek reminder SEGERA setelah sesi selesai. Jadwal yang baru saja
                # dibuat bisa jadi sudah masuk ambang pengingat — menunggu siklus
                # berikutnya bikin pengingatnya telat.
                try:
                    check_all_tiers(
                        say_bg,
                        _get(config, "reminder", "lead_tiers_minutes", default=[30, 15, 5]),
                    )
                except Exception as e:
                    logger.warning(f"Cek reminder setelah sesi gagal: {e}")
                logger.info("Kembali ke mode standby...")
    except KeyboardInterrupt:
        logger.info("AKIRA dimatikan. Sampai jumpa, Bos.")
    except SystemExit:
        # Dilempar oleh self destruct — keluar diam-diam, jangan dianggap error
        raise
    except Exception as e:
        # Jangan pernah menutup dengan traceback mentah — user tidak bisa
        # berbuat apa-apa dengannya, dan saat demo itu terlihat buruk.
        logger.error(f"AKIRA berhenti karena error tak terduga: {e}")
        logger.exception("Detail lengkap untuk debugging:")


if __name__ == "__main__":
    run()
