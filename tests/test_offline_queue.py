"""
Uji antrean offline: jadwal yang dibuat saat internet putus disimpan dulu,
lalu dikirim otomatis ke Google Calendar saat online lagi.

Jalankan: pytest tests/test_offline_queue.py -v
"""
import socket

import pytest

from src.calendar_service import offline_queue


class HttpErrorPalsu(Exception):
    """Meniru googleapiclient HttpError: punya .resp.status."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.resp = type("Resp", (), {"status": status})()


class ServerNotFoundError(Exception):
    """Nama kelas sama dengan galat httplib2 saat DNS gagal."""


@pytest.fixture(autouse=True)
def antrean_sementara(tmp_path, monkeypatch):
    monkeypatch.setattr(offline_queue, "ANTREAN_PATH", str(tmp_path / "pending_events.json"))
    yield


def _data_catat():
    return {"aksi": "catat", "kegiatan": "Rapat tim", "tanggal": "2026-10-20",
            "jam": "15:00", "deskripsi": None}


# ------------------------------------------------------------ deteksi jaringan
@pytest.mark.parametrize("galat", [
    ConnectionError("putus"),
    TimeoutError("timeout"),
    socket.gaierror("dns"),
    ServerNotFoundError("Unable to find the server at www.googleapis.com"),
    HttpErrorPalsu(503),
])
def test_galat_jaringan_dikenali(galat):
    assert offline_queue.galat_jaringan(galat)


@pytest.mark.parametrize("galat", [
    HttpErrorPalsu(400),
    HttpErrorPalsu(401),
    HttpErrorPalsu(404),
    FileNotFoundError("config/credentials.json"),
    ValueError("format jam salah"),
])
def test_galat_lain_tidak_dianggap_offline(galat):
    assert not offline_queue.galat_jaringan(galat)


def test_galat_jaringan_dibungkus_tetap_dikenali():
    try:
        try:
            raise ConnectionError("putus")
        except ConnectionError as dalam:
            raise RuntimeError("gagal membuat event") from dalam
    except RuntimeError as luar:
        assert offline_queue.galat_jaringan(luar)


# ------------------------------------------------------------ simpan & baca
def test_simpan_tersimpan_ke_file_dan_bisa_dibaca_ulang():
    item = offline_queue.simpan("Rapat tim", "2026-10-20T15:00:00", "2026-10-20T16:00:00")
    assert offline_queue.jumlah() == 1
    tersimpan = offline_queue.daftar()[0]
    assert tersimpan["id"] == item["id"]
    assert tersimpan["summary"] == "Rapat tim"
    # ID harus memenuhi syarat Google: base32hex (0-9, a-v), panjang 5-1024
    assert all(c in "0123456789abcdefghijklmnopqrstuv" for c in item["id"])
    assert 5 <= len(item["id"]) <= 1024


def test_file_rusak_tidak_menghentikan_akira(tmp_path):
    with open(offline_queue.ANTREAN_PATH, "w", encoding="utf-8") as f:
        f.write("{bukan json")
    assert offline_queue.daftar() == []
    offline_queue.simpan("Rapat", "2026-10-20T15:00:00", "2026-10-20T16:00:00")
    assert offline_queue.jumlah() == 1


# ------------------------------------------------------------ executor
def test_catat_saat_offline_disimpan_ke_antrean(monkeypatch):
    from src.calendar_service import crud, executor

    def gagal(*a, **k):
        raise ServerNotFoundError("Unable to find the server")

    monkeypatch.setattr(crud, "create_event", gagal)
    hasil = executor.execute(_data_catat())

    assert hasil["success"] is True
    assert hasil["offline"] is True
    assert "terputus" in hasil["message"]
    assert offline_queue.jumlah() == 1
    assert hasil["data"]["summary"] == "Rapat tim"


def test_catat_galat_bukan_jaringan_tidak_diantrekan(monkeypatch):
    from src.calendar_service import crud, executor

    def ditolak(*a, **k):
        raise HttpErrorPalsu(401)

    monkeypatch.setattr(crud, "create_event", ditolak)
    hasil = executor.execute(_data_catat())

    assert hasil["success"] is False
    assert offline_queue.jumlah() == 0


def test_catat_saat_online_tidak_menyentuh_antrean(monkeypatch):
    from src.calendar_service import crud, executor

    monkeypatch.setattr(crud, "create_event",
                        lambda *a, **k: {"id": "ev1", "summary": a[0]})
    hasil = executor.execute(_data_catat())

    assert hasil["success"] is True
    assert "offline" not in hasil
    assert offline_queue.jumlah() == 0


# ------------------------------------------------------------ sinkronisasi
def test_sinkron_mengirim_semua_lalu_mengosongkan_antrean():
    offline_queue.simpan("Rapat", "2026-10-20T15:00:00", "2026-10-20T16:00:00")
    offline_queue.simpan("Futsal", "2026-10-21T19:00:00", "2026-10-21T20:00:00")
    terkirim = []

    def kirim(summary, start, end, description=None, event_id=None):
        terkirim.append((summary, event_id))
        return {"id": event_id}

    berhasil, masih_offline = offline_queue.sinkronkan(kirim)

    assert [b["summary"] for b in berhasil] == ["Rapat", "Futsal"]
    assert masih_offline is False
    assert offline_queue.jumlah() == 0
    assert all(event_id for _, event_id in terkirim)   # ID antrean ikut dikirim


def test_sinkron_berhenti_kalau_masih_offline():
    offline_queue.simpan("Rapat", "2026-10-20T15:00:00", "2026-10-20T16:00:00")
    offline_queue.simpan("Futsal", "2026-10-21T19:00:00", "2026-10-21T20:00:00")
    percobaan = []

    def kirim(summary, *a, **k):
        percobaan.append(summary)
        raise ConnectionError("masih putus")

    berhasil, masih_offline = offline_queue.sinkronkan(kirim)

    assert berhasil == []
    assert masih_offline is True
    assert percobaan == ["Rapat"]          # tidak mencoba sisanya
    assert offline_queue.jumlah() == 2     # tidak ada yang hilang


def test_sinkron_409_dianggap_sudah_masuk_bukan_dibuat_ganda():
    offline_queue.simpan("Rapat", "2026-10-20T15:00:00", "2026-10-20T16:00:00")

    def kirim(*a, **k):
        raise HttpErrorPalsu(409)

    berhasil, _ = offline_queue.sinkronkan(kirim)
    assert len(berhasil) == 1
    assert offline_queue.jumlah() == 0


def test_sinkron_400_dikirim_ulang_tanpa_id():
    offline_queue.simpan("Rapat", "2026-10-20T15:00:00", "2026-10-20T16:00:00")
    panggilan = []

    def kirim(summary, start, end, description=None, event_id=None):
        panggilan.append(event_id)
        if event_id:
            raise HttpErrorPalsu(400)
        return {"id": "dari-google"}

    berhasil, _ = offline_queue.sinkronkan(kirim)
    assert len(berhasil) == 1
    assert panggilan[0] is not None and panggilan[1] is None
    assert offline_queue.jumlah() == 0


def test_sinkron_galat_permanen_tidak_menghalangi_item_lain():
    offline_queue.simpan("Rusak", "2026-10-20T15:00:00", "2026-10-20T16:00:00")
    offline_queue.simpan("Futsal", "2026-10-21T19:00:00", "2026-10-21T20:00:00")

    def kirim(summary, *a, **k):
        if summary == "Rusak":
            raise HttpErrorPalsu(403)
        return {"id": "ok"}

    berhasil, masih_offline = offline_queue.sinkronkan(kirim)
    assert [b["summary"] for b in berhasil] == ["Futsal"]
    assert masih_offline is False
    assert [i["summary"] for i in offline_queue.daftar()] == ["Rusak"]


# ------------------------------------------------------------ loop reminder
def test_loop_reminder_mengumumkan_jadwal_yang_tersinkron(monkeypatch):
    from src.calendar_service import crud
    from src.dialog import reminder

    offline_queue.simpan("Rapat tim", "2026-10-20T15:00:00", "2026-10-20T16:00:00")
    monkeypatch.setattr(crud, "create_event", lambda *a, **k: {"id": k.get("event_id")})
    diucapkan = []

    reminder.set_busy(False)
    assert reminder.sinkron_antrean(diucapkan.append) == 1
    assert offline_queue.jumlah() == 0
    assert "Rapat tim" in diucapkan[0]


def test_loop_reminder_menunda_sinkron_saat_akira_sibuk(monkeypatch):
    from src.calendar_service import crud
    from src.dialog import reminder

    offline_queue.simpan("Rapat tim", "2026-10-20T15:00:00", "2026-10-20T16:00:00")
    monkeypatch.setattr(crud, "create_event", lambda *a, **k: {"id": "x"})

    reminder.set_busy(True)
    try:
        assert reminder.sinkron_antrean(lambda t: None) == 0
        assert offline_queue.jumlah() == 1
    finally:
        reminder.set_busy(False)


def test_ucapan_hasil_sinkron():
    satu = offline_queue.ucapkan_hasil_sinkron([{"summary": "Rapat"}])
    assert "Rapat" in satu and "tersambung" in satu
    banyak = offline_queue.ucapkan_hasil_sinkron(
        [{"summary": n} for n in ["A", "B", "C", "D", "E"]])
    assert "5 jadwal" in banyak and "2 lainnya" in banyak
    assert offline_queue.ucapkan_hasil_sinkron([]) == ""


# ------------------------------------------------------------ alur utuh
def test_alur_utuh_offline_lalu_online_lagi(monkeypatch):
    """
    Sesi AKIRA sungguhan (handle_session) saat internet putus, lalu internet
    kembali dan loop reminder mengirim antrean. Memakai perkakas simulasi
    dari test_alur_percakapan: mic, speaker, dan kalender tiruan.
    """
    from tests.test_alur_percakapan import Kalender, jalankan_sesi
    from src.dialog import reminder

    class KalenderBisaOffline(Kalender):
        offline = True

        def create_event(self, *a, **k):
            if self.offline:
                raise ConnectionError("internet putus")
            return super().create_event(*a, **k)

        def read_events(self, **kwargs):
            if self.offline:
                raise ConnectionError("internet putus")
            return super().read_events(**kwargs)

    kalender = KalenderBisaOffline()
    percakapan, kalender = jalankan_sesi(monkeypatch, [
        "catat meeting besok jam 3 sore",
        "lewati",          # jam selesai
        "lewati",          # deskripsi
        "benar",           # konfirmasi
        "terima kasih",
    ], kalender=kalender)

    # Saat offline: tidak ada yang masuk kalender, tapi jadwal tidak hilang
    assert kalender.dibuat == []
    assert offline_queue.jumlah() == 1
    assert percakapan.mengandung("internet sedang terputus", "saya simpan dulu")

    # Internet kembali: siklus loop reminder berikutnya mengirimnya
    kalender.offline = False
    diucapkan = []
    reminder.set_busy(False)
    assert reminder.sinkron_antrean(diucapkan.append) == 1

    assert len(kalender.dibuat) == 1
    assert kalender.dibuat[0]["summary"] == "meeting"
    assert offline_queue.jumlah() == 0
    assert "meeting" in diucapkan[0]
