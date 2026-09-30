# Stand-in for Workstream B - not part of the Part C deliverable
"""Connect HelpMate to your Google account (Gmail + Calendar). Run once; again if Google says the
sign-in expired (apps in "Testing" get 7-day sign-ins).

    cd backend
    uv run python ../scripts/google_auth.py

Needs data/google_client_secret.json (a "Desktop app" OAuth client from Google Cloud Console).
Opens Google's consent page in your browser and saves a refresh token (never your password) to
data/google_token.json. Both files are git-ignored. Permissions asked for, as narrow as possible:

  gmail.readonly   read and search your mail (processed only on this machine)
  gmail.send       send a message, and only after you approve its card in HelpMate
  calendar.events  read your events and create one after you approve it

Revoke any time at https://myaccount.google.com/permissions (then delete data/google_token.json).
"""

from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "data" / "google_client_secret.json"
TOKEN = ROOT / "data" / "google_token.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
]


def main() -> None:
    if not CLIENT.exists():
        sys.exit(f"{CLIENT} not found: download the Desktop OAuth client JSON there first.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    print("Opening Google's consent page in your browser (a local page receives the answer).")
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        access_type="offline",
        prompt="consent",  # always return a refresh token
        authorization_prompt_message="If the browser didn't open, visit: {url}",
        success_message="HelpMate is connected. You can close this tab.",
    )
    missing = set(SCOPES) - set(credentials.granted_scopes or [])
    if missing:
        sys.exit(f"Some permissions were not granted: {sorted(missing)}. Run again and tick all.")
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Saved the sign-in to {TOKEN} (git-ignored). Set HELPMATE_MAIL=gmail and")
    print("HELPMATE_CALENDAR=google in .env and restart the API.")


if __name__ == "__main__":
    main()
