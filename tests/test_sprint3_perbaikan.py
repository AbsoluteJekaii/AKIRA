"""
Test regresi untuk perbaikan Sprint 3.
Setiap test di sini mewakili satu keluhan nyata dari demo Sprint 2 —
kalau ada yang merah, artinya bug lama kambuh.
"""
from datetime import datetime

import pytest

from src.nlp.date_time_parser import parse_date_id, parse_date_range_id, parse_time_id
from src.nlp.intent_classifier import classify_intent_keyword
from src.nlp.parser import parse_command
from src.nlp.slm_extractor import detect_skip, extract_kegiatan_regex
from src.nlp.text_normalizer import convert_number_words, normalize
from src.tts.speaker import split_sentences

REF = datetime(2026, 8, 29, 10, 0)  # Sabtu


# --- Keluhan: "tahun 2026" jadi 2006/2020 ---------------------------------
def test_angka_kata_jadi_tahun_benar():
    assert convert_number_words("dua ribu dua puluh enam") == "2026"
    assert convert_number_words("dua ribu tiga puluh") == "2030"
    assert convert_number_words("tujuh belas") == "17"


def test_tahun_terpisah_disatukan():
    assert "2026" in normalize("bacakan jadwal untuk tahun 20 26")
    assert "2026" in normalize("bacakan jadwal untuk tahun 2 0 2 6")
    assert "2026" in normalize("bacakan jadwal untuk tahun 26")


def test_permintaan_tahun_jadi_rentang_penuh():
    hasil = parse_date_range_id("bacakan jadwal saya untuk tahun 2026", REF)
    assert hasil == ("2026-01-01", "2026-12-31", "tahun 2026")


def test_parse_command_tahun_menghasilkan_rentang():
    data = parse_command("Bacakan jadwal saya untuk tahun 2026", use_slm=False)
    assert data["aksi"] == "baca"
    assert data["tanggal_mulai"] == "2026-01-01"
    assert data["tanggal_akhir"] == "2026-12-31"
    assert data["tanggal"] is None


# --- Keluhan: "30 agustus" tanpa tahun jadi 2027 --------------------------
def test_tanggal_tanpa_tahun_pakai_tahun_berjalan():
    hasil = parse_date_id("catat jadwal tanggal 30 agustus", REF)
    assert hasil.date() == datetime(2026, 8, 30).date()


def test_tanggal_yang_sudah_lewat_pindah_ke_tahun_depan():
    hasil = parse_date_id("catat jadwal 5 januari", REF)
    assert hasil.date() == datetime(2027, 1, 5).date()


def test_tanggal_dengan_tahun_eksplisit_dihormati():
    hasil = parse_date_id("cek jadwal 17 november 2026", REF)
    assert hasil.date() == datetime(2026, 11, 17).date()


# --- Keluhan: harus ngomong kaku, "coba cek dong" tidak dipahami ----------
@pytest.mark.parametrize("kalimat", [
    "coba cek dong jadwal besok",
    "gimana jadwal saya minggu ini",
    "kasih tau dong jadwal saya hari ini",
    "bacakan jadwal besok ya",
    "ada jadwal apa saja besok",
    "tolong tunjukkan jadwal saya",
])
def test_kalimat_santai_tetap_terbaca_sebagai_baca(kalimat):
    assert classify_intent_keyword(kalimat) == "baca"


@pytest.mark.parametrize("kalimat", [
    "tolong bikin jadwal meeting besok",
    "catat dong jadwal rapat",
    "jadwalkan presentasi hari senin",
])
def test_kalimat_santai_tetap_terbaca_sebagai_catat(kalimat):
    assert classify_intent_keyword(kalimat) == "catat"


# --- Fitur baru: tanya jam & tanggal --------------------------------------
@pytest.mark.parametrize("kalimat", [
    "sekarang jam berapa ya akira",
    "sekarang tanggal berapa",
    "hari ini hari apa",
    "sekarang pukul berapa",
])
def test_pertanyaan_waktu_dikenali(kalimat):
    assert classify_intent_keyword(kalimat) == "waktu"


def test_aksi_waktu_tidak_butuh_field():
    from src.dialog.state_machine import is_complete

    data = parse_command("sekarang jam berapa ya akira", use_slm=False)
    assert data["aksi"] == "waktu"
    assert is_complete(data) is True


def test_jawaban_waktu_tidak_menyentuh_kalender():
    from src.calendar_service.executor import _handle_waktu

    hasil = _handle_waktu({"teks_asli": "sekarang jam berapa"})
    assert hasil["success"] is True
    assert "jam" in hasil["message"].lower()


# --- Keluhan: SKIP salah trigger ------------------------------------------
@pytest.mark.parametrize("kalimat", [
    "ada apa aja aja",
    "cek jadwal saya besok ada apa saja",
    "meeting dengan klien",
    "ada jadwal apa hari ini",
])
def test_skip_tidak_salah_trigger(kalimat):
    assert detect_skip(kalimat) is False


@pytest.mark.parametrize("kalimat", ["skip", "gausah", "kosongin aja", "lewati"])
def test_skip_asli_tetap_terdeteksi(kalimat):
    assert detect_skip(kalimat) is True


# --- Ekstraksi kegiatan tanpa SLM (jalur cepat) ---------------------------
def test_kegiatan_regex_membuang_kata_perintah_dan_waktu():
    assert extract_kegiatan_regex("catat jadwal meeting besok jam 3 sore") == "meeting"
    assert extract_kegiatan_regex("jadwalkan rapat divisi hari kamis") == "rapat divisi"


def test_kegiatan_kosong_untuk_perintah_baca():
    assert extract_kegiatan_regex("cek jadwal saya besok") is None


# --- TTS: pemecahan kalimat untuk pipelining & barge-in -------------------
def test_teks_panjang_dipecah_jadi_beberapa_potongan():
    teks = ("Hari ini Anda punya tiga jadwal. Rapat divisi jam sembilan pagi. "
            "Makan siang dengan klien jam dua belas siang.")
    potongan = split_sentences(teks)
    assert len(potongan) >= 3
    assert all(len(p) <= 140 for p in potongan)


def test_teks_pendek_tidak_dipecah():
    assert split_sentences("Halo Bos.") == ["Halo Bos."]


# --- Normalisasi salah eja Whisper ----------------------------------------
def test_salah_eja_whisper_diperbaiki():
    hasil = normalize("Cata jadual meting bahsok jam tiga sore")
    assert "catat" in hasil
    assert "jadwal" in hasil
    assert "meeting" in hasil
    assert "besok" in hasil
    assert "jam 3 sore" in hasil


def test_jam_tetap_terbaca_setelah_normalisasi():
    assert parse_time_id(normalize("catat meeting besok jam setengah delapan pagi")) == "07:30"


# --- Rentang lain ---------------------------------------------------------
@pytest.mark.parametrize("kalimat,label", [
    ("jadwal seminggu ke depan", "seminggu ke depan"),
    ("jadwal minggu ini", "minggu ini"),
    ("jadwal 3 hari ke depan", "3 hari ke depan"),
])
def test_rentang_relatif(kalimat, label):
    hasil = parse_date_range_id(kalimat, REF)
    assert hasil is not None
    assert hasil[2] == label


def test_perintah_satu_hari_bukan_rentang():
    assert parse_date_range_id("cek jadwal besok", REF) is None


# =========================================================================
# Sprint 3.1 — perbaikan dari demo kedua
# =========================================================================

# --- "Buatkan jadwal untuk besok" salah terbaca sebagai BACA -------------
@pytest.mark.parametrize("kalimat", [
    "buatkan jadwal untuk besok",
    "buatin jadwal meeting besok jam 3",
    "bikinin jadwal kuliah senin jam 8",
    "tolong catatkan jadwal rapat besok",
])
def test_akhiran_kan_in_tetap_terbaca_catat(kalimat):
    assert parse_command(kalimat, use_slm=False)["aksi"] == "catat"


def test_kata_jadwal_telanjang_tidak_bikin_baca_menang():
    # "hapus jadwal" harus tetap hapus, bukan terbagi skor dengan baca
    assert classify_intent_keyword("hapus jadwal rapat") == "hapus"
    assert classify_intent_keyword("buat jadwal rapat besok") == "catat"


def test_perintah_baca_asli_tidak_ikut_berubah():
    for kalimat in ["cek jadwal besok", "coba cek dong jadwal besok", "bacakan jadwal saya"]:
        assert classify_intent_keyword(kalimat) == "baca"


# --- Briefing tidak boleh diulang tiap wake word -------------------------
def test_status_briefing_per_run():
    """
    Briefing sekali per RUN. Sprint 3.5 mengubah ini dari 'sekali per hari
    yang bertahan antar-restart' — restart program harus memicu briefing lagi.
    """
    from src.utils import session_state

    session_state.reset_briefing()
    assert session_state.sudah_briefing_hari_ini() is False
    session_state.tandai_briefing_selesai()
    assert session_state.sudah_briefing_hari_ini() is True
    session_state.reset_briefing()
    assert session_state.sudah_briefing_hari_ini() is False


def test_status_briefing_tidak_disimpan_ke_file(tmp_path, monkeypatch):
    """
    Status harus di memori proses saja — kalau ada file, restart tidak memicu briefing.

    Dijalankan di folder kosong: yang diuji adalah apakah KODE menulis berkas,
    bukan apakah berkas itu kebetulan ada. Versi lama AKIRA memang menulisnya,
    dan sisanya tertinggal di folder pengembang — test yang memeriksa folder
    kerja jadi gagal karena riwayat, bukan karena kode sekarang.
    """
    import os

    from src.utils import session_state

    monkeypatch.chdir(tmp_path)
    session_state.reset_briefing()
    session_state.tandai_briefing_selesai()
    assert not hasattr(session_state, "STATE_PATH")
    assert not os.path.exists("config/session_state.json")


def test_briefing_muncul_lagi_setelah_ganti_hari(monkeypatch):
    from datetime import datetime, timedelta

    from src.utils import session_state

    session_state.reset_briefing()
    session_state.tandai_briefing_selesai()
    assert session_state.sudah_briefing_hari_ini() is True

    # Majukan "hari ini" satu hari — status harus kedaluwarsa sendiri
    besok = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    monkeypatch.setattr(session_state, "_hari_ini", lambda: besok)
    assert session_state.sudah_briefing_hari_ini() is False
    session_state.reset_briefing()


def test_sapaan_singkat_beda_dari_sapaan_pembuka():
    from src.utils.greeting import get_greeting

    panjang = {get_greeting("Bos") for _ in range(20)}
    singkat = {get_greeting("Bos", singkat=True) for _ in range(20)}
    assert not (panjang & singkat)
    assert all(len(s) < 30 for s in singkat)


# --- Halusinasi Whisper saat sunyi ---------------------------------------
@pytest.mark.parametrize("kalimat", [
    "Terima kasih kerana menonton!",
    "Jangan lupa like dan subscribe",
    "Thanks for watching!",
])
def test_halusinasi_whisper_dibuang(kalimat):
    import re as _re

    src = open("src/stt/transcriber.py", encoding="utf-8").read()
    ns = {}
    exec(src[src.index("HALUSINASI_UMUM"):src.index("def transcribe(")], ns)
    assert ns["_is_halusinasi"](kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "Terima kasih.",
    "Oke, terima kasih.",
    "Sekarang jam berapa.",
    "catat jadwal meeting besok",
])
def test_kalimat_asli_tidak_ikut_dibuang(kalimat):
    src = open("src/stt/transcriber.py", encoding="utf-8").read()
    ns = {}
    exec(src[src.index("HALUSINASI_UMUM"):src.index("def transcribe(")], ns)
    assert ns["_is_halusinasi"](kalimat) is False


# --- Reminder berjenjang: konfigurasi tier benar-benar dipakai ------------
def _fake_event(eid, menit_dari_sekarang, judul="Rapat divisi"):
    from datetime import datetime as _dt, timedelta as _td

    mulai = _dt.now().astimezone() + _td(minutes=menit_dari_sekarang)
    return {"id": eid, "summary": judul, "start": {"dateTime": mulai.isoformat()}}


def _pasang_kalender_palsu(events, monkeypatch):
    """
    Ganti modul crud dengan tiruan. Dilakukan lewat sys.modules supaya test ini
    tetap jalan di mesin yang belum memasang google-api-python-client
    (mis. CI atau laptop anggota tim yang baru clone).
    """
    import sys
    import types

    fake = types.ModuleType("src.calendar_service.crud")
    fake.read_events = lambda **kw: events
    monkeypatch.setitem(sys.modules, "src.calendar_service.crud", fake)


def _jalankan_reminder(events, tiers, monkeypatch):
    """Jalankan satu siklus reminder dengan kalender palsu, kembalikan kalimat yang diucapkan."""
    from src.dialog import reminder

    reminder._reminded.clear()
    reminder.set_busy(False)
    _pasang_kalender_palsu(events, monkeypatch)

    diucapkan = []
    reminder.check_all_tiers(diucapkan.append, tiers)
    return diucapkan


def test_reminder_bunyi_saat_masuk_tier(monkeypatch):
    hasil = _jalankan_reminder([_fake_event("a", 14)], [30, 15, 5], monkeypatch)
    assert len(hasil) == 1
    assert "Rapat divisi" in hasil[0]
    assert "menit lagi" in hasil[0]


def test_reminder_diam_kalau_masih_jauh(monkeypatch):
    assert _jalankan_reminder([_fake_event("a", 45)], [30, 15, 5], monkeypatch) == []


def test_reminder_tidak_diulang_di_tier_yang_sama(monkeypatch):
    from src.dialog import reminder

    events = [_fake_event("a", 14)]
    pertama = _jalankan_reminder(events, [30, 15, 5], monkeypatch)
    kedua = []
    reminder.check_all_tiers(kedua.append, [30, 15, 5])
    assert len(pertama) == 1
    assert kedua == []


def test_tier_kustom_dari_config_dipakai(monkeypatch):
    # Event 50 menit lagi: diam untuk tier default, bunyi untuk tier [60, ...]
    assert _jalankan_reminder([_fake_event("a", 50)], [30, 15, 5], monkeypatch) == []
    assert len(_jalankan_reminder([_fake_event("b", 50)], [60, 30, 10], monkeypatch)) == 1


def test_reminder_diam_saat_akira_sedang_melayani(monkeypatch):
    from src.dialog import reminder

    reminder._reminded.clear()
    _pasang_kalender_palsu([_fake_event("a", 10)], monkeypatch)
    reminder.set_busy(True)
    diucapkan = []
    reminder.check_all_tiers(diucapkan.append, [30, 15, 5])
    reminder.set_busy(False)
    assert diucapkan == []


def test_pesan_reminder_menyebut_jam_acara():
    from src.dialog.reminder import build_reminder_message, parse_event_start

    event = _fake_event("a", 14, "Presentasi proposal")
    pesan = build_reminder_message(event, parse_event_start(event))
    assert "Presentasi proposal" in pesan
    assert "jam" in pesan


def test_tier_lebih_jauh_tidak_bunyi_susulan(monkeypatch):
    """
    Acara 14 menit lagi harus bunyi H-15 saja. Tier H-30 sudah terlewat,
    jangan ikut bunyi di siklus berikutnya sebagai pengingat basi.
    """
    from src.dialog import reminder

    hasil = _jalankan_reminder([_fake_event("a", 14)], [30, 15, 5], monkeypatch)
    assert len(hasil) == 1

    susulan = []
    reminder.check_all_tiers(susulan.append, [30, 15, 5])
    assert susulan == []


def test_tier_lebih_dekat_tetap_bunyi_nanti(monkeypatch):
    """Setelah H-15 bunyi, H-5 harus tetap bunyi saat waktunya tiba."""
    from src.dialog import reminder

    _jalankan_reminder([_fake_event("a", 14)], [30, 15, 5], monkeypatch)

    # Acara yang sama, sekarang tinggal 4 menit lagi
    _pasang_kalender_palsu([_fake_event("a", 4)], monkeypatch)
    lanjutan = []
    reminder.check_all_tiers(lanjutan.append, [30, 15, 5])
    assert len(lanjutan) == 1


# =========================================================================
# Sprint 3.2 — perbaikan dari demo ketiga
# =========================================================================

# --- "jam 7.60" bikin crash di executor ----------------------------------
@pytest.mark.parametrize("kalimat", ["jam 7.60", "jam 7.75", "jam 25", "jam 30 pagi"])
def test_jam_tidak_masuk_akal_ditolak(kalimat):
    assert parse_time_id(kalimat) is None


@pytest.mark.parametrize("kalimat,harapan", [
    ("jam 8 pagi", "08:00"),
    ("jam 14:30", "14:30"),
    ("jam 7 lewat 15", "07:15"),
    ("jam 12 malam", "00:00"),
    ("jam 12 siang", "12:00"),
    ("jam 9 malam", "21:00"),
    ("jam setengah 8 pagi", "07:30"),
])
def test_jam_valid_tetap_lolos(kalimat, harapan):
    assert parse_time_id(kalimat) == harapan


def test_jam_ditolak_bikin_slot_filling_bertanya_lagi():
    from src.dialog.state_machine import check_missing_fields
    from src.nlp.parser import merge_answer

    data = {"aksi": "catat", "tanggal": "2026-08-29", "jam": None, "kegiatan": "rapat"}
    data = merge_answer(data, "jam", "jam 7.60")
    assert data["jam"] is None
    assert "jam" in check_missing_fields(data)


# --- Kalimat tanya "apakah ada jadwal..." --------------------------------
@pytest.mark.parametrize("kalimat", [
    "apakah aku ada jadwal 7 hari ke depan",
    "apakah tahun ini saya ada jadwal",
    "saya ada agenda apa besok",
    "punya jadwal apa minggu depan",
    "apa ada acara besok",
])
def test_kalimat_tanya_terbaca_sebagai_baca(kalimat):
    assert classify_intent_keyword(kalimat) == "baca"


def test_pertanyaan_rentang_menghasilkan_rentang():
    data = parse_command("Apakah aku ada jadwal 7 hari kedepan?", use_slm=False)
    assert data["aksi"] == "baca"
    assert data["label_rentang"] == "7 hari ke depan"
    assert data["tanggal"] is None


def test_tahun_ini_dan_tahun_depan_jadi_rentang():
    ini = parse_date_range_id("apakah tahun ini saya ada jadwal", REF)
    assert ini[1] == "2026-12-31"
    depan = parse_date_range_id("jadwal tahun depan", REF)
    assert depan[0] == "2027-01-01" and depan[1] == "2027-12-31"


# --- Batas hari harus ikut zona waktu Jakarta, bukan UTC -----------------
def test_batas_hari_pakai_zona_lokal():
    from src.calendar_service.executor import _batas_hari

    awal = _batas_hari("2026-08-29")
    akhir = _batas_hari("2026-08-29", akhir_hari=True)
    assert awal.startswith("2026-08-29T00:00:00")
    assert akhir.startswith("2026-08-29T23:59:59")
    # Yang penting: ada offset zona waktu, bukan 'Z' alias UTC
    assert awal.endswith("+07:00")
    assert not awal.endswith("Z")


# --- "Tidak." setelah ditanya "masih ada lagi?" --------------------------
def _muat_is_negatif():
    src = open("src/app.py", encoding="utf-8").read()
    ns = {}
    exec(src[src.index("KATA_NEGATIF"):src.index("def load_config")], ns)
    return ns["is_negatif"]


@pytest.mark.parametrize("kalimat", ["Tidak.", "tidak", "nggak", "engga deh", "belum"])
def test_jawaban_menolak_dikenali(kalimat):
    assert _muat_is_negatif()(kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "Buatkan jadwal untuk hari ini.",
    "tidak usah buatkan jadwal meeting besok",
    "cek jadwal besok",
])
def test_perintah_biasa_tidak_dianggap_menolak(kalimat):
    assert _muat_is_negatif()(kalimat) is False


# --- Nama kegiatan wajib untuk aksi catat --------------------------------
def test_catat_tanpa_kegiatan_ditanya_dulu():
    from src.dialog.state_machine import check_missing_fields, get_next_question

    data = parse_command("Buatkan jadwal untuk hari ini.", use_slm=False)
    assert data["aksi"] == "catat"
    assert "kegiatan" in check_missing_fields(data)
    # Kegiatan ditanya PALING DULU, sebelum tanggal & jam
    assert get_next_question(data)[0] == "kegiatan"


def test_kegiatan_masih_boleh_di_skip():
    from src.dialog.state_machine import is_complete
    from src.nlp.parser import merge_answer

    data = {"aksi": "catat", "tanggal": "2026-08-29", "jam": "08:00", "kegiatan": None}
    data = merge_answer(data, "kegiatan", "gak usah")
    assert data["_kegiatan_skipped"] is True
    assert is_complete(data) is True


# --- Whisper memecah kata berimbuhan -------------------------------------
def test_kata_terpecah_disatukan():
    hasil = normalize("Baca kan jadwal ku hari ini?")
    assert "bacakan" in hasil
    assert "jadwal saya" in hasil


# =========================================================================
# Sprint 3.4 — perbaikan dari demo keempat (hapus & reschedule)
# =========================================================================

# --- Reschedule menyebut DUA tanggal, yang dipakai harus yang tujuan -----
def test_reschedule_pakai_tanggal_tujuan_bukan_asal():
    """
    Tanggal ditulis eksplisit dengan tahun supaya test tidak bergantung pada
    tanggal hari ini — "31 Agustus" tanpa tahun akan jatuh ke tahun depan
    kalau test dijalankan pada bulan September.
    """
    data = parse_command(
        "Reschedule jadwal saya yang tanpa nama pada 30 Agustus 2027 jam 9, "
        "jadi tanggal 31 Agustus 2027.",
        use_slm=False,
    )
    assert data["aksi"] == "reschedule"
    assert data["tanggal"] == "2027-08-31"      # tujuan, bukan 30 Agustus
    assert data["kegiatan"] == "tanpa nama"     # tanpa kata "jadi" ikut terbawa


@pytest.mark.parametrize("kalimat,tanggal,jam", [
    # Tahun ditulis eksplisit supaya hasil tidak berubah tergantung kapan
    # test dijalankan — "5 september" tanpa tahun benar jatuh ke tahun depan
    # bila hari ini sudah lewat tanggal itu.
    ("geser jadwal rapat divisi ke tanggal 5 september 2027 jam 2 siang", "2027-09-05", "14:00"),
    ("pindahkan meeting klien jadi besok jam 10 pagi", None, "10:00"),
])
def test_variasi_kalimat_reschedule(kalimat, tanggal, jam):
    data = parse_command(kalimat, use_slm=False)
    assert data["aksi"] == "reschedule"
    if tanggal:
        assert data["tanggal"] == tanggal
    assert data["jam"] == jam


def test_pisah_asal_tujuan_tanpa_penanda():
    from src.nlp.date_time_parser import pisah_asal_tujuan

    teks = "geser jadwal rapat besok"
    assert pisah_asal_tujuan(teks) == (teks, None)


# --- Tahun masa lalu = salah dengar Whisper ------------------------------
def test_tahun_lampau_dikoreksi():
    """Whisper menulis 2026 jadi 2006. Orang tidak menjadwalkan di tahun lewat."""
    assert parse_date_id("30 agustus 2006", REF).date() == datetime(2026, 8, 30).date()
    assert parse_date_id("17 november 2020", REF).date() == datetime(2026, 11, 17).date()


def test_tahun_masa_depan_tetap_dihormati():
    assert parse_date_id("30 agustus 2027", REF).date() == datetime(2027, 8, 30).date()


# --- Jam opsional untuk reschedule ---------------------------------------
def test_reschedule_tanpa_jam_tidak_ditanya_lagi():
    from src.dialog.state_machine import check_missing_fields, is_complete

    data = {"aksi": "reschedule", "kegiatan": "rapat", "tanggal": "2026-08-31", "jam": None}
    assert check_missing_fields(data) == []
    assert is_complete(data) is True


def test_konfirmasi_reschedule_tanpa_jam_menyebut_jam_tetap():
    from src.dialog.state_machine import build_confirmation

    pesan = build_confirmation(
        {"aksi": "reschedule", "kegiatan": "rapat", "tanggal": "2026-08-31", "jam": None}
    )
    assert "31 Agustus 2026" in pesan
    assert "semula" in pesan


def test_catat_tetap_wajib_punya_jam():
    from src.dialog.state_machine import check_missing_fields

    data = {"aksi": "catat", "kegiatan": "rapat", "tanggal": "2026-08-31", "jam": None}
    assert "jam" in check_missing_fields(data)


# --- "Jadwal Jadwal tanpa nama sudah dihapus" ----------------------------
@pytest.mark.parametrize("judul,harapan", [
    ("Jadwal tanpa nama", "Jadwal tanpa nama"),
    ("Rapat divisi", "jadwal Rapat divisi"),
    ("", "jadwal tanpa nama"),
])
def test_frasa_jadwal_tidak_ganda(judul, harapan):
    from src.calendar_service.executor import _sebut_jadwal

    assert _sebut_jadwal(judul) == harapan


# =========================================================================
# Sprint 3.5 — perbaikan dari demo kelima
# =========================================================================

# --- "Jadwal saya hari ini apa aja ya?" dijawab jam dinding --------------
@pytest.mark.parametrize("kalimat", [
    "jadwal saya hari ini apa aja ya",
    "jadwal saya hari ini apa saja",
    "agenda hari ini apa aja",
])
def test_pertanyaan_jadwal_tidak_terbaca_sebagai_waktu(kalimat):
    assert classify_intent_keyword(kalimat) == "baca"


@pytest.mark.parametrize("kalimat", [
    "sekarang jam berapa",
    "hari ini tanggal berapa",
    "hari ini hari apa",
])
def test_pertanyaan_waktu_asli_tetap_waktu(kalimat):
    assert classify_intent_keyword(kalimat) == "waktu"


# --- Jam selesai & deskripsi ---------------------------------------------
def test_rentang_jam_terbaca():
    data = parse_command("catat jadwal rapat besok dari jam 9 sampai jam 11", use_slm=False)
    assert data["jam"] == "09:00"
    assert data["jam_selesai"] == "11:00"


def test_tanpa_rentang_jam_selesai_kosong():
    data = parse_command("catat meeting besok jam 3 sore", use_slm=False)
    assert data["jam"] == "15:00"
    assert data["jam_selesai"] is None


def test_jam_siang_tidak_digeser_salah():
    """'jam 11 siang' itu 11:00, bukan 23:00."""
    assert parse_time_id("jam 11 siang") == "11:00"
    assert parse_time_id("jam 12 siang") == "12:00"
    assert parse_time_id("jam 1 siang") == "13:00"


def test_field_opsional_ditanyakan_untuk_catat():
    from src.dialog.state_machine import get_next_optional_question

    data = {"aksi": "catat", "kegiatan": "rapat", "tanggal": "2026-08-30", "jam": "09:00"}
    field, _ = get_next_optional_question(data)
    assert field == "jam_selesai"


def test_field_opsional_bisa_dilewati():
    from src.dialog.state_machine import get_next_optional_question, run_optional_filling
    from src.nlp.parser import merge_answer

    data = {"aksi": "catat", "kegiatan": "rapat", "tanggal": "2026-08-30", "jam": "09:00"}
    jawaban = iter(["lewati saja", "gausah"])
    data = run_optional_filling(
        data,
        ask_fn=lambda q: None,
        listen_fn=lambda: next(jawaban, ""),
        merge_fn=merge_answer,
    )
    assert get_next_optional_question(data) is None
    assert data["jam_selesai"] is None
    assert data["deskripsi"] is None


