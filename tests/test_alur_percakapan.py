"""
Uji ALUR PERCAKAPAN penuh, dari ucapan sampai kalender.

Kenapa berkas terpisah:
Test lain menguji satu fungsi. Berkas ini menjalankan `handle_session()`
yang sesungguhnya — dengan mikrofon, speaker, dan Google Calendar diganti
tiruan — lalu memeriksa percakapan yang dihasilkan dari awal sampai akhir.

Ini menangkap kelas cacat yang lolos dari unit test: urutan pertanyaan yang
keliru, pembatalan yang tidak dihormati, konfirmasi yang terlewat, dan aksi
yang dijalankan padahal seharusnya berhenti. Beberapa cacat paling serius di
proyek ini justru dari kelas itu.

Jalankan: pytest tests/test_alur_percakapan.py -v
"""
import sys
import types
from datetime import datetime, timedelta

import pytest


# -------------------------------------------------------------------------
# Pengganti pustaka berat
#
# `whisper` menarik PyTorch (>2 GB) dan tidak pernah benar-benar dipakai di
# sini — transkripsi sudah diganti tiruan. Memasangnya hanya agar impor
# berhasil membuat test ini lambat dan sulit dijalankan di mesin lain.
# -------------------------------------------------------------------------
def _pasang_pengganti():
    if "whisper" not in sys.modules:
        palsu = types.ModuleType("whisper")
        palsu.load_model = lambda *a, **k: None
        sys.modules["whisper"] = palsu


_pasang_pengganti()


# =========================================================================
# Perkakas simulasi
# =========================================================================
class Kalender:
    """Google Calendar tiruan yang mencatat setiap operasi."""

    def __init__(self, events=None):
        self.events = list(events or [])
        self.dibuat = []
        self.dihapus = []
        self.diperbarui = []
        self._urutan = 100

    # --- yang dipanggil crud
    def read_events(self, **kwargs):
        return list(self.events)

    def find_event_by_keyword(self, keyword, max_results=20):
        k = (keyword or "").lower()
        return [e for e in self.events if k in e.get("summary", "").lower()]

    def create_event(self, summary, start_datetime, end_datetime,
                     description=None, **kwargs):
        self._urutan += 1
        event = {
            "id": f"ev{self._urutan}",
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_datetime},
            "end": {"dateTime": end_datetime},
        }
        self.events.append(event)
        self.dibuat.append(event)
        return event

    def delete_event(self, event_id):
        self.events = [e for e in self.events if e["id"] != event_id]
        self.dihapus.append(event_id)

    def update_event(self, event_id, perubahan):
        self.diperbarui.append((event_id, perubahan))
        for e in self.events:
            if e["id"] == event_id:
                e.update(perubahan)
                return e
        return {}

    def set_event_reminder(self, event_id, menit, method="popup"):
        return {"id": event_id, "reminders": menit}

    def reschedule_event(self, event_id, new_start_datetime, new_end_datetime, timezone=None):
        return self.update_event(event_id, {
            "start": {"dateTime": new_start_datetime},
            "end": {"dateTime": new_end_datetime},
        })


def pasang_kalender(monkeypatch, kalender):
    """Ganti modul crud dengan kalender tiruan."""
    palsu = types.ModuleType("src.calendar_service.crud")
    palsu.read_events = kalender.read_events
    palsu.find_event_by_keyword = kalender.find_event_by_keyword
    palsu.create_event = kalender.create_event
    palsu.delete_event = kalender.delete_event
    palsu.update_event = kalender.update_event
    palsu.set_event_reminder = kalender.set_event_reminder
    palsu.reschedule_event = kalender.reschedule_event
    monkeypatch.setitem(sys.modules, "src.calendar_service.crud", palsu)
    return kalender


class Percakapan:
    """
    Menjalankan satu sesi AKIRA dengan daftar ucapan yang sudah ditentukan.

    `ucapan` adalah apa yang "didengar" AKIRA secara berurutan. Semua kalimat
    AKIRA dikumpulkan di `dikatakan` untuk diperiksa.
    """

    def __init__(self, ucapan):
        self.antre = list(ucapan)
        self.dikatakan = []
        self.habis = False

    def dengar(self, timeout=None):
        if not self.antre:
            self.habis = True
            return ""
        return self.antre.pop(0)

    def katakan(self, teks, interruptible=True):
        self.dikatakan.append(teks)
        return True

    @property
    def transkrip(self):
        return " | ".join(self.dikatakan)

    def mengandung(self, *potongan):
        gabung = self.transkrip.lower()
        return all(p.lower() in gabung for p in potongan)


