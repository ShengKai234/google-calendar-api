"""Tests for infrastructure.google_calendar.auth."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from gcal_epd.infrastructure.google_calendar.auth import (
    get_credentials,
    get_service_account_email,
    SCOPES,
)


def _write_fake_sa(path: Path, email: str = "sa@project.iam.gserviceaccount.com") -> None:
    path.write_text(json.dumps({
        "type": "service_account",
        "client_email": email,
        "private_key_id": "key-id",
        "private_key": "fake-key",
        "client_id": "123",
        "project_id": "my-project",
    }))


def test_scopes_contains_calendar_readonly():
    assert "https://www.googleapis.com/auth/calendar.readonly" in SCOPES


def test_get_service_account_email():
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        email = "mysa@project.iam.gserviceaccount.com"
        json.dump({"client_email": email, "other": "stuff"}, f)
        tmp_path = f.name

    result = get_service_account_email(tmp_path)
    assert result == email


def test_get_credentials_calls_from_service_account_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        sa_path = Path(tmpdir) / "sa.json"
        _write_fake_sa(sa_path)

        with patch(
            "gcal_epd.infrastructure.google_calendar.auth.service_account.Credentials.from_service_account_file"
        ) as mock_creds:
            mock_creds.return_value = MagicMock()
            creds = get_credentials(str(sa_path))
            mock_creds.assert_called_once_with(str(sa_path), scopes=SCOPES)
