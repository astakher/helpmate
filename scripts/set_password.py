"""Set the owner's password for HELPMATE_AUTH=totp (stand-in for Workstream B's login).

Run it in YOUR OWN terminal (it asks for the password without showing it), from backend/:

    uv run python ../scripts/set_password.py              # set / change the password
    uv run python ../scripts/set_password.py --reset-2fa  # lost phone: turn two-step off

Writes only an argon2id hash to .env (HELPMATE_OWNER_PASSWORD_HASH), never the password. Then set
HELPMATE_AUTH=totp in .env and restart the API. Changing the password also forgets every saved
sign-in (data/auth.json), so after the restart every device has to sign in again. --reset-2fa
removes the TOTP secret from data/auth.json; anyone who can run this has the machine anyway, which
is why it's the recovery path.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from pathlib import Path

from argon2 import PasswordHasher

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
AUTH_STATE = ROOT / "data" / "auth.json"
MIN_LENGTH = 12


def write_env(name: str, value: str) -> None:
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    line = f"{name}='{value}'"  # single quotes: the hash contains '$', which must not expand
    pattern = rf"^{name}=.*$"
    if re.search(pattern, text, flags=re.MULTILINE):
        text = re.sub(pattern, lambda _: line, text, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    ENV.write_text(text, encoding="utf-8", newline="\n")


def set_password() -> None:
    if not sys.stdin.isatty():
        sys.exit("Run this in your own terminal: it needs to ask for the password privately.")
    first = getpass.getpass(f"New HelpMate password (at least {MIN_LENGTH} characters): ")
    if len(first) < MIN_LENGTH:
        sys.exit(f"Too short: use at least {MIN_LENGTH} characters (a passphrase works well).")
    if getpass.getpass("Type it again: ") != first:
        sys.exit("The two entries didn't match. Nothing was changed.")
    write_env("HELPMATE_OWNER_PASSWORD_HASH", PasswordHasher().hash(first))
    forget_sessions()
    print(f"Saved the password hash to {ENV}. Set HELPMATE_AUTH=totp there and restart the API.")
    print("Every device will have to sign in again after the restart.")


def forget_sessions() -> None:
    """A new password must end the old sign-ins (the API reads them from here at start-up)."""
    if not AUTH_STATE.exists():
        return
    state = json.loads(AUTH_STATE.read_text(encoding="utf-8"))
    if state.pop("sessions", None) is not None:
        AUTH_STATE.write_text(json.dumps(state), encoding="utf-8")


def reset_2fa() -> None:
    if not AUTH_STATE.exists():
        print("Two-step verification isn't set up; nothing to reset.")
        return
    state = json.loads(AUTH_STATE.read_text(encoding="utf-8"))
    state.pop("totp_secret", None)
    state.pop("last_step", None)
    AUTH_STATE.write_text(json.dumps(state), encoding="utf-8")
    print(
        "Two-step verification is off. Restart the API, sign in, and set it up again in Settings."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Set the HelpMate owner password (totp auth).")
    parser.add_argument("--reset-2fa", action="store_true", help="turn two-step verification off")
    args = parser.parse_args()
    reset_2fa() if args.reset_2fa else set_password()


if __name__ == "__main__":
    main()