def test_field_opsional_tidak_ditanyakan_untuk_baca():
    from src.dialog.state_machine import get_next_optional_question

    assert get_next_optional_question({"aksi": "baca"}) is None


def test_ringkasan_menyebut_semua_detail():
    from src.dialog.state_machine import build_ringkasan

    pesan = build_ringkasan({
        "aksi": "catat", "kegiatan": "rapat divisi", "tanggal": "2026-08-30",
        "jam": "09:00", "jam_selesai": "11:00", "deskripsi": "bawa laptop",
    })
    assert "rapat divisi" in pesan
    assert "30 Agustus 2026" in pesan
    assert "09:00" in pesan and "11:00" in pesan
    assert "bawa laptop" in pesan
    assert "benar" in pesan.lower()


# --- Konfirmasi ya/tidak --------------------------------------------------
@pytest.mark.parametrize("jawaban,harapan", [
    ("ya", True), ("iya benar", True), ("sudah benar", True), ("oke", True),
    ("tidak", False), ("salah Bos", False), ("batalkan aja", False),
    ("nggak jadi ya", False),          # 'tidak' harus menang atas 'ya'
    ("hmm", None), ("", None),
])
def test_tafsir_ya_tidak(jawaban, harapan):
    from src.dialog.confirmation import tafsir_ya_tidak

    assert tafsir_ya_tidak(jawaban) is harapan


def test_konfirmasi_default_menolak_kalau_tidak_jelas():
    from src.dialog.confirmation import konfirmasi

    jawaban = iter(["hmm", "apa ya"])
    assert konfirmasi("Yakin?", lambda q: None, lambda: next(jawaban, "")) is False


def test_konfirmasi_diam_berarti_batal():
    from src.dialog.confirmation import konfirmasi

    assert konfirmasi("Yakin?", lambda q: None, lambda: "") is False


# --- Hapus: pilih kandidat & konfirmasi ----------------------------------
def test_hapus_boleh_tanpa_nama_kalau_ada_tanggal():
    from src.dialog.state_machine import check_missing_fields

    assert check_missing_fields({"aksi": "hapus", "kegiatan": None, "tanggal": "2026-08-30"}) == []
    assert check_missing_fields({"aksi": "hapus", "kegiatan": "rapat", "tanggal": None}) == []
    assert "kegiatan" in check_missing_fields({"aksi": "hapus", "kegiatan": None, "tanggal": None})


@pytest.mark.parametrize("jawaban,harapan", [
    ("nomor dua", 1), ("2", 1), ("yang ketiga", 2), ("batal", None), ("apa ya", None),
])
def test_tafsir_pilihan_kandidat(jawaban, harapan):
    from src.dialog.confirmation import tafsir_pilihan

    assert tafsir_pilihan(jawaban, 3) == harapan


def test_kandidat_tunggal_tidak_perlu_ditanya():
    from src.dialog.confirmation import pilih_kandidat

    ditanya = []
    hasil = pilih_kandidat(
        [{"summary": "rapat"}],
        lambda e: e["summary"],
        ask_fn=ditanya.append,
        listen_fn=lambda: "",
    )
    assert hasil == 0
    assert ditanya == []      # tidak ada pertanyaan yang diucapkan


def test_kandidat_banyak_dibacakan_dan_dipilih():
    from src.dialog.confirmation import pilih_kandidat

    kandidat = [{"summary": "rapat"}, {"summary": "kuliah"}, {"summary": "seminar"}]
    diucapkan = []
    hasil = pilih_kandidat(
        kandidat, lambda e: e["summary"], ask_fn=diucapkan.append, listen_fn=lambda: "nomor dua"
    )
    assert hasil == 1
    assert "kuliah" in diucapkan[0]


def test_tanggal_tanpa_nama_bulan():
    """'hapus jadwal saya tanggal 30' — angka hari saja, tanpa bulan."""
    ref = datetime(2026, 8, 29, 10, 0)
    assert parse_date_id("hapus jadwal saya tanggal 30", ref).date() == datetime(2026, 8, 30).date()
    # Hari yang sudah lewat di bulan ini -> bulan depan
    assert parse_date_id("catat rapat tanggal 5", ref).date() == datetime(2026, 9, 5).date()


def test_tanggal_dengan_bulan_tetap_menang():
    ref = datetime(2026, 8, 29, 10, 0)
    assert parse_date_id("tanggal 5 september", ref).date() == datetime(2026, 9, 5).date()


@pytest.mark.parametrize("kalimat", [
    "ciptakan jadwal meeting besok jam 9",
    "create jadwal rapat besok",
    "masukin jadwal kuliah senin",
])
def test_variasi_kata_kerja_membuat_jadwal(kalimat):
    assert classify_intent_keyword(kalimat) == "catat"


# =========================================================================
# Sprint 3.6 — perbaikan dari demo keenam
# =========================================================================

# --- "nggak jadi meeting" bukan perintah pindah --------------------------
def test_nggak_jadi_bukan_penanda_tujuan():
    from src.nlp.date_time_parser import pisah_asal_tujuan

    teks = "saya nggak jadi meeting hari ini bisa di reschedule nggak"
    assert pisah_asal_tujuan(teks) == (teks, None)


def test_jadi_tanpa_waktu_setelahnya_diabaikan():
    from src.nlp.date_time_parser import pisah_asal_tujuan

    teks = "reschedule rapat jadi gimana Bos"
    assert pisah_asal_tujuan(teks) == (teks, None)


def test_jadi_dengan_waktu_tetap_memisah():
    from src.nlp.date_time_parser import pisah_asal_tujuan

    _, tujuan = pisah_asal_tujuan("reschedule rapat 30 agustus jadi tanggal 31 agustus")
    assert tujuan == "tanggal 31 agustus"


def test_kegiatan_tidak_kebawa_kata_negasi():
    data = parse_command(
        "Saya nggak jadi meeting hari ini, bisa di reschedule nggak?", use_slm=False
    )
    assert data["kegiatan"] == "meeting"


# --- Kata rujukan: "itu", "tersebut", "tadi" -----------------------------
def test_rujukan_diselesaikan_dari_konteks():
    from src.dialog.context import KonteksSesi, resolusi_rujukan

    konteks = KonteksSesi()
    konteks.catat_event([{"summary": "meeting", "id": "1"}])

    data = {"aksi": "reschedule", "kegiatan": "itu", "teks_asli": "reschedule meeting itu ke besok"}
    assert resolusi_rujukan(data, konteks)["kegiatan"] == "meeting"


def test_kegiatan_kosong_diisi_dari_konteks():
    from src.dialog.context import KonteksSesi, resolusi_rujukan

    konteks = KonteksSesi()
    konteks.catat_event([{"summary": "rapat divisi", "id": "1"}])

    data = {"aksi": "hapus", "kegiatan": None, "teks_asli": "hapus jadwal tersebut"}
    assert resolusi_rujukan(data, konteks)["kegiatan"] == "rapat divisi"


def test_nama_eksplisit_tidak_ditimpa_konteks():
    from src.dialog.context import KonteksSesi, resolusi_rujukan

    konteks = KonteksSesi()
    konteks.catat_event([{"summary": "meeting", "id": "1"}])

    data = {"aksi": "hapus", "kegiatan": "kuliah pagi", "teks_asli": "hapus jadwal kuliah pagi"}
    assert resolusi_rujukan(data, konteks)["kegiatan"] == "kuliah pagi"


def test_konteks_tidak_dipakai_untuk_aksi_baca():
    from src.dialog.context import KonteksSesi, resolusi_rujukan

    konteks = KonteksSesi()
    konteks.catat_event([{"summary": "meeting", "id": "1"}])

    data = {"aksi": "baca", "kegiatan": None, "teks_asli": "cek jadwal itu"}
    assert resolusi_rujukan(data, konteks)["kegiatan"] is None


def test_konteks_banyak_event_tidak_menebak():
    from src.dialog.context import KonteksSesi, resolusi_rujukan

    konteks = KonteksSesi()
    konteks.catat_event([{"summary": "a", "id": "1"}, {"summary": "b", "id": "2"}])

    data = {"aksi": "hapus", "kegiatan": None, "teks_asli": "hapus jadwal itu"}
    assert resolusi_rujukan(data, konteks)["kegiatan"] is None


# --- Bahasa non-baku ------------------------------------------------------
@pytest.mark.parametrize("kalimat", [
    "hari ini saya ada kerjaan nggak sih",
    "besok saya sibuk gak",
    "minggu depan kosong gak",
    "hari ini ngapain aja",
    "besok ada kegiatan apa",
])
def test_bahasa_santai_terbaca_sebagai_baca(kalimat):
    assert classify_intent_keyword(kalimat) == "baca"


# --- Tahun harus ikut disebut --------------------------------------------
def test_tanggal_diucapkan_dengan_tahun():
    from src.calendar_service.executor import _ucapkan_tanggal

    assert _ucapkan_tanggal("2026-08-31") == "31 Agustus 2026"


def test_ringkasan_menyebut_hari_dan_tahun():
    from src.dialog.state_machine import build_ringkasan

    pesan = build_ringkasan(
        {"aksi": "catat", "kegiatan": "rapat", "tanggal": "2026-08-31", "jam": "09:00"}
    )
    assert "2026" in pesan
    assert "Senin" in pesan


# --- "N hari lagi" jadi rentang ------------------------------------------
def test_n_hari_lagi_jadi_rentang():
    hasil = parse_date_range_id("3 hari lagi saya ada jadwal ga", REF)
    assert hasil[0] == "2026-08-29"
    assert hasil[2] == "3 hari ke depan"


# --- Output thinking Qwen3 harus dibuang ---------------------------------
def test_blok_thinking_dibuang():
    from src.nlp.slm_extractor import _buang_thinking

    assert _buang_thinking("<think>ini perintah baca</think>\nbaca") == "baca"
    assert _buang_thinking('<think>x</think>{"kegiatan": "rapat"}') == '{"kegiatan": "rapat"}'
    assert _buang_thinking("<think>terpotong di tengah") == ""
    assert _buang_thinking("baca") == "baca"


# =========================================================================
# Sprint 3.7 — "Saya tidak menemukan jadwal meeting" padahal ada
# =========================================================================

def _kalender_palsu(events, monkeypatch):
    """Ganti modul crud dengan tiruan berisi event yang kita tentukan."""
    import sys
    import types

    fake = types.ModuleType("src.calendar_service.crud")
    fake.read_events = lambda **kw: events
    fake.find_event_by_keyword = lambda kw, max_results=20: [
        e for e in events if kw.lower() in e.get("summary", "").lower()
    ]
    monkeypatch.setitem(sys.modules, "src.calendar_service.crud", fake)


MEETING_HARI_INI = {
    "id": "1",
    "summary": "meeting",
    "start": {"dateTime": "2026-08-29T18:00:00+07:00"},
}


def test_reschedule_tidak_menyaring_dengan_tanggal_tujuan(monkeypatch):
    """
    'reschedule meeting saya hari ini menjadi tanggal 31' — meeting-nya ada di
    tanggal 29, tujuannya 31. Menyaring kandidat dengan tanggal tujuan selalu
    menghasilkan nol.
    """
    from src.calendar_service.executor import cari_kandidat

    _kalender_palsu([MEETING_HARI_INI], monkeypatch)

    data = {
        "aksi": "reschedule",
        "kegiatan": "meeting",
        "tanggal": "2026-08-31",       # tujuan
        "tanggal_asal": "2026-08-29",  # jadwal yang dicari
    }
    assert [e["summary"] for e in cari_kandidat(data)] == ["meeting"]


def test_reschedule_tanpa_tanggal_asal_tetap_ketemu(monkeypatch):
    from src.calendar_service.executor import cari_kandidat

    _kalender_palsu([MEETING_HARI_INI], monkeypatch)

    data = {"aksi": "reschedule", "kegiatan": "meeting",
            "tanggal": "2026-08-31", "tanggal_asal": None}
    assert len(cari_kandidat(data)) == 1


def test_hapus_tetap_menyaring_pakai_tanggal_event(monkeypatch):
    """Untuk hapus, 'tanggal' memang tanggal event-nya — penyaringan harus tetap jalan."""
    from src.calendar_service.executor import cari_kandidat

    _kalender_palsu([MEETING_HARI_INI], monkeypatch)

    cocok = {"aksi": "hapus", "kegiatan": "meeting", "tanggal": "2026-08-29"}
    tidak_cocok = {"aksi": "hapus", "kegiatan": "meeting", "tanggal": "2026-08-31"}
    assert len(cari_kandidat(cocok)) == 1
    assert cari_kandidat(tidak_cocok) == []


def test_parser_memisah_tanggal_asal_dan_tujuan():
    from datetime import datetime as _dt

    data = parse_command(
        "Reschedule jadwal meeting saya hari ini menjadi tanggal 31 Desember 2027.",
        use_slm=False,
    )
    assert data["kegiatan"] == "meeting"
    assert data["tanggal"] == "2027-12-31"                       # tujuan
    assert data["tanggal_asal"] == _dt.now().strftime("%Y-%m-%d")  # "hari ini"


def test_tanggal_asal_kosong_kalau_tidak_disebut():
    data = parse_command(
        "pindahkan rapat divisi ke tanggal 5 september 2027", use_slm=False
    )
    assert data["tanggal"] == "2027-09-05"
    assert data["tanggal_asal"] is None


# =========================================================================
# Sprint 3.8 — konfirmasi harus menerima koreksi
# =========================================================================

# =========================================================================
# Sprint 3.9 — AKIRA yang lebih nyambung
# =========================================================================

# --- Balas dengan kata yang dipakai user ---------------------------------
@pytest.mark.parametrize("teks,harapan", [
    ("besok ada kegiatan ga", "kegiatan"),
    ("ada acara apa besok", "acara"),
    ("cek agenda minggu depan", "agenda"),
    ("cek jadwal besok", "jadwal"),
    ("besok gimana", "jadwal"),          # default
])
def test_deteksi_sebutan(teks, harapan):
    from src.nlp.text_normalizer import deteksi_sebutan

    assert deteksi_sebutan(teks) == harapan


def test_balasan_memakai_kata_user(monkeypatch):
    from src.calendar_service.executor import _handle_baca

    _kalender_palsu([], monkeypatch)

    hasil = _handle_baca(
        {"aksi": "baca", "tanggal": "2026-08-30", "teks_asli": "besok ada kegiatan ga"}
    )
    assert "kegiatan" in hasil["message"]
    assert "jadwal" not in hasil["message"]


# --- Pernyataan vs pertanyaan --------------------------------------------
@pytest.mark.parametrize("kalimat", [
    "besok saya ada kegiatan kondangan jam 1 siang",
    "saya ada meeting jam 3 sore",
    "aku punya acara sabtu depan",
])
def test_pernyataan_jadwal_dikenali(kalimat):
    from src.nlp.intent_classifier import deteksi_pernyataan_jadwal

    assert deteksi_pernyataan_jadwal(kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "besok ada kegiatan ga",
    "besok ada kegiatan ga?",
    "cek jadwal besok",
    "jadwal saya hari ini apa aja ya",
    "saya mau makan",              # tanpa petunjuk waktu
])
def test_pertanyaan_bukan_pernyataan(kalimat):
    from src.nlp.intent_classifier import deteksi_pernyataan_jadwal

    assert deteksi_pernyataan_jadwal(kalimat) is False


def test_nama_kegiatan_terambil_dari_pernyataan():
    from src.nlp.slm_extractor import extract_kegiatan_regex
    from src.nlp.text_normalizer import normalize

    hasil = extract_kegiatan_regex(normalize("Besok, saya ada kegiatan kondangan jam 1 siang."))
    assert hasil == "kondangan"


# --- Jawaban lisan yang mengulang pertanyaan -----------------------------
@pytest.mark.parametrize("jawaban,harapan", [
    ("Kegiatannya meeting.", "meeting"),
    ("acaranya kondangan", "kondangan"),
    ("namanya rapat divisi", "rapat divisi"),
    ("meeting", "meeting"),
])
def test_jawaban_kegiatan_dibersihkan(jawaban, harapan):
    from src.nlp.parser import merge_answer

    assert merge_answer({"kegiatan": None}, "kegiatan", jawaban)["kegiatan"] == harapan


# --- SKIP yang diucapkan berulang ----------------------------------------
@pytest.mark.parametrize("jawaban", ["lewati-lewati", "skip skip", "lewati", "kosongin"])
def test_skip_berulang_terdeteksi(jawaban):
    assert detect_skip(jawaban) is True


# --- Qwen3 menalar tanpa tag <think> -------------------------------------
def test_narasi_sebelum_json_dibuang():
    """Qwen3 kadang menalar dalam bahasa Inggris tanpa tag, lalu baru JSON."""
    from src.nlp.slm_extractor import _clean_json_response

    raw = 'Okay, let\'s tackle this problem. The answer is {"kegiatan": "meeting"} done'
    assert _clean_json_response(raw) == '{"kegiatan": "meeting"}'


# --- Prosodi TTS ----------------------------------------------------------
def test_prosodi_menyisipkan_jeda():
    from src.tts.speaker import perhalus_prosodi

    assert perhalus_prosodi("Baik saya batalkan.") == "Baik, saya batalkan."
    assert "09.00" in perhalus_prosodi("meeting jam 09:00.")


def test_prosodi_tidak_menumpuk_koma():
    from src.tts.speaker import perhalus_prosodi

    hasil = perhalus_prosodi("Baik Bos, saya batalkan.")
    assert ",," not in hasil
    assert hasil.count(",") == 1


# =========================================================================
# Sprint 3.10 — pengingat yang bisa disetel sendiri
# =========================================================================

@pytest.mark.parametrize("kalimat,menit", [
    ("ingatkan saya 1 jam sebelum meeting", 60),
    ("kasih tau 30 menit sebelumnya", 30),
    ("ingetin sehari sebelum", 1440),
    ("setengah jam sebelum", 30),
    ("ingatkan 2 hari sebelum acara", 2880),
    ("dua jam sebelum", 120),
    ("seminggu sebelumnya", 10080),
    ("ingatkan saya 10 detik sebelum", 1),      # dibulatkan ke 1 menit
])
def test_parse_jeda_pengingat(kalimat, menit):
    from src.nlp.date_time_parser import parse_lead_time

    assert parse_lead_time(kalimat) == menit


@pytest.mark.parametrize("kalimat", [
    "catat meeting besok jam 3",
    "ingatkan 15 menit lagi",      # relatif dari sekarang, bukan sebelum acara
    "cek jadwal besok",
])
def test_bukan_jeda_pengingat(kalimat):
    from src.nlp.date_time_parser import parse_lead_time

    assert parse_lead_time(kalimat) is None


@pytest.mark.parametrize("menit,ucapan", [
    (60, "satu jam"), (120, "2 jam"), (1440, "satu hari"),
    (2880, "2 hari"), (30, "30 menit"), (10080, "satu minggu"),
])
def test_ucapkan_jeda(menit, ucapan):
    from src.nlp.date_time_parser import ucapkan_lead_time

    assert ucapkan_lead_time(menit) == ucapan


@pytest.mark.parametrize("kalimat", [
    "ingatkan saya 1 jam sebelum meeting",
    "pasang pengingat buat rapat divisi 30 menit sebelumnya",
    "ingetin sehari sebelum kondangan",
])
def test_intent_reminder_dikenali(kalimat):
    assert classify_intent_keyword(kalimat) == "reminder"


def test_perintah_catat_tidak_ikut_jadi_reminder():
    assert classify_intent_keyword("catat meeting besok jam 3") == "catat"


def test_parse_perintah_reminder_lengkap():
    data = parse_command("ingatkan saya 1 jam sebelum meeting", use_slm=False)
    assert data["aksi"] == "reminder"
    assert data["kegiatan"] == "meeting"
    assert data["lead_menit"] == 60


def test_nama_kegiatan_bersih_dari_kata_pengingat():
    data = parse_command(
        "ingatkan saya perihal meeting 1 jam sebelum mulai ya", use_slm=False
    )
    assert data["kegiatan"] == "meeting"


def test_reminder_butuh_kegiatan_atau_tanggal():
    from src.dialog.state_machine import check_missing_fields

    lengkap = {"aksi": "reminder", "kegiatan": "meeting", "lead_menit": 60}
    assert check_missing_fields(lengkap) == []

    tanpa_apa_apa = {"aksi": "reminder", "kegiatan": None, "tanggal": None, "lead_menit": 60}
    assert "kegiatan" in check_missing_fields(tanpa_apa_apa)

    tanpa_jeda = {"aksi": "reminder", "kegiatan": "meeting", "lead_menit": None}
    assert "lead_menit" in check_missing_fields(tanpa_jeda)


def test_jawaban_susulan_jeda_pengingat():
    from src.nlp.parser import merge_answer

    assert merge_answer({"lead_menit": None}, "lead_menit", "30 menit")["lead_menit"] == 30
    assert merge_answer({"lead_menit": None}, "lead_menit", "sehari sebelumnya")["lead_menit"] == 1440
    assert merge_answer({"lead_menit": None}, "lead_menit", "satu jam")["lead_menit"] == 60


# --- Loop reminder menghormati pengingat khusus --------------------------
def _event_dengan_pengingat(menit_dari_sekarang, menit_pengingat=None, eid="x"):
    from datetime import datetime as _dt, timedelta as _td

    ev = {
        "id": eid,
        "summary": "meeting",
        "start": {"dateTime": (_dt.now().astimezone() + _td(minutes=menit_dari_sekarang)).isoformat()},
    }
    if menit_pengingat is None:
        ev["reminders"] = {"useDefault": True}
    else:
        ev["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": menit_pengingat}],
        }
    return ev


def test_pengingat_khusus_dibaca_dari_event():
    from src.dialog.reminder import pengingat_khusus

    assert pengingat_khusus(_event_dengan_pengingat(30, 60)) == [60]
    assert pengingat_khusus(_event_dengan_pengingat(30)) == []


def test_pengingat_khusus_menggantikan_tier_default(monkeypatch):
    """User minta diingatkan sejam sebelum: jangan juga bunyi di menit 30/15/5."""
    from src.dialog import reminder

    # Acara 50 menit lagi: di luar tier default [30,15,5], tapi masuk pengingat 60 menit
    hasil = _jalankan_reminder([_event_dengan_pengingat(50, 60)], [30, 15, 5], monkeypatch)
    assert len(hasil) == 1

    # Acara 25 menit lagi dengan pengingat khusus 60 menit yang SUDAH terpakai:
    # tidak boleh bunyi lagi lewat tier default
    reminder._reminded.clear()
    hasil2 = _jalankan_reminder([_event_dengan_pengingat(25, 60)], [30, 15, 5], monkeypatch)
    assert len(hasil2) == 1     # bunyi sekali untuk tier 60
    lanjutan = []
    reminder.check_all_tiers(lanjutan.append, [30, 15, 5])
    assert lanjutan == []       # tidak ada susulan dari tier default


def test_event_tanpa_pengingat_khusus_pakai_tier_default(monkeypatch):
    hasil = _jalankan_reminder([_event_dengan_pengingat(50, None)], [30, 15, 5], monkeypatch)
    assert hasil == []          # 50 menit masih di luar tier default

    hasil2 = _jalankan_reminder([_event_dengan_pengingat(14, None)], [30, 15, 5], monkeypatch)
    assert len(hasil2) == 1


# =========================================================================
# Sprint 3.11 — slang Indonesia & Qwen3 yang keras kepala
# =========================================================================

@pytest.mark.parametrize("kalimat,harapan", [
    ("gue senggang ga besok", "saya kosong ga besok"),
    ("Hari ini saya free ga?", "hari ini saya kosong ga"),
    ("Hari ini saya 0 nggak?", "hari ini saya kosong nggak"),
    ("kalo udah selesai kabarin", "kalau sudah selesai kabarin"),
    ("ntar sore gua ada meeting", "nanti sore saya ada meeting"),
])
def test_slang_dinormalkan(kalimat, harapan):
    assert normalize(kalimat) == harapan


def test_jam_nol_tidak_ikut_jadi_kosong():
    """'jam 0' itu tengah malam, bukan 'jam kosong'."""
    assert "jam 0" in normalize("catat rapat jam 0 pagi")
    assert normalize("catat meeting jam 10:00") == "catat meeting jam 10:00"


def test_kosong_tidak_dianggap_angka_nol():
    """
    'kosong' pernah terdaftar sebagai kata angka, sehingga
    'hari ini saya kosong' berubah jadi 'hari ini saya 0'.
    """
    assert "kosong" in normalize("hari ini saya kosong nggak")


def test_konversi_angka_kata_tetap_jalan():
    assert normalize("tahun dua ribu dua puluh enam") == "tahun 2026"


# --- Pertanyaan ketersediaan ---------------------------------------------
@pytest.mark.parametrize("kalimat", [
    "hari ini saya free ga",
    "hari ini saya 0 nggak",
    "besok saya sibuk nggak",
    "minggu depan padat ga",
    "gue senggang ga besok",
    "sabtu saya bebas apa nggak",
])
def test_pertanyaan_ketersediaan_jadi_baca(kalimat):
    assert classify_intent_keyword(normalize(kalimat)) == "baca"


@pytest.mark.parametrize("kalimat", ["kosongin aja", "kosongkan saja", "lewati"])
def test_perintah_skip_bukan_pertanyaan_ketersediaan(kalimat):
    assert classify_intent_keyword(normalize(kalimat)) != "baca"


def test_pertanyaan_ketersediaan_ikut_tanggalnya():
    data = parse_command("besok saya sibuk nggak", use_slm=False)
    assert data["aksi"] == "baca"
    assert data["tanggal"] is not None


# --- Qwen3 menalar sebelum menjawab --------------------------------------
def test_kata_aksi_diambil_dari_ujung_bukan_awal():
    """
    Qwen3 sering menalar dulu ("the user is asking...") lalu menaruh
    kesimpulannya di ujung. Mengambil kata valid PERTAMA berarti menangkap
    kata yang kebetulan muncul di tengah penalaran.
    """
    import re as _re

    from src.nlp.slm_extractor import VALID_AKSI

    def ambil(raw):
        kv = [k for k in _re.findall(r"[a-z]+", raw.lower()) if k in VALID_AKSI or k == "lain"]
        return kv[-1] if kv else None

    assert ambil("the user wants to catat something, but actually they want baca") == "baca"
    assert ambil("baca") == "baca"
    assert ambil("okay, let's see. hmm") is None


@pytest.mark.parametrize("kalimat,jam", [
    ("nanti sore ada meeting jam 4", "16:00"),
    ("nanti malam saya ada acara jam 7", "19:00"),
    ("catat rapat besok jam 4 sore", "16:00"),
    ("jam 4 pagi", "04:00"),
    ("jam 4", "04:00"),                    # tanpa periode, jangan menebak
])
def test_periode_boleh_disebut_sebelum_jam(kalimat, jam):
    assert parse_time_id(kalimat) == jam


@pytest.mark.parametrize("kalimat", ["nanti sore ada meeting jam 4", "malam ini saya ada janji jam 8"])
def test_nanti_dan_malam_ini_berarti_hari_ini(kalimat):
    from datetime import datetime as _dt

    hasil = parse_date_id(kalimat, REF)
    assert hasil.date() == _dt(2026, 8, 29).date()


# =========================================================================
# Sprint 3.12 — kecepatan: jangan panggil SLM kalau sudah pasti sia-sia
# =========================================================================