def jalankan_sesi(monkeypatch, ucapan, kalender=None, config=None):
    """
    Jalankan handle_session() sungguhan dengan mic, speaker, dan STT tiruan.

    Ini titik beda utama dari unit test: yang diuji adalah orkestrasi
    sesungguhnya di app.py, bukan potongan fungsinya.
    """
    kalender = kalender or Kalender()
    pasang_kalender(monkeypatch, kalender)

    import src.app as app
    import src.audio.recorder as recorder
    import src.stt.transcriber as transcriber
    import src.tts.speaker as speaker

    percakapan = Percakapan(ucapan)

    # app.py mengimpor fungsi-fungsi ini DI DALAM fungsi, jadi menambalnya
    # di app tidak berpengaruh — yang harus ditambal modul sumbernya.
    monkeypatch.setattr(recorder, "record_with_vad", lambda **kw: b"audio-palsu")
    monkeypatch.setattr(recorder, "save_wav", lambda audio, path=None: "palsu.wav")
    monkeypatch.setattr(transcriber, "transcribe",
                        lambda path, **kw: percakapan.dengar())
    monkeypatch.setattr(speaker, "speak",
                        lambda teks, **kw: percakapan.katakan(teks))

    cfg = config or _config_uji()
    app.handle_session(cfg)
    return percakapan, kalender


def _config_uji():
    return {
        "wakeword": {"threshold": 0.6, "model_path": "models/x.onnx"},
        "audio": {"max_silence_frames": 18, "vad_aggressiveness": 3,
                  "max_duration_s": 10, "rms_ambang": 320},
        "stt": {"engine": "whisper", "model_size": "small",
                "language": "id", "device": "cpu"},
        "nlp": {"ollama_model": "qwen3:4b"},
        "dialog": {"follow_up_timeout_s": 8, "max_idle_turns": 2,
                   "briefing_days": 7, "briefing_on_start": False,
                   "briefing_once_per_day": True},
        "ambient": {"enabled": False},
        "reminder": {"check_interval_seconds": 30, "lead_tiers_minutes": [30, 15, 5]},
        "self_destruct": {},
        "tts": {"use_online": False},
    }


def besok(jam="14:00"):
    t = datetime.now() + timedelta(days=1)
    return f"{t:%Y-%m-%d}T{jam}:00+07:00"


# =========================================================================
# ALUR 1 — Mencatat jadwal
# =========================================================================
def test_alur_catat_lengkap(monkeypatch):
    """Perintah lengkap: hanya perlu melewati field opsional dan konfirmasi."""
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "catat meeting besok jam 3 sore",
        "lewati",          # jam selesai
        "lewati",          # deskripsi
        "benar",           # konfirmasi
        "terima kasih",
    ])

    assert len(kalender.dibuat) == 1
    assert kalender.dibuat[0]["summary"] == "meeting"
    assert percakapan.mengandung("sudah saya catat")


def test_alur_catat_bertahap(monkeypatch):
    """Perintah tanpa detail: AKIRA harus menanyakan satu per satu."""
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "buatkan jadwal besok",
        "main bola",       # kegiatan
        "jam 4 sore",      # jam
        "lewati",
        "lewati",
        "ya",
        "makasih",
    ])

    assert len(kalender.dibuat) == 1
    assert kalender.dibuat[0]["summary"] == "main bola"
    assert percakapan.mengandung("kegiatannya apa")


def test_alur_catat_dibatalkan_saat_konfirmasi(monkeypatch):
    """Menolak di konfirmasi berarti TIDAK ada yang masuk kalender."""
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "catat meeting besok jam 3 sore",
        "lewati",
        "lewati",
        "batalkan",
        "terima kasih",
    ])

    assert kalender.dibuat == []
    assert percakapan.mengandung("batalkan")


def test_alur_catat_dibatalkan_saat_field_opsional(monkeypatch):
    """
    Pembatalan di field opsional harus menghentikan perintah. Dulu tidak:
    jawabannya dianggap "lewati" dan jadwalnya tetap tersimpan.
    """
    _, kalender = jalankan_sesi(monkeypatch, [
        "catat meeting besok jam 3 sore",
        "batalkan semuanya",
        "terima kasih",
    ])

    assert kalender.dibuat == []


