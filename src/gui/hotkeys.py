"""
Pintasan keyboard: menjalankan aksi AKIRA tanpa mengucapkan wake word.
Tanggung jawab: Person 4 (Dialog UX) — Sprint 4.1

Berguna dalam tiga keadaan yang sering terjadi:
- Ruangan bising sehingga wake word tidak terdeteksi
- Sedang rapat, tidak bisa bicara keras
- Mikrofon bermasalah dan butuh jalur yang tidak bergantung padanya

Pintasan global (berfungsi meski jendela AKIRA tidak aktif) membutuhkan
pustaka `keyboard`, yang TIDAK wajib dipasang:

    pip install keyboard

Tanpa pustaka itu, pintasan tetap berfungsi selama jendela AKIRA sedang aktif
— cukup untuk kebanyakan keperluan, dan tidak menambah dependensi wajib.

Catatan yang perlu diketahui: di Windows, `keyboard` kadang menuntut hak
Administrator untuk menangkap tombol secara global. Kalau pintasan global
tidak bereaksi, itu penyebab yang paling mungkin.
"""
import json
import os

from loguru import logger

PATH_PINTASAN = "config/pintasan.json"

# Aksi yang bisa dipasangkan ke pintasan, beserta penjelasannya.
AKSI_PINTASAN = {
    "dengar": (
        "Dengarkan sekarang",
        "Langsung mendengarkan perintah, melewati wake word",
    ),
    "baca_hari_ini": (
        "Bacakan jadwal hari ini",
        "Langsung membacakan agenda hari ini",
    ),
    "baca_besok": (
        "Bacakan jadwal besok",
        "Langsung membacakan agenda besok",
    ),
    "catat": (
        "Mulai catat jadwal",
        "Membuka sesi pencatatan; AKIRA akan bertanya detailnya",
    ),
    "hapus": (
        "Mulai hapus jadwal",
        "Membuka sesi penghapusan dengan konfirmasi seperti biasa",
    ),
    "reschedule": (
        "Mulai pindah jadwal",
        "Membuka sesi pemindahan jadwal",
    ),
    "edit": (
        "Mulai edit jadwal",
        "Membuka sesi penyuntingan isi jadwal",
    ),
    "jam_berapa": (
        "Sekarang jam berapa",
        "Menyebutkan waktu saat ini",
    ),
    "buka_jendela": (
        "Tampilkan jendela AKIRA",
        "Memunculkan aplikasi ke depan (tidak menyentuh mikrofon)",
    ),
    "bantu": (
        "Panggil AKIRA (bantu saya)",
        "Membuka sesi seperti mengucapkan 'AKIRA, tolong bantu saya'",
    ),
}

# Kalimat yang dikirim ke AKIRA untuk tiap aksi. "dengar" dan "buka_jendela"
# tidak punya kalimat karena keduanya bukan perintah.
KALIMAT_AKSI = {
    "baca_hari_ini": "bacakan jadwal hari ini",
    # Sengaja kosong: sesi dibuka, lalu AKIRA menunggu perintah lisan.
    # Berguna di ruangan bising, saat nama AKIRA tidak pernah tertangkap.
    "baca_besok": "bacakan jadwal besok",
    "catat": "catat jadwal",
    "hapus": "hapus jadwal",
    "reschedule": "pindahkan jadwal",
    "edit": "edit jadwal",
    "jam_berapa": "sekarang jam berapa",
}

BAWAAN = {
    "dengar": "ctrl+alt+a",
    "bantu": "ctrl+alt+b",
    "baca_hari_ini": "ctrl+alt+h",
    "catat": "ctrl+alt+c",
    "buka_jendela": "ctrl+alt+w",
}

_terdaftar: list = []


def muat() -> dict:
    """Baca pemasangan pintasan. Berkas rusak tidak menghentikan apa pun."""
    if not os.path.exists(PATH_PINTASAN):
        return dict(BAWAAN)
    try:
        with open(PATH_PINTASAN, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in (data or {}).items()
                if k in AKSI_PINTASAN and isinstance(v, str) and v.strip()}
    except Exception as e:
        logger.warning(f"Gagal baca pintasan ({e}), memakai bawaan")
        return dict(BAWAAN)