@pytest.mark.parametrize("kalimat", [
    "hapus jadwal tersebut",
    "hapus jadwal itu",
    "buat jadwal untuk besok",
    "cek jadwal saya besok",
])
def test_kalimat_tanpa_kandidat_nama(kalimat):
    from src.nlp.slm_extractor import _tidak_ada_kandidat_nama

    assert _tidak_ada_kandidat_nama(kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "hapus jadwal rapat divisi",
    "ingatkan saya 1 jam sebelum meeting",
])
def test_kalimat_punya_kandidat_nama(kalimat):
    from src.nlp.slm_extractor import _tidak_ada_kandidat_nama

    assert _tidak_ada_kandidat_nama(kalimat) is False


def test_slm_dilewati_kalau_tidak_ada_nama():
    """Tanpa Ollama sekalipun harus langsung selesai, bukan menunggu timeout."""
    from src.nlp.slm_extractor import extract_entities

    hasil = extract_entities("hapus jadwal tersebut")
    assert hasil["kegiatan"] is None
    assert hasil["source"] == "regex-kosong"


def test_perintah_rujukan_tidak_manggil_slm():
    import time

    mulai = time.time()
    data = parse_command("hapus jadwal tersebut", use_slm=True)
    durasi = time.time() - mulai

    assert data["aksi"] == "hapus"
    assert data["kegiatan"] is None
    assert durasi < 1.0, "parsing perintah rujukan harus instan, tanpa panggilan SLM"


# --- "hari ini" bukan kata rujukan ---------------------------------------
@pytest.mark.parametrize("kalimat", [
    "saya nggak jadi meeting hari ini bisa di reschedule nggak",
    "reschedule jadwal meeting saya hari ini menjadi tanggal 31",
    "hapus jadwal hari itu",
    "cek jadwal minggu ini",
])
def test_keterangan_waktu_bukan_rujukan(kalimat):
    from src.dialog.context import mengandung_rujukan

    assert mengandung_rujukan(kalimat) is False


@pytest.mark.parametrize("kalimat", [
    "hapus jadwal tersebut",
    "meeting itu reschedule ke besok",
    "hapus yang tadi",
])
def test_rujukan_asli_tetap_terdeteksi(kalimat):
    from src.dialog.context import mengandung_rujukan

    assert mengandung_rujukan(kalimat) is True


# =========================================================================
# Sprint 3.13 — nama panggilan, noise, jeda, kecepatan bicara
# =========================================================================

@pytest.mark.parametrize("kalimat,nama", [
    ("panggil saya Dzaky", "Dzaky"),
    ("panggil aku dengan nama Kak Dzaky", "Kak Dzaky"),
    ("nama saya Maulana Dzaky Putra", "Maulana Dzaky Putra"),
    ("ganti panggilan jadi Bos Besar", "Bos Besar"),
    ("sebut saya kapten", "Kapten"),
])
def test_deteksi_ganti_nama(kalimat, nama):
    from src.utils.user_settings import deteksi_ganti_nama

    assert deteksi_ganti_nama(kalimat) == nama


@pytest.mark.parametrize("kalimat", [
    "catat jadwal meeting besok",
    "hapus jadwal tersebut",
    "hari ini saya kosong nggak",
])
def test_perintah_biasa_bukan_ganti_nama(kalimat):
    from src.utils.user_settings import deteksi_ganti_nama

    assert deteksi_ganti_nama(kalimat) is None


def test_nama_dibersihkan_dari_kata_pengisi():
    from src.utils.user_settings import bersihkan_nama

    assert bersihkan_nama("saya dzaky aja dong") == "Dzaky"
    assert bersihkan_nama("dzaky!!!") == "Dzaky"
    assert bersihkan_nama("   ") is None


def test_nama_panggilan_tersimpan(tmp_path, monkeypatch):
    from src.utils import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_PATH", str(tmp_path / "s.json"))

    assert user_settings.get_nama_panggilan() == "Bos"
    user_settings.set_nama_panggilan("Dzaky")
    assert user_settings.get_nama_panggilan() == "Dzaky"
    # Bertahan setelah "restart" — dibaca ulang dari file
    assert user_settings._load()["nama_panggilan"] == "Dzaky"


def test_sapaan_memakai_nama_baru():
    from src.utils.greeting import get_greeting

    assert "Dzaky" in get_greeting("Dzaky")


def test_substitusi_nama_di_kalimat_akira():
    """AKIRA menulis semua kalimat dengan 'Bos'; penggantinya di satu tempat."""
    import re as _re

    kalimat = "Tidak ada kegiatan pada 30 Agustus 2026, Bos."
    assert _re.sub(r"\bBos\b", "Dzaky", kalimat).endswith("Dzaky.")


# --- Penyaring noise ------------------------------------------------------
def _frame(amplitudo):
    import array
    import math

    return array.array("h", [int(amplitudo * math.sin(i / 5)) for i in range(480)]).tobytes()


def _muat_recorder_tanpa_audio():
    """
    Ambil bagian murni-hitungan dari recorder.py tanpa mengimpor sounddevice.
    Perlu karena mesin tanpa PortAudio (CI, container) tidak bisa mengimpor
    modul audio, padahal logika RMS-nya tetap layak diuji.
    """
    import array
    import math

    src = open("src/audio/recorder.py", encoding="utf-8").read()
    ns = {"array": array, "math": math}
    exec(src[src.index("RMS_AMBANG ="):src.index("def record_with_vad")], ns)
    return ns


def test_hitung_rms_membedakan_noise_dan_suara():
    ns = _muat_recorder_tanpa_audio()
    hitung_rms, ambang = ns["hitung_rms"], ns["RMS_AMBANG"]

    assert hitung_rms(_frame(0)) == 0
    assert hitung_rms(_frame(120)) < ambang      # noise latar
    assert hitung_rms(_frame(6000)) > ambang     # suara sungguhan


def test_ambang_noise_masuk_akal():
    ns = _muat_recorder_tanpa_audio()
    assert 100 < ns["RMS_AMBANG"] < 2000


def test_rekaman_terlalu_sedikit_suara_dibuang():
    """Ambang minimal frame bicara harus ada, supaya batuk/ketukan tidak diproses."""
    ns = _muat_recorder_tanpa_audio()
    assert 3 <= ns["MIN_FRAME_BICARA"] <= 20


def test_jeda_diam_lebih_pendek():
    """max_silence_frames default harus di bawah 20 frame (~0,6 detik)."""
    import re as _re

    src = open("src/audio/recorder.py", encoding="utf-8").read()
    m = _re.search(r"max_silence_frames:\s*int\s*=\s*(\d+)", src)
    assert m and int(m.group(1)) <= 20


def test_config_punya_ambang_noise():
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    assert "rms_ambang" in cfg["audio"]
    assert cfg["audio"]["max_silence_frames"] <= 20


def test_kecepatan_bicara_cepat_tapi_wajar():
    from src.tts.speaker import EDGE_RATE

    persen = int(EDGE_RATE.strip("%+"))
    assert 10 <= persen <= 25, "terlalu lambat terasa lelet, terlalu cepat jadi tidak jelas"


# =========================================================================
# Sprint 3.14 — celah yang ketahuan saat menyusun daftar perintah
# =========================================================================

def test_rentang_tanpa_kata_perintah_jadi_baca():
    """'jadwal 3 hari ke depan' tidak punya kata kerja, tapi maksudnya jelas."""
    data = parse_command("jadwal 3 hari ke depan", use_slm=False)
    assert data["aksi"] == "baca"
    assert data["label_rentang"] == "3 hari ke depan"


def test_kata_kerja_membuat_tidak_kebawa_ke_nama():
    data = parse_command("ciptakan jadwal rapat divisi hari senin jam 9", use_slm=False)
    assert data["kegiatan"] == "rapat divisi"


def test_sebelumnya_bukan_kata_rujukan():
    """'30 menit sebelumnya' itu jeda pengingat, bukan rujukan ke event."""
    from src.dialog.context import mengandung_rujukan

    assert mengandung_rujukan("pasang pengingat buat rapat 30 menit sebelumnya") is False

    data = parse_command("pasang pengingat buat rapat 30 menit sebelumnya", use_slm=False)
    assert data["aksi"] == "reminder"
    assert data["kegiatan"] == "rapat"
    assert data["lead_menit"] == 30


# =========================================================================
# Sprint 3.14 — perintah rahasia self destruct
# =========================================================================

def test_kata_kode_harus_diucapkan_utuh():
    from src.dialog.self_destruct import cocok_kata_kode

    assert cocok_kata_kode("MERAK", "MERAK") is True
    assert cocok_kata_kode("merak", "MERAK") is True
    assert cocok_kata_kode("kodenya MERAK.", "MERAK") is True
    assert cocok_kata_kode("GARUDA", "MERAK") is False
    assert cocok_kata_kode("batal", "MERAK") is False
    assert cocok_kata_kode("", "MERAK") is False


def test_kata_kode_tidak_cocok_sebagian():
    """'MERA' atau 'MERAKAN' tidak boleh lolos sebagai 'MERAK'."""
    from src.dialog.self_destruct import cocok_kata_kode

    assert cocok_kata_kode("mera", "MERAK") is False
    assert cocok_kata_kode("merakan", "MERAK") is False


def test_kata_kode_acak_dari_daftar():
    from src.dialog.self_destruct import KATA_KODE, pilih_kata_kode

    assert pilih_kata_kode() in KATA_KODE
    assert len(KATA_KODE) >= 3


def test_tingkat_data_tidak_menyentuh_model():
    """Tingkat default HARUS aman: model wake word hasil training tidak boleh ikut."""
    from src.dialog.self_destruct import daftar_target

    target = [str(p) for p in daftar_target("data")]
    assert not any("models" in t for t in target)
    assert not any(t.endswith(".onnx") for t in target)


def test_tingkat_model_menyertakan_folder_models():
    from src.dialog.self_destruct import akar_proyek, daftar_target

    if not (akar_proyek() / "models").exists():
        pytest.skip("folder models tidak ada di lingkungan ini")
    assert any("models" in str(p) for p in daftar_target("model"))


def test_tingkat_total_adalah_akar_proyek():
    from src.dialog.self_destruct import akar_proyek, daftar_target

    assert daftar_target("total") == [akar_proyek()]


def test_hapus_sekarang_menolak_tingkat_total():
    """Tingkat total wajib lewat penjadwalan, bukan penghapusan langsung."""
    from src.dialog.self_destruct import hapus_sekarang

    with pytest.raises(ValueError):
        hapus_sekarang("total")


def test_ringkasan_menyebutkan_apa_yang_hilang():
    from src.dialog.self_destruct import ringkas_target

    assert "kode program" in ringkas_target("total")
    assert "wake word" in ringkas_target("model")
    assert "token" in ringkas_target("data")


def test_cadangan_melewati_venv(tmp_path, monkeypatch):
    """Cadangan tidak boleh menyertakan venv — besar dan bisa dibuat ulang."""
    import zipfile

    from src.dialog import self_destruct

    proyek = tmp_path / "akira"
    (proyek / "src").mkdir(parents=True)
    (proyek / "venv" / "Lib").mkdir(parents=True)
    (proyek / "src" / "app.py").write_text("kode")
    (proyek / "venv" / "Lib" / "besar.pyd").write_text("x" * 100)

    monkeypatch.setattr(self_destruct, "akar_proyek", lambda: proyek)
    hasil = self_destruct.buat_cadangan(tmp_path)

    assert hasil is not None
    with zipfile.ZipFile(hasil) as z:
        isi = z.namelist()
    assert any("app.py" in n for n in isi)
    assert not any("venv" in n for n in isi)


def test_config_default_tingkat_aman():
    """Default di settings.yaml harus 'data' dan backup menyala."""
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    assert cfg["self_destruct"]["tingkat"] == "data"
    assert cfg["self_destruct"]["backup"] is True


def test_skrip_hapus_diputus_dari_pipe_induk():
    """
    Skrip penghapus TIDAK boleh mewarisi stdin/stdout/stderr induknya.
    Kalau mewarisi, induk menunggu skrip selesai sementara skrip menunggu
    induk mati — saling menunggu, AKIRA menggantung selamanya.
    """
    src = open("src/dialog/self_destruct.py", encoding="utf-8").read()
    blok = src[src.index("def jadwalkan_hapus_total"):]
    assert "stdin=subprocess.DEVNULL" in blok
    assert "stdout=subprocess.DEVNULL" in blok
    assert "stderr=subprocess.DEVNULL" in blok


def test_skrip_hapus_menunggu_pid_lalu_hapus_dirinya():
    """Skrip harus menunggu PID mati, hapus folder, lalu hapus dirinya sendiri."""
    import os
    import re as _re

    src = open("src/dialog/self_destruct.py", encoding="utf-8").read()
    blok = src[src.index("def jadwalkan_hapus_total"):src.index("def ringkas_target")]

    # Windows
    assert "tasklist" in blok and "rmdir /s /q" in blok and 'del "%~f0"' in blok
    # POSIX
    assert "kill -0" in blok and "rm -rf" in blok and 'rm -- "$0"' in blok


def test_backup_bisa_dimatikan_sepenuhnya():
    """Self destroy sungguhan = tingkat total + backup false, tanpa sisa apa pun."""
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    assert "backup" in cfg["self_destruct"]
    assert isinstance(cfg["self_destruct"]["backup"], bool)

    # Peringatan berbeda saat cadangan dimatikan
    app_src = open("src/app.py", encoding="utf-8").read()
    assert "Tidak ada cadangan yang dibuat" in app_src


# --- Dua wake word yang sama-sama diawali "AKIRA" ------------------------
def _pemenang(prediksi, threshold=0.6, per_model=None):
    """Tiru logika pemilihan model di detector, tanpa perlu mic."""
    per_model = per_model or {}

    def ambang(n):
        for k, v in per_model.items():
            if k in n:
                return v
        return threshold

    nama = list(prediksi)
    terbaik = max(nama, key=lambda n: prediksi[n] - ambang(n))
    return terbaik if prediksi[terbaik] > ambang(terbaik) else None


AMBANG_KHUSUS = {"akira_destroy": 0.8}


def test_wake_up_menang_saat_diucapkan():
    hasil = _pemenang(
        {"akira_wake_up": 0.95, "akira_destroy": 0.55}, per_model=AMBANG_KHUSUS
    )
    assert hasil == "akira_wake_up"


def test_destroy_menang_saat_diucapkan():
    hasil = _pemenang(
        {"akira_wake_up": 0.40, "akira_destroy": 0.92}, per_model=AMBANG_KHUSUS
    )
    assert hasil == "akira_destroy"


def test_kebocoran_kata_akira_tidak_memicu_destroy():
    """
    Kedua frasa diawali "AKIRA", jadi "akira wake up" bisa menaikkan skor
    model destroy sampai 0.72 — di atas ambang biasa 0.6, tapi di bawah
    ambang khususnya 0.8. Yang menang harus tetap wake_up.
    """
    hasil = _pemenang(
        {"akira_wake_up": 0.88, "akira_destroy": 0.72}, per_model=AMBANG_KHUSUS
    )
    assert hasil == "akira_wake_up"


def test_noise_tidak_memicu_apa_pun():
    assert _pemenang({"akira_wake_up": 0.20, "akira_destroy": 0.15}) is None


def test_ambang_destroy_lebih_tinggi_dari_wake_up():
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    assert cfg["self_destruct"]["threshold"] > cfg["wakeword"]["threshold"]


def test_detector_menerima_ambang_per_model():
    import inspect

    src = open("src/wakeword/detector.py", encoding="utf-8").read()
    assert "threshold_per_model" in src
    # Model yang tidak disebut memakai ambang umum
    assert "return threshold" in src


# =========================================================================
# Sprint 3.15 — mode ambient, alarm/timer, jam ambigu, input beruntun
# =========================================================================

# --- Jam ambigu: pagi atau malam? ----------------------------------------
@pytest.mark.parametrize("kalimat,ambigu", [
    ("besok aku ada meeting jam 10", True),
    ("jam 10 pagi", False),
    ("jam 8 malam", False),
    ("jam 22", False),
    ("jam 14:30", False),
    ("jam 12", False),
    ("catat rapat besok", False),
])
def test_deteksi_jam_ambigu(kalimat, ambigu):
    from src.nlp.date_time_parser import jam_ambigu

    assert jam_ambigu(kalimat) is ambigu


def test_perjelas_periode_mengubah_jam():
    from src.dialog.state_machine import perjelas_periode, perlu_perjelas_jam

    data = {"aksi": "catat", "jam": "10:00", "teks_asli": "meeting jam 10"}
    assert perlu_perjelas_jam(data) is True

    assert perjelas_periode(dict(data), "malam")["jam"] == "22:00"
    assert perjelas_periode(dict(data), "pagi")["jam"] == "10:00"


def test_tidak_tanya_dua_kali():
    from src.dialog.state_machine import perjelas_periode, perlu_perjelas_jam

    data = perjelas_periode(
        {"aksi": "catat", "jam": "10:00", "teks_asli": "meeting jam 10"}, "malam"
    )
    assert perlu_perjelas_jam(data) is False


def test_jam_jelas_tidak_ditanya():
    from src.dialog.state_machine import perlu_perjelas_jam

    data = {"aksi": "catat", "jam": "10:00", "teks_asli": "meeting jam 10 pagi"}
    assert perlu_perjelas_jam(data) is False


# --- Timer & alarm --------------------------------------------------------
@pytest.mark.parametrize("kalimat,detik", [
    ("timer 30 detik", 30),
    ("ingetin 5 menit lagi", 300),
    ("hitung mundur 2 menit", 120),
    ("dua jam lagi ingatkan saya", 7200),
])
def test_permintaan_timer(kalimat, detik):
    from src.dialog.alarm import is_permintaan_timer, parse_durasi

    assert is_permintaan_timer(kalimat) is True
    assert parse_durasi(kalimat) == detik


@pytest.mark.parametrize("kalimat", [
    "rapat 30 menit",                      # durasi acara, bukan timer
    "ingatkan 1 jam sebelum meeting",      # pengingat event kalender
    "catat meeting besok",
])
def test_bukan_permintaan_timer(kalimat):
    from src.dialog.alarm import is_permintaan_timer

    assert is_permintaan_timer(kalimat) is False


@pytest.mark.parametrize("kalimat", [
    "ingetin nanti jam 3 sore",
    "alarm jam 5 pagi",
    "bangunkan saya jam 6",
])
def test_permintaan_alarm(kalimat):
    from src.dialog.alarm import is_permintaan_alarm

    assert is_permintaan_alarm(kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "ingatkan 1 jam sebelum meeting",      # itu pengingat event
    "timer 30 detik",                      # itu timer
    "catat meeting besok jam 3",
])
def test_bukan_permintaan_alarm(kalimat):
    from src.dialog.alarm import is_permintaan_alarm

    assert is_permintaan_alarm(kalimat) is False


def test_timer_berbunyi_saat_waktunya():
    from datetime import datetime, timedelta

    from src.dialog import alarm

    alarm.batalkan_semua()
    diucapkan = []
    alarm.tambah_timer(60, "minum obat", say_fn=diucapkan.append)

    assert alarm.cek_sekali(datetime.now()) == []          # belum waktunya
    alarm.cek_sekali(datetime.now() + timedelta(seconds=61))
    assert len(diucapkan) == 1
    assert "minum obat" in diucapkan[0]
    alarm.batalkan_semua()


def test_alarm_jam_lewat_dipasang_besok():
    from datetime import datetime

    from src.dialog import alarm

    alarm.batalkan_semua()
    a = alarm.tambah_alarm("00:01")     # hampir pasti sudah lewat
    assert a["waktu"] > datetime.now()
    alarm.batalkan_semua()


def test_timer_tidak_berbunyi_dua_kali():
    from datetime import datetime, timedelta

    from src.dialog import alarm

    alarm.batalkan_semua()
    diucapkan = []
    alarm.tambah_timer(10, None, say_fn=diucapkan.append)

    nanti = datetime.now() + timedelta(seconds=20)
    alarm.cek_sekali(nanti)
    alarm.cek_sekali(nanti)
    assert len(diucapkan) == 1
    alarm.batalkan_semua()


@pytest.mark.parametrize("detik,ucapan", [
    (30, "30 detik"), (60, "satu menit"), (300, "5 menit"), (7200, "2 jam"),
])
def test_ucapkan_durasi(detik, ucapan):
    from src.dialog.alarm import ucapkan_durasi

    assert ucapkan_durasi(detik) == ucapan


# --- Mode ambient ---------------------------------------------------------
def _muat_helper_app(awal, akhir):
    """
    Muat sepotong app.py tanpa mengimpor modul penuh (yang butuh audio).

    `logger` ikut disediakan: di app.py ia ada di lingkup modul, dan fungsi
    yang dipotong ke sini memakainya untuk mencatat kegagalan.
    """
    import re as _re

    from loguru import logger as _logger

    src = open("src/app.py", encoding="utf-8").read()
    ns = {"re": _re, "logger": _logger}
    exec(src[src.index(awal):src.index(akhir)], ns)
    return ns


@pytest.mark.parametrize("kalimat,disapa", [
    ("Akira besok aku ada meeting jam 10 tambahkan ya", True),
    ("Akhira tolong catat rapat", True),          # toleran salah dengar
    ("besok aku ada meeting", False),
    ("tolong catat rapat", False),
])
def test_deteksi_disapa_akira(kalimat, disapa):
    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["disapa_akira"](kalimat) is disapa


def test_config_ambient_ada():
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    assert cfg["ambient"]["enabled"] is True
    assert cfg["ambient"]["timeout_menit"] > 0


# --- Input beruntun -------------------------------------------------------
@pytest.mark.parametrize("kalimat,hasil", [
    ("eh selama sebulan aku ada beberapa kegiatan, coba kamu tambahin", True),
    ("tambahin beberapa jadwal dong", True),
    ("cek beberapa jadwal saya", False),      # membaca, bukan mencatat
    ("catat meeting besok jam 3", False),     # cuma satu
])
def test_deteksi_minta_banyak_jadwal(kalimat, hasil):
    ns = _muat_helper_app("MINTA_BANYAK =", "def _lanjut_tambah_jadwal")
    assert ns["_minta_banyak_jadwal"](kalimat) is hasil


# =========================================================================
# Sprint 3.16 — koreksi saat konfirmasi, tanpa mengulang dari awal
# =========================================================================

DATA_CONTOH = {"aksi": "catat", "kegiatan": "berenang",
               "tanggal": "2026-09-02", "jam": "12:00"}


@pytest.mark.parametrize("kalimat,field,nilai", [
    ("jamnya jadi 3 sore", "jam", "15:00"),
    # Tahun eksplisit supaya tidak bergantung tanggal dijalankannya test
    ("tanggalnya 3 september 2027", "tanggal", "2027-09-03"),
    ("kegiatannya futsal", "kegiatan", "futsal"),
    ("bukan berenang, tapi futsal", "kegiatan", "futsal"),
    ("selesainya jam 5 sore", "jam_selesai", "17:00"),
    ("sampai jam 11", "jam_selesai", "11:00"),
    ("catatannya bawa handuk", "deskripsi", "bawa handuk"),
])
def test_koreksi_rule_based(kalimat, field, nilai):
    from src.nlp.correction import parse_koreksi

    hasil = parse_koreksi(dict(DATA_CONTOH), kalimat, use_llm=False)
    assert hasil.get(field) == nilai


def test_mulai_vs_selesai_dibedakan():
    """'selesainya jam 5' dan 'mulainya jam 5' menyebut kata 'jam' dua-duanya."""
    from src.nlp.correction import parse_koreksi

    assert "jam_selesai" in parse_koreksi(dict(DATA_CONTOH), "selesainya jam 5 sore", use_llm=False)
    assert "jam" in parse_koreksi(dict(DATA_CONTOH), "mulainya jam 5 sore", use_llm=False)


def test_jawaban_setuju_bukan_koreksi():
    from src.nlp.correction import parse_koreksi

    for kalimat in ["sudah benar", "ya", "oke"]:
        assert parse_koreksi(dict(DATA_CONTOH), kalimat, use_llm=False) == {}


def test_validasi_menolak_nilai_ngawur():
    """LLM boleh menebak, tapi nilai tidak valid harus ditolak sebelum dipakai."""
    from src.nlp.correction import _valid

    assert _valid("jam", "15:00") is True
    assert _valid("jam", "25:00") is False
    assert _valid("jam", "sore") is False
    assert _valid("tanggal", "2026-09-05") is True
    assert _valid("tanggal", "2026-13-45") is False
    assert _valid("tanggal", "besok") is False
    assert _valid("kegiatan", "futsal") is True
    assert _valid("kegiatan", "") is False
    assert _valid("kegiatan", "x" * 200) is False


def test_ucapkan_perubahan():
    from src.nlp.correction import ucapkan_perubahan

    assert ucapkan_perubahan({"kegiatan": "futsal"}) == "kegiatannya jadi futsal"
    gabung = ucapkan_perubahan({"kegiatan": "futsal", "jam": "15:00"})
    assert "dan" in gabung


# --- Alur konfirmasi penuh ------------------------------------------------
def _jalankan_konfirmasi(jawaban, data):
    from src.dialog.confirmation import konfirmasi_dengan_koreksi

    antre = iter(jawaban)
    log = []
    hasil = konfirmasi_dengan_koreksi(
        data,
        lambda: f"{data['kegiatan']}, {data['tanggal']}, jam {data['jam']}. Benar?",
        ask_fn=log.append,
        listen_fn=lambda: next(antre, ""),
        use_llm=False,
    )
    return hasil, log


def test_koreksi_langsung_lalu_setuju():
    data = dict(DATA_CONTOH)
    ok, log = _jalankan_konfirmasi(["kegiatannya futsal", "ya"], data)
    assert ok is True
    assert data["kegiatan"] == "futsal"
    assert "futsal" in log[-1]      # ringkasan dibacakan ulang dengan nilai baru


def test_bilang_tidak_lalu_dikoreksi_bukan_dibatalkan():
    """'Tidak' TIDAK langsung membatalkan — AKIRA tanya bagian mana yang salah."""
    data = dict(DATA_CONTOH)
    ok, log = _jalankan_konfirmasi(["tidak", "jamnya jadi 3 sore", "ya"], data)
    assert ok is True
    assert data["jam"] == "15:00"
    assert data["kegiatan"] == "berenang"     # field lain tidak ikut berubah
    assert any("Bagian mana" in l for l in log)


def test_tetap_bisa_dibatalkan():
    data = dict(DATA_CONTOH)
    ok, _ = _jalankan_konfirmasi(["tidak", "batalkan saja"], data)
    assert ok is False


def test_diam_setelah_ditanya_berarti_batal():
    data = dict(DATA_CONTOH)
    ok, _ = _jalankan_konfirmasi(["tidak", ""], data)
    assert ok is False


def test_dua_koreksi_berturut_turut():
    data = dict(DATA_CONTOH)
    ok, _ = _jalankan_konfirmasi(
        ["bukan berenang, tapi futsal", "tanggalnya 5 september 2027", "ya"], data
    )
    assert ok is True
    assert data["kegiatan"] == "futsal"
    assert data["tanggal"] == "2027-09-05"


def test_koreksi_menang_atas_kata_bukan():
    """'bukan, kegiatannya futsal' mengandung penolakan TAPI berisi perbaikan."""
    data = dict(DATA_CONTOH)
    ok, log = _jalankan_konfirmasi(["bukan, kegiatannya futsal", "ya"], data)
    assert ok is True
    assert data["kegiatan"] == "futsal"
    assert not any("Bagian mana" in l for l in log)


# =========================================================================
# Sprint 3.17 — auto-start
# =========================================================================

