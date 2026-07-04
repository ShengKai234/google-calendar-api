import json
from pathlib import Path

from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def get_credentials(service_account_file: str) -> service_account.Credentials:
    return service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=SCOPES,
    )


def get_service_account_email(service_account_file: str) -> str:
    data = json.loads(Path(service_account_file).read_text())
    return data["client_email"]
