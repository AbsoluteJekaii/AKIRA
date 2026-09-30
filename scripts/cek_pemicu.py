"""
Alat diagnosa: kenapa sebuah kalimat memicu (atau tidak memicu) AKIRA.

Jalankan dari folder proyek:

    python scripts/cek_pemicu.py
    python scripts/cek_pemicu.py "Akira, destrui diri sendiri."

Tanpa argumen, semua kalimat contoh diuji. Dengan argumen, kalimat itu
dibedah satu per satu syaratnya — berguna saat sesuatu "tidak jalan" dan
kamu perlu tahu syarat mana yang gagal.

Tidak menyentuh mikrofon, kalender, maupun LLM. Aman dijalankan kapan saja.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def muat_pemicu():
    """Ambil fungsi pemicu dari app.py tanpa mengimpor modul audio."""
    src = open("src/app.py", encoding="utf-8").read()
    ns = {"re": re}
    exec(src[src.index("PANGGILAN_AKIRA ="):src.index("KATA_NEGATIF")], ns)
    return ns


def periksa(kalimat: str, ns: dict):
    disapa = ns["disapa_akira"](kalimat)
    niat = bool(ns["NIAT_PERINTAH"].search(kalimat.lower()))
    frasa = bool(ns["FRASA_DESTRUCT"].search(kalimat.lower()))

    print(f"\n  Kalimat : {kalimat!r}")
    print(f"  {'[OK] ' if disapa else '[X]  '}menyebut nama AKIRA")
    print(f"  {'[OK] ' if niat else '[X]  '}mengandung niat perintah")
    print(f"  {'[OK] ' if frasa else '[X]  '}mengandung frasa penghancuran")

    if ns["minta_self_destruct"](kalimat):
        print("  ==> MEMICU SELF DESTRUCT")
    elif ns["perintah_untuk_akira"](kalimat):
        print("  ==> MEMBUKA SESI (perintah biasa)")
    else:
        kurang = []
        if not disapa:
            kurang.append("nama AKIRA tidak terdengar")
        elif not niat and not frasa:
            kurang.append("tidak ada kata perintah maupun frasa penghancuran")
        print(f"  ==> DIABAIKAN ({'; '.join(kurang) or 'tidak memenuhi syarat'})")


def cek_konfigurasi():
    import yaml

    print("=" * 62)
    print("KONFIGURASI")
    print("=" * 62)

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    sd = cfg.get("self_destruct", {})
    amb = cfg.get("ambient", {})

    model = sd.get("model_path", "(tidak diatur)")
    ada = os.path.exists(model) if model else False

    print(f"  model wake word rahasia : {model}")
    print(f"  file-nya ada?           : {'YA' if ada else 'TIDAK — jalur wake word mati'}")
    print(f"  ambang wake word        : {sd.get('threshold')}")
    print(f"  deteksi lewat teks      : {sd.get('aktif_lewat_teks')}")
    print(f"  tingkat penghapusan     : {sd.get('tingkat')}")
    print(f"  cadangan dibuat?        : {sd.get('backup')}")
    print(f"  mode ambient            : {amb.get('enabled')} ({amb.get('timeout_menit')} menit)")

    if amb.get("enabled") and not sd.get("aktif_lewat_teks"):
        print("\n  [MASALAH] Mode ambient menyala tapi deteksi teks mati.")
        print("            Selama ambient jalan, mikrofon dipakai merekam kalimat")
        print("            penuh — model wake word tidak pernah dapat giliran,")
        print("            jadi perintah rahasia TIDAK AKAN PERNAH terpicu.")
        print("            Perbaiki: set self_destruct.aktif_lewat_teks: true")


CONTOH = [
    "Akira, destrui diri sendiri.",
    "Akhirnya, destrui diri sendiri.",
    "akira destroy yourself",
    "akira hancurkan dirimu",
    "destroy yourself",
    "Akira, coba bacakan jadwal saya",
    "Terima kasih.",
    "akhirnya selesai juga tugasnya",
]


def main():
    ns = muat_pemicu()
    cek_konfigurasi()

    print("\n" + "=" * 62)
    print("UJI KALIMAT")
    print("=" * 62)

    kalimat = sys.argv[1:] or CONTOH
    for k in kalimat:
        periksa(k, ns)

    print("\n" + "=" * 62)
    print("Kalau kalimatmu DIABAIKAN padahal seharusnya memicu, tambahkan")
    print("variasi salah dengarnya ke PANGGILAN_AKIRA atau FRASA_DESTRUCT")
    print("di src/app.py — satu baris, tidak perlu ubah logika.")
    print("=" * 62)


if __name__ == "__main__":
    main()