def test_alur_catat_dengan_koreksi(monkeypatch):
    """Mengoreksi satu field saat konfirmasi, tanpa mengulang perintah."""
    _, kalender = jalankan_sesi(monkeypatch, [
        "catat meeting besok jam 3 sore",
        "lewati",
        "lewati",
        "kegiatannya futsal",      # koreksi
        "benar",
        "terima kasih",
    ])

    assert len(kalender.dibuat) == 1
    assert kalender.dibuat[0]["summary"] == "futsal"


def test_alur_jam_ambigu_ditanyakan(monkeypatch):
    """Jam 1-11 tanpa keterangan harus diperjelas dulu."""
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "catat meeting besok jam 10",
        "pagi",
        "lewati",
        "lewati",
        "benar",
        "terima kasih",
    ])

    assert percakapan.mengandung("pagi atau malam")
    assert "T10:00" in kalender.dibuat[0]["start"]["dateTime"]


# =========================================================================
# ALUR 2 — Membaca jadwal
# =========================================================================
def test_alur_baca_kosong(monkeypatch):
    percakapan, _ = jalankan_sesi(monkeypatch, [
        "cek jadwal besok",
        "terima kasih",
    ])
    assert percakapan.mengandung("tidak ada jadwal")


def test_alur_baca_terisi(monkeypatch):
    kalender = Kalender([
        {"id": "ev1", "summary": "rapat divisi",
         "start": {"dateTime": besok("09:00")}},
    ])
    percakapan, _ = jalankan_sesi(monkeypatch, [
        "cek jadwal besok",
        "terima kasih",
    ], kalender=kalender)

    assert percakapan.mengandung("rapat divisi", "09:00")


def test_alur_baca_bahasa_santai(monkeypatch):
    """"besok saya kosong ga?" harus dipahami sebagai permintaan membaca."""
    percakapan, _ = jalankan_sesi(monkeypatch, [
        "besok saya kosong ga",
        "terima kasih",
    ])
    assert percakapan.mengandung("tidak ada jadwal")


# =========================================================================
# ALUR 3 — Menghapus jadwal
# =========================================================================
def test_alur_hapus_dengan_konfirmasi(monkeypatch):
    kalender = Kalender([
        {"id": "ev1", "summary": "rapat divisi",
         "start": {"dateTime": besok("09:00")}},
    ])
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "hapus jadwal rapat divisi",
        "ya",
        "terima kasih",
    ], kalender=kalender)

    assert kalender.dihapus == ["ev1"]
    assert percakapan.mengandung("hapus")


def test_alur_hapus_ditolak(monkeypatch):
    """Menolak konfirmasi berarti jadwalnya TETAP ada."""
    kalender = Kalender([
        {"id": "ev1", "summary": "rapat divisi",
         "start": {"dateTime": besok("09:00")}},
    ])
    _, kalender = jalankan_sesi(monkeypatch, [
        "hapus jadwal rapat divisi",
        "batalkan",
        "terima kasih",
    ], kalender=kalender)

    assert kalender.dihapus == []
    assert len(kalender.events) == 1


def test_alur_hapus_tidak_ketemu(monkeypatch):
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "hapus jadwal rapat divisi",
        "terima kasih",
    ])
    assert kalender.dihapus == []
    assert percakapan.mengandung("tidak menemukan")


def test_alur_hapus_pilih_dari_beberapa(monkeypatch):
    kalender = Kalender([
        {"id": "ev1", "summary": "rapat divisi",
         "start": {"dateTime": besok("09:00")}},
        {"id": "ev2", "summary": "rapat klien",
         "start": {"dateTime": besok("14:00")}},
    ])
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "hapus jadwal rapat",
        "nomor dua",
        "ya",
        "terima kasih",
    ], kalender=kalender)

    assert kalender.dihapus == ["ev2"]
    assert percakapan.mengandung("pilih nomor")


