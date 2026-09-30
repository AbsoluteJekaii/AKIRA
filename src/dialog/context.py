"""
Konteks percakapan dalam satu sesi.
Tanggung jawab: Person 4 (Dialog UX Lead) — Sprint 3.6

Tanpa modul ini, tiap perintah berdiri sendiri. Percakapan seperti ini gagal:

    User : "hari ini saya ada kerjaan nggak?"
    AKIRA: "Ada 1 jadwal: meeting jam 18:00."
    User : "meeting itu reschedule ke besok dong"   <- "itu" merujuk ke apa?

AKIRA sekarang mengingat jadwal yang BARU SAJA dibicarakan, jadi kata rujukan
("itu", "tersebut", "tadi", "yang barusan") bisa diselesaikan.

Konteks sengaja hidup hanya selama satu sesi dan dihapus saat sesi berakhir —
merujuk "jadwal itu" ke sesuatu yang dibicarakan setengah jam lalu justru
berbahaya untuk aksi hapus.
"""
import re

from loguru import logger

# Kata yang menandakan user merujuk ke sesuatu yang baru saja dibicarakan.
KATA_RUJUKAN = [
    "itu", "tersebut", "tadi", "barusan", "yang tadi", "yang barusan",
    "yang itu", "yang ini", "berikut", "yang di atas", "yang sebelumnya",
]

# "sebelumnya" sendirian TIDAK masuk daftar: "30 menit sebelumnya" adalah
# keterangan waktu pengingat, bukan rujukan ke jadwal tertentu.

# Kata "ini" sendirian SENGAJA tidak masuk daftar. "hari ini", "minggu ini",
# "sore ini" adalah keterangan waktu biasa, bukan rujukan ke jadwal tertentu —
# memasukkannya bikin hampir semua perintah dikira memakai rujukan.
_RUJUKAN_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in KATA_RUJUKAN) + r")\b"
)

# "hari itu", "tanggal itu" juga keterangan waktu, bukan rujukan ke event.
_ITU_WAKTU = re.compile(r"\b(?:hari|tanggal|minggu|bulan|tahun|jam|waktu)\s+itu\b")


class KonteksSesi:
    """Ingatan jangka pendek untuk satu sesi percakapan."""

    def __init__(self):
        self.event_terakhir = []     # event yang terakhir dibacakan / dibuat

    def catat_event(self, events):
        """Simpan event yang baru saja dibacakan atau dibuat."""
        if not events:
            return
        if isinstance(events, dict):
            events = [events]
        self.event_terakhir = list(events)[:5]
        judul = [e.get("summary", "?") for e in self.event_terakhir]
        logger.debug(f"Konteks: {len(self.event_terakhir)} event diingat {judul}")

    def bersihkan(self):
        self.event_terakhir = []


def mengandung_rujukan(text: str) -> bool:
    """True kalau kalimat memakai kata rujukan seperti 'itu' atau 'tersebut'."""
    t = (text or "").lower()
    # Buang dulu bentuk keterangan waktu supaya "hari itu" tidak dihitung
    t = _ITU_WAKTU.sub(" ", t)
    return bool(_RUJUKAN_RE.search(t))


def resolusi_rujukan(data: dict, konteks: KonteksSesi) -> dict:
    """
    Isi field yang kosong dari konteks percakapan.

    Dua kasus:
    1. User memakai kata rujukan ("reschedule meeting itu ke besok") — nama
       kegiatan diambil dari event yang terakhir dibicarakan.
    2. User tidak menyebut kegiatan sama sekali untuk aksi hapus/reschedule/reminder,
       padahal barusan cuma ada SATU jadwal yang dibahas — itu yang dimaksud.

    Aman karena hapus & reschedule tetap minta konfirmasi sebelum dieksekusi;
    kalau tebakannya salah, user tinggal bilang "tidak".
    """
    if data.get("aksi") not in ("hapus", "reschedule", "reminder", "edit"):
        return data
    if not konteks or not konteks.event_terakhir:
        return data

    # Perintah yang sudah menyebut SASARANNYA SENDIRI tidak boleh ditimpa
    # konteks. "hapus jadwal hari ini" berarti semua jadwal hari ini —
    # bukan jadwal yang kebetulan barusan dibicarakan.
    if data.get("tanggal") or data.get("tanggal_mulai") or data.get("hapus_semua"):
        logger.debug("Perintah punya sasaran sendiri, konteks tidak dipakai")
        return data

    teks = data.get("teks_asli", "")
    punya_rujukan = mengandung_rujukan(teks)
    kegiatan = data.get("kegiatan")

    # Nama kegiatan yang isinya cuma kata rujukan tidak berguna untuk pencarian
    kegiatan_kosong = not kegiatan or _RUJUKAN_RE.fullmatch(kegiatan.strip())

    if not (punya_rujukan or kegiatan_kosong):
        return data

    if len(konteks.event_terakhir) == 1:
        judul = konteks.event_terakhir[0].get("summary")
        if judul:
            data["kegiatan"] = judul
            data["_dari_konteks"] = True
            logger.info(f"Rujukan diselesaikan dari konteks: '{judul}'")
        return data

    # Lebih dari satu kandidat: biarkan kosong supaya AKIRA membacakan pilihan
    logger.info(
        f"Ada {len(konteks.event_terakhir)} event di konteks, "
        f"user akan diminta memilih"
    )
    return data


if __name__ == "__main__":
    # python -m src.dialog.context
    k = KonteksSesi()
    k.catat_event([{"summary": "meeting", "id": "1"}])

    for teks, kegiatan in [
        ("meeting itu reschedule ke besok dong", "itu"),
        ("hapus jadwal tersebut", None),
        ("hapus jadwal rapat divisi", "rapat divisi"),
    ]:
        data = {"aksi": "hapus", "kegiatan": kegiatan, "teks_asli": teks}
        hasil = resolusi_rujukan(data, k)
        print(f"{teks!r:42} -> kegiatan={hasil['kegiatan']!r}")
