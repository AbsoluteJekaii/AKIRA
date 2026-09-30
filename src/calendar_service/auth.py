"""
Modul autentikasi Google Calendar (OAuth 2.0).
Tanggung jawab: Person 1 (Calendar & Backend Integration Lead)
"""
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from loguru import logger

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = "config/token.json"
CREDENTIALS_PATH = "config/credentials.json"


def get_credentials():
    """
    Ambil kredensial Google Calendar yang valid.
    Kalau belum pernah login -> buka browser untuk OAuth flow.
    Kalau token expired -> refresh otomatis tanpa perlu login ulang.
    """
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Token expired, mencoba refresh...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"'{CREDENTIALS_PATH}' tidak ditemukan. "
                    "Download dari Google Cloud Console > Credentials > OAuth client ID (Desktop app)."
                )
            logger.info("Membuka browser untuk login Google Calendar...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())
        logger.info(f"Token disimpan di {TOKEN_PATH}")

    return creds


if __name__ == "__main__":
    # Jalankan langsung file ini untuk test login pertama kali:
    #   python -m src.calendar_service.auth
    creds = get_credentials()
    print("Login berhasil! Token valid:", creds.valid)