def test_alur_hapus_semuanya_sekaligus(monkeypatch):
    """"dua-duanya" harus menghapus keduanya, bukan memilih nomor 2."""
    kalender = Kalender([
        {"id": "ev1", "summary": "rapat divisi",
         "start": {"dateTime": besok("09:00")}},
        {"id": "ev2", "summary": "rapat klien",
         "start": {"dateTime": besok("14:00")}},
    ])
    _, kalender = jalankan_sesi(monkeypatch, [
        "hapus jadwal rapat",
        "dua-duanya",
        "ya",
        "terima kasih",
    ], kalender=kalender)

    assert sorted(kalender.dihapus) == ["ev1", "ev2"]


# =========================================================================
# ALUR 4 — Bentrok jadwal
# =========================================================================
def test_alur_bentrok_ditawarkan_pilihan(monkeypatch):
    kalender = Kalender([
        {"id": "ev1", "summary": "rapat divisi",
         "start": {"dateTime": besok("15:00")},
         "end": {"dateTime": besok("16:00")}},
    ])
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "catat meeting besok jam 3 sore",
        "lewati",
        "lewati",
        "tetap saja",      # jawaban atas tawaran bentrok
        "benar",
        "terima kasih",
    ], kalender=kalender)

    assert percakapan.mengandung("sudah ada", "rapat divisi")
    assert len(kalender.dibuat) == 1


def test_alur_bentrok_ganti_jam(monkeypatch):
    """Menyebut jam baru langsung saat ditanya, tanpa mengulang perintah."""
    kalender = Kalender([
        {"id": "ev1", "summary": "rapat divisi",
         "start": {"dateTime": besok("15:00")},
         "end": {"dateTime": besok("16:00")}},
    ])
    _, kalender = jalankan_sesi(monkeypatch, [
        "catat meeting besok jam 3 sore",
        "lewati",
        "lewati",
        "jamnya jadi jam 8 malam",
        "benar",
        "terima kasih",
    ], kalender=kalender)

    assert len(kalender.dibuat) == 1
    assert "T20:00" in kalender.dibuat[0]["start"]["dateTime"]


# =========================================================================
# ALUR 5 — Rujukan antar-giliran
# =========================================================================
def test_alur_rujukan_jadwal_tersebut(monkeypatch):
    """Membaca dulu, lalu "hapus jadwal tersebut" tanpa menyebut namanya."""
    kalender = Kalender([
        {"id": "ev1", "summary": "rapat divisi",
         "start": {"dateTime": besok("09:00")}},
    ])
    _, kalender = jalankan_sesi(monkeypatch, [
        "cek jadwal besok",
        "hapus jadwal tersebut",
        "ya",
        "terima kasih",
    ], kalender=kalender)

    assert kalender.dihapus == ["ev1"]


# =========================================================================
# ALUR 6 — Perintah yang tidak dimengerti
# =========================================================================
def test_alur_tidak_dimengerti(monkeypatch):
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "bektr matasi",
        "terima kasih",
    ])
    assert kalender.dibuat == []
    assert percakapan.mengandung("belum mengerti")


def test_alur_kata_benda_sendirian_diabaikan(monkeypatch):
    """"Jadwal" saja, hasil salah dengar, tidak boleh memicu pembacaan."""
    percakapan, _ = jalankan_sesi(monkeypatch, [
        "jadwal",
        "terima kasih",
    ])
    assert not percakapan.mengandung("ada 1 jadwal")
    assert percakapan.mengandung("belum mengerti")


def test_alur_diam_kembali_ke_standby(monkeypatch):
    """Dua giliran diam berturut-turut mengakhiri sesi."""
    percakapan, _ = jalankan_sesi(monkeypatch, ["", ""])
    assert percakapan.mengandung("masih ada yang bisa saya bantu")


# =========================================================================
# ALUR 7 — Beberapa perintah dalam satu sesi
# =========================================================================
def test_alur_banyak_perintah_satu_sesi(monkeypatch):
    """Satu wake word, beberapa perintah berturut-turut."""
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "catat meeting besok jam 3 sore",
        "lewati", "lewati", "benar",
        "cek jadwal besok",
        "sekarang jam berapa",
        "terima kasih",
    ])

    assert len(kalender.dibuat) == 1
    assert percakapan.mengandung("sudah saya catat")
    assert percakapan.mengandung("meeting")


def test_alur_ganti_nama_panggilan(monkeypatch, tmp_path):
    import src.utils.user_settings as us

    monkeypatch.setattr(us, "SETTINGS_PATH", str(tmp_path / "u.json"))

    percakapan, _ = jalankan_sesi(monkeypatch, [
        "panggil saya Dzaky",
        "terima kasih",
    ])
    assert percakapan.mengandung("dzaky")


