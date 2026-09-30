"""
Sapaan dinamis AKIRA berdasarkan jam sistem, dengan variasi acak.

Variasi ini penting: kalau AKIRA selalu bilang kalimat yang sama persis,
terasa robotik walaupun suaranya bagus. Acak kalimat bikin terasa lebih hidup.
"""
import random
from datetime import datetime


def get_time_period() -> str:
    """Tentukan periode waktu berdasarkan jam sistem."""
    hour = datetime.now().hour
    if 4 <= hour < 11:
        return "Pagi"
    if 11 <= hour < 15:
        return "Siang"
    if 15 <= hour < 18:
        return "Sore"
    return "Malam"


# {name} = panggilan user, {waktu} = Pagi/Siang/Sore/Malam
GREETING_TEMPLATES = [
    "Halo {name}, Selamat {waktu}. Bagaimana kabar Anda?",
    "Selamat {waktu}, {name}. Ada yang bisa saya bantu?",
    "Halo {name}, Selamat {waktu}. Saya siap membantu.",
    "Selamat {waktu}, {name}. Apa yang bisa saya lakukan untuk Anda?",
    "Halo {name}. Selamat {waktu}, semoga hari Anda menyenangkan. Ada yang bisa dibantu?",
]

# Sapaan khusus larut malam (di atas jam 11 malam) — terasa lebih perhatian
LATE_NIGHT_TEMPLATES = [
    "Halo {name}, sudah larut malam. Ada yang bisa saya bantu?",
    "Selamat Malam {name}. Masih terjaga? Ada yang bisa saya bantu?",
]


# Sapaan singkat untuk panggilan KEDUA dan seterusnya di hari yang sama.
# Sapaan panjang tiap kali dipanggil terasa bertele-tele — user sudah tahu
# sekarang pagi, dia cuma mau langsung memberi perintah.
SHORT_TEMPLATES = [
    "Ya {name}?",
    "Siap {name}.",
    "Ya, saya dengar.",
    "Ada apa {name}?",
    "Silakan {name}.",
]


def get_greeting(speaker_name: str = "Bos", singkat: bool = False) -> str:
    """
    Susun kalimat sapaan sesuai waktu, dipilih acak dari beberapa variasi.
    singkat=True -> sapaan pendek, dipakai untuk panggilan kedua dst di hari sama.
    """
    if singkat:
        return random.choice(SHORT_TEMPLATES).format(name=speaker_name)

    hour = datetime.now().hour
    waktu = get_time_period()

    templates = LATE_NIGHT_TEMPLATES if hour >= 23 or hour < 4 else GREETING_TEMPLATES
    template = random.choice(templates)
    return template.format(name=speaker_name, waktu=waktu)


if __name__ == "__main__":
    # Jalankan beberapa kali untuk lihat variasinya:
    #   python -m src.utils.greeting
    print(f"Periode saat ini: {get_time_period()}\n")
    print("Sapaan pembuka hari:")
    for i in range(5):
        print(f"  {i+1}. {get_greeting()}")
    print("\nSapaan singkat (panggilan berikutnya):")
    for i in range(5):
        print(f"  {i+1}. {get_greeting(singkat=True)}")
