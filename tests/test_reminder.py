"""
Unit test untuk reminder.py (pakai event palsu, tanpa API Google) — Sprint 2
Jalankan: pytest tests/test_reminder.py -v
"""
from datetime import datetime, timedelta

from src.dialog.reminder import build_reminder_message, parse_event_start


def test_parse_event_start():
    now = datetime.now().astimezone()
    event = {"start": {"dateTime": (now + timedelta(minutes=10)).isoformat()}}
    result = parse_event_start(event)
    assert result is not None


def test_parse_event_allday_return_none():
    """Event all-day tidak punya dateTime, harus di-skip (tidak crash)."""
    event = {"start": {"date": "2026-09-10"}}
    assert parse_event_start(event) is None


def test_build_reminder_message():
    now = datetime.now().astimezone()
    event = {"id": "x", "summary": "Meeting klien", "start": {"dateTime": (now + timedelta(minutes=10)).isoformat()}}
    start_dt = parse_event_start(event)
    msg = build_reminder_message(event, start_dt)
    assert "Meeting klien" in msg
    assert "menit lagi" in msg
