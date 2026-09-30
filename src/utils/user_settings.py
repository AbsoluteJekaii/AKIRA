"""
Pengaturan pribadi yang bisa diubah lewat suara.
Tanggung jawab: Person 4 (Dialog UX Lead) — Sprint 3.12

Saat ini hanya nama panggilan, tapi strukturnya siap untuk pengaturan lain
(kecepatan bicara, suara, dsb) tanpa perlu bongkar kode.

Disimpan ke file supaya bertahan antar-restart. Beda dengan status briefing
yang sengaja per-run, nama panggilan jelas harus diingat selamanya.
"""
import json
import os
import re

from loguru import logger

SETTINGS_PATH = "config/user_settings.json"

# Kata yang tidak mungkin jadi nama panggilan — biasanya kebawa dari kalimat.
BUKAN_NAMA = {
    "saya", "aku", "gue", "gua", "kamu", "dia", "dong", "aja", "saja", "ya",
    "dengan", "pakai", "panggil", "nama", "namaku", "namanya", "sebagai",
    "mulai", "sekarang", "lagi", "jangan", "bukan", "itu", "ini", "yang",
    "tolong", "coba", "deh", "sih", "nih", "kok", "aja",
}

POLA_GANTI_NAMA = [
    r"panggil\s+(?:saya|aku|gue|gua)\s+(?:dengan\s+)?(?:nama\s+)?(.+)",
    r"nama\s*(?:saya|ku|aku|panggilan\s*saya)\s*(?:adalah\s*)?(.+)",
    r"(?:ganti|ubah)\s+(?:nama\s+)?panggilan(?:\s*saya)?\s*(?:jadi|menjadi|ke)\s*(.+)",
    r"jangan\s+panggil\s+(?:saya|aku)\s+\w+[,.]?\s*panggil\s+(.+)",
    r"sebut\s+(?:saya|aku)\s+(.+)",
]

_COMPILED_NAMA = [re.compile(p) for p in POLA_GANTI_NAMA]


def _load() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        return {}
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Gagal baca pengaturan pengguna ({e}), pakai default")
        return {}


def _save(data: dict):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Gagal simpan pengaturan pengguna: {e}")


def get_nama_panggilan(default: str = None) -> str:
    """
    Nama panggilan yang dipakai AKIRA.
    Urutan: file pengaturan -> variabel .env -> "Bos".
    """
    tersimpan = _load().get("nama_panggilan")
    if tersimpan:
        return tersimpan
    return default or os.getenv("SPEAKER_NAME", "Bos")


def set_nama_panggilan(nama: str) -> str:
    """Simpan nama panggilan baru. Return nama yang benar-benar tersimpan."""
    nama = bersihkan_nama(nama)
    if not nama:
        raise ValueError("Nama panggilan kosong")

    data = _load()
    data["nama_panggilan"] = nama
    _save(data)
    logger.info(f"Nama panggilan diubah jadi '{nama}'")
    return nama


def bersihkan_nama(teks: str) -> str | None:
    """
    Rapikan hasil tangkapan jadi nama yang layak diucapkan.
    Maksimal 3 kata, tanpa kata pengisi, huruf awal kapital.
    """
    if not teks:
        return None

    teks = re.sub(r"[^\w\s'-]", " ", teks.strip())
    kata = [k for k in teks.split() if k.lower() not in BUKAN_NAMA]
    if not kata:
        return None

    return " ".join(k.capitalize() for k in kata[:3])


def deteksi_ganti_nama(text: str) -> str | None:
    """
    Deteksi permintaan ganti nama panggilan dari kalimat bebas.

    "panggil saya Dzaky"              -> "Dzaky"
    "nama saya Maulana Dzaky"         -> "Maulana Dzaky"
    "ganti panggilan jadi Kak Dzaky"  -> "Kak Dzaky"

    Return None kalau bukan permintaan ganti nama.
    """
    if not text:
        return None
    t = text.lower().strip(" .!?")

    for pola in _COMPILED_NAMA:
        m = pola.search(t)
        if not m:
            continue
        nama = bersihkan_nama(m.group(1))
        if nama:
            logger.info(f"Permintaan ganti nama panggilan terdeteksi: '{nama}'")
            return nama
    return None


if __name__ == "__main__":
    # python -m src.utils.user_settings
    print("Nama sekarang:", get_nama_panggilan())

    for kalimat in [
        "panggil saya Dzaky",
        "panggil aku dengan nama Kak Dzaky",
        "nama saya Maulana Dzaky Putra",
        "ganti panggilan jadi Bos Besar",
        "sebut saya kapten",
        "catat jadwal meeting besok",     # bukan ganti nama
    ]:
        print(f"  {kalimat!r:42} -> {deteksi_ganti_nama(kalimat)!r}")