def test_skrip_autostart_ada():
    import os

    for f in [
        "scripts/akira_start.bat",
        "scripts/akira_start_hidden.vbs",
        "scripts/pasang_autostart.ps1",
        "scripts/hapus_autostart.ps1",
    ]:
        assert os.path.exists(f), f"{f} tidak ada"


def test_bat_tidak_hardcode_path():
    """Folder proyek harus boleh dipindah tanpa mengedit skrip."""
    isi = open("scripts/akira_start.bat", encoding="utf-8").read()
    assert "%~dp0.." in isi
    assert "C:\\Users" not in isi


def _tanpa_komentar(path: str, penanda: tuple) -> str:
    """
    Buang baris komentar sebelum memeriksa isi skrip.
    Tanpa ini, kata yang justru DILARANG muncul di baris perintah bisa lolos
    hanya karena ditulis di komentar penjelasan.
    """
    baris = []
    for b in open(path, encoding="utf-8").read().splitlines():
        if b.strip().lower().startswith(penanda):
            continue
        baris.append(b)
    return "\n".join(baris)


def test_bat_pakai_python_venv_langsung():
    """Lebih andal untuk Task Scheduler daripada memanggil 'activate'."""
    perintah = _tanpa_komentar("scripts/akira_start.bat", ("rem", "::"))
    assert "venv\\Scripts\\python.exe" in perintah
    assert "activate" not in perintah


def test_bat_menangani_venv_hilang():
    isi = open("scripts/akira_start.bat", encoding="utf-8").read()
    assert "if not exist" in isi and "venv tidak ditemukan" in isi


def test_task_jalan_sebagai_user_interaktif():
    """
    'Run whether user is logged on or not' memutus akses mikrofon dan speaker.
    Pengaturannya harus tetap Interactive.
    """
    perintah = _tanpa_komentar("scripts/pasang_autostart.ps1", ("#",))
    assert "LogonType Interactive" in perintah
    assert "RunLevel Limited" in perintah
    assert "RunLevel Highest" not in perintah


def test_task_punya_jeda_setelah_login():
    isi = open("scripts/pasang_autostart.ps1", encoding="utf-8").read()
    assert "Delay" in isi and "PT1M" in isi


def test_task_menunjuk_ke_vbs_bukan_bat():
    """Kalau menunjuk langsung ke .bat, jendela hitam akan muncul tiap login."""
    isi = open("scripts/pasang_autostart.ps1", encoding="utf-8").read()
    assert "akira_start_hidden.vbs" in isi
    assert "wscript.exe" in isi


def test_vbs_menyembunyikan_jendela():
    isi = open("scripts/akira_start_hidden.vbs", encoding="utf-8").read()
    # Argumen kedua 0 = jendela tersembunyi
    assert ", 0, False" in isi


def test_uninstaller_tidak_menghapus_data():
    isi = open("scripts/hapus_autostart.ps1", encoding="utf-8").read()
    assert "Unregister-ScheduledTask" in isi
    for berbahaya in ("Remove-Item", "rmdir", "del "):
        assert berbahaya not in isi


# =========================================================================
# Sprint 3.18 — salah dengar "setelkan", batal di tengah, "akhirnya"
# =========================================================================

@pytest.mark.parametrize("kalimat,harapan", [
    ("Setelah pengingat untuk 30 minit lagi ya", "setel pengingat untuk 30 menit lagi ya"),
    ("setelkan pengingat 30 menit lagi", "setel pengingat 30 menit lagi"),
    ("setelahkan alarm jam 5", "setel alarm jam 5"),
])
def test_salah_dengar_setelkan_diperbaiki(kalimat, harapan):
    assert normalize(kalimat) == harapan


def test_setel_pengingat_jadi_timer():
    """'setel pengingat 30 menit lagi' itu timer, bukan pengingat event."""
    from src.dialog.alarm import is_permintaan_timer, parse_durasi

    bersih = normalize("Setelah pengingat untuk 30 minit lagi ya")
    assert is_permintaan_timer(bersih) is True
    assert parse_durasi(bersih) == 1800


def test_kata_perintah_pengingat_tidak_jadi_nama_kegiatan():
    """Dulu jadi kegiatan 'setelah minit' — nama yang tidak pernah cocok."""
    data = parse_command("Setelah pengingat untuk 30 minit lagi ya", use_slm=False)
    assert data["kegiatan"] is None


# --- Batal di tengah slot filling ----------------------------------------
@pytest.mark.parametrize("jawaban", [
    "Batalkan deh.", "batal", "gajadi", "udahlah", "nggak jadi", "lupakan",
])
def test_minta_batal_dikenali(jawaban):
    from src.dialog.state_machine import minta_batal

    assert minta_batal(jawaban) is True


@pytest.mark.parametrize("jawaban", [
    "batalkan jadwal rapat besok",   # ini PERINTAH hapus, bukan pembatalan
    "batalkan meeting hari ini",
    "30 menit sebelum",
    "jam 3 sore",
])
def test_bukan_permintaan_batal(jawaban):
    from src.dialog.state_machine import minta_batal

    assert minta_batal(jawaban) is False


def test_slot_filling_berhenti_saat_dibatalkan():
    """
    Dulu 'batalkan deh' dianggap jawaban gagal parse, dan AKIRA mengulang
    pertanyaan yang sama sampai batas percobaan habis.
    """
    from src.dialog.state_machine import run_slot_filling
    from src.nlp.parser import merge_answer

    data = {"aksi": "catat", "kegiatan": "rapat", "tanggal": "2026-09-01", "jam": None}
    diucapkan = []
    hasil = run_slot_filling(
        data,
        ask_fn=diucapkan.append,
        listen_fn=lambda: "batalkan deh",
        merge_fn=merge_answer,
    )

    assert hasil is None
    assert any("batalkan" in u.lower() for u in diucapkan)
    assert len(diucapkan) <= 2, "tidak boleh mengulang pertanyaan setelah dibatalkan"


def test_slot_filling_normal_tetap_jalan():
    from src.dialog.state_machine import run_slot_filling
    from src.nlp.parser import merge_answer

    data = {"aksi": "catat", "kegiatan": "rapat", "tanggal": "2026-09-01", "jam": None}
    hasil = run_slot_filling(
        data, ask_fn=lambda q: None, listen_fn=lambda: "jam 9 pagi", merge_fn=merge_answer
    )
    assert hasil is not None
    assert hasil["jam"] == "09:00"


# --- "akira" terdengar jadi "akhirnya" -----------------------------------
def _muat_pemicu_ambient():
    return _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")


@pytest.mark.parametrize("kalimat", [
    "Akhirnya, coba bacakan jadwal saya.",
    "Akhirnya cuma bacakan jadwal saya.",
    "Akira besok aku ada meeting jam 10 tambahkan ya",
    "Akira sekarang jam berapa",
    "akhira tolong hapus jadwal rapat",
])
def test_perintah_untuk_akira_dikenali(kalimat):
    ns = _muat_pemicu_ambient()
    assert ns["perintah_untuk_akira"](kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "akhirnya selesai juga tugasnya",     # obrolan biasa
    "akhirnya dia dateng",
    "bacakan jadwal saya",                # tidak menyebut AKIRA
    "besok aku ada meeting",
])
def test_obrolan_biasa_tidak_membangunkan(kalimat):
    ns = _muat_pemicu_ambient()
    assert ns["perintah_untuk_akira"](kalimat) is False


# =========================================================================
# Sprint 3.19 — banyak tanggal, "617 hari lagi", transkripsi macet
# =========================================================================

def test_beberapa_tanggal_dalam_satu_kalimat():
    """Dulu hanya tanggal PERTAMA yang tersimpan, dua sisanya hilang diam-diam."""
    data = parse_command(
        "Saya bakal ada jadwal tanggal 9, tanggal 10 dan tanggal 11 itu buat meeting.",
        use_slm=False,
    )
    assert len(data["tanggal_lain"]) == 3
    assert data["tanggal_lain"][0].endswith("-09")
    assert data["tanggal_lain"][2].endswith("-11")


def test_jam_tidak_terbaca_sebagai_tanggal_kedua():
    """'tanggal 5 jam 9' itu SATU tanggal — angka jam jangan ikut terhitung."""
    data = parse_command("catat meeting tanggal 5 jam 9", use_slm=False)
    assert data["tanggal_lain"] == []


def test_tahun_tidak_terbaca_sebagai_tanggal():
    data = parse_command("cek jadwal 17 november 2026", use_slm=False)
    assert data["tanggal_lain"] == []


def test_multi_tanggal_dengan_nama_bulan():
    from datetime import datetime as _dt

    from src.nlp.date_time_parser import parse_multi_dates

    hasil = parse_multi_dates("catat rapat tanggal 3 dan 4 oktober", _dt(2026, 9, 1))
    assert hasil == ["2026-10-03", "2026-10-04"]


def test_satu_tanggal_bukan_multi():
    from datetime import datetime as _dt

    from src.nlp.date_time_parser import parse_multi_dates

    assert parse_multi_dates("catat rapat tanggal 5", _dt(2026, 9, 1)) == []


def test_ringkasan_menyebut_semua_tanggal():
    from src.dialog.state_machine import build_ringkasan

    pesan = build_ringkasan({
        "aksi": "catat", "kegiatan": "meeting", "tanggal": "2026-09-09",
        "jam": "09:00", "tanggal_lain": ["2026-09-09", "2026-09-10", "2026-09-11"],
    })
    for tanggal in ("9 September", "10 September", "11 September"):
        assert tanggal in pesan


def test_catat_banyak_tanggal_membuat_semua():
    """Satu event per tanggal, dan kegagalan satu tanggal tidak membatalkan sisanya."""
    import sys

    sys.path.insert(0, ".")
    from src.dialog.context import KonteksSesi

    src = open("src/app.py", encoding="utf-8").read()
    ns = {"logger": __import__("loguru").logger}
    awal = src.index("def _catat_banyak_tanggal")
    exec(src[awal:src.index("\ndef ", awal + 10)], ns)

    dibuat = []

    def execute_palsu(d):
        dibuat.append(d["tanggal"])
        if d["tanggal"].endswith("-10"):
            return {"success": False, "message": "gagal"}
        return {"success": True, "message": "ok", "data": {"summary": d["kegiatan"]}}

    diucapkan = []
    data = {
        "aksi": "catat", "kegiatan": "meeting", "jam": "09:00",
        "tanggal": "2026-09-09",
        "tanggal_lain": ["2026-09-09", "2026-09-10", "2026-09-11"],
    }
    ns["_catat_banyak_tanggal"](data, execute_palsu, KonteksSesi(), diucapkan.append)

    assert dibuat == ["2026-09-09", "2026-09-10", "2026-09-11"]
    assert any("gagal" in u.lower() for u in diucapkan)


# --- "617 hari lagi itu hari apa?" ---------------------------------------
def test_pertanyaan_tanggal_relatif_dihitung():
    from datetime import datetime as _dt, timedelta as _td

    from src.calendar_service.executor import _handle_waktu

    hasil = _handle_waktu({"teks_asli": "617 hari lagi itu hari apa"})
    target = _dt.now() + _td(days=617)
    assert str(target.year) in hasil["message"]
    assert str(target.day) in hasil["message"]


def test_pertanyaan_waktu_biasa_tidak_berubah():
    from src.calendar_service.executor import _handle_waktu

    hasil = _handle_waktu({"teks_asli": "sekarang jam berapa"})
    assert "jam" in hasil["message"].lower()


def test_rentang_ratusan_hari():
    from datetime import datetime as _dt

    hasil = parse_date_range_id("617 hari lagi aku ada jadwal ga", _dt(2026, 9, 1))
    assert hasil is not None
    assert hasil[2] == "617 hari ke depan"


# --- Whisper terjebak mengulang ------------------------------------------
def _muat_penjaga_transkripsi():
    import re as _re

    src = open("src/stt/transcriber.py", encoding="utf-8").read()
    ns = {"re": _re}
    exec(src[src.index("def _terjebak_mengulang"):src.index("def transcribe(")], ns)
    return ns


def test_transkripsi_macet_dibuang():
    ns = _muat_penjaga_transkripsi()
    macet = "Kepandangan diberi di Kuala Lumpur, " + "Kuala Lumpur, " * 30
    assert ns["_terjebak_mengulang"](macet) is True


@pytest.mark.parametrize("kalimat", [
    "Catatannya diganti dengan saya datang harus menggunakan baju batik",
    "Terima kasih.",
    "catat jadwal meeting besok jam 3 sore",
])
def test_transkripsi_normal_tidak_dibuang(kalimat):
    ns = _muat_penjaga_transkripsi()
    assert ns["_terjebak_mengulang"](kalimat) is False


# --- "Catatannya diganti" tanpa nilai ------------------------------------
def test_kata_perubahan_tidak_jadi_isi_field():
    """'Catatannya diganti' berarti ingin mengubah, bukan mengisi 'diganti'."""
    from src.nlp.correction import parse_koreksi

    data = {"kegiatan": "kondangan", "deskripsi": "Acomalaka",
            "tanggal": "2026-09-02", "jam": "13:00"}
    assert parse_koreksi(dict(data), "Catatannya diganti.", use_llm=False) == {}
    assert parse_koreksi(dict(data), "kegiatannya salah", use_llm=False) == {}


def test_koreksi_dengan_nilai_tetap_jalan():
    from src.nlp.correction import parse_koreksi

    data = {"kegiatan": "kondangan", "deskripsi": "Acomalaka"}
    hasil = parse_koreksi(dict(data), "catatannya diganti dengan baju batik", use_llm=False)
    assert hasil == {"deskripsi": "baju batik"}


def test_salah_dengar_katatan():
    assert "catatan" in normalize("Katatannya diganti dengan baju batik")


# =========================================================================
# Sprint 3.20 — self destruct tak terjangkau saat ambient, spam LLM
# =========================================================================

@pytest.mark.parametrize("kalimat", [
    "Akira, destrui diri sendiri.",
    "Akhirnya, destrui diri sendiri.",     # salah dengar nama
    "akira destroy yourself",
    "akira hancurkan dirimu",
    "akira musnahkan diri sendiri",
])
def test_self_destruct_lewat_teks_dikenali(kalimat):
    """
    Saat mode ambient jalan, mikrofon dipakai merekam kalimat penuh — model
    wake word tidak pernah dapat giliran. Tanpa deteksi teks ini, perintah
    rahasia tidak bisa dipanggil sama sekali.
    """
    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["minta_self_destruct"](kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "Terima kasih.",
    "destroy yourself",                    # tidak menyebut AKIRA
    "akira bacakan jadwal saya",
    "akira hapus jadwal rapat",
])
def test_bukan_self_destruct(kalimat):
    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["minta_self_destruct"](kalimat) is False


# --- LLM tidak dipanggil untuk jawaban kosong/ngawur ---------------------
@pytest.mark.parametrize("jawaban", [
    "", "   ", "Nah, nah, nah.", "hmm hmm", "ya", "terima kasih", "hmm",
])
def test_jawaban_tidak_informatif_tidak_ke_llm(jawaban):
    from src.nlp.correction import layak_ke_llm

    assert layak_ke_llm(jawaban) is False


@pytest.mark.parametrize("jawaban", [
    "catatannya baju batik",
    "jam 9",
    "nah kegiatannya futsal",
])
def test_jawaban_berisi_tetap_ke_llm(jawaban):
    from src.nlp.correction import layak_ke_llm

    assert layak_ke_llm(jawaban) is True


def test_koreksi_kosong_tidak_memanggil_llm(monkeypatch):
    """Jawaban kosong harus langsung kembali kosong, tanpa jeda panggilan LLM."""
    from src.nlp import correction

    dipanggil = []
    monkeypatch.setattr(
        correction, "koreksi_via_llm",
        lambda *a, **k: dipanggil.append(1) or {},
    )

    assert correction.parse_koreksi({"kegiatan": "meeting"}, "", use_llm=True) == {}
    assert dipanggil == []


def test_deteksi_teks_tidak_bergantung_file_onnx():
    """
    Jalur teks harus tetap hidup walau model wake word rahasia tidak ada.
    Sebelumnya digerbangi oleh nama_destruct, yang bernilai None kalau
    file .onnx hilang — fitur mati diam-diam.
    """
    src = open("src/app.py", encoding="utf-8").read()
    blok = src[src.index("if ambient_aktif and pernah_dibangunkan"):]
    baris = blok[:blok.index("if text and perintah_untuk_akira")]
    assert "destruct_lewat_teks and minta_self_destruct" in baris
    assert "nama_destruct and minta_self_destruct" not in baris


def test_config_deteksi_teks_menyala_default():
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    assert cfg["self_destruct"]["aktif_lewat_teks"] is True


def test_ambang_destruct_tidak_terlalu_ketat():
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    ambang = cfg["self_destruct"]["threshold"]
    assert cfg["wakeword"]["threshold"] < ambang <= 0.75


def test_skrip_diagnosa_ada():
    import os

    assert os.path.exists("scripts/cek_pemicu.py")


# =========================================================================
# Sprint 3.21 — variabel dipakai sebelum didefinisikan
# =========================================================================

def _variabel_dipakai_sebelum_didefinisikan(path: str) -> list:
    """
    Cari variabel lokal yang dibaca di baris LEBIH AWAL daripada baris
    penugasan pertamanya.

    Menangkap kelas bug yang hanya meledak saat dijalankan
    (UnboundLocalError) — tidak terdeteksi py_compile maupun test unit yang
    mengimpor fungsi lain. Persis yang terjadi pada `destruct_lewat_teks`:
    definisinya tak sengaja ditaruh setelah pemakaiannya, AKIRA crash di
    startup, padahal 501 test lolos.

    Dua hal yang harus benar supaya tidak banjir false positive:
    - pakai baris TERKECIL untuk store maupun load (ast.walk menelusuri
      per level, bukan urut baris)
    - lewati variabel comprehension dan lambda — keduanya punya scope sendiri
    """
    import ast

    masalah = []
    pohon = ast.parse(open(path, encoding="utf-8").read())

    for fn in ast.walk(pohon):
        if not isinstance(fn, ast.FunctionDef):
            continue

        arg_names = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        if fn.args.vararg:
            arg_names.add(fn.args.vararg.arg)
        if fn.args.kwarg:
            arg_names.add(fn.args.kwarg.arg)

        # Variabel dengan scope sendiri: comprehension, lambda, fungsi bersarang
        scope_lain = set()
        for n in ast.walk(fn):
            if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                for gen in n.generators:
                    for t in ast.walk(gen.target):
                        if isinstance(t, ast.Name):
                            scope_lain.add(t.id)
            elif isinstance(n, ast.Lambda):
                scope_lain.update(a.arg for a in n.args.args)
            elif isinstance(n, ast.FunctionDef) and n is not fn:
                scope_lain.add(n.name)
                scope_lain.update(a.arg for a in n.args.args)
            elif isinstance(n, (ast.ExceptHandler,)) and n.name:
                scope_lain.add(n.name)

        simpan, baca, global_names = {}, {}, set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Global):
                global_names.update(n.names)
            elif isinstance(n, ast.Name):
                target = simpan if isinstance(n.ctx, ast.Store) else baca
                target[n.id] = min(target.get(n.id, n.lineno), n.lineno)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for alias in n.names:
                    nama = (alias.asname or alias.name).split(".")[0]
                    simpan[nama] = min(simpan.get(nama, n.lineno), n.lineno)

        for nama, baris_baca in baca.items():
            if (
                nama in arg_names
                or nama in global_names
                or nama in scope_lain
                or nama not in simpan
            ):
                continue
            if simpan[nama] > baris_baca:
                masalah.append(f"{fn.name}(): '{nama}' dibaca di baris "
                               f"{baris_baca}, baru didefinisikan di {simpan[nama]}")
    return masalah


@pytest.mark.parametrize("modul", [
    "src/app.py",
    "src/dialog/state_machine.py",
    "src/dialog/confirmation.py",
    "src/dialog/alarm.py",
    "src/dialog/reminder.py",
    "src/dialog/self_destruct.py",
    "src/nlp/parser.py",
    "src/nlp/correction.py",
    "src/nlp/date_time_parser.py",
    "src/calendar_service/executor.py",
])
def test_tidak_ada_variabel_dipakai_sebelum_didefinisikan(modul):
    masalah = _variabel_dipakai_sebelum_didefinisikan(modul)
    assert not masalah, "UnboundLocalError menunggu terjadi:\n  " + "\n  ".join(masalah)


def test_pendeteksi_ini_benar_benar_bekerja():
    """Pastikan pemeriksanya sendiri tidak diam-diam selalu lolos."""
    import tempfile
    import os

    kode = "def f():\n    print(x)\n    x = 1\n"
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(kode)
        assert _variabel_dipakai_sebelum_didefinisikan(path)
    finally:
        os.remove(path)


# =========================================================================
# Sprint 3.22 — wake word ambient tanpa Whisper
# =========================================================================

def _fungsi_dipanggil_tapi_tidak_ada(path: str) -> list:
    """
    Cari pemanggilan fungsi lokal yang fungsinya tidak ada di modul.

    Menangkap kesalahan editing seperti yang barusan terjadi: mengganti satu
    blok kode ikut menghapus fungsi lain yang kebetulan berada di dalam
    rentang yang sama. Sintaksnya tetap sah, jadi py_compile lolos — dan
    error-nya baru muncul saat fungsi itu dipanggil.
    """
    import ast

    src = open(path, encoding="utf-8").read()
    pohon = ast.parse(src)

    didefinisikan = {
        n.name for n in ast.walk(pohon) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    diimpor = set()
    for n in ast.walk(pohon):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                diimpor.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            diimpor.add(n.id)
        elif isinstance(n, ast.arg):
            diimpor.add(n.arg)

    hilang = []
    for n in ast.walk(pohon):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)):
            continue
        nama = n.func.id
        # Hanya periksa helper internal (berawalan _) supaya tidak salah tuduh
        # terhadap builtin dan fungsi hasil impor di dalam fungsi.
        if not nama.startswith("_") or nama.startswith("__"):
            continue
        if nama not in didefinisikan and nama not in diimpor:
            hilang.append(f"baris {n.lineno}: {nama}() dipanggil tapi tidak ada")
    return hilang


@pytest.mark.parametrize("modul", [
    "src/app.py",
    "src/dialog/state_machine.py",
    "src/dialog/confirmation.py",
    "src/nlp/parser.py",
    "src/nlp/correction.py",
    "src/calendar_service/executor.py",
])
def test_semua_helper_yang_dipanggil_ada(modul):
    hilang = _fungsi_dipanggil_tapi_tidak_ada(modul)
    assert not hilang, "fungsi hilang:\n  " + "\n  ".join(hilang)


def test_pendeteksi_fungsi_hilang_bekerja():
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("def a():\n    return _tidak_ada()\n")
        assert _fungsi_dipanggil_tapi_tidak_ada(path)
    finally:
        os.remove(path)


# --- Pendengar ambient: satu stream, dua tugas ---------------------------
def test_ambient_listener_ada():
    import os

    assert os.path.exists("src/audio/ambient_listener.py")


def test_wake_word_dinilai_dari_audio_bukan_teks():
    """
    Perintah rahasia harus dideteksi openWakeWord langsung dari audio.
    Bergantung pada teks Whisper untuk perintah yang menghapus sistem
    itu pilihan buruk — Whisper rutin salah dengar.
    """
    src = open("src/audio/ambient_listener.py", encoding="utf-8").read()
    assert "oww.predict" in src
    assert "transcribe" not in src, "pendengar ambient tidak boleh memanggil Whisper"


def test_wake_word_dicek_juga_saat_merekam():
    """
    Wake word harus dinilai pada SETIAP potongan, termasuk saat sedang
    merekam kalimat lain — kalau tidak, frasa rahasia di tengah kalimat
    akan terlewat.
    """
    import ast

    src = open("src/audio/ambient_listener.py", encoding="utf-8").read()
    fn = [
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "dengar"
    ][0]

    panggilan = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_cek_wakeword"
    ]
    assert panggilan, "_cek_wakeword() harus dipanggil di dalam loop dengar()"


def _konstanta_ambient():
    """
    Baca konstanta tanpa mengimpor modul — mesin tanpa PortAudio/pyaudio
    (CI, container) tidak bisa mengimpor modul audio, padahal angkanya
    tetap layak diperiksa.
    """
    import re as _re

    src = open("src/audio/ambient_listener.py", encoding="utf-8").read()
    return {
        nama: int(_re.search(rf"^{nama} = (\d+)", src, _re.M).group(1))
        for nama in ("SAMPLE_RATE", "CHUNK_SAMPLES", "VAD_FRAME_SAMPLES")
    }


def test_ukuran_frame_vad_valid():
    """webrtcvad hanya menerima frame 10, 20, atau 30 ms."""
    k = _konstanta_ambient()
    durasi_ms = k["VAD_FRAME_SAMPLES"] / k["SAMPLE_RATE"] * 1000
    assert durasi_ms in (10, 20, 30)
    assert k["CHUNK_SAMPLES"] % k["VAD_FRAME_SAMPLES"] == 0


def test_ukuran_chunk_sesuai_openwakeword():
    """openWakeWord mengharapkan potongan 80 ms pada 16 kHz."""
    k = _konstanta_ambient()
    assert k["CHUNK_SAMPLES"] == 1280
    assert k["SAMPLE_RATE"] == 16000


# =========================================================================
# Sprint 3.23 — ensemble STT tiga lapis
# =========================================================================

def test_semua_mesin_terdaftar():
    from src.stt.backends import BACKEND

    for nama in ("whisper", "groq", "groq-turbo", "groq-v3"):
        assert nama in BACKEND


def test_mesin_tak_dikenal_jatuh_ke_whisper():
    from src.stt.backends import BACKEND, get_backend

    assert get_backend("tidak-ada") is BACKEND["whisper"]
    assert get_backend(None) is BACKEND["whisper"]


def test_cek_kesiapan_melaporkan_api_key_kosong(monkeypatch):
    from src.stt.backends import cek_kesiapan

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    status = cek_kesiapan()
    assert "GROQ_API_KEY" in status["groq"]


def test_mesin_belum_siap_disaring(monkeypatch):
    """Memanggil mesin tanpa API key cuma menambah jeda untuk kegagalan pasti."""
    from src.stt import backends

    monkeypatch.setattr(
        backends, "cek_kesiapan",
        lambda: {"whisper": "siap", "groq": "GROQ_API_KEY KOSONG", "assemblyai": "siap"},
    )
    assert backends.mesin_siap(["whisper", "groq", "assemblyai"]) == ["whisper", "assemblyai"]


# --- Voting ---------------------------------------------------------------
def test_voting_dua_sepakat_menang():
    from src.stt.ensemble import voting

    hasil = voting({
        "whisper": "catat jadwal meeting besok jam 3 sore",
        "assemblyai": "Catat jadwal meeting besok jam 3 sore.",
        "gladia": "catat jadwal miting besok jam 3",
    })
    assert hasil is not None
    assert "meeting" in hasil


def test_voting_toleran_tanda_baca_dan_huruf_besar():
    from src.stt.ensemble import voting

    assert voting({
        "a": "cek jadwal besok",
        "b": "Cek jadwal besok.",
    }) is not None


def test_voting_menyerah_kalau_semua_beda():
    from src.stt.ensemble import voting

    assert voting({
        "whisper": "setelah pengingat untuk 30 minit lagi",
        "assemblyai": "hapus jadwal rapat divisi",
        "gladia": "sekarang jam berapa ya",
    }) is None