# =========================================================================
# ALUR 8 — Timer
# =========================================================================
def test_alur_timer_dipasang_dan_dibatalkan(monkeypatch):
    from src.dialog import alarm

    alarm.batalkan_semua()
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "timer 30 detik",
        "matikan timernya",
        "terima kasih",
    ])

    # Timer tidak boleh masuk kalender
    assert kalender.dibuat == []
    assert percakapan.mengandung("timer")
    assert alarm.daftar_aktif() == []


# =========================================================================
# ALUR 9 — Skenario nyata: jawaban pendek atas tawaran mencatat
# =========================================================================
def test_alur_jawaban_pendek_atas_tawaran(monkeypatch):
    """
    Dari log: user menyatakan jadwal, AKIRA menawarkan mencatat, user
    menjawab singkat. Sebelumnya jawabannya dibuang dua kali — sekali karena
    terlalu pendek, sekali karena dianggap derau — lalu tawaran dibatalkan.
    """
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "besok saya ada kondangan jam 1 siang",
        "Ya, catat, catat, catat.",     # persis seperti keluaran STT di log
        "lewati",
        "lewati",
        "benar",
        "terima kasih",
    ])

    assert percakapan.mengandung("mau saya catat")
    assert not percakapan.mengandung("tolong jawab ya atau tidak")
    assert len(kalender.dibuat) == 1


def test_alur_jawaban_tak_lazim_lewat_penalaran(monkeypatch):
    """
    Jawaban yang tidak ada di daftar kata kunci ("gas aja") harus dipahami
    lewat penalaran, bukan dibalas "tolong jawab ya atau tidak".
    """
    import src.nlp.groq_reasoner as gr

    monkeypatch.setattr(gr, "tafsir_jawaban_groq",
                        lambda p, j: True if "gas" in j else None)

    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "besok saya ada kondangan jam 1 siang",
        "gas aja",
        "lewati",
        "lewati",
        "benar",
        "terima kasih",
    ])

    assert not percakapan.mengandung("tolong jawab ya atau tidak")
    assert len(kalender.dibuat) == 1


# =========================================================================
# ALUR 10 — Skenario nyata: dua hari, "makan siang", "terimakasih"
# =========================================================================
def test_alur_dua_hari_dari_log(monkeypatch):
    """
    Persis dari log: "saya ada jadwal hari sabtu dan kamis" hanya
    menghasilkan SATU jadwal (Sabtu), "makan siang" tersimpan sebagai
    "makan", dan "terimakasih" dibalas "saya belum mengerti".
    """
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "saya ada jadwal hari sabtu dan kamis",
        "boleh",
        "sama",               # AKIRA kini bertanya: kegiatannya sama semua?
        "makan siang",
        "jam 8 malam",
        "lewati",
        "lewati",
        "benar",
        "terimakasih",
    ])

    assert len(kalender.dibuat) == 2, "dua hari disebut, dua jadwal harus dibuat"
    assert all(e["summary"] == "makan siang" for e in kalender.dibuat)
    assert all("T20:00" in e["start"]["dateTime"] for e in kalender.dibuat)
    assert not percakapan.mengandung("belum mengerti")
    assert percakapan.mengandung("panggil")


@pytest.mark.parametrize("penutup", [
    "terimakasih", "baiklah terimakasih", "sudah cukup", "itu aja", "thanks",
])
def test_alur_penutup_mengakhiri_sesi(monkeypatch, penutup):
    """Ucapan penutup apa pun harus mengakhiri sesi, bukan dianggap perintah."""
    percakapan, _ = jalankan_sesi(monkeypatch, [penutup])
    assert percakapan.mengandung("panggil")
    assert not percakapan.mengandung("belum mengerti")


# =========================================================================
# ALUR 11 — Skenario nyata: Sabtu & Minggu, lalu "yang minggunya beda"
# =========================================================================
def _groq_koreksi_tiruan(jadwal, kalimat):
    """Meniru penalaran Groq dengan perilaku yang dijanjikan prompt-nya."""
    t = kalimat.lower()
    minggu = next(j["tanggal"] for j in jadwal if j["hari"] == "Minggu") \
        if any(j["hari"] == "Minggu" for j in jadwal) else jadwal[0]["tanggal"]
    if "beda" in t and not any(k in t for k in ("futsal", "jam")):
        return {"ubah": [], "tanya": [minggu]}
    ubah = {"tanggal": minggu}
    if "futsal" in t:
        ubah["kegiatan"] = "futsal"
    if "jam 8" in t:
        ubah["jam"] = "08:00"
    return {"ubah": [ubah] if len(ubah) > 1 else [], "tanya": []}


