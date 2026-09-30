"""
Modul CRUD Google Calendar: create, read, delete, reschedule event.
Tanggung jawab: Person 1 (Calendar & Backend Integration Lead)
"""
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger

from src.calendar_service.auth import get_credentials

TIMEZONE = "Asia/Jakarta"


def get_service():
    creds = get_credentials()
    return build("calendar", "v3", credentials=creds)


def create_event(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    timezone: str = TIMEZONE,
    description: str = None,
):
    """
    start_datetime / end_datetime format ISO: '2026-09-10T15:00:00'
    description opsional — diisi dari pertanyaan susulan AKIRA kalau user mau.
    """
    service = get_service()
    event = {
        "summary": summary,
        "start": {"dateTime": start_datetime, "timeZone": timezone},
        "end": {"dateTime": end_datetime, "timeZone": timezone},
    }
    if description:
        event["description"] = description
    try:
        created = service.events().insert(calendarId="primary", body=event).execute()
        logger.info(f"Event dibuat: {created.get('summary')} ({created.get('id')})")
        return created
    except HttpError as e:
        logger.error(f"Gagal membuat event: {e}")
        raise


def read_events(max_results: int = 10, time_min: str = None, time_max: str = None):
    """
    Baca event ke depan (default: dari sekarang), diurutkan berdasarkan waktu mulai.

    time_max ditambahkan di Sprint 3 supaya permintaan rentang ("jadwal tahun 2026")
    disaring di sisi Google, bukan dengan mengambil N event terdekat lalu
    menyaring manual di Python — cara lama tidak pernah sampai ke bulan Desember.
    """
    import datetime

    service = get_service()
    if time_min is None:
        time_min = datetime.datetime.utcnow().isoformat() + "Z"

    params = dict(
        calendarId="primary",
        timeMin=time_min,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    )
    if time_max:
        params["timeMax"] = time_max

    events_result = service.events().list(**params).execute()
    events = events_result.get("items", [])
    logger.info(f"Ditemukan {len(events)} event")
    return events


def update_event(event_id: str, perubahan: dict):
    """
    Perbarui sebagian isi event (patch), bukan menimpa seluruhnya.

    Dipakai fitur edit: user cuma mengubah nama atau jam, sisanya —
    termasuk pengingat khusus yang sudah dipasang — harus tetap utuh.
    """
    service = get_service()
    try:
        updated = service.events().patch(
            calendarId="primary", eventId=event_id, body=perubahan
        ).execute()
        logger.info(f"Event {event_id} diperbarui: {list(perubahan)}")
        return updated
    except HttpError as e:
        logger.error(f"Gagal memperbarui event {event_id}: {e}")
        raise


def set_event_reminder(event_id: str, minutes_before: int, method: str = "popup"):
    """
    Pasang pengingat khusus pada satu event (menimpa pengingat default kalender).

    Disimpan di Google Calendar, bukan di file lokal, jadi:
    - tetap ada walau AKIRA dimatikan atau dipindah ke laptop lain
    - ikut muncul sebagai notifikasi di HP lewat aplikasi Google Calendar
    - dibaca balik oleh loop reminder AKIRA untuk menentukan kapan bicara

    minutes_before: 0 - 40320 (maksimal 4 minggu, batas dari Google).
    """
    service = get_service()
    minutes_before = max(0, min(int(minutes_before), 40320))

    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        event["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": method, "minutes": minutes_before}],
        }
        updated = service.events().update(
            calendarId="primary", eventId=event_id, body=event
        ).execute()
        logger.info(f"Pengingat event {event_id} diatur {minutes_before} menit sebelumnya")
        return updated
    except HttpError as e:
        logger.error(f"Gagal mengatur pengingat event {event_id}: {e}")
        raise


def find_event_by_keyword(keyword: str, max_results: int = 20):
    """
    Cari event berdasarkan keyword di judul (dipakai untuk hapus/reschedule via suara,
    karena user biasanya menyebut nama kegiatan, bukan event ID).
    """
    events = read_events(max_results=max_results)
    matches = [e for e in events if keyword.lower() in e.get("summary", "").lower()]
    return matches


def delete_event(event_id: str):
    service = get_service()
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info(f"Event {event_id} dihapus")
        return True
    except HttpError as e:
        logger.error(f"Gagal menghapus event {event_id}: {e}")
        raise


def reschedule_event(event_id: str, new_start_datetime: str, new_end_datetime: str, timezone: str = TIMEZONE):
    service = get_service()
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        event["start"] = {"dateTime": new_start_datetime, "timeZone": timezone}
        event["end"] = {"dateTime": new_end_datetime, "timeZone": timezone}
        updated = service.events().update(calendarId="primary", eventId=event_id, body=event).execute()
        logger.info(f"Event {event_id} di-reschedule ke {new_start_datetime}")
        return updated
    except HttpError as e:
        logger.error(f"Gagal reschedule event {event_id}: {e}")
        raise


if __name__ == "__main__":
    # Test manual cepat:
    #   python -m src.calendar_service.crud
    import datetime

    start = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(
        hour=15, minute=0, second=0, microsecond=0
    ).isoformat()
    end = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(
        hour=16, minute=0, second=0, microsecond=0
    ).isoformat()

    event = create_event("Test Event dari AKIRA", start, end)
    print("Event ID:", event["id"])

    events = read_events(max_results=5)
    for e in events:
        print("-", e.get("summary"), e["start"].get("dateTime", e["start"].get("date")))