def test_voting_butuh_minimal_dua_mesin():
    from src.stt.ensemble import voting

    assert voting({"whisper": "cek jadwal besok"}) is None


# --- Validasi hasil LLM ---------------------------------------------------
def test_llm_tidak_boleh_mengarang():
    """
    Kalimat karangan yang terdengar masuk akal lebih berbahaya daripada
    salah dengar biasa — user tidak punya petunjuk bahwa itu salah.
    """
    from src.stt.ensemble import _valid_hasil_llm

    kandidat = {
        "a": "setel pengingat 30 menit lagi",
        "b": "setelkan pengingat untuk 30 menit lagi",
    }
    assert _valid_hasil_llm("setel pengingat untuk 30 menit lagi", kandidat) is True
    assert _valid_hasil_llm("hapus semua jadwal saya", kandidat) is False
    assert _valid_hasil_llm("", kandidat) is False


# --- Alur ensemble penuh (mesin ditiru) ----------------------------------
def _pasang_mesin_palsu(monkeypatch, hasil_per_mesin):
    from src.stt import backends, ensemble

    monkeypatch.setattr(
        ensemble, "mesin_siap", lambda daftar: list(hasil_per_mesin), raising=False
    )
    monkeypatch.setattr(backends, "mesin_siap", lambda daftar: list(hasil_per_mesin))

    def fake_get_backend(nama):
        def fn(path, **kw):
            nilai = hasil_per_mesin[nama]
            if isinstance(nilai, Exception):
                raise nilai
            return nilai
        return fn

    monkeypatch.setattr(backends, "get_backend", fake_get_backend)


def test_ensemble_memakai_hasil_voting(monkeypatch):
    from src.stt.ensemble import transcribe_ensemble

    _pasang_mesin_palsu(monkeypatch, {
        "whisper": "cek jadwal besok",
        "groq": "Cek jadwal besok.",
        "assemblyai": "cek jadwal minggu depan",
    })
    hasil = transcribe_ensemble("dummy.wav", ["whisper", "groq", "assemblyai"])
    assert "besok" in hasil.lower()


def test_ensemble_satu_mesin_gagal_tidak_menggagalkan(monkeypatch):
    from src.stt.ensemble import transcribe_ensemble

    _pasang_mesin_palsu(monkeypatch, {
        "whisper": "cek jadwal besok",
        "groq": RuntimeError("API key salah"),
        "assemblyai": "cek jadwal besok",
    })
    assert "besok" in transcribe_ensemble("dummy.wav", ["whisper", "groq", "assemblyai"]).lower()


def test_ensemble_semua_gagal_kembali_kosong(monkeypatch):
    from src.stt.ensemble import transcribe_ensemble

    _pasang_mesin_palsu(monkeypatch, {
        "whisper": RuntimeError("x"),
        "groq": RuntimeError("y"),
    })
    assert transcribe_ensemble("dummy.wav", ["whisper", "groq"]) == ""


def test_ensemble_pakai_llm_kalau_semua_beda(monkeypatch):
    from src.stt import ensemble

    _pasang_mesin_palsu(monkeypatch, {
        "whisper": "setelah pengingat untuk 30 minit lagi",
        "groq": "setelkan pengingat untuk 30 menit lagi",
        "assemblyai": "setel pengingat 30 menit lagi ya",
    })

    dipanggil = []

    def fake_ganda(kandidat, perekonsiliasi, model_per_nama=None):
        dipanggil.append(len(kandidat))
        return "setel pengingat untuk 30 menit lagi"

    monkeypatch.setattr(ensemble, "rekonsiliasi_ganda", fake_ganda)
    hasil = ensemble.transcribe_ensemble("dummy.wav", ["whisper", "groq", "assemblyai"])

    assert dipanggil == [3]
    assert hasil == "setel pengingat untuk 30 menit lagi"


def test_llm_tidak_dipanggil_kalau_sudah_sepakat(monkeypatch):
    """Voting gratis; LLM hanya untuk kasus yang benar-benar buntu."""
    from src.stt import ensemble

    _pasang_mesin_palsu(monkeypatch, {
        "whisper": "cek jadwal besok",
        "groq": "cek jadwal besok",
    })

    dipanggil = []
    monkeypatch.setattr(
        ensemble, "rekonsiliasi_ganda",
        lambda *a, **k: dipanggil.append(1) or "x",
    )
    ensemble.transcribe_ensemble("dummy.wav", ["whisper", "groq"])
    assert dipanggil == []


def test_ensemble_jaring_terakhir_kandidat_terpanjang(monkeypatch):
    from src.stt import ensemble

    # Kandidat harus cukup mirip untuk lolos deteksi derau, tapi tidak cukup
    # mirip untuk memenangkan voting — itulah kondisi yang memanggil lapis 2.
    _pasang_mesin_palsu(monkeypatch, {
        "whisper": "hapus rapat divisi",
        "groq": "hapus rapat divisi besok pagi sekali",
        "assemblyai": "hapus rapat divisi besok",
    })
    monkeypatch.setattr(ensemble, "rekonsiliasi_ganda", lambda *a, **k: None)

    hasil = ensemble.transcribe_ensemble("dummy.wav", ["whisper", "groq", "assemblyai"])
    assert hasil == "hapus rapat divisi besok pagi sekali"


def test_config_ensemble_lengkap():
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    ens = cfg["stt"]["ensemble"]
    assert "timeout_s" in ens and "perekonsiliasi" in ens


def test_skrip_cek_api_key_ada():
    import os

    assert os.path.exists("scripts/cek_api_key.py")


def test_cek_api_key_menyamarkan_nilai():
    """Skrip diagnosa tidak boleh mencetak API key apa adanya ke layar/log."""
    import re as _re

    src = open("scripts/cek_api_key.py", encoding="utf-8").read()
    ns = {"re": _re}
    exec(src[src.index("def samarkan"):src.index("def cek_file_env")], ns)

    hasil = ns["samarkan"]("gsk_rahasia_sekali_1234567890")
    assert "rahasia" not in hasil
    assert hasil.startswith("gsk_")
    assert ns["samarkan"]("") == "(kosong)"


# =========================================================================
# Sprint 3.24 — tiga lapis: STT ensemble -> rekonsiliasi ganda -> qwen3
# =========================================================================

def test_perekonsiliasi_terdaftar():
    from src.stt.ensemble import PEREKONSILIASI

    for nama in ("groq", "groq2", "lokal"):
        assert nama in PEREKONSILIASI


def test_perekonsiliasi_tanpa_key_dilewati(monkeypatch):
    from src.stt.ensemble import _perekonsiliasi_siap

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert _perekonsiliasi_siap(["groq", "groq2"]) == ["lokal"]

    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    assert _perekonsiliasi_siap(["groq", "groq2"]) == ["groq", "groq2"]


def test_lokal_selalu_tersedia(monkeypatch):
    from src.stt.ensemble import _perekonsiliasi_siap

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert "lokal" in _perekonsiliasi_siap(["groq"])


def _pasang_perekonsiliasi_palsu(monkeypatch, jawaban: dict):
    """jawaban: {nama: teks JSON atau Exception}"""
    from src.stt import ensemble

    def buat(nama):
        def fn(system, pesan, model=None):
            nilai = jawaban[nama]
            if isinstance(nilai, Exception):
                raise nilai
            return f'{{"teks": "{nilai}"}}'
        return fn

    monkeypatch.setattr(
        ensemble, "PEREKONSILIASI", {n: buat(n) for n in jawaban}, raising=False
    )
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")


KANDIDAT_CONTOH = {
    "whisper": "Akhirah baca tang jadwal saya",
    "groq": "Akira bacakan jadwal saya",
    "assemblyai": "Kira bacakan jadwal saya",
}


def test_dua_perekonsiliasi_sepakat(monkeypatch):
    from src.stt.ensemble import rekonsiliasi_ganda

    _pasang_perekonsiliasi_palsu(monkeypatch, {
        "groq2": "Akira bacakan jadwal saya",
        "groq": "Akira bacakan jadwal saya",
    })
    hasil = rekonsiliasi_ganda(KANDIDAT_CONTOH, ["groq", "groq2"])
    assert hasil == "Akira bacakan jadwal saya"


def test_perekonsiliasi_beda_pilih_yang_terdekat_kandidat(monkeypatch):
    """
    Kalau dua LLM tidak sepakat, yang dipilih adalah yang paling dekat dengan
    apa yang BENAR-BENAR didengar mesin STT. Yang menyimpang jauh biasanya
    hasil mengarang.
    """
    from src.stt.ensemble import rekonsiliasi_ganda

    _pasang_perekonsiliasi_palsu(monkeypatch, {
        "groq2": "Akira bacakan jadwal saya",
        "groq": "Akira bacakan jadwal saya besok pagi",
    })
    hasil = rekonsiliasi_ganda(KANDIDAT_CONTOH, ["groq", "groq2"])
    assert hasil == "Akira bacakan jadwal saya"


def test_satu_perekonsiliasi_gagal_yang_lain_dipakai(monkeypatch):
    from src.stt.ensemble import rekonsiliasi_ganda

    _pasang_perekonsiliasi_palsu(monkeypatch, {
        "groq2": RuntimeError("403 Forbidden"),
        "groq": "Akira bacakan jadwal saya",
    })
    assert rekonsiliasi_ganda(KANDIDAT_CONTOH, ["groq", "groq2"]) == "Akira bacakan jadwal saya"


def test_semua_perekonsiliasi_gagal(monkeypatch):
    from src.stt.ensemble import rekonsiliasi_ganda

    _pasang_perekonsiliasi_palsu(monkeypatch, {
        "groq2": RuntimeError("x"),
        "groq": RuntimeError("y"),
    })
    assert rekonsiliasi_ganda(KANDIDAT_CONTOH, ["groq", "groq2"]) is None


def test_hasil_karangan_ditolak_walau_dua_llm_sepakat(monkeypatch):
    """
    Dua LLM sepakat pada kalimat yang tidak ada di kandidat mana pun tetap
    ditolak. Kesepakatan bukan bukti kebenaran kalau dua-duanya mengarang.
    """
    from src.stt.ensemble import rekonsiliasi_ganda

    _pasang_perekonsiliasi_palsu(monkeypatch, {
        "groq2": "hapus semua jadwal saya sekarang",
        "groq": "hapus semua jadwal saya sekarang",
    })
    assert rekonsiliasi_ganda(KANDIDAT_CONTOH, ["groq", "groq2"]) is None


def test_blok_think_dibersihkan_dari_balasan():
    from src.stt.ensemble import _bersihkan_json

    assert _bersihkan_json('<think>hmm</think>{"teks": "halo"}') == '{"teks": "halo"}'
    assert _bersihkan_json('```json\n{"teks": "halo"}\n```') == '{"teks": "halo"}'
    assert _bersihkan_json('Sure! {"teks": "halo"} done') == '{"teks": "halo"}'


def test_config_tiga_lapis_lengkap():
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    stt = cfg["stt"]
    ens = stt["ensemble"]

    # Lapis 1: beberapa mesin STT
    assert isinstance(stt["engine"], list) and len(stt["engine"]) >= 2
    # Lapis 2: beberapa perekonsiliasi
    assert isinstance(ens["perekonsiliasi"], list) and len(ens["perekonsiliasi"]) >= 2
    assert "model_perekonsiliasi" in ens


@pytest.mark.parametrize("kalimat", [
    "Akhirah baca tang jadwal saya",
    "Kira bacakan jadwal saya",
    "Akira bacakan jadwal saya",
])
def test_variasi_salah_dengar_nama_dari_log(kalimat):
    """Variasi yang benar-benar muncul di log demo, bukan karangan."""
    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["perintah_untuk_akira"](kalimat) is True


# =========================================================================
# Sprint 3.25 — dua model Groq, model cadangan, label log yang jujur
# =========================================================================

def test_dua_model_groq_terdaftar_terpisah():
    from src.stt.backends import BACKEND

    assert "groq-turbo" in BACKEND
    assert "groq-v3" in BACKEND
    assert BACKEND["groq-turbo"] is not BACKEND["groq-v3"]


def test_groq_turbo_dan_v3_memakai_model_berbeda(monkeypatch):
    from src.stt import backends

    dipakai = []
    monkeypatch.setattr(
        backends, "transcribe_groq",
        lambda path, groq_model=None, **kw: dipakai.append(groq_model) or "teks",
    )
    # BACKEND menyimpan lambda yang menutup transcribe_groq lama, jadi panggil
    # lewat modul supaya monkeypatch terpakai
    backends.transcribe_groq("x.wav", groq_model="whisper-large-v3-turbo")
    backends.transcribe_groq("x.wav", groq_model="whisper-large-v3")
    assert dipakai == ["whisper-large-v3-turbo", "whisper-large-v3"]


def test_kesiapan_mengenali_varian_groq(monkeypatch):
    from src.stt.backends import cek_kesiapan

    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    status = cek_kesiapan()
    assert status["groq-turbo"] == "siap"
    assert status["groq-v3"] == "siap"


# --- Model cadangan saat nama model ditolak ------------------------------
@pytest.fixture(autouse=True)
def _bersihkan_ingatan_model():
    """
    Kosongkan ingatan model antar-test.

    `_MODEL_BERHASIL` sengaja bertahan selama proses berjalan (itu gunanya),
    tapi kalau bocor antar-test, urutan test jadi menentukan hasilnya —
    dan kegagalan seperti itu paling membingungkan untuk dilacak.
    """
    try:
        from src.stt.ensemble import _MODEL_BERHASIL

        _MODEL_BERHASIL.clear()
        yield
        _MODEL_BERHASIL.clear()
    except ImportError:
        yield


def test_daftar_model_mendahulukan_pilihan_pengguna():
    from src.stt.ensemble import _daftar_model

    hasil = _daftar_model("groq", "model/pilihan-saya")
    assert hasil[0] == "model/pilihan-saya"
    assert len(hasil) > 1, "harus ada cadangan di belakangnya"


def test_daftar_model_kosong_pakai_cadangan():
    from src.stt.ensemble import MODEL_CADANGAN, _daftar_model

    assert _daftar_model("groq2", None)[0] == MODEL_CADANGAN["groq2"][0]


def test_model_404_lanjut_ke_cadangan(monkeypatch):
    """
    Nama model di Groq & OpenRouter berubah cukup sering. Satu nama yang
    sudah dihentikan tidak boleh mematikan seluruh lapis 2.
    """
    from src.stt import ensemble

    dicoba = []

    def fungsi_palsu(system, pesan, model=None):
        dicoba.append(model)
        if len(dicoba) < 3:
            raise RuntimeError("404 Client Error: Not Found")
        return '{"teks": "cek jadwal besok"}'

    monkeypatch.setattr(ensemble, "PEREKONSILIASI", {"groq": fungsi_palsu}, raising=False)
    hasil = ensemble._satu_rekonsiliasi("groq", {"a": "cek jadwal besok"}, None)

    assert hasil == "cek jadwal besok"
    assert len(dicoba) == 3, "harus mencoba model berikutnya, bukan menyerah"


def test_model_berhasil_diingat(monkeypatch):
    """Model yang terbukti jalan didahulukan di panggilan berikutnya."""
    from src.stt import ensemble

    ensemble._MODEL_BERHASIL.clear()

    def fungsi_palsu(system, pesan, model=None):
        if model != "qwen/qwen3.8-27b":
            raise RuntimeError("404 not found")
        return '{"teks": "cek jadwal besok"}'

    monkeypatch.setattr(ensemble, "PEREKONSILIASI", {"groq": fungsi_palsu}, raising=False)
    ensemble._satu_rekonsiliasi("groq", {"a": "cek jadwal besok"}, None)

    assert ensemble._MODEL_BERHASIL["groq"] == "qwen/qwen3.8-27b"
    assert ensemble._daftar_model("groq", None)[0] == "qwen/qwen3.8-27b"
    ensemble._MODEL_BERHASIL.clear()


def test_error_selain_404_tidak_dicoba_ulang(monkeypatch):
    """Kuota habis atau key salah tidak akan membaik dengan ganti model."""
    from src.stt import ensemble

    dicoba = []

    def fungsi_palsu(system, pesan, model=None):
        dicoba.append(model)
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(ensemble, "PEREKONSILIASI", {"groq": fungsi_palsu}, raising=False)
    assert ensemble._satu_rekonsiliasi("groq", {"a": "x"}, None) is None
    assert len(dicoba) == 1


# --- Label log harus jujur ------------------------------------------------
def test_label_menyebut_mesin_yang_benar_benar_dipakai(monkeypatch):
    """
    Log sempat menulis 'whisper+groq+assemblyai' padahal assemblyai dilewati.
    Label harus mencerminkan yang benar-benar menghasilkan kandidat.
    """
    from src.stt import ensemble

    _pasang_mesin_palsu(monkeypatch, {
        "whisper": "cek jadwal besok",
        "groq-turbo": "cek jadwal besok",
    })
    ensemble.transcribe_ensemble("dummy.wav", ["whisper", "groq-turbo"])

    terpakai = ensemble.mesin_terpakai()
    assert "assemblyai" not in terpakai
    assert set(terpakai) == {"whisper", "groq-turbo"}


def test_config_lapis1_tiga_mesin_tanpa_assemblyai():
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    engine = cfg["stt"]["engine"]
    assert len(engine) == 3
    assert "assemblyai" not in engine
    assert "groq-turbo" in engine and "groq-v3" in engine


def test_skrip_cek_model_ada():
    import os

    assert os.path.exists("scripts/cek_model_llm.py")


# =========================================================================
# Sprint 3.26 — OpenRouter 402, dua perekonsiliasi Groq
# =========================================================================

def test_groq2_terdaftar_sebagai_perekonsiliasi():
    from src.stt.ensemble import PEREKONSILIASI

    assert "groq2" in PEREKONSILIASI


def test_groq_dan_groq2_pakai_model_berbeda():
    """
    Pendapat kedua harus benar-benar independen. Dua model dari keluarga
    yang sama cenderung salah dengan cara yang sama.
    """
    from src.stt.ensemble import _daftar_model

    assert _daftar_model("groq", None)[0] != _daftar_model("groq2", None)[0]


def test_groq2_butuh_key_groq(monkeypatch):
    from src.stt.ensemble import _perekonsiliasi_siap

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert _perekonsiliasi_siap(["groq", "groq2"]) == ["lokal"]

    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    assert _perekonsiliasi_siap(["groq", "groq2"]) == ["groq", "groq2"]


def test_model_groq_yang_terbukti_hidup():
    """
    Daftar cadangan Groq hanya berisi model yang sudah diverifikasi hidup
    lewat scripts/cek_model_llm.py. Model yang dihentikan harus dibuang,
    bukan dibiarkan menambah jeda percobaan.
    """
    from src.stt.ensemble import MODEL_CADANGAN

    assert "llama-3.3-70b-versatile" not in MODEL_CADANGAN["groq"]
    assert "qwen/qwen3.6-27b" not in MODEL_CADANGAN["groq"]
    for m in MODEL_CADANGAN["groq"]:
        assert m in ("openai/gpt-oss-20b", "qwen/qwen3.8-27b", "openai/gpt-oss-120b")


def test_config_lapis2_dua_perekonsiliasi_yang_hidup():
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    ens = cfg["stt"]["ensemble"]

    assert len(ens["perekonsiliasi"]) == 2
    # OpenRouter tidak dipakai default karena akun belum berkredit
    assert "openrouter" not in ens["perekonsiliasi"]
    model = ens["model_perekonsiliasi"]
    assert model["groq"] != model["groq2"]


# =========================================================================
# Sprint 3.27 — ambient satu mesin, jam per tanggal, bentrok jadwal
# =========================================================================

def test_ambient_meneruskan_daftar_mesin():
    """
    Mode ambient sempat diam-diam memakai satu mesin saja karena `engine`
    tidak diteruskan ke transcribe(). Sesi biasa pakai tiga mesin, ambient
    cuma satu — dan tidak ada tanda apa pun di log.
    """
    src = open("src/app.py", encoding="utf-8").read()
    awal = src.index("def _transkripsi_ambient")
    blok = src[awal:src.index("\ndef ", awal + 10)]
    assert "engine=" in blok, "engine wajib diteruskan ke transcribe()"


def test_semua_pemanggil_transcribe_menyertakan_engine():
    """Setiap pemanggilan transcribe() di app.py harus menyebut engine."""
    import re as _re

    src = open("src/app.py", encoding="utf-8").read()

    # Hanya pemanggilan multi-baris yang sesungguhnya: "transcribe(" langsung
    # diikuti baris baru. Tanpa pembatas ini, penyebutan "transcribe()" di
    # dalam docstring ikut tertangkap dan test gagal tanpa sebab nyata.
    panggilan = _re.findall(r"[^_\w]transcribe\(\n(.*?)\n\s*\)", src, _re.DOTALL)
    assert panggilan, "tidak menemukan pemanggilan transcribe() sama sekali"
    for isi in panggilan:
        assert "engine=" in isi, f"transcribe() tanpa engine: {isi[:60]}"


# --- Jam berbeda per tanggal ---------------------------------------------
def test_jam_per_tanggal_terbaca():
    from datetime import datetime as _dt

    from src.nlp.date_time_parser import parse_jam_per_tanggal

    hasil = parse_jam_per_tanggal(
        "Tanggal 10 mulainya jam 2 siang, untuk tanggal 12 mulainya jam 12 siang, "
        "untuk tanggal 15 mulainya jam 7 pagi.",
        _dt(2026, 9, 2),
    )
    assert hasil == {"2026-09-10": "14:00", "2026-09-12": "12:00", "2026-09-15": "07:00"}


def test_satu_jam_untuk_semua_bukan_per_tanggal():
    from datetime import datetime as _dt

    from src.nlp.date_time_parser import parse_jam_per_tanggal

    assert parse_jam_per_tanggal("tanggal 10, 12 dan 15 september", _dt(2026, 9, 2)) == {}
    assert parse_jam_per_tanggal("catat rapat tanggal 5 jam 9", _dt(2026, 9, 2)) == {}


def test_jawaban_jam_berbeda_per_tanggal_tersimpan():
    """
    Bulan sengaja disebut eksplisit. Tanpa itu, "tanggal 12" diselesaikan
    relatif terhadap hari ini dan hasilnya berpindah bulan begitu tanggal
    tersebut terlewat — test gagal padahal kode tidak berubah.
    """
    from src.nlp.parser import merge_answer

    data = {
        "aksi": "catat", "jam": None,
        "tanggal_lain": ["2027-09-10", "2027-09-12", "2027-09-15"],
    }
    data = merge_answer(
        data, "jam",
        "Tanggal 10 September 2027 mulainya jam 2 siang, "
        "untuk tanggal 12 September 2027 mulainya jam 12 siang, "
        "untuk tanggal 15 September 2027 mulainya jam 7 pagi.",
    )
    assert data["jam_per_tanggal"]["2027-09-12"] == "12:00"
    assert data["jam"] == "14:00"      # jam tanggal paling awal


def test_ringkasan_menyebut_jam_tiap_tanggal():
    """
    Kalau jamnya berbeda, ringkasan harus menyebut pasangannya. Menggabung
    jadi satu jam berarti user tidak punya kesempatan menyadari yang salah.
    """
    from src.dialog.state_machine import build_ringkasan

    pesan = build_ringkasan({
        "aksi": "catat", "kegiatan": "main bola", "tanggal": "2026-09-10",
        "jam": "14:00",
        "tanggal_lain": ["2026-09-10", "2026-09-12", "2026-09-15"],
        "jam_per_tanggal": {"2026-09-10": "14:00", "2026-09-12": "12:00",
                            "2026-09-15": "07:00"},
    })
    assert "10 September jam 14:00" in pesan
    assert "12 September jam 12:00" in pesan
    assert "15 September jam 07:00" in pesan


def test_catat_banyak_tanggal_pakai_jam_masing_masing():
    from src.dialog.context import KonteksSesi

    src = open("src/app.py", encoding="utf-8").read()
    ns = {"logger": __import__("loguru").logger}
    awal = src.index("def _catat_banyak_tanggal")
    exec(src[awal:src.index("\ndef ", awal + 10)], ns)

    dibuat = {}

    def execute_palsu(d):
        dibuat[d["tanggal"]] = d["jam"]
        return {"success": True, "message": "ok", "data": {"summary": d["kegiatan"]}}

    ns["_catat_banyak_tanggal"](
        {
            "aksi": "catat", "kegiatan": "main bola", "jam": "14:00",
            "tanggal_lain": ["2026-09-10", "2026-09-12"],
            "jam_per_tanggal": {"2026-09-10": "14:00", "2026-09-12": "12:00"},
        },
        execute_palsu, KonteksSesi(), lambda t: None,
    )
    assert dibuat == {"2026-09-10": "14:00", "2026-09-12": "12:00"}


def test_kata_urutan_bukan_nama_kegiatan():
    """'ketiga hari berikut' bukan nama kegiatan."""
    data = parse_command(
        "Catatkan jadwal buat ketiga hari berikut, tanggal 10, tanggal 12, "
        "dan tanggal 15 September.",
        use_slm=False,
    )
    assert data["kegiatan"] is None
    assert len(data["tanggal_lain"]) == 3


# --- Bentrok jadwal -------------------------------------------------------
def _kalender_dengan_meeting(monkeypatch):
    _kalender_palsu([{
        "id": "1", "summary": "meeting",
        "start": {"dateTime": "2026-09-03T14:00:00+07:00"},
        "end": {"dateTime": "2026-09-03T15:00:00+07:00"},
    }], monkeypatch)


@pytest.mark.parametrize("jam,bentrok", [
    ("14:00", True),    # mulai sama persis
    ("14:30", True),    # beririsan di tengah
    ("13:30", True),    # mulai lebih awal, berakhir di dalam
    ("15:00", False),   # tepat setelah selesai
    ("09:00", False),   # jauh
])
def test_deteksi_bentrok(monkeypatch, jam, bentrok):
    from src.calendar_service.executor import cari_bentrok

    _kalender_dengan_meeting(monkeypatch)
    assert bool(cari_bentrok("2026-09-03", jam)) is bentrok


def test_event_seharian_bukan_bentrok(monkeypatch):
    """Ulang tahun dan hari libur tidak menghalangi apa pun."""
    from src.calendar_service.executor import cari_bentrok

    _kalender_palsu([{
        "id": "1", "summary": "ulang tahun", "start": {"date": "2026-09-03"},
    }], monkeypatch)
    assert cari_bentrok("2026-09-03", "14:00") == []


def test_pesan_bentrok_menyebut_jadwal_yang_ada(monkeypatch):
    from src.calendar_service.executor import cari_bentrok, ucapkan_bentrok

    _kalender_dengan_meeting(monkeypatch)
    pesan = ucapkan_bentrok(cari_bentrok("2026-09-03", "14:00"), "2026-09-03")
    assert "meeting" in pesan and "14:00" in pesan


def test_bentrok_diperiksa_sebelum_konfirmasi():
    """
    Peringatan bentrok harus keluar SEBELUM ringkasan konfirmasi — kalau
    sesudah, user sudah terlanjur menyetujui.
    """
    src = open("src/app.py", encoding="utf-8").read()
    assert src.index("_tangani_bentrok(data, ask, dengar, say)") < src.index("build_ringkasan(data)")


# =========================================================================
# Sprint 3.28 — timer: label, batalkan, tanya sisa
# =========================================================================