def test_alur_hari_minggu_beda_lewat_penalaran(monkeypatch):
    """
    Persis dari log: "yang minggunya beda" dibalas "jawab ya atau sebutkan
    bagian yang perlu diubah". Groq sebenarnya menafsirkannya benar, tapi
    sistem koreksi tidak punya konsep "ubah yang Minggu saja".
    """
    import src.nlp.groq_reasoner as gr

    monkeypatch.setattr(gr, "koreksi_banyak_groq", _groq_koreksi_tiruan)

    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "saya ada jadwal sabtu dan minggu",
        "boleh",
        "sama",
        "makan malam",
        "jam 7",
        "lewati",
        "lewati",
        "yang minggunya beda",
        "futsal jam 8 pagi",
        "benar",
        "terima kasih",
    ])

    per_hari = {e["start"]["dateTime"][:10]: e for e in kalender.dibuat}
    assert len(per_hari) == 2
    sabtu, minggu = sorted(per_hari)

    assert per_hari[sabtu]["summary"] == "makan malam"
    assert "T19:00" in per_hari[sabtu]["start"]["dateTime"], "makan malam jam 7 = 19.00"
    assert per_hari[minggu]["summary"] == "futsal"
    assert "T08:00" in per_hari[minggu]["start"]["dateTime"]

    assert percakapan.mengandung("apa yang berbeda")
    assert not percakapan.mengandung("jawab ya atau sebutkan")


def test_alur_hari_minggu_beda_tanpa_groq(monkeypatch):
    """Saat Groq tidak tersedia, aturan harus tetap bisa menangani hal yang sama."""
    import src.nlp.groq_reasoner as gr

    monkeypatch.setattr(gr, "koreksi_banyak_groq", lambda j, k: None)

    _, kalender = jalankan_sesi(monkeypatch, [
        "saya ada jadwal sabtu dan minggu",
        "boleh",
        "sama",
        "makan malam",
        "jam 7",
        "lewati",
        "lewati",
        "yang minggunya beda",
        "futsal",
        "benar",
        "terima kasih",
    ])

    ringkas = sorted((e["start"]["dateTime"][:10], e["summary"]) for e in kalender.dibuat)
    assert [k for _, k in ringkas] == ["makan malam", "futsal"]


def test_alur_kegiatan_beda_sejak_awal(monkeypatch):
    """Menjawab "beda" saat ditanya sama/beda -> AKIRA menanyakan tiap hari."""
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "saya ada jadwal sabtu dan minggu",
        "boleh",
        "beda",
        "makan malam", "jam 7",          # Sabtu
        "futsal", "jam 8 pagi",          # Minggu
        "lewati",
        "lewati",
        "benar",
        "terima kasih",
    ])

    assert percakapan.mengandung("sama semua")
    hasil = sorted((e["start"]["dateTime"][:16], e["summary"]) for e in kalender.dibuat)
    assert hasil[0][1] == "makan malam" and hasil[0][0].endswith("T19:00")
    assert hasil[1][1] == "futsal" and hasil[1][0].endswith("T08:00")


def test_alur_koreksi_tanpa_hari_berlaku_untuk_semua(monkeypatch):
    """
    "jamnya jadi jam 8 malam" tanpa menyebut hari harus mengubah SEMUA.
    Kalau hanya field umum yang berubah, nilai per hari menimpanya saat
    menyimpan dan koreksinya hilang diam-diam.
    """
    import src.nlp.groq_reasoner as gr

    monkeypatch.setattr(gr, "koreksi_banyak_groq", lambda j, k: None)

    _, kalender = jalankan_sesi(monkeypatch, [
        "saya ada jadwal sabtu dan minggu",
        "boleh",
        "beda",
        "makan malam", "jam 7",
        "futsal", "jam 8 pagi",
        "lewati", "lewati",
        "jamnya jadi jam 9 malam",
        "benar",
        "terima kasih",
    ])

    assert all("T21:00" in e["start"]["dateTime"] for e in kalender.dibuat)


