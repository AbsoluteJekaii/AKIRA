"""
Cek model LLM & STT mana yang benar-benar bisa dipakai dengan API key-mu.

    python scripts/cek_model_llm.py

Nama model di Groq dan OpenRouter berubah cukup sering — model yang kemarin
ada bisa dihentikan hari ini, dan gejalanya cuma 404 yang tidak menjelaskan
apa pun. Skrip ini menanyakan langsung ke penyedianya.

Butuh internet. Tidak mengubah apa pun, hanya membaca.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env")


def daftar_model_groq():
    import requests

    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        print("  GROQ_API_KEY kosong — dilewati")
        return []

    try:
        r = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
        r.raise_for_status()
        return sorted(m["id"] for m in r.json().get("data", []))
    except Exception as e:
        print(f"  Gagal mengambil daftar model Groq: {e}")
        return []


def uji_model_llm(penyedia: str, model: str) -> str:
    """Panggil satu model dengan pesan sangat pendek. Return 'OK' atau alasan gagal."""
    from src.stt.ensemble import _panggil_groq_llm

    fungsi = {"groq": _panggil_groq_llm, "groq2": _panggil_groq_llm}[penyedia]
    try:
        fungsi('Balas JSON: {"teks": "ok"}', "tes", model)
        return "OK"
    except Exception as e:
        pesan = str(e)
        if "404" in pesan:
            return "tidak ada / dihentikan"
        if "401" in pesan or "403" in pesan:
            return "API key ditolak"
        if "402" in pesan or "payment" in pesan.lower():
            return "akun tanpa kredit (butuh saldo, atau pakai model :free)"
        if "429" in pesan:
            return "kuota habis / terlalu cepat"
        return pesan[:60]


def main():
    from src.stt.ensemble import MODEL_CADANGAN

    print("=" * 64)
    print("MODEL YANG TERSEDIA DI GROQ")
    print("=" * 64)

    semua = daftar_model_groq()
    if semua:
        stt = [m for m in semua if "whisper" in m]
        llm = [m for m in semua if "whisper" not in m and "guard" not in m]
        print(f"\n  Model transkripsi ({len(stt)}):")
        for m in stt:
            print(f"    - {m}")
        print(f"\n  Model bahasa ({len(llm)}):")
        for m in llm:
            print(f"    - {m}")

    print("\n" + "=" * 64)
    print("UJI MODEL PEREKONSILIASI (lapis 2)")
    print("=" * 64)

    for penyedia in ("groq", "groq2"):
        env_key = "GROQ_API_KEY"
        print(f"\n  {penyedia}:")

        if not os.getenv(env_key, "").strip():
            print(f"    {env_key} kosong — dilewati")
            continue

        for model in MODEL_CADANGAN[penyedia]:
            hasil = uji_model_llm(penyedia, model)
            tanda = "OK " if hasil == "OK" else "-  "
            print(f"    [{tanda}] {model:38} {hasil if hasil != 'OK' else ''}")

    print("\n" + "=" * 64)
    print("Model pertama yang OK akan otomatis dipakai AKIRA, dan diingat")
    print("supaya panggilan berikutnya langsung ke model yang terbukti hidup.")
    print("=" * 64)


if __name__ == "__main__":
    main()
