"""
Cek API key mana yang sudah terbaca AKIRA.

    python scripts/cek_api_key.py

Menampilkan isi .env yang relevan (nilainya disamarkan) dan status tiap mesin
STT. Berguna saat sebuah mesin "tidak jalan" dan kamu perlu tahu apakah
masalahnya di key, di library, atau di config.

Tidak menyentuh jaringan — hanya membaca file dan variabel lingkungan.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

KEY_PENTING = [
    ("GROQ_API_KEY", "STT groq-turbo/groq-v3 + penalar lapis 2"),
    ("GROQ_LLM_MODEL", "model LLM Groq untuk rekonsiliasi (opsional)"),
    ("GROQ_STT_MODEL", "model Whisper di Groq (opsional)"),
    ("STT_ENGINE", "timpa stt.engine dari settings.yaml (opsional)"),
]


def samarkan(nilai: str) -> str:
    """Tampilkan cukup untuk memastikan key-nya benar, tanpa membocorkan isinya."""
    if not nilai:
        return "(kosong)"
    if len(nilai) <= 8:
        return "*" * len(nilai)
    return f"{nilai[:4]}...{nilai[-4:]}  ({len(nilai)} karakter)"


def cek_file_env():
    print("=" * 64)
    print("FILE .env")
    print("=" * 64)

    if not os.path.exists(".env"):
        print("  [MASALAH] File .env TIDAK ADA.")
        print("            AKIRA membaca .env, bukan .env.example.")
        print("            Buat dengan: Copy-Item .env.example .env")
        return False

    ukuran = os.path.getsize(".env")
    print(f"  File .env ditemukan ({ukuran} byte)")

    # Kesalahan paling sering: file tersimpan sebagai .env.txt
    lain = [f for f in os.listdir(".") if f.lower().startswith(".env") and f != ".env"]
    if lain:
        print(f"  Catatan: ada juga {', '.join(lain)} — pastikan yang diisi adalah .env")
    return True


def cek_key():
    load_dotenv()

    print("\n" + "=" * 64)
    print("API KEY & PENGATURAN")
    print("=" * 64)

    terisi = 0
    for nama, keterangan in KEY_PENTING:
        nilai = os.getenv(nama, "").strip()
        tanda = "OK " if nilai else "-  "
        if nilai:
            terisi += 1
        print(f"  [{tanda}] {nama:22} {samarkan(nilai)}")
        print(f"        {keterangan}")
    return terisi


def cek_mesin():
    print("\n" + "=" * 64)
    print("STATUS MESIN STT")
    print("=" * 64)

    try:
        from src.stt.backends import cek_kesiapan

        for nama, keterangan in cek_kesiapan().items():
            tanda = "OK " if keterangan == "siap" else "-  "
            print(f"  [{tanda}] {nama:16} {keterangan}")
    except Exception as e:
        print(f"  Tidak bisa mengecek: {e}")


def cek_config():
    print("\n" + "=" * 64)
    print("CONFIG YANG SEDANG DIPAKAI")
    print("=" * 64)

    try:
        import yaml

        cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
        stt = cfg.get("stt", {})
        ens = stt.get("ensemble", {}) or {}

        engine = stt.get("engine")
        print(f"  stt.engine              : {engine}")
        print(f"  stt.model_size          : {stt.get('model_size')}")
        print(f"  perekonsiliasi lapis 2  : {ens.get('perekonsiliasi')}")

        pakai_groq = any("groq" in str(m) for m in (engine if isinstance(engine, list) else [engine]))
        pakai_groq = pakai_groq or any("groq" in str(m) for m in ens.get("perekonsiliasi", []))
        if pakai_groq and not os.getenv("GROQ_API_KEY", "").strip():
            print()
            print("  [MASALAH] Config memakai Groq tapi GROQ_API_KEY kosong.")
            print("            AKIRA akan jatuh ke Whisper lokal dan qwen3 lokal saja.")
    except Exception as e:
        print(f"  Tidak bisa membaca config: {e}")


def main():
    if not cek_file_env():
        return
    cek_key()
    cek_mesin()
    cek_config()

    print("\n" + "=" * 64)
    print("Menambahkan key baru: buka .env di VS Code, tambahkan barisnya,")
    print("simpan, lalu jalankan skrip ini lagi untuk memastikan terbaca.")
    print("=" * 64)


if __name__ == "__main__":
    main()