# =========================================================================
# ALUR 12 — Hapus / pindah / edit: pilih hari dulu, lalu pilih dari daftar
# =========================================================================
def _kalender_dua_jadwal_besok():
    return Kalender([
        {"id": "ev1", "summary": "rapat divisi", "start": {"dateTime": besok("09:00")}},
        {"id": "ev2", "summary": "futsal", "start": {"dateTime": besok("16:00")}},
    ])


def test_alur_hapus_tanpa_nama_pilih_dari_hari(monkeypatch):
    """
    Sebelumnya AKIRA langsung bertanya "kegiatannya apa?" — memaksa user
    mengingat judul persis jadwalnya. Sekarang: hari apa -> daftar -> pilih.
    """
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "hapus jadwal",
        "besok",
        "nomor dua",
        "ya",
        "terima kasih",
    ], kalender=_kalender_dua_jadwal_besok())

    assert percakapan.mengandung("hari apa")
    assert percakapan.mengandung("rapat divisi", "futsal")   # daftar dibacakan
    assert not percakapan.mengandung("kegiatannya apa")
    assert kalender.dihapus == ["ev2"]


def test_alur_pindah_pilih_dulu_baru_tujuan(monkeypatch):
    """Untuk pindah: pilih jadwalnya DULU, baru ditanya mau dipindah ke mana."""
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "pindahkan jadwal",
        "besok",
        "nomor satu",
        "lusa",
        "ya",
        "terima kasih",
    ], kalender=_kalender_dua_jadwal_besok())

    teks = percakapan.transkrip.lower()
    assert teks.index("pilih nomor") < teks.index("tanggal berapa"), (
        "jadwal harus dipilih sebelum menanyakan tujuan"
    )
    assert kalender.diperbarui and kalender.diperbarui[0][0] == "ev1"


def test_alur_hapus_hari_kosong(monkeypatch):
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "hapus jadwal",
        "besok",
        "terima kasih",
    ])
    assert percakapan.mengandung("tidak ada jadwal")
    assert kalender.dihapus == []


def test_alur_hapus_dengan_nama_tidak_ditanya_hari(monkeypatch):
    """Kalau nama sudah disebut, langkah baru ini tidak boleh menyela."""
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "hapus jadwal futsal",
        "ya",
        "terima kasih",
    ], kalender=_kalender_dua_jadwal_besok())

    assert not percakapan.mengandung("hari apa")
    assert kalender.dihapus == ["ev2"]


# =========================================================================
# ALUR 13 — Pertanyaan waktu bukan timer
# =========================================================================
def test_alur_menit_lagi_jam_berapa_bukan_timer(monkeypatch):
    """"15 menit lagi jam berapa" sempat memasang timer 15 menit."""
    from src.dialog import alarm

    alarm.batalkan_semua()
    percakapan, _ = jalankan_sesi(monkeypatch, [
        "15 menit lagi jam berapa",
        "terima kasih",
    ])

    assert percakapan.mengandung("15 menit lagi itu jam")
    assert alarm.daftar_aktif() == []


# =========================================================================
# ALUR 14 — Penalaran Groq: terjemahkan maksud ke perintah baku
# =========================================================================
def test_alur_groq_menerjemahkan_bahasa_bebas(monkeypatch):
    """Kalimat yang lolos dari semua aturan dipahami lewat terjemahan Groq."""
    import src.nlp.groq_reasoner as gr

    monkeypatch.setattr(gr, "pahami_maksud_groq", lambda k, p=None: (
        {"perintah": "cek jadwal besok", "aksi": "baca"}
        if "free" in k else None))

    percakapan, _ = jalankan_sesi(monkeypatch, [
        "besok aku free gak sih",
        "terima kasih",
    ])
    assert percakapan.mengandung("tidak ada jadwal")
    assert not percakapan.mengandung("belum mengerti")


def test_alur_terjemahan_ke_timer_melewati_jalur_timer(monkeypatch):
    """Terjemahan diproses dari AWAL — termasuk pendeteksi timer, bukan cuma parser."""
    import src.nlp.groq_reasoner as gr
    from src.dialog import alarm

    alarm.batalkan_semua()
    monkeypatch.setattr(gr, "pahami_maksud_groq", lambda k, p=None: (
        {"perintah": "timer 10 menit untuk angkat jemuran", "aksi": "timer"}
        if "jemuran" in k else None))

    percakapan, _ = jalankan_sesi(monkeypatch, [
        "sepuluh menitan lagi kabarin soal jemuran ya",
        "matikan timer",
        "terima kasih",
    ])
    assert percakapan.mengandung("timer")
    alarm.batalkan_semua()