@pytest.mark.parametrize("kalimat,label", [
    ("timer 15 menit buat minum obat", "minum obat"),
    ("ingetin minum obat 15 menit lagi", "minum obat"),
    ("timer 5 menit dengan catatan angkat jemuran", "angkat jemuran"),
])
def test_label_timer_terbaca(kalimat, label):
    from src.dialog.alarm import _label_dari_teks

    assert _label_dari_teks(kalimat) == label


@pytest.mark.parametrize("kalimat", [
    "buatkan timer 1 menit dengan catatan",   # pembuka tanpa isi
    "timer 30 detik",
    "hitung mundur 5 menit",
])
def test_label_kosong_kalau_tidak_disebut(kalimat):
    """
    'dengan catatan' tanpa lanjutan bukan keperluan. Kalau dipaksakan,
    AKIRA berteriak "waktunya catatan" — persis yang terjadi di log.
    """
    from src.dialog.alarm import _label_dari_teks

    assert _label_dari_teks(kalimat) is None


def test_pesan_bunyi_tanpa_label():
    from datetime import datetime as _dt

    from src.dialog.alarm import pesan_bunyi

    pesan = pesan_bunyi({"label": None, "jenis": "timer", "waktu": _dt.now()})
    assert "timer" in pesan.lower()
    assert "catatan" not in pesan.lower()


# --- Membatalkan timer ----------------------------------------------------
@pytest.mark.parametrize("kalimat", [
    "Matikan timernya.",
    "batalkan alarm",
    "stop timer",
    "hentikan timernya",
    "timernya batalkan aja",
])
def test_permintaan_batal_timer(kalimat):
    from src.dialog.alarm import is_batal_timer

    assert is_batal_timer(kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "timer 30 detik",
    "catat meeting besok",
    "hapus jadwal rapat",          # menghapus JADWAL, bukan timer
])
def test_bukan_permintaan_batal_timer(kalimat):
    from src.dialog.alarm import is_batal_timer

    assert is_batal_timer(kalimat) is False


def test_batalkan_semua_mengembalikan_jumlah():
    from src.dialog import alarm

    alarm.batalkan_semua()
    alarm.tambah_timer(60, "a")
    alarm.tambah_timer(120, "b")
    assert alarm.batalkan_semua() == 2
    assert alarm.daftar_aktif() == []


def test_timer_dibatalkan_tidak_berbunyi():
    from datetime import datetime as _dt, timedelta as _td

    from src.dialog import alarm

    alarm.batalkan_semua()
    diucapkan = []
    alarm.tambah_timer(60, "minum obat", say_fn=diucapkan.append)
    alarm.batalkan_semua()

    alarm.cek_sekali(_dt.now() + _td(seconds=120))
    assert diucapkan == []


# --- Menanyakan sisa waktu ------------------------------------------------
@pytest.mark.parametrize("kalimat", [
    "timernya berapa lama lagi",
    "sisa timer berapa",
    "timer tinggal berapa",
    "alarmnya kapan bunyi",
])
def test_pertanyaan_sisa_timer(kalimat):
    from src.dialog.alarm import is_tanya_timer

    assert is_tanya_timer(kalimat) is True


def test_laporan_sisa_menyebut_label_dan_waktu():
    from src.dialog import alarm

    alarm.batalkan_semua()
    alarm.tambah_timer(90, "minum obat")
    pesan = alarm.ucapkan_sisa()
    assert "minum obat" in pesan
    assert "menit" in pesan
    alarm.batalkan_semua()


def test_laporan_saat_tidak_ada_timer():
    from src.dialog import alarm

    alarm.batalkan_semua()
    assert "tidak ada" in alarm.ucapkan_sisa().lower()


@pytest.mark.parametrize("detik,ucapan", [
    (45, "45 detik"),
    (60, "sekitar 1 menit"),
    (89, "sekitar 1 menit"),      # 89 detik benar tapi janggal diucapkan
    (300, "sekitar 5 menit"),
    (3600, "sekitar 1 jam"),
])
def test_sisa_waktu_dibulatkan(detik, ucapan):
    from src.dialog.alarm import ucapkan_sisa_kasar

    assert ucapkan_sisa_kasar(detik) == ucapan


def test_batal_diperiksa_sebelum_buat_timer():
    """
    'matikan timernya' mengandung kata 'timer'. Kalau urutan pemeriksaan
    terbalik, kalimat itu bisa terbaca sebagai permintaan timer baru.
    """
    src = open("src/app.py", encoding="utf-8").read()
    awal = src.index("def _proses_alarm")
    blok = src[awal:src.index("\ndef ", awal + 10)]
    assert blok.index("is_batal_timer") < blok.index("is_permintaan_timer")
    assert blok.index("is_tanya_timer") < blok.index("is_permintaan_timer")


# =========================================================================
# Sprint 3.29 — konteks pertanyaan & bentrok yang ditanyakan
# =========================================================================

def test_konteks_pertanyaan_masuk_ke_prompt(monkeypatch):
    """
    Tanpa konteks, "Kalim, betalkan" dan "Salim, batalkan" sama-sama
    terdengar masuk akal. Begitu LLM tahu pertanyaannya "Sudah benar?",
    pilihannya jadi jelas.
    """
    from src.stt import ensemble

    dikirim = []

    def fungsi_palsu(system, pesan, model=None):
        dikirim.append(pesan)
        return '{"teks": "Batalkan"}'

    monkeypatch.setattr(ensemble, "PEREKONSILIASI", {"groq": fungsi_palsu}, raising=False)
    ensemble.set_konteks_pertanyaan("Sudah benar?")
    ensemble._satu_rekonsiliasi("groq", {"a": "Kalim betalkan", "b": "Batalkan"}, None)
    ensemble.set_konteks_pertanyaan("")

    assert "Sudah benar?" in dikirim[0]
    assert "Pertanyaan asisten" in dikirim[0]


def test_tanpa_konteks_prompt_tetap_jalan(monkeypatch):
    from src.stt import ensemble

    dikirim = []
    monkeypatch.setattr(
        ensemble, "PEREKONSILIASI",
        {"groq": lambda s, p, m=None: dikirim.append(p) or '{"teks": "cek jadwal"}'},
        raising=False,
    )
    ensemble.set_konteks_pertanyaan("")
    ensemble._satu_rekonsiliasi("groq", {"a": "cek jadwal"}, None)

    assert "Pertanyaan asisten" not in dikirim[0]


def test_say_mencatat_konteks():
    """Setiap kalimat AKIRA harus jadi konteks untuk jawaban berikutnya."""
    src = open("src/app.py", encoding="utf-8").read()
    awal = src.index("    def say(text, interruptible=True):")
    assert "_catat_konteks(text)" in src[awal:awal + 400]


# --- Bentrok: ditanyakan, bukan sekadar diberitahu -----------------------
def _jalankan_bentrok(monkeypatch, jawaban, data, events):
    """Jalankan _tangani_bentrok dengan kalender palsu dan jawaban tertentu."""
    import re as _re

    _kalender_palsu(events, monkeypatch)

    src = open("src/app.py", encoding="utf-8").read()
    ns = {"logger": __import__("loguru").logger, "re": _re}
    awal = src.index("def _tangani_bentrok")
    exec(src[awal:src.index("\ndef ", awal + 10)], ns)

    antre = iter(jawaban)
    log = []
    hasil = ns["_tangani_bentrok"](
        data, log.append, lambda: next(antre, ""), log.append
    )
    return hasil, log


EVENT_BENTROK = [{
    "id": "1", "summary": "buku",
    "start": {"dateTime": "2026-09-02T23:00:00+07:00"},
    "end": {"dateTime": "2026-09-03T00:00:00+07:00"},
}]


def test_bentrok_menawarkan_pilihan(monkeypatch):
    data = {"aksi": "catat", "kegiatan": "nonton netflix",
            "tanggal": "2026-09-02", "jam": "23:00"}
    hasil, log = _jalankan_bentrok(monkeypatch, ["tetap saja"], data, EVENT_BENTROK)

    assert hasil is True
    gabung = " ".join(log).lower()
    assert "buku" in gabung          # sebutkan jadwal yang bertabrakan
    assert "ganti" in gabung         # tawarkan mengganti jam
    assert "batalkan" in gabung      # tawarkan membatalkan


def test_bentrok_bisa_dibatalkan(monkeypatch):
    data = {"aksi": "catat", "kegiatan": "nonton netflix",
            "tanggal": "2026-09-02", "jam": "23:00"}
    hasil, _ = _jalankan_bentrok(monkeypatch, ["batalkan"], data, EVENT_BENTROK)
    assert hasil is False


def test_bentrok_bisa_ganti_jam_di_tempat(monkeypatch):
    """
    Menyebut jam baru langsung saat ditanya — tanpa mengulang seluruh
    perintah dari awal.
    """
    data = {"aksi": "catat", "kegiatan": "nonton netflix",
            "tanggal": "2026-09-02", "jam": "23:00"}
    hasil, _ = _jalankan_bentrok(
        monkeypatch, ["jamnya jadi jam 9 malam"], data, EVENT_BENTROK
    )
    assert hasil is True
    assert data["jam"] == "21:00"     # tidak lagi bentrok


def test_tanpa_bentrok_tidak_bertanya(monkeypatch):
    data = {"aksi": "catat", "kegiatan": "nonton netflix",
            "tanggal": "2026-09-02", "jam": "09:00"}
    hasil, log = _jalankan_bentrok(monkeypatch, [], data, EVENT_BENTROK)

    assert hasil is True
    assert log == [], "jangan bertanya kalau tidak ada yang bertabrakan"


# =========================================================================
# Sprint 3.30 — hapus massal, edit jadwal, batal langsung
# =========================================================================

@pytest.mark.parametrize("jawaban", [
    "Batalkan", "batalkan.", "batal", "jangan", "gak jadi", "lupakan",
])
def test_batal_tegas_langsung_batal(jawaban):
    """
    'Batalkan' itu perintah, bukan keberatan atas satu detail. Menanyakan
    'bagian mana yang salah' setelah itu terasa seperti tidak mendengarkan.
    """
    from src.dialog.confirmation import konfirmasi_dengan_koreksi

    data = {"kegiatan": "buku", "tanggal": "2026-09-04", "jam": "23:00"}
    log = []
    hasil = konfirmasi_dengan_koreksi(
        data, lambda: "Pindahkan buku?", log.append, lambda: jawaban, use_llm=False
    )
    assert hasil is False
    assert not any("Bagian mana" in l for l in log)


def test_tidak_biasa_masih_ditanya_bagian_mana():
    """'Tidak' saja belum tentu ingin membatalkan — mungkin satu field keliru."""
    from src.dialog.confirmation import konfirmasi_dengan_koreksi

    data = {"kegiatan": "buku", "tanggal": "2026-09-04", "jam": "23:00"}
    jawaban = iter(["tidak", "jamnya jadi jam 9 malam", "ya"])
    log = []
    hasil = konfirmasi_dengan_koreksi(
        data, lambda: "Pindahkan buku?", log.append,
        lambda: next(jawaban, ""), use_llm=False,
    )
    assert hasil is True
    assert data["jam"] == "21:00"
    assert any("Bagian mana" in l for l in log)


# --- Hapus massal ---------------------------------------------------------
@pytest.mark.parametrize("kalimat,semua", [
    ("Hapus seluruh jadwal saya.", True),
    ("hapus semua jadwal", True),
    ("hapus jadwal rapat divisi", False),
    ("hapus jadwal tanggal 5", False),
])
def test_deteksi_hapus_semua(kalimat, semua):
    assert parse_command(kalimat, use_slm=False)["hapus_semua"] is semua


def test_kata_seluruh_bukan_nama_kegiatan():
    """Dulu jadi kegiatan 'seluruh', lalu dicari dan tentu tidak ketemu."""
    data = parse_command("Hapus seluruh jadwal saya.", use_slm=False)
    assert data["kegiatan"] is None


def test_hapus_dalam_rentang():
    data = parse_command("hapus semua jadwal minggu depan", use_slm=False)
    assert data["aksi"] == "hapus"
    assert data["label_rentang"] == "minggu depan"
    assert data["tanggal_mulai"] and data["tanggal_akhir"]


def test_kandidat_hapus_semua_ambil_semua_event(monkeypatch):
    from src.calendar_service.executor import cari_kandidat

    _kalender_palsu([
        {"id": "1", "summary": "a", "start": {"dateTime": "2026-09-03T09:00:00+07:00"}},
        {"id": "2", "summary": "b", "start": {"dateTime": "2026-09-04T10:00:00+07:00"}},
    ], monkeypatch)

    hasil = cari_kandidat({"aksi": "hapus", "hapus_semua": True, "kegiatan": None})
    assert len(hasil) == 2


def test_hapus_semua_masih_bisa_disaring_nama(monkeypatch):
    """'hapus semua rapat' — massal, tapi tetap hanya yang bernama rapat."""
    from src.calendar_service.executor import cari_kandidat

    _kalender_palsu([
        {"id": "1", "summary": "rapat divisi", "start": {"dateTime": "2026-09-03T09:00:00+07:00"}},
        {"id": "2", "summary": "kondangan", "start": {"dateTime": "2026-09-04T10:00:00+07:00"}},
    ], monkeypatch)

    hasil = cari_kandidat({"aksi": "hapus", "hapus_semua": True, "kegiatan": "rapat"})
    assert [e["summary"] for e in hasil] == ["rapat divisi"]


