"""Write the HTTP contract to contracts/openapi.yaml.

Run from backend/:   uv run python ../scripts/export_openapi.py
CI runs it and fails if the committed file differs (contract drift).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from helpmate.main import create_app

OUT = Path(__file__).resolve().parents[1] / "contracts" / "openapi.yaml"


def main() -> None:
    schema = create_app().openapi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(schema, sort_keys=False, allow_unicode=True, width=100)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