def test_alur_terjemahan_yang_tidak_terbukti_dibuang(monkeypatch):
    """
    Groq mengklaim "catat", tapi kalimat terjemahannya tidak dibaca parser
    sebagai catat. Hasilnya harus dibuang: Groq hanya boleh menerjemahkan,
    tidak boleh memutuskan sendiri.
    """
    import src.nlp.groq_reasoner as gr

    monkeypatch.setattr(gr, "pahami_maksud_groq", lambda k, p=None: (
        {"perintah": "kucing tetangga lucu sekali", "aksi": "catat"}))

    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "hmm kucing tetangga lucu",
        "terima kasih",
    ])
    assert kalender.dibuat == []
    assert percakapan.mengandung("belum mengerti")


def test_alur_kata_benda_tunggal_tidak_diterjemahkan(monkeypatch):
    """
    "Jadwal" sendirian biasanya hasil derau. Mengirimnya ke Groq akan
    menghasilkan "cek jadwal" dan menjebol perbaikan derau sebelumnya.
    """
    import src.nlp.groq_reasoner as gr

    dipanggil = []
    monkeypatch.setattr(gr, "pahami_maksud_groq",
                        lambda k, p=None: dipanggil.append(k) or None)

    jalankan_sesi(monkeypatch, ["jadwal", "terima kasih"])
    assert dipanggil == []


def test_alur_terjemahan_tidak_berputar(monkeypatch):
    """Kalau terjemahan pun tidak dipahami, jangan diterjemahkan lagi."""
    import src.nlp.groq_reasoner as gr

    dipanggil = []
    def selalu_menerjemahkan(k, p=None):
        dipanggil.append(k)
        return {"perintah": "bla bla bla", "aksi": "baca"}

    monkeypatch.setattr(gr, "pahami_maksud_groq", selalu_menerjemahkan)
    jalankan_sesi(monkeypatch, ["sesuatu yang aneh sekali", "terima kasih"])
    assert len(dipanggil) == 1



def test_alur_timer_menang_melawan_label_groq_yang_salah(monkeypatch):
    """
    Meniru persis log dari laptop dengan Groq sungguhan: pengklasifikasi
    label menjawab "reminder" untuk kalimat tentang timer. Penerjemah harus
    dicoba LEBIH DULU, sehingga label yang salah itu tidak pernah dipakai.
    """
    import src.nlp.groq_reasoner as gr
    from src.dialog import alarm

    alarm.batalkan_semua()
    label_dipakai = []
    monkeypatch.setattr(gr, "classify_intent_groq",
                        lambda t: label_dipakai.append(t) or ("reminder", None))
    monkeypatch.setattr(gr, "pahami_maksud_groq", lambda k, p=None: (
        {"perintah": "timer 10 menit untuk angkat jemuran", "aksi": "timer"}
        if "jemuran" in k else None))

    percakapan, _ = jalankan_sesi(monkeypatch, [
        "sepuluh menitan lagi kabarin soal jemuran ya",
        "matikan timer",
        "terima kasih",
    ])

    assert percakapan.mengandung("timer")
    assert not percakapan.mengandung("berapa lama sebelum acara")
    assert label_dipakai == [], "label Groq yang salah tidak boleh sampai dipakai"
    alarm.batalkan_semua()


def test_alur_bukan_perintah_tidak_dipaksa_jadi_label(monkeypatch):
    """Groq menilai "bukan perintah" -> pengklasifikasi label tidak boleh memaksakan."""
    import src.nlp.groq_reasoner as gr

    label_dipakai = []
    monkeypatch.setattr(gr, "classify_intent_groq",
                        lambda t: label_dipakai.append(t) or ("catat", None))
    monkeypatch.setattr(gr, "pahami_maksud_groq", lambda k, p=None: {"bukan": True})

    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "kucing tetangga lucu banget",
        "terima kasih",
    ])
    assert label_dipakai == []
    assert kalender.dibuat == []
    assert percakapan.mengandung("belum mengerti")