def test_hapus_banyak_lapor_yang_gagal(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("src.calendar_service.crud")

    def delete_event(eid):
        if eid == "2":
            raise RuntimeError("gagal")

    fake.delete_event = delete_event
    monkeypatch.setitem(sys.modules, "src.calendar_service.crud", fake)

    from src.calendar_service.executor import hapus_banyak

    hasil = hapus_banyak([{"id": "1", "summary": "a"}, {"id": "2", "summary": "b"}])
    assert "1 jadwal sudah dihapus" in hasil["message"]
    assert "1 gagal" in hasil["message"]


def test_hapus_massal_konfirmasi_jumlah_bukan_pilih_satu():
    """
    Untuk 20 jadwal, meminta user memilih satu per satu tidak masuk akal —
    yang benar adalah mengonfirmasi jumlahnya sekali.
    """
    src = open("src/app.py", encoding="utf-8").read()
    awal = src.index("def _proses_aksi_berisiko")
    blok = src[awal:src.index("\ndef ", awal + 10)]
    assert blok.index("hapus_banyak") < blok.index("pilih_kandidat")


# --- Edit jadwal ----------------------------------------------------------
@pytest.mark.parametrize("kalimat", [
    "edit jadwal saya",
    "ubah nama jadwal rapat",
    "sunting jadwal besok",
])
def test_intent_edit_dikenali(kalimat):
    assert classify_intent_keyword(kalimat) == "edit"


def test_edit_tidak_butuh_field_di_awal():
    """AKIRA mencari jadwalnya dulu, baru bertanya apa yang mau diubah."""
    from src.dialog.state_machine import check_missing_fields

    assert check_missing_fields({"aksi": "edit", "kegiatan": None}) == []


def test_ubah_event_menyusun_patch_benar(monkeypatch):
    import sys
    import types

    dikirim = {}
    fake = types.ModuleType("src.calendar_service.crud")
    fake.update_event = lambda eid, body: dikirim.update(body) or {"id": eid}
    monkeypatch.setitem(sys.modules, "src.calendar_service.crud", fake)

    from src.calendar_service.executor import ubah_event

    event = {
        "id": "1", "summary": "rapat",
        "start": {"dateTime": "2026-09-03T09:00:00+07:00"},
    }
    hasil = ubah_event(event, {"kegiatan": "rapat divisi", "jam": "14:00"})

    assert hasil["success"] is True
    assert dikirim["summary"] == "rapat divisi"
    assert dikirim["start"]["dateTime"].endswith("T14:00:00")


def test_ubah_event_tanpa_perubahan_ditolak(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("src.calendar_service.crud")
    fake.update_event = lambda eid, body: {}
    monkeypatch.setitem(sys.modules, "src.calendar_service.crud", fake)

    from src.calendar_service.executor import ubah_event

    hasil = ubah_event({"id": "1", "summary": "rapat"}, {})
    assert hasil["success"] is False


def test_update_event_memakai_patch_bukan_update():
    """
    patch() hanya mengubah field yang dikirim. update() menimpa seluruh event,
    dan pengingat khusus yang sudah dipasang akan hilang.
    """
    src = open("src/calendar_service/crud.py", encoding="utf-8").read()
    awal = src.index("def update_event")
    blok = src[awal:src.index("\ndef ", awal + 10)]
    assert ".patch(" in blok


# =========================================================================
# Sprint 3.31 — hapus yang masuk akal
# =========================================================================

def test_konteks_tidak_menimpa_perintah_bertanggal():
    """
    'hapus jadwal hari ini' berarti jadwal DI HARI ITU — bukan jadwal yang
    kebetulan barusan dibicarakan. Dulu konteks menimpanya dan AKIRA
    menawarkan menghapus event yang salah.
    """
    from src.dialog.context import KonteksSesi, resolusi_rujukan

    konteks = KonteksSesi()
    konteks.catat_event([{"summary": "belajar", "id": "1"}])

    data = {"aksi": "hapus", "kegiatan": None, "tanggal": "2026-09-02",
            "teks_asli": "hapus jadwal hari ini"}
    assert resolusi_rujukan(data, konteks)["kegiatan"] is None


def test_konteks_tidak_menimpa_hapus_semua():
    from src.dialog.context import KonteksSesi, resolusi_rujukan

    konteks = KonteksSesi()
    konteks.catat_event([{"summary": "belajar", "id": "1"}])

    data = {"aksi": "hapus", "kegiatan": None, "hapus_semua": True,
            "teks_asli": "hapus seluruh jadwal"}
    assert resolusi_rujukan(data, konteks)["kegiatan"] is None


def test_rujukan_tanpa_tanggal_tetap_pakai_konteks():
    """Yang tanpa sasaran sendiri tetap boleh mengambil dari konteks."""
    from src.dialog.context import KonteksSesi, resolusi_rujukan

    konteks = KonteksSesi()
    konteks.catat_event([{"summary": "belajar", "id": "1"}])

    data = {"aksi": "hapus", "kegiatan": None, "teks_asli": "hapus jadwal tersebut"}
    assert resolusi_rujukan(data, konteks)["kegiatan"] == "belajar"


def test_hapus_semua_dibatasi_tanggal(monkeypatch):
    """
    'hapus seluruh jadwal MALAM INI' = semua jadwal hari itu, bukan seluruh
    isi kalender. Tanpa penjagaan ini satu kalimat bisa menghapus 32 event.
    """
    from src.calendar_service.executor import cari_kandidat

    _kalender_palsu([
        {"id": "1", "summary": "netflix", "start": {"dateTime": "2026-09-02T23:00:00+07:00"}},
        {"id": "2", "summary": "belajar", "start": {"dateTime": "2026-09-02T23:59:00+07:00"}},
        {"id": "3", "summary": "ultah", "start": {"date": "2026-11-17"}},
    ], monkeypatch)

    hasil = cari_kandidat({
        "aksi": "hapus", "hapus_semua": True,
        "tanggal": "2026-09-02", "kegiatan": None,
    })
    assert {e["summary"] for e in hasil} == {"netflix", "belajar"}


# --- Memilih semua kandidat ----------------------------------------------
@pytest.mark.parametrize("jawaban", [
    "dua-duanya dihapus", "semuanya", "keduanya", "ketiganya", "tiga-tiganya",
])
def test_pilih_semua_kandidat(jawaban):
    from src.dialog.confirmation import SEMUA_KANDIDAT, tafsir_pilihan

    assert tafsir_pilihan(jawaban, 3) == SEMUA_KANDIDAT


@pytest.mark.parametrize("jawaban,indeks", [
    ("nomor dua", 1),
    ("yang kedua", 1),
    ("yang ketiga", 2),
    ("2", 1),
])
def test_pilih_satu_tetap_satu(jawaban, indeks):
    """
    'yang ketiga' berarti nomor 3, 'ketiganya' berarti semuanya.
    Salah membedakan berarti menghapus tiga jadwal padahal diminta satu.
    """
    from src.dialog.confirmation import tafsir_pilihan

    assert tafsir_pilihan(jawaban, 3) == indeks


def test_pilih_semua_hanya_untuk_hapus():
    """Reschedule dan edit butuh satu jadwal — 'semuanya' tidak masuk akal."""
    src = open("src/app.py", encoding="utf-8").read()
    awal = src.index("if indeks == SEMUA_KANDIDAT:")
    blok = src[awal:awal + 400]
    assert 'data["aksi"] != "hapus"' in blok


# --- Variasi salah dengar nama -------------------------------------------
@pytest.mark.parametrize("kalimat", [
    "Akhirnya hapus jadwal hari ini",
    "Akhir ya bacakan jadwal saya",
    "Kira-kira cek jadwal besok",
    "akir tolong catat rapat besok",
])
def test_varian_salah_dengar_tetap_memicu(kalimat):
    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["perintah_untuk_akira"](kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "akhirnya selesai juga tugasnya",
    "akhirnya dia dateng",
    "hapus jadwal hari ini",          # tanpa menyebut AKIRA
])
def test_varian_tanpa_niat_perintah_tidak_memicu(kalimat):
    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["perintah_untuk_akira"](kalimat) is False


# =========================================================================
# Sprint 3.32 — "dipindahkan" mengandung "dah"
# =========================================================================

def _muat_is_penutup():
    """Ambil is_penutup beserta dependensinya tanpa mengimpor app.py penuh."""
    import re as _re

    src = open("src/app.py", encoding="utf-8").read()
    ns = {"re": _re}
    exec(src[src.index("KATA_PENUTUP = ["):src.index("# Jawaban menolak")], ns)
    exec(src[src.index("NIAT_PERINTAH = re.compile("):src.index("def disapa_akira")], ns)
    exec(src[src.index("_PENUTUP_RE = re.compile("):src.index("def _proses_aksi_berisiko")], ns)
    return ns["is_penutup"]


@pytest.mark.parametrize("kalimat", [
    # Kasus nyata dari log: "dipindahkan" mengandung "dah", dan seluruh
    # perintah reschedule berubah jadi perintah menutup sesi.
    "Jadwal besok, kondangan dipindahkan ke hari ini nanti jam 3 sore.",
    "pindahkan rapat ke besok",
    "jadwal dipindahkan ke tanggal 5",
    # "istirahat" ada di daftar penutup, tapi di sini nama kegiatan
    "catat jadwal istirahat siang besok jam 12",
    # "cukup" sebagai bagian kata lain
    "catat rapat kalau waktunya mencukupi",
])
def test_perintah_tidak_salah_dibaca_sebagai_penutup(kalimat):
    assert _muat_is_penutup()(kalimat) is False


@pytest.mark.parametrize("kalimat", [
    "makasih", "terima kasih", "udah", "cukup", "selesai",
    "stop", "bye", "oke terima kasih", "sampai jumpa",
])
def test_pamit_asli_tetap_menutup_sesi(kalimat):
    assert _muat_is_penutup()(kalimat) is True


def test_pencocokan_penutup_pakai_batas_kata():
    """
    Kata pendek seperti 'dah', 'stop', dan 'cukup' sangat rawan pada
    pencocokan substring. Batas kata wajib.
    """
    src = open("src/app.py", encoding="utf-8").read()
    awal = src.index("def is_penutup")
    blok = src[awal:src.index("\ndef ", awal + 10)]
    assert "_PENUTUP_RE.search" in blok
    assert "any(k in t for k in KATA_PENUTUP)" not in blok


def test_semua_pencocokan_kata_kunci_pakai_batas_kata():
    """
    Pemeriksaan menyeluruh: tidak boleh ada lagi pencocokan substring
    pada daftar kata kunci di seluruh modul.
    """
    import glob
    import re as _re

    pelanggaran = []
    for path in glob.glob("src/**/*.py", recursive=True):
        isi = open(path, encoding="utf-8").read()
        for m in _re.finditer(r"any\(\s*(\w+)\s+in\s+(\w+)\s+for\s+\1\s+in\s+(KATA_\w+)", isi):
            baris = isi[:m.start()].count("\n") + 1
            pelanggaran.append(f"{path}:{baris} — {m.group(3)}")

    assert not pelanggaran, "pencocokan substring pada kata kunci:\n  " + "\n  ".join(pelanggaran)


def test_tidak_ada_tanggal_tanpa_tahun_di_input_test():
    """
    Cegah test yang membusuk seiring berjalannya waktu.

    Sudah empat kali test gagal bukan karena kode rusak, melainkan karena
    input seperti "tanggal 5 september" berpindah tahun begitu hari ini
    melewati tanggal itu. Kegagalan seperti ini menyita waktu untuk
    memastikan bahwa memang bukan regresi.

    Yang diperiksa HANYA baris yang memanggil fungsi penyelesai tanggal.
    Teks keluaran yang diharapkan (mis. "10 September jam 14:00") tidak
    mengalami penyelesaian tahun, jadi aman tanpa tahun.
    """
    import re as _re

    bulan = ("januari|februari|maret|april|mei|juni|juli|agustus|"
             "september|oktober|november|desember")
    # Fungsi yang menyelesaikan tahun dari tanggal tanpa tahun
    pemanggil = _re.compile(
        r"\b(?:parse_command|parse_date_id|parse_date_range_id|"
        r"merge_answer|parse_koreksi|_jalankan_konfirmasi)\b"
    )

    pelanggaran = []
    for i, baris in enumerate(open(__file__, encoding="utf-8").read().splitlines(), 1):
        bersih = baris.strip()
        if bersih.startswith("#") or not pemanggil.search(bersih):
            continue
        # Waktu acuan tetap membuat hasilnya tidak bergantung hari ini
        if "REF" in baris or "_dt(" in baris or "datetime(" in baris:
            continue
        if _re.search(rf"\b\d{{1,2}}\s+({bulan})\b(?!\s+\d{{4}})", bersih, _re.I):
            pelanggaran.append(f"baris {i}: {bersih[:70]}")

    assert not pelanggaran, (
        "tanggal tanpa tahun pada INPUT test — akan gagal sendiri saat "
        "tanggal itu terlewat. Tambahkan tahun eksplisit atau pakai REF:\n  "
        + "\n  ".join(pelanggaran)
    )


# =========================================================================
# Sprint 4 — antarmuka grafis
# =========================================================================

def test_berkas_gui_ada():
    import os

    for f in ["akira_app.py", "src/gui/runner.py", "src/gui/tema.py", "src/gui/hotkeys.py"]:
        assert os.path.exists(f), f"{f} tidak ada"


def test_gui_tidak_memanggil_run_secara_langsung():
    """
    app.run() adalah loop tak berujung. Memanggilnya dari thread Tkinter
    membekukan jendela total — Windows menandainya "Not Responding".
    """
    src = open("akira_app.py", encoding="utf-8").read()
    assert "from src.app import run" not in src
    assert "runner" in src


def test_runner_memakai_thread_daemon():
    """Tanpa daemon, proses Python tetap hidup setelah jendela ditutup."""
    src = open("src/gui/runner.py", encoding="utf-8").read()
    assert "daemon=True" in src


def test_pekerjaan_lambat_tidak_di_thread_tkinter():
    """
    Pemanggilan jaringan/model wajib lewat _di_latar(). Kalau tidak,
    jendela membeku beberapa detik tiap tombol ditekan.
    """
    import re as _re

    src = open("akira_app.py", encoding="utf-8").read()
    for nama in ("_periksa", "_uji_mic", "_muat_jadwal", "_hapus_jadwal",
                 "_urai_perintah", "_kirim_diam"):
        awal = src.index(f"def {nama}(")
        blok = src[awal:src.index("\n    def ", awal + 10)]
        assert "_di_latar(" in blok, f"{nama}() memblokir antarmuka"


def test_antrean_log_dibatasi():
    """Antrean tak terbatas akan membocorkan memori bila antarmuka tertinggal."""
    from src.gui.runner import antrean_log

    assert antrean_log.maxsize > 0


def test_aksi_destruktif_tidak_lewat_kotak_ketik():
    """
    Hapus/reschedule/edit menuntut konfirmasi lisan. Menjalankannya dari
    kotak teks berarti melewati pengaman yang sengaja dibangun.
    """
    src = open("akira_app.py", encoding="utf-8").read()
    awal = src.index("def _kirim_diam(")
    blok = src[awal:src.index("\n    def ", awal + 10)]
    assert '"hapus", "reschedule", "edit"' in blok


def test_peluncur_aplikasi_ada():
    import os

    assert os.path.exists("scripts/buka_aplikasi.bat")


def test_peluncur_tidak_menyembunyikan_error():
    """
    pythonw.exe menyembunyikan jendela DAN pesan error. Kalau aplikasi gagal
    start, klik ganda tidak menghasilkan apa-apa dan tidak ada petunjuk
    kenapa — kegagalan paling membingungkan untuk dilacak.
    """
    # Baris komentar dibuang dulu — kata "pythonw" memang disebut di
    # penjelasan, justru untuk menerangkan kenapa TIDAK dipakai.
    perintah = "\n".join(
        b for b in open("scripts/buka_aplikasi.bat", encoding="utf-8").read().splitlines()
        if not b.strip().lower().startswith(("rem", "::"))
    )
    assert "pythonw" not in perintah
    assert "pause" in perintah


# =========================================================================
# Sprint 4.1 — pintasan keyboard & aksi cepat
# =========================================================================

def test_app_tidak_mengimpor_gui():
    """
    app.py tidak boleh bergantung pada modul gui/. Kalau ia melakukannya,
    menjalankan AKIRA lewat terminal ikut memuat Tkinter — dan di mesin
    tanpa tampilan grafis, itu gagal total.
    """
    src = open("src/app.py", encoding="utf-8").read()
    assert "from src.gui" not in src
    assert "import src.gui" not in src
    assert "from src.utils import trigger" in src


def test_pemicu_diperiksa_sebelum_wake_word():
    """
    Kalau pemicu diperiksa setelah mendengarkan, permintaan dari antarmuka
    baru terbaca ketika mikrofon selesai — bisa beberapa detik.
    """
    src = open("src/app.py", encoding="utf-8").read()
    assert src.index("trigger.ada_pemicu()") < src.index("terpicu = listen_for_wakeword")


def test_wake_word_bisa_diinterupsi():
    """
    listen_for_wakeword memblokir selamanya. Tanpa hook interupsi, pemicu
    dari antarmuka tidak akan PERNAH terbaca.
    """
    src = open("src/wakeword/detector.py", encoding="utf-8").read()
    assert "interupsi" in src

    app = open("src/app.py", encoding="utf-8").read()
    assert "interupsi=trigger.ada_pemicu" in app


def test_alur_pemicu_dengar():
    from src.utils import trigger

    trigger.bersihkan()
    assert trigger.ada_pemicu() is False

    trigger.picu_dengar(sumber="uji")
    assert trigger.ada_pemicu() is True

    p = trigger.ambil()
    assert p.jenis == "dengar"
    assert p.sumber == "uji"
    assert trigger.ada_pemicu() is False


def test_alur_pemicu_perintah():
    from src.utils import trigger

    trigger.bersihkan()
    trigger.picu_perintah("bacakan jadwal besok", sumber="pintasan")

    p = trigger.ambil()
    assert p.jenis == "perintah"
    assert p.perintah == "bacakan jadwal besok"
    trigger.bersihkan()


def test_pemicu_kosong_diabaikan():
    from src.utils import trigger

    trigger.bersihkan()
    trigger.picu_perintah("   ")
    assert trigger.ada_pemicu() is False


def test_antrean_pemicu_berurutan():
    from src.utils import trigger

    trigger.bersihkan()
    for t in ("satu", "dua", "tiga"):
        trigger.picu_perintah(t)

    assert [trigger.ambil().perintah for _ in range(3)] == ["satu", "dua", "tiga"]
    assert trigger.ambil() is None
    trigger.bersihkan()


# --- Pemasangan pintasan --------------------------------------------------
def test_pintasan_wajib_pakai_modifier():
    """
    Tanpa Ctrl/Alt/Shift, menekan "a" saat mengetik di aplikasi lain akan
    membangunkan AKIRA.
    """
    from src.gui.hotkeys import validasi

    assert validasi("a", "catat", {})[0] is False
    assert validasi("f5", "catat", {})[0] is False
    assert validasi("ctrl+alt+z", "catat", {})[0] is True


def test_pintasan_bentrok_ditolak():
    from src.gui.hotkeys import validasi

    boleh, pesan = validasi("ctrl+alt+a", "hapus", {"dengar": "ctrl+alt+a"})
    assert boleh is False
    assert "Dengarkan" in pesan


def test_semua_aksi_pintasan_punya_kalimat_atau_khusus():
    """
    Tiap aksi harus punya kalimat perintah, kecuali dua yang memang bukan
    perintah: 'dengar' dan 'buka_jendela'.
    """
    from src.gui.hotkeys import AKSI_PINTASAN, KALIMAT_AKSI

    for aksi in AKSI_PINTASAN:
        if aksi in ("dengar", "buka_jendela", "bantu"):
            continue
        assert aksi in KALIMAT_AKSI, f"aksi '{aksi}' tidak punya kalimat"


def test_kalimat_pintasan_terklasifikasi_benar():
    """Kalimat yang dikirim pintasan harus dikenali pengklasifikasi intent."""
    from src.gui.hotkeys import KALIMAT_AKSI

    harapan = {
        "baca_hari_ini": "baca", "baca_besok": "baca", "catat": "catat",
        "hapus": "hapus", "reschedule": "reschedule", "edit": "edit",
        "jam_berapa": "waktu",
    }
    for aksi, kalimat in KALIMAT_AKSI.items():
        assert classify_intent_keyword(normalize(kalimat)) == harapan[aksi], (
            f"'{kalimat}' tidak terbaca sebagai {harapan[aksi]}"
        )


def test_format_tkinter():
    from src.gui.hotkeys import ke_format_tkinter

    assert ke_format_tkinter("ctrl+alt+a") == "<Control-Alt-a>"
    assert ke_format_tkinter("ctrl+shift+h") == "<Control-Shift-h>"


def test_pintasan_global_gagal_tidak_fatal(monkeypatch):
    """
    Pustaka 'keyboard' opsional. Ketidakhadirannya harus melaporkan pesan,
    bukan melempar exception — pintasan dalam jendela tetap berfungsi.
    """
    import builtins

    asli = builtins.__import__

    def tolak_keyboard(nama, *a, **k):
        if nama == "keyboard":
            raise ImportError("tidak ada")
        return asli(nama, *a, **k)

    monkeypatch.setattr(builtins, "__import__", tolak_keyboard)

    from src.gui.hotkeys import pasang_global

    berhasil, pesan = pasang_global({"dengar": "ctrl+alt+a"})
    assert berhasil is False
    assert "keyboard" in pesan


def test_pintasan_rusak_pakai_bawaan(tmp_path, monkeypatch):
    from src.gui import hotkeys

    berkas = tmp_path / "rusak.json"
    berkas.write_text("{ bukan json", encoding="utf-8")
    monkeypatch.setattr(hotkeys, "PATH_PINTASAN", str(berkas))

    assert hotkeys.muat() == hotkeys.BAWAAN


def test_tombol_aksi_cepat_ada_untuk_tiap_crud():
    """
    Empat operasi CRUD harus punya tombol satu klik.

    Diperiksa dari daftar tombol di dalam _isi_tab_pintasan(), bukan dari
    seluruh berkas — mencari string di mana saja akan lolos hanya karena
    kata itu muncul di komentar.
    """
    src = open("akira_app.py", encoding="utf-8").read()
    awal = src.index("def _isi_tab_pintasan")
    blok = src[awal:src.index("\n    def ", awal + 10)]

    for aksi in ("catat", "hapus", "reschedule", "edit", "dengar",
                 "baca_hari_ini", "baca_besok", "jam_berapa"):
        assert f'"{aksi}"' in blok, f"tombol aksi cepat '{aksi}' tidak ada"


# =========================================================================
# Sprint 4.2 — pintasan tidak terproses & perombakan tampilan
# =========================================================================

def test_pemicu_diperiksa_sebelum_blok_ambient():
    """
    Blok mode ambient SELALU berakhir dengan `continue`. Pemeriksaan pemicu
    yang ditaruh sesudahnya tidak akan pernah tercapai selama ambient aktif —
    dan ambient aktif tiap kali AKIRA baru selesai dipakai.

    Gejalanya persis seperti di log: pintasan tercatat, tapi tidak terjadi
    apa-apa.
    """
    src = open("src/app.py", encoding="utf-8").read()
    i_pemicu = src.index("if trigger.ada_pemicu():")
    i_ambient = src.index("if ambient_aktif and pernah_dibangunkan:")
    assert i_pemicu < i_ambient, "pemicu harus diperiksa SEBELUM blok ambient"


def test_ambient_menghormati_pemicu_di_tengah_rekaman():
    """Pemicu yang datang saat ambient merekam tidak boleh menunggu selesai."""
    src = open("src/app.py", encoding="utf-8").read()
    awal = src.index("jenis, isi = _dengar_ambient(")
    assert "trigger.ada_pemicu()" in src[awal:awal + 500]


@pytest.mark.parametrize("kalimat", [
    "Akhirnya, wake up.",      # salah dengar yang nyata muncul di log
    "Akira wake up.",
    "Akhirnya wake up",
])
def test_frasa_bangun_dari_teks(kalimat):
    """
    Di mode ambient, "AKIRA WAKE UP" sering tertulis "Akhirnya wake up" dan
    tidak memicu apa pun karena "wake up" bukan kata perintah jadwal.
    """
    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["minta_bangun"](kalimat) is True


@pytest.mark.parametrize("kalimat", [
    "Kira-kira",
    "akhirnya selesai juga tugasnya",
    "wake up",                 # tanpa menyebut AKIRA
])
def test_bukan_frasa_bangun(kalimat):
    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["minta_bangun"](kalimat) is False


def test_pemicu_ganda_diabaikan():
    """Klik dua kali tidak boleh menjalankan perintah yang sama dua kali."""
    from src.utils import trigger

    trigger.bersihkan()
    for _ in range(3):
        trigger.picu_perintah("bacakan jadwal hari ini")
    assert len(trigger._antrean_perintah) == 1
    trigger.bersihkan()


def test_pemicu_berbeda_tidak_diabaikan():
    from src.utils import trigger

    trigger.bersihkan()
    trigger.picu_perintah("bacakan jadwal hari ini")
    trigger.picu_perintah("bacakan jadwal besok")
    assert len(trigger._antrean_perintah) == 2
    trigger.bersihkan()


# --- Tema visual ----------------------------------------------------------
def test_modul_tema_ada():
    import os

    assert os.path.exists("src/gui/tema.py")


def test_tombol_punya_tepi_yang_terlihat():
    """
    Tema clam menggambar tepi dari TIGA properti: bordercolor, lightcolor,
    dan darkcolor. Mengatur bordercolor saja membuat tombol tampak seperti
    teks biasa — orang tidak tahu itu bisa diklik.
    """
    src = open("src/gui/tema.py", encoding="utf-8").read()
    awal = src.index('gaya.configure("TButton"')
    blok = src[awal:awal + 400]
    for properti in ("bordercolor", "lightcolor", "darkcolor"):
        assert properti in blok, f"TButton tanpa {properti} — tepinya tak terlihat"


def test_tema_memakai_clam():
    """Satu-satunya tema ttk bawaan yang menghormati warna kustom di Windows."""
    src = open("src/gui/tema.py", encoding="utf-8").read()
    assert 'theme_use("clam")' in src


def test_aplikasi_memakai_tema():
    src = open("akira_app.py", encoding="utf-8").read()
    assert "from src.gui.tema import" in src
    assert "pasang_tema(self)" in src


def test_hierarki_font_lengkap():
    """Judul, isi, dan keterangan harus jelas berbeda ukurannya."""
    src = open("src/gui/tema.py", encoding="utf-8").read()
    for nama in ("judul", "subjudul", "isi", "kecil", "mono"):
        assert f'"{nama}"' in src


# =========================================================================
# Sprint 4.3 — pintasan saat sesi sedang berjalan
# =========================================================================

def test_pemicu_diperiksa_di_dalam_sesi():
    """
    Pintasan yang ditekan SAAT sesi berjalan harus langsung dijalankan.
    Tanpa ini, perintahnya menunggu sesi berakhir karena kehabisan waktu
    diam — di log terpantau 14 detik, dan terasa seperti tombol rusak.
    """
    src = open("src/app.py", encoding="utf-8").read()
    awal = src.index("# --- Loop percakapan: banyak perintah dalam satu sesi")
    blok = src[awal:awal + 1400]
    assert "trigger.ada_pemicu()" in blok
    assert "pemicu.perintah" in blok


def test_perekaman_bisa_diinterupsi():
    """
    Perekaman memblokir sampai ada suara atau waktu habis. Tanpa hook
    interupsi, pemicu tetap tertahan meski sudah diperiksa di loop sesi.
    """
    src = open("src/audio/recorder.py", encoding="utf-8").read()
    assert "interupsi" in src

    awal = src.index("while len(frames) < max_frames:")
    assert "interupsi()" in src[awal:awal + 500], "interupsi harus dicek di dalam loop"

    app = open("src/app.py", encoding="utf-8").read()
    assert app.count("interupsi=trigger.ada_pemicu") >= 2


def test_interupsi_hanya_sebelum_bicara():
    """
    Memotong di tengah kalimat akan membuang ucapan yang sudah separuh
    terekam. Interupsi hanya berlaku selama belum ada suara.
    """
    src = open("src/audio/recorder.py", encoding="utf-8").read()
    awal = src.index("while len(frames) < max_frames:")
    assert "not speech_started" in src[awal:awal + 400]


def test_pemicu_kedaluwarsa_dibuang():
    """
    User yang menekan beberapa tombol karena mengira tidak berfungsi tidak
    bermaksud menjalankan semuanya sekaligus setelah sesi selesai.
    """
    import time as _t

    from src.utils import trigger

    trigger.bersihkan()
    asli = trigger.UMUR_MAKS_DETIK
    try:
        trigger.picu_perintah("perintah lama")
        trigger.UMUR_MAKS_DETIK = 0.3
        _t.sleep(0.5)
        trigger.picu_perintah("perintah baru")

        diambil = trigger.ambil()
        assert diambil.perintah == "perintah baru"
        assert trigger.ambil() is None
    finally:
        trigger.UMUR_MAKS_DETIK = asli
        trigger.bersihkan()


def test_pemicu_segar_tidak_dibuang():
    from src.utils import trigger

    trigger.bersihkan()
    trigger.picu_perintah("masih segar")
    assert trigger.ambil().perintah == "masih segar"
    trigger.bersihkan()


# =========================================================================
# Sprint 4.4 — penalaran sapaan & perintah ketik bersuara
# =========================================================================

def test_sapaan_tanpa_kata_perintah_lewat_llm(monkeypatch):
    """
    "Kira tolong bantu saya" jelas ditujukan ke AKIRA, tapi tidak memuat
    satu pun kata seperti "jadwal" atau "catat" — lapis kata kunci menyerah.
    """
    import src.nlp.groq_reasoner as gr

    monkeypatch.setattr(gr, "untuk_akira_groq",
                        lambda t: (True, "minta bantuan"))

    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["perintah_untuk_akira"]("Kira tolong bantu saya") is True


def test_kata_kunci_tidak_memanggil_llm(monkeypatch):
    """LLM hanya dipakai saat kata kunci menyerah — bukan di setiap kalimat."""
    import src.nlp.groq_reasoner as gr

    dipanggil = []
    monkeypatch.setattr(gr, "untuk_akira_groq",
                        lambda t: dipanggil.append(t) or (True, None))

    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["perintah_untuk_akira"]("akira bacakan jadwal saya") is True
    assert dipanggil == []


def test_tanpa_nama_tidak_pernah_lewat_llm(monkeypatch):
    """Nama AKIRA wajib ada — tanpa itu, LLM tidak perlu ditanya sama sekali."""
    import src.nlp.groq_reasoner as gr

    dipanggil = []
    monkeypatch.setattr(gr, "untuk_akira_groq",
                        lambda t: dipanggil.append(t) or (True, None))

    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["perintah_untuk_akira"]("tolong bantu saya") is False
    assert dipanggil == []


def test_llm_menolak_obrolan_biasa(monkeypatch):
    import src.nlp.groq_reasoner as gr

    monkeypatch.setattr(gr, "untuk_akira_groq",
                        lambda t: (False, "obrolan antar-orang"))

    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["perintah_untuk_akira"]("kira-kira dia jadi datang nggak") is False


def test_llm_gagal_tidak_membangunkan(monkeypatch):
    """
    Kalau penalaran error, AKIRA harus diam. Menyahut obrolan orang lain
    lebih mengganggu daripada melewatkan satu panggilan.
    """
    import src.nlp.groq_reasoner as gr

    def meledak(_t):
        raise RuntimeError("jaringan mati")

    monkeypatch.setattr(gr, "untuk_akira_groq", meledak)

    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["perintah_untuk_akira"]("Kira tolong bantu saya") is False


def test_penalaran_bisa_dimatikan():
    """Pemanggil boleh melewati LLM — dipakai test dan jalur offline."""
    ns = _muat_helper_app("VARIAN_AKIRA =", "KATA_NEGATIF")
    assert ns["perintah_untuk_akira"]("Kira tolong bantu saya", pakai_llm=False) is False


# --- Perintah ketik bersuara ---------------------------------------------
def test_perintah_ketik_punya_pilihan_suara():
    src = open("akira_app.py", encoding="utf-8").read()
    assert "pakai_suara" in src
    assert "Jawab dengan suara" in src


def test_jalur_suara_memakai_saluran_pemicu():
    """
    Dengan suara, perintah harus masuk ke sesi AKIRA — bukan dieksekusi
    diam-diam. Itu yang membuat AKIRA bisa bertanya balik dan menjawab
    lewat speaker.
    """
    src = open("akira_app.py", encoding="utf-8").read()
    awal = src.index("def _kirim_lewat_suara")
    blok = src[awal:src.index("\n    def ", awal + 10)]
    assert "trigger.picu_perintah" in blok


def test_pintasan_bantu_ada():
    """Tombol panggil untuk ruangan bising, saat nama AKIRA tak tertangkap."""
    from src.gui.hotkeys import AKSI_PINTASAN, BAWAAN

    assert "bantu" in AKSI_PINTASAN
    assert "bantu" in BAWAAN


# =========================================================================
# Sprint 4.5 — jawaban ketikan & "N hari dari sekarang"
# =========================================================================

def test_listen_mengembalikan_perintah_ketikan():
    """
    Perekaman dihentikan pemicu, tapi teksnya harus dikembalikan. Tanpa itu
    pemanggil menerima string kosong dan menganggap user diam — di log,
    slot filling bertanya tiga kali padahal jawabannya sudah diketik.
    """
    src = open("src/app.py", encoding="utf-8").read()
    # Potong sampai fungsi berikutnya, bukan sejumlah karakter tetap —
    # jendela tetap patah begitu komentar di dalam fungsinya bertambah.
    awal = src.index("def listen(timeout: float | None = None, jawaban: bool = False) -> str:")
    blok = src[awal:src.index("\n    def ", awal + 10)]

    assert "trigger.ambil()" in blok, "listen() harus mengambil pemicu"
    assert blok.count("return pemicu.perintah") >= 2, (
        "harus ditangani di dua tempat: sebelum merekam, dan setelah "
        "rekaman dihentikan interupsi"
    )


def test_pemicu_dengar_tidak_jadi_jawaban():
    """
    Hanya pemicu jenis 'perintah' yang jadi jawaban. Pemicu 'dengar' berarti
    user ingin bicara — bukan menitipkan teks.
    """
    src = open("src/app.py", encoding="utf-8").read()
    # Potong sampai fungsi berikutnya, bukan sejumlah karakter tetap —
    # jendela tetap patah begitu komentar di dalam fungsinya bertambah.
    awal = src.index("def listen(timeout: float | None = None, jawaban: bool = False) -> str:")
    blok = src[awal:src.index("\n    def ", awal + 10)]
    assert blok.count('pemicu.jenis == "perintah"') >= 2


@pytest.mark.parametrize("kalimat", [
    "512 hari dari sekarang itu hari apa",
    "tolong cek 512 hari dari sekarang itu hari apa ya",
    "512 hari lagi itu hari apa",
    "512 hari dari hari ini",
    "512 hari kemudian",
])
def test_offset_relatif_dihitung(kalimat):
    """
    "dari sekarang" sama artinya dengan "lagi". Sebelumnya bentuk itu tidak
    dikenali dan pertanyaannya dijawab dengan tanggal HARI INI.
    """
    from datetime import datetime as _dt, timedelta as _td

    from src.calendar_service.executor import _handle_waktu

    target = _dt.now() + _td(days=512)
    pesan = _handle_waktu({"teks_asli": kalimat})["message"]
    assert str(target.year) in pesan
    assert str(target.day) in pesan


def test_offset_satuan_lain():
    from datetime import datetime as _dt, timedelta as _td

    from src.nlp.date_time_parser import parse_date_id

    hasil = parse_date_id("3 minggu dari sekarang")
    target = _dt.now() + _td(weeks=3)
    assert hasil.date() == target.date()


def test_pertanyaan_waktu_biasa_tidak_terpengaruh():
    from datetime import datetime as _dt

    from src.calendar_service.executor import _handle_waktu

    pesan = _handle_waktu({"teks_asli": "sekarang jam berapa"})["message"]
    assert "jam" in pesan.lower()

    pesan2 = _handle_waktu({"teks_asli": "sekarang tanggal berapa"})["message"]
    assert str(_dt.now().day) in pesan2


@pytest.mark.parametrize("kalimat,tanggal_ini", [
    ("cek jadwal hari ini", True),
    ("hari ini ada jadwal apa", True),
    ("nanti sore ada jadwal ga", True),
    ("catat rapat hari ini jam 3", True),
])
def test_hari_ini_biasa_tetap_hari_ini(kalimat, tanggal_ini):
    """
    Penjagaan "dari hari ini" tidak boleh merusak pemakaian biasa.
    """
    from datetime import datetime as _dt

    data = parse_command(kalimat, use_slm=False)
    assert data["tanggal"] == _dt.now().strftime("%Y-%m-%d")


def test_dari_hari_ini_bukan_hari_ini():
    """
    Pada "512 hari dari hari ini", frasa "hari ini" cuma titik acuan.
    Menghitungnya sebagai tanggal jawaban membuat pertanyaan dijawab
    dengan tanggal hari ini — persis yang terjadi sebelum diperbaiki.
    """
    from datetime import datetime as _dt, timedelta as _td

    from src.nlp.date_time_parser import parse_date_id

    hasil = parse_date_id("512 hari dari hari ini")
    assert hasil.date() == (_dt.now() + _td(days=512)).date()


# =========================================================================
# Sprint 4.6 — batal di field opsional, kata benda sendirian, jendela ringkas
# =========================================================================

@pytest.mark.parametrize("jawaban", [
    "Batalkan, batalkan semuanya.",
    "batalkan semuanya",
    "batal aja deh",
    "batalkan",
])
def test_batal_dikenali_walau_ada_kata_pengisi(jawaban):
    """
    "batalkan semuanya" tiga kata, dan user sering menegaskan dengan
    mengulang. Kata pengisi tidak boleh membuatnya lolos dari deteksi.
    """
    from src.dialog.state_machine import minta_batal

    assert minta_batal(jawaban) is True


def test_batal_saat_field_opsional_menghentikan_perintah():
    """
    Sebelumnya field opsional mengabaikan pembatalan: "batalkan semuanya"
    gagal diparse sebagai jam, dianggap "lewati", dan perintahnya tetap
    tersimpan. Perintah yang diminta batal justru diteruskan.
    """
    from src.dialog.state_machine import run_optional_filling
    from src.nlp.parser import merge_answer

    data = {"aksi": "catat", "kegiatan": "rapat",
            "tanggal": "2027-09-01", "jam": "21:00"}
    diucapkan = []

    hasil = run_optional_filling(
        data, ask_fn=diucapkan.append,
        listen_fn=lambda: "batalkan, batalkan semuanya", merge_fn=merge_answer,
    )

    assert hasil is None
    assert any("batalkan" in u.lower() for u in diucapkan)


def test_field_opsional_normal_tetap_dilewati():
    from src.dialog.state_machine import run_optional_filling
    from src.nlp.parser import merge_answer

    data = {"aksi": "catat", "kegiatan": "rapat",
            "tanggal": "2027-09-01", "jam": "21:00"}
    hasil = run_optional_filling(
        data, ask_fn=lambda q: None, listen_fn=lambda: "lewati",
        merge_fn=merge_answer,
    )
    assert hasil is not None
    assert hasil.get("_jam_selesai_skipped") or hasil.get("_deskripsi_skipped")


def test_pembatalan_opsional_ditangani_pemanggil():
    """run_optional_filling kini bisa mengembalikan None — caller harus cek."""
    src = open("src/app.py", encoding="utf-8").read()
    awal = src.index("data = run_optional_filling(")
    assert "if data is None:" in src[awal:awal + 250]


# --- Kata benda sendirian -------------------------------------------------
@pytest.mark.parametrize("kalimat", ["Jadwal", "jadwal", "agenda", "besok", "sekarang"])
def test_kata_benda_sendirian_bukan_perintah(kalimat):
    """
    "Jadwal" saja tidak menyatakan ingin melihat, membuat, atau menghapus.
    Di log kata itu muncul dari salah dengar "Selamat tinggal", lalu AKIRA
    membacakan agenda tanpa diminta.
    """
    assert parse_command(kalimat, use_slm=False)["aksi"] is None


@pytest.mark.parametrize("kalimat,aksi", [
    ("cek jadwal", "baca"),
    ("jadwal besok apa", "baca"),
    ("bacakan jadwal", "baca"),
    ("catat rapat besok jam 3", "catat"),
])
def test_perintah_asli_tidak_ikut_ditolak(kalimat, aksi):
    assert parse_command(kalimat, use_slm=False)["aksi"] == aksi


def test_hanya_kata_benda_helper():
    from src.nlp.intent_classifier import hanya_kata_benda

    assert hanya_kata_benda("jadwal") is True
    assert hanya_kata_benda("Jadwal.") is True
    assert hanya_kata_benda("cek jadwal") is False
    assert hanya_kata_benda("futsal") is False      # kata benda lain: boleh


# --- Jendela ringkas ------------------------------------------------------
def test_jendela_tidak_memenuhi_layar():
    """
    Aplikasi ini dipakai berdampingan dengan pekerjaan lain — jendela
    selebar layar justru merepotkan.
    """
    import re as _re

    src = open("akira_app.py", encoding="utf-8").read()
    m = _re.search(r'self\.geometry\("(\d+)x(\d+)"\)', src)
    assert m, "ukuran jendela tidak ditemukan"

    lebar, tinggi = int(m.group(1)), int(m.group(2))
    assert lebar <= 900, f"jendela terlalu lebar ({lebar})"
    assert tinggi <= 660, f"jendela terlalu tinggi ({tinggi})"


def test_subjudul_memakai_kepanjangan_resmi():
    src = open("akira_app.py", encoding="utf-8").read()
    assert "Audio-driven Kalendar & Interactive Reminder Assistant" in src


# =========================================================================
# Sprint 4.7 — deteksi derau & mesin tambahan
# =========================================================================

def test_derau_dari_log_terdeteksi():
    """
    Kasus nyata: tidak ada yang bicara, tapi ketiga mesin menghasilkan
    tebakan yang saling asing. Merekonsiliasinya menghasilkan "Jadwal",
    dan AKIRA membacakan agenda tanpa diminta.
    """
    from src.stt.ensemble import kemungkinan_derau

    assert kemungkinan_derau({
        "whisper": "Selamat tinggal.",
        "groq-turbo": "Perniatra, jadwal, jadwal.",
        "groq-v3": "Jadwal.",
    }) is True


@pytest.mark.parametrize("kandidat", [
    {"a": "Pegiatannya main bola.", "b": "kegiatannya main bola",
     "c": "Kursus kegiatannya main bola."},
    {"a": "Akhirah baca tang jadwal saya", "b": "Akira bacakan jadwal saya",
     "c": "Kira bacakan jadwal saya"},
    {"a": "catat meeting besok jam 3 sore", "b": "Catat meeting besok jam 3 sore.",
     "c": "catat miting besok jam 3"},
])
def test_ucapan_asli_tidak_dianggap_derau(kandidat):
    """Mesin boleh salah satu-dua kata; kerangka kalimatnya tetap sama."""
    from src.stt.ensemble import kemungkinan_derau

    assert kemungkinan_derau(kandidat) is False


def test_kesepakatan_dirata_rata_bukan_diambil_maksimum():
    """
    Dua mesin yang kebetulan berbagi satu kata sudah cukup membuat nilai
    maksimum terlihat tinggi, padahal mesin ketiga mendengar hal lain —
    tanda khas derau.
    """
    from src.stt.ensemble import tingkat_kesepakatan

    skor = tingkat_kesepakatan({
        "a": "Selamat tinggal.", "b": "Perniatra, jadwal, jadwal.", "c": "Jadwal.",
    })
    assert skor < 0.35, f"rata-rata harusnya rendah, dapat {skor}"


def test_derau_dibuang_sebelum_memanggil_llm(monkeypatch):
    """Merekonsiliasi derau membuang waktu DAN menghasilkan kalimat palsu."""
    from src.stt import ensemble

    _pasang_mesin_palsu(monkeypatch, {
        "whisper": "Selamat tinggal.",
        "groq-turbo": "Perniatra, jadwal, jadwal.",
        "groq-v3": "Jadwal.",
    })

    dipanggil = []
    monkeypatch.setattr(ensemble, "rekonsiliasi_ganda",
                        lambda *a, **k: dipanggil.append(1) or "Jadwal")

    hasil = ensemble.transcribe_ensemble(
        "dummy.wav", ["whisper", "groq-turbo", "groq-v3"])

    assert hasil == ""
    assert dipanggil == [], "LLM tidak boleh dipanggil untuk derau"


def test_gerbang_frame_menyesuaikan_konteks():
    """
    Satu batas untuk semua kondisi terbukti salah ke dua arah. Batas rendah
    meloloskan derau sebagai perintah; batas tinggi (sempat 18 frame)
    membuang jawaban satu kata seperti "boleh" yang hanya 4 frame — AKIRA
    lalu bertanya ulang padahal sudah dijawab.

    Jawaban atas pertanyaan AKIRA boleh jauh lebih pendek daripada perintah
    bebas, karena di titik itu user memang sedang diajak bicara.
    """
    from src.audio.recorder import MIN_FRAME_BICARA, MIN_FRAME_JAWABAN

    assert MIN_FRAME_JAWABAN < MIN_FRAME_BICARA
    assert MIN_FRAME_JAWABAN <= 4, "jawaban satu kata harus lolos"
    assert MIN_FRAME_BICARA >= 8, "perintah bebas tetap butuh penyaring derau"


def test_dengar_jawaban_memakai_batas_longgar():
    src = open("src/app.py", encoding="utf-8").read()
    assert "return listen(timeout=12, jawaban=True)" in src
    assert "MIN_FRAME_JAWABAN if jawaban else MIN_FRAME_BICARA" in src




# =========================================================================
# Sprint 5 — pembersihan & sensitivitas self destruct
# =========================================================================

def test_env_example_hanya_memuat_yang_dibaca_kode():
    """
    .env.example harus mencerminkan kode, bukan sejarahnya. Kunci untuk mesin
    yang sudah dihapus hanya membuat orang mendaftar layanan yang tidak dipakai.
    """
    import glob
    import re as _re

    dibaca = set()
    for path in glob.glob("src/**/*.py", recursive=True) + ["akira_app.py", "run.py"]:
        isi = open(path, encoding="utf-8").read()
        dibaca |= set(_re.findall(r'getenv\("([A-Z_]+)"', isi))

    contoh = open(".env.example", encoding="utf-8").read()
    disebut = set(_re.findall(r"^#?\s*([A-Z][A-Z_]+)=", contoh, _re.M))

    usang = disebut - dibaca
    assert not usang, f".env.example menyebut kunci yang tidak dibaca kode: {usang}"
    assert "GROQ_API_KEY" in disebut


def test_dokumen_proyek_hanya_yang_publik():
    """
    Repositori publik hanya boleh memuat README (halaman depan GitHub) dan
    SETUP (panduan pemasangan). Dokumen internal — berisi perintah rahasia,
    catatan kredensial, dan proposal — tidak boleh ikut.
    """
    import glob

    md = sorted(glob.glob("*.md") + glob.glob("docs/*.md"))
    assert set(md) <= {"README.md", "SETUP.md"}, f"dokumen tak terduga: {md}"
    assert "SETUP.md" in md

    for rahasia in ("INFORMASI_AKIRA.md", "PANDUAN_PENGGUNAAN_AKIRA.md",
                    "PROPOSAL_AKIRA.md", "PROPOSAL_AKIRA.docx", "SELF_DESTRUCT.md"):
        assert not glob.glob(rahasia), f"{rahasia} tidak boleh ada di repositori"


def test_mesin_yang_dihapus_tidak_tersisa():
    """Pembersihan harus tuntas — tidak ada rujukan tersisa di kode."""
    import glob

    usang = ("assemblyai", "gladia", "openrouter", "cerebras", "gemini",
             "huggingface", "cloudflare", "faster_whisper")
    for path in glob.glob("src/**/*.py", recursive=True) + ["akira_app.py"]:
        isi = open(path, encoding="utf-8").read().lower()
        for nama in usang:
            assert nama not in isi, f"{path} masih menyebut '{nama}'"


# --- Sensitivitas self destruct ------------------------------------------
def _muat_tingkat():
    import re as _re

    src = open("akira_app.py", encoding="utf-8").read()
    m = _re.search(r"TINGKAT_SENSITIVITAS = \{(.*?)\}", src, _re.S)
    ns = {}
    exec("TINGKAT_SENSITIVITAS = {" + m.group(1) + "}", ns)
    return ns["TINGKAT_SENSITIVITAS"]


def test_sensitivitas_tersedia_di_pengaturan():
    src = open("akira_app.py", encoding="utf-8").read()
    assert '"Sensitivitas self destruct"' in src
    assert '"Self destruct lewat teks"' in src


def test_sensitivitas_selalu_di_atas_wake_word_utama():
    """
    Kedua frasa diawali "AKIRA". Kalau ambang frasa penghancur sama atau
    lebih rendah dari wake word utama, "AKIRA WAKE UP" berisiko ikut menaikkan
    skornya — dan salah picu di arah ini fatal.
    """
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    ambang_utama = cfg["wakeword"]["threshold"]

    for tingkat, ambang in _muat_tingkat().items():
        assert ambang > ambang_utama, (
            f"tingkat '{tingkat}' ({ambang}) tidak di atas wake word utama ({ambang_utama})"
        )


def test_sensitivitas_tinggi_berarti_ambang_rendah():
    """Mudah terpicu = ambang rendah. Urutan terbalik akan membingungkan."""
    t = _muat_tingkat()
    rendah = next(v for k, v in t.items() if k.startswith("Rendah"))
    tinggi = next(v for k, v in t.items() if k.startswith("Tinggi"))
    assert rendah > tinggi


def test_config_self_destruct_cocok_dengan_salah_satu_tingkat():
    """Nilai di config harus bisa ditampilkan tepat sebagai salah satu pilihan."""
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    assert cfg["self_destruct"]["threshold"] in _muat_tingkat().values()


def test_self_destruct_data_menghapus_rekaman_sungguhan():
    """
    Daftar tingkat 'data' sempat mencantumkan "temp.wav" — nama lama — sehingga
    rekaman suara yang sebenarnya tertinggal. Itu data paling pribadi di
    seluruh daftar. Nama berkasnya harus diambil dari tempat ia ditulis.
    """
    import inspect

    from src.audio.recorder import save_wav
    from src.dialog.self_destruct import TINGKAT

    berkas_rekaman = inspect.signature(save_wav).parameters["path"].default
    assert berkas_rekaman in TINGKAT["data"], (
        f"rekaman '{berkas_rekaman}' tidak ikut dihapus pada tingkat data"
    )


def test_self_destruct_data_mencakup_semua_berkas_pribadi():
    from src.dialog.self_destruct import TINGKAT

    for berkas in ("config/token.json", "config/user_settings.json",
                   "config/pintasan.json", "logs", "temp_recording.wav"):
        assert berkas in TINGKAT["data"], f"{berkas} tidak ikut dihapus"


def test_self_destruct_data_tidak_menyentuh_kredensial_aplikasi():
    """
    credentials.json milik aplikasi, bukan data pribadi pengguna. Menghapusnya
    pada tingkat 'data' berarti AKIRA tidak bisa login lagi sama sekali.
    """
    from src.dialog.self_destruct import TINGKAT

    assert "config/credentials.json" not in TINGKAT["data"]


@pytest.mark.parametrize("kalimat,aksi", [
    ("tambahin jadwal kuliah lusa jam 1 siang", "catat"),
    ("catetin rapat besok jam 9 pagi", "catat"),
    ("hapusin jadwal rapat", "hapus"),
    ("pindahin meeting ke besok", "reschedule"),
    ("bacain jadwal besok", "baca"),
    ("ingetin 1 jam sebelum meeting", "reminder"),
])
def test_akhiran_in_bahasa_santai(kalimat, aksi):
    """
    Ditemukan saat menguji contoh untuk panduan penggunaan: bentuk santai
    berakhiran "-in" tidak dikenali, karena batas kata membuat "tambahin"
    tidak cocok dengan kata kunci "tambah".
    """
    assert parse_command(kalimat, use_slm=False)["aksi"] == aksi


def test_tidak_ada_kunci_ganda_di_aturan_normalisasi():
    """
    Dalam dict Python, kunci yang sama ditulis dua kali diam-diam menimpa
    yang pertama. pyflakes hanya memperingatkan bila NILAINYA berbeda;
    duplikat bernilai sama lolos tanpa tanda. Ditemukan dua kasus sekaligus
    saat menambah aturan akhiran "-in".
    """
    import ast

    src = open("src/nlp/text_normalizer.py", encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Dict):
            kunci = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            ganda = {k for k in kunci if kunci.count(k) > 1}
            assert not ganda, f"kunci ganda: {ganda}"


# =========================================================================
# Sprint 5.1 — jawaban pendek, sinonim, dan penalaran jawaban
# =========================================================================

def test_jawaban_dari_log_bukan_derau():
    """
    Kasus nyata: user menjawab "boleh", STT menghasilkan tiga kandidat yang
    maknanya sama tapi ejaannya beda — dan semuanya dibuang sebagai derau.
    """
    from src.stt import ensemble

    kandidat = {
        "whisper": "Ya, jadwal, jadwal, jadwal.",
        "groq-turbo": "Ya, catat, catat, catat.",
        "groq-v3": "Iya catat, catat, catat.",
    }
    ensemble.set_konteks_pertanyaan("Mau saya catat jadwal itu ke kalender?")
    try:
        assert ensemble.kemungkinan_derau(kandidat) is False
    finally:
        ensemble.set_konteks_pertanyaan("")


@pytest.mark.parametrize("a,b", [
    ("ya catat", "iya catat"),
    ("oke", "boleh"),
    ("tidak", "nggak"),
])
def test_sinonim_dihitung_sama(a, b):
    from src.stt.ensemble import _mirip

    assert _mirip(a, b) == 1.0


def test_derau_tetap_terdeteksi_walau_ada_konteks():
    """Melonggarkan ambang saat menjawab tidak boleh mematikan deteksi derau."""
    from src.stt import ensemble

    ensemble.set_konteks_pertanyaan("Sudah benar?")
    try:
        assert ensemble.kemungkinan_derau({
            "a": "Selamat tinggal.", "b": "Perniatra, jadwal, jadwal.", "c": "Jadwal.",
        }) is True
    finally:
        ensemble.set_konteks_pertanyaan("")


def test_penalaran_dipanggil_saat_aturan_menyerah(monkeypatch):
    """"gas aja" tidak ada di daftar kata — penalaran yang harus menangkapnya."""
    import src.nlp.groq_reasoner as gr
    from src.dialog.confirmation import tafsir_dengan_penalaran

    dipanggil = []
    monkeypatch.setattr(gr, "tafsir_jawaban_groq",
                        lambda p, j: dipanggil.append((p, j)) or True)

    assert tafsir_dengan_penalaran("hajar terus", "Mau saya catat?") is True
    assert dipanggil == [("Mau saya catat?", "hajar terus")]


def test_penalaran_tidak_dipanggil_untuk_jawaban_jelas(monkeypatch):
    """Aturan kata kunci gratis dan instan — LLM hanya untuk yang buntu."""
    import src.nlp.groq_reasoner as gr
    from src.dialog.confirmation import tafsir_dengan_penalaran

    dipanggil = []
    monkeypatch.setattr(gr, "tafsir_jawaban_groq",
                        lambda p, j: dipanggil.append(1) or True)

    for jawaban in ("ya", "boleh", "tidak", "batalkan"):
        tafsir_dengan_penalaran(jawaban, "Mau saya catat?")
    assert dipanggil == []


def test_penalaran_gagal_bukan_persetujuan(monkeypatch):
    """
    Kalau penalaran error, hasilnya harus None — konfirmasi lalu bertanya
    ulang. Tidak pernah dianggap setuju.
    """
    import src.nlp.groq_reasoner as gr
    from src.dialog.confirmation import tafsir_dengan_penalaran

    def meledak(p, j):
        raise RuntimeError("jaringan mati")

    monkeypatch.setattr(gr, "tafsir_jawaban_groq", meledak)
    assert tafsir_dengan_penalaran("hajar terus", "Hapus rapat?") is None


def test_konfirmasi_memakai_pertanyaan_asli_sebagai_konteks(monkeypatch):
    """
    Pada percobaan kedua AKIRA bertanya "tolong jawab ya atau tidak" — tapi
    konteks yang berguna ada di pertanyaan PERTAMA.
    """
    import src.nlp.groq_reasoner as gr
    from src.dialog.confirmation import konfirmasi

    konteks_terkirim = []
    monkeypatch.setattr(gr, "tafsir_jawaban_groq",
                        lambda p, j: konteks_terkirim.append(p) or None)

    jawaban = iter(["hmm gimana ya", "entahlah"])
    konfirmasi("Hapus rapat divisi?", lambda q: None, lambda: next(jawaban))

    assert konteks_terkirim, "penalaran harus dipanggil"
    assert all(k == "Hapus rapat divisi?" for k in konteks_terkirim)


def test_konfirmasi_menerima_hasil_penalaran(monkeypatch):
    import src.nlp.groq_reasoner as gr
    from src.dialog.confirmation import konfirmasi

    monkeypatch.setattr(gr, "tafsir_jawaban_groq", lambda p, j: True)
    assert konfirmasi("Mau saya catat?", lambda q: None, lambda: "gas aja") is True


# =========================================================================
# Sprint 5.2 — daftar nama hari, kegiatan berwaktu, penutup
# =========================================================================

@pytest.mark.parametrize("kalimat,jumlah", [
    ("saya ada jadwal hari sabtu dan kamis", 2),
    ("rapat senin, rabu, dan jumat", 3),       # pemisah ", dan" berurutan
    ("senin, rabu, jumat", 3),
    ("sabtu dan minggu ada acara", 2),          # "minggu" di dalam daftar = hari
])
def test_daftar_hari_semua_tertangkap(kalimat, jumlah):
    """
    Sebelumnya hanya daftar ANGKA tanggal yang dikenali. "hari sabtu dan
    kamis" menghasilkan satu jadwal — hari kedua hilang tanpa jejak.
    """
    from datetime import datetime as _dt

    from src.nlp.date_time_parser import parse_multi_dates

    assert len(parse_multi_dates(kalimat, _dt(2026, 9, 28))) == jumlah


@pytest.mark.parametrize("kalimat", [
    "sabtu atau minggu",         # pilihan, bukan dua jadwal
    "jadwal minggu depan",       # "minggu" = pekan
    "catat rapat hari kamis",    # satu hari saja
    "rapat senin dan senin",     # hari yang sama
])
def test_bukan_daftar_hari(kalimat):
    """Salah tafsir di sini berarti membuat jadwal ganda tanpa diminta."""
    from datetime import datetime as _dt

    from src.nlp.date_time_parser import parse_multi_dates

    assert parse_multi_dates(kalimat, _dt(2026, 9, 28)) == []


def test_gabung_tanggal_menyebut_nama_hari():
    from src.nlp.date_time_parser import gabung_tanggal

    hasil = gabung_tanggal(["2026-10-01", "2026-10-03"])
    assert hasil == "Kamis 1 Oktober dan Sabtu 3 Oktober"


@pytest.mark.parametrize("jawaban,kegiatan", [
    ("makan siang", "makan siang"),
    ("kegiatannya olahraga pagi", "olahraga pagi"),
    ("kuliah malam", "kuliah malam"),
])
def test_kegiatan_berwaktu_utuh(jawaban, kegiatan):
    """
    "siang" sempat dibuang sebagai penanda jam, sehingga "makan siang"
    tersimpan sebagai "makan" — judul yang kehilangan maknanya.
    """
    from src.nlp.parser import merge_answer

    hasil = merge_answer({"aksi": "catat", "kegiatan": None}, "kegiatan", jawaban)
    assert hasil["kegiatan"] == kegiatan


def test_keterangan_waktu_biasa_tetap_dibuang():
    """Perlindungan tidak boleh membuat "jam 3 sore" ikut jadi nama kegiatan."""
    assert parse_command("catat meeting besok jam 3 sore", use_slm=False)["kegiatan"] == "meeting"


@pytest.mark.parametrize("kalimat", [
    "terimakasih", "baiklah terimakasih", "sudah cukup", "itu aja",
    "thanks", "gak ada lagi", "trimakasih",
])
def test_penutup_berbagai_ejaan(kalimat):
    """"terimakasih" menyambung — paling sering dari jalur ketik — sempat tak dikenali."""
    assert _muat_is_penutup()(kalimat) is True


def test_pesan_penutup_memberitahu_mode_ambient():
    """
    Setelah sesi berakhir, AKIRA masuk mode ambient. Tanpa diberi tahu,
    pengguna akan mengucapkan "AKIRA WAKE UP" lagi padahal cukup menyebut nama.
    """
    ns = _muat_helper_app("def _pesan_penutup", "def is_negatif")
    ns["_get"] = lambda cfg, *k, default=None: {
        ("ambient", "enabled"): True, ("ambient", "timeout_menit"): 15,
    }.get(k, default)

    pesan = ns["_pesan_penutup"]({})
    assert "standby" in pesan.lower() and "15 menit" in pesan



# =========================================================================
# Sprint 5.3 — log antarmuka, penghapusan frasa kustom, waktu, pemilihan hari
# =========================================================================

def test_log_tetap_sampai_ke_antarmuka_setelah_akira_menyala(tmp_path):
    """
    `logger.remove()` tanpa argumen melepas SEMUA handler loguru — termasuk
    saluran ke antarmuka yang dipasang sebelum AKIRA dijalankan. Panel Log
    kosong total begitu AKIRA menyala.
    """
    from loguru import logger

    from src.gui import runner
    from src.utils.logger_config import setup_logger

    runner.pasang_sink()
    setup_logger(str(tmp_path / "uji.log"))
    logger.info("penanda-uji-log-antarmuka")

    baris = []
    while not runner.antrean_log.empty():
        baris.append(runner.antrean_log.get_nowait())
    assert any("penanda-uji-log-antarmuka" in b for b in baris)


def test_tidak_ada_logger_remove_tanpa_argumen():
    """
    Periksa PEMANGGILAN sungguhan lewat AST — bukan teks — supaya komentar
    yang menjelaskan larangan ini tidak ikut terhitung. Berlaku untuk
    seluruh kode sumber: satu pemanggilan di mana pun memutus log antarmuka.
    """
    import ast
    import glob

    for path in glob.glob("src/**/*.py", recursive=True) + ["akira_app.py", "run.py"]:
        pohon = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(pohon):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "remove"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logger"
                    and not node.args):
                raise AssertionError(f"{path}:{node.lineno} memanggil logger.remove() tanpa argumen")


