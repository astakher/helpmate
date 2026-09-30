"""Generate the VAPID key pair for Web Push (Workstream C). Run ONCE for the whole team.

    cd backend
    uv run python ../scripts/gen_vapid.py            # print the two .env lines
    uv run python ../scripts/gen_vapid.py --write    # fill them into ../.env if they're empty

Use the SAME keys on every host (XPS, demo laptop): phones subscribe against the public key, so a
new key pair means every phone has to subscribe again. Keep the private key out of git (.env is
git-ignored). Formats: public key = base64url uncompressed P-256 point (the browser's
applicationServerKey); private key = base64url raw 32 bytes (what pywebpush/py_vapid read).
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ENV = Path(__file__).resolve().parents[1] / ".env"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64url(public), b64url(private)


def write_env(public: str, private: str, force: bool) -> None:
    if not ENV.exists():
        sys.exit(f"{ENV} not found. Copy .env.example to .env first.")
    text = ENV.read_text(encoding="utf-8")
    existing = re.search(r"^HELPMATE_VAPID_PRIVATE_KEY=(\S+)", text, re.MULTILINE)
    if existing and not force:
        sys.exit(
            "VAPID keys are already set in .env. Keep them (phones are subscribed to them). "
            "Use --force only if you really want new keys."
        )
    for name, value in (("PUBLIC", public), ("PRIVATE", private)):
        line = f"HELPMATE_VAPID_{name}_KEY={value}"
        pattern = rf"^HELPMATE_VAPID_{name}_KEY=.*$"
        if re.search(pattern, text, re.MULTILINE):
            text = re.sub(pattern, line, text, flags=re.MULTILINE)
        else:
            text = text.rstrip("\n") + "\n" + line + "\n"
    ENV.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote the VAPID keys to {ENV}. Restart the API to use them.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate VAPID keys for Web Push.")
    parser.add_argument("--write", action="store_true", help="fill them into the repo's .env")
    parser.add_argument("--force", action="store_true", help="replace keys already in .env")
    args = parser.parse_args()
    public, private = generate()
    if args.write:
        write_env(public, private, args.force)
    else:
        print(f"HELPMATE_VAPID_PUBLIC_KEY={public}\nHELPMATE_VAPID_PRIVATE_KEY={private}")


if __name__ == "__main__":
    main()