def simpan(data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(PATH_PINTASAN), exist_ok=True)
        with open(PATH_PINTASAN, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Pintasan disimpan: {len(data)} pemasangan")
        return True
    except Exception as e:
        logger.error(f"Gagal simpan pintasan: {e}")
        return False


def validasi(kombinasi: str, aksi: str, semua: dict) -> tuple:
    """
    Periksa kombinasi sebelum dipasang. Return (boleh, pesan).

    Dua pemeriksaan penting:
    - Harus memakai tombol pengubah (Ctrl/Alt/Shift). Tanpa itu, menekan "a"
      di mana pun akan membangunkan AKIRA.
    - Tidak boleh bentrok dengan aksi lain.
    """
    kombinasi = (kombinasi or "").strip().lower()
    if not kombinasi:
        return False, "Kombinasi kosong."

    bagian = [b.strip() for b in kombinasi.split("+") if b.strip()]
    if len(bagian) < 2:
        return False, "Harus gabungan, misalnya ctrl+alt+a."

    if not any(b in ("ctrl", "alt", "shift", "win") for b in bagian[:-1]):
        return False, (
            "Wajib memakai Ctrl, Alt, atau Shift. Tanpa itu, tombol biasa "
            "akan memicu AKIRA saat kamu sedang mengetik di aplikasi lain."
        )

    for aksi_lain, komb_lain in semua.items():
        if aksi_lain != aksi and komb_lain.lower() == kombinasi:
            nama = AKSI_PINTASAN.get(aksi_lain, (aksi_lain,))[0]
            return False, f"Sudah dipakai untuk '{nama}'."

    return True, kombinasi


def _jalankan(aksi: str, saat_buka_jendela=None):
    """Kirim aksi ke mesin AKIRA lewat saluran pemicu."""
    from src.utils import trigger

    if aksi == "buka_jendela":
        if saat_buka_jendela:
            saat_buka_jendela()
        return

    if aksi in ("dengar", "bantu"):
        trigger.picu_dengar(sumber="pintasan")
        return

    kalimat = KALIMAT_AKSI.get(aksi)
    if kalimat:
        trigger.picu_perintah(kalimat, sumber="pintasan")


def pasang_global(pemasangan: dict, saat_buka_jendela=None) -> tuple:
    """
    Daftarkan pintasan global lewat pustaka `keyboard`.

    Return (berhasil, pesan). Kegagalan tidak fatal — pintasan dalam jendela
    tetap berfungsi.
    """
    lepas_global()

    try:
        import keyboard
    except ImportError:
        return False, (
            "Pustaka 'keyboard' belum terpasang, jadi pintasan hanya berfungsi "
            "saat jendela AKIRA aktif. Untuk pintasan global: pip install keyboard"
        )

    dipasang = 0
    for aksi, kombinasi in pemasangan.items():
        if aksi not in AKSI_PINTASAN:
            continue
        try:
            keyboard.add_hotkey(
                kombinasi,
                lambda a=aksi: _jalankan(a, saat_buka_jendela),
                suppress=False,
            )
            _terdaftar.append(kombinasi)
            dipasang += 1
        except Exception as e:
            logger.warning(f"Pintasan '{kombinasi}' gagal dipasang: {e}")

    if not dipasang:
        return False, (
            "Tidak ada pintasan yang berhasil dipasang. Di Windows, penangkapan "
            "tombol global kadang menuntut hak Administrator."
        )

    logger.info(f"{dipasang} pintasan global aktif")
    return True, f"{dipasang} pintasan global aktif."


def lepas_global():
    """Lepas semua pintasan global yang sedang terpasang."""
    global _terdaftar
    if not _terdaftar:
        return
    try:
        import keyboard

        for kombinasi in _terdaftar:
            try:
                keyboard.remove_hotkey(kombinasi)
            except Exception:
                pass
    except ImportError:
        pass
    _terdaftar = []


def ke_format_tkinter(kombinasi: str) -> str:
    """
    Ubah "ctrl+alt+a" menjadi "<Control-Alt-a>" untuk bind() Tkinter.

    Dipakai jalur cadangan yang hanya aktif saat jendela sedang fokus.
    """
    peta = {"ctrl": "Control", "alt": "Alt", "shift": "Shift"}
    bagian = [b.strip().lower() for b in kombinasi.split("+") if b.strip()]
    if not bagian:
        return ""
    ubah = [peta.get(b, b) for b in bagian[:-1]]
    return "<" + "-".join(ubah + [bagian[-1]]) + ">"


if __name__ == "__main__":
    # python -m src.gui.hotkeys
    print("Aksi yang tersedia:\n")
    for aksi, (nama, jelas) in AKSI_PINTASAN.items():
        print(f"  {aksi:16} {nama:28} {jelas}")

    print("\nPemasangan saat ini:")
    for aksi, komb in muat().items():
        print(f"  {komb:16} -> {AKSI_PINTASAN[aksi][0]}")

    print("\nUji validasi:")
    semua = muat()
    for komb, aksi in [("ctrl+alt+z", "hapus"), ("a", "hapus"),
                       ("ctrl+alt+a", "hapus"), ("f5", "hapus")]:
        print(f"  {komb:14} -> {validasi(komb, aksi, semua)}")