def test_frasa_kustom_sudah_dihapus_tuntas():
    """Fitur yang dihapus dari antarmuka tidak boleh tersisa sebagai fitur tersembunyi."""
    import os

    assert not os.path.exists("src/gui/custom_commands.py")
    for path in ("akira_app.py", "src/nlp/intent_classifier.py"):
        isi = open(path, encoding="utf-8").read()
        assert "custom_commands" not in isi and "_muat_frasa" not in isi


@pytest.mark.parametrize("kalimat", [
    "15 menit lagi jam berapa", "2 jam lagi jam berapa", "3 hari lagi hari apa",
])
def test_pertanyaan_waktu_bukan_timer(kalimat):
    """"15 menit lagi jam berapa" sempat memasang timer 15 menit."""
    from src.dialog.alarm import is_permintaan_timer

    assert is_permintaan_timer(kalimat) is False


@pytest.mark.parametrize("kalimat", ["timer 15 menit", "ingetin minum obat 15 menit lagi"])
def test_timer_asli_tetap_timer(kalimat):
    from src.dialog.alarm import is_permintaan_timer

    assert is_permintaan_timer(kalimat) is True


def test_menit_lagi_dijawab_dengan_jam():
    from datetime import datetime as _dt, timedelta as _td

    from src.calendar_service.executor import _handle_waktu

    target = _dt.now() + _td(minutes=15)
    pesan = _handle_waktu({"teks_asli": "15 menit lagi jam berapa"})["message"]
    assert f"{target:%H}:" in pesan


@pytest.mark.parametrize("jam,menit,harapan", [
    (20, 0, "8 malam"), (7, 30, "7 lewat 30 pagi"), (12, 0, "12 siang"),
    (0, 0, "12 malam"), (15, 0, "3 sore"), (2, 15, "2 lewat 15 dini hari"),
])
def test_jam_alami(jam, menit, harapan):
    """Tidak semua orang terbiasa dengan format 24 jam."""
    from src.nlp.date_time_parser import jam_alami

    assert jam_alami(jam, menit) == harapan


def test_jam_24_diucapkan_alami_di_speaker():
    """Konversi dipasang di satu-satunya pintu keluar suara."""
    src = open("src/tts/speaker.py", encoding="utf-8").read()
    assert "ucapkan_jam_alami(text)" in src


def test_angka_bukan_jam_tidak_diubah():
    from src.nlp.date_time_parser import ucapkan_jam_alami

    assert ucapkan_jam_alami("tanggal 3.10 ada acara") == "tanggal 3.10 ada acara"


@pytest.mark.parametrize("kegiatan,harapan", [
    ("makan malam", "19:00"), ("sarapan", "07:00"),
])
def test_periode_disimpulkan_dari_kegiatan(kegiatan, harapan):
    """"makan malam jam 7" jelas 19.00 — bertanya pagi/malam justru terdengar bodoh."""
    from src.dialog.state_machine import perlu_perjelas_jam
    from src.nlp.parser import merge_answer

    data = {"aksi": "catat", "kegiatan": kegiatan, "teks_asli": "ada jadwal sabtu"}
    data = merge_answer(data, "jam", "jam 7")
    assert perlu_perjelas_jam(data) is False
    assert data["jam"] == harapan


def test_jam_ambigu_diperiksa_dari_kalimat_jawaban():
    """
    Jam yang disebut di JAWABAN harus diperiksa, bukan perintah awal. Dulu
    "futsal" + "jam 7" tidak ditanya karena perintah awal tidak memuat jam.
    """
    from src.dialog.state_machine import perlu_perjelas_jam
    from src.nlp.parser import merge_answer

    data = {"aksi": "catat", "kegiatan": "futsal", "teks_asli": "ada jadwal sabtu"}
    data = merge_answer(data, "jam", "jam 7")
    assert perlu_perjelas_jam(data) is True



# =========================================================================
# Sprint 5.4 — temuan dari menjalankan test di laptop dengan Groq sungguhan
# =========================================================================

def test_pengujian_tidak_memanggil_groq_sungguhan():
    """
    Di laptop dengan GROQ_API_KEY, test sempat memanggil API sungguhan:
    hasilnya bergantung jawaban LLM saat itu, dan tiap pytest memakan kuota.
    """
    import os

    from src.nlp import groq_reasoner

    assert not os.getenv("GROQ_API_KEY"), "kunci .env bocor ke dalam pengujian"
    assert groq_reasoner._panggil_groq("sistem", "pesan") is None


def test_ollama_lokal_diblokir_saat_pengujian():
    from src.nlp import slm_extractor

    with pytest.raises(RuntimeError):
        slm_extractor._chat("qwen3:4b", [], {})


def test_penerjemah_membedakan_bukan_perintah_dari_gagal(monkeypatch):
    """
    "Bukan perintah" dan "Groq tak terhubung" harus dibedakan. Kalau Groq
    sudah menilai kalimat bukan perintah, pengklasifikasi label tidak boleh
    memaksakan label; kalau Groq tak terhubung, cadangan lokal boleh dipakai.
    """
    from src.nlp import groq_reasoner

    monkeypatch.setattr(groq_reasoner, "_panggil_groq",
                        lambda *a, **k: '{"perintah": null, "aksi": null, "alasan": "obrolan"}')
    assert groq_reasoner.pahami_maksud_groq("kucing tetangga lucu") == {"bukan": True}

    monkeypatch.setattr(groq_reasoner, "_panggil_groq", lambda *a, **k: None)
    assert groq_reasoner.pahami_maksud_groq("kucing tetangga lucu") is None


def test_penerjemah_didahulukan_dari_pengklasifikasi_label():
    """
    Pengklasifikasi label hanya mengenal 7 aksi kalender dan tidak tahu timer
    ada. Dengan Groq sungguhan, "10 menitan lagi kabarin soal jemuran"
    dilabeli "reminder" dan AKIRA menanyakan "berapa lama sebelum acara?".
    Penerjemah (katalog lengkap + validasi) harus dicoba lebih dulu.
    """
    src = open("src/app.py", encoding="utf-8").read()
    i_terjemah = src.index("status, terjemahan = _terjemahkan_maksud(text, sudah_diterjemahkan)")
    i_parse = src.index("data = parse_command(text, use_slm=use_slm, model=model)")
    assert i_terjemah < i_parse
