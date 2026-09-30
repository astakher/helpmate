# Stand-in for Workstream B - not part of the Part C deliverable
"""Privacy check: during inference, does anything leave this machine except push notifications?

The spec (Updated, validation): "network activity during inference will be monitored to confirm
that prompts and retrieved personal data are processed by the local model". This watches every
HelpMate process (API, speech service, Ollama server + model runner) while it drives a realistic
workload through the API, and classifies every remote address it sees:

  loopback              expected (API <-> Ollama, API <-> speech)
  push service          expected, for push only (FCM, Apple, Mozilla, Windows)
  Tailscale 100.64/10   expected: your own devices reaching the app over `tailscale serve`
  anything else         UNEXPECTED -> the check fails

Run with the stack up (./scripts/dev.ps1 -Prod, HELPMATE_AUTH=dev), from backend/:

    uv run --no-project --with psutil --with httpx python ../scripts/privacy_check.py

It writes docs/privacy/<host>.md. Limits: connections are sampled every 50 ms, so a connection
that opens and closes faster can be missed; for a formal test, also capture with Wireshark or
`pktmon` (admin) while running the same workload. The Ollama tray app ("ollama app.exe") checks for
updates on its own; it isn't part of inference and is reported separately.
"""

from __future__ import annotations

import ipaddress
import platform
import socket
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx
import psutil

API = "http://127.0.0.1:8000/api"
ROOT = Path(__file__).resolve().parents[1]
PUSH_SUFFIXES = (
    "push.apple.com",
    "fcm.googleapis.com",
    "googleapis.com",
    "1e100.net",  # Google's reverse DNS for FCM hosts
    "push.services.mozilla.com",
    "notify.windows.com",
)
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def helpmate_processes() -> dict[int, str]:
    found: dict[int, str] = {}
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        name = (p.info["name"] or "").lower()
        cmd = " ".join(p.info["cmdline"] or []).lower()
        if "helpmate-speech" in cmd or "helpmate_speech" in cmd:
            found[p.info["pid"]] = "speech service"
        elif "helpmate-api" in cmd or "helpmate.main" in cmd:
            found[p.info["pid"]] = "HelpMate API"
        elif name == "ollama.exe" or name == "ollama":
            found[p.info["pid"]] = "Ollama server"
        elif name.startswith("llama-server") or "runner" in cmd and "ollama" in cmd:
            found[p.info["pid"]] = "Ollama model runner"
        elif name == "ollama app.exe":
            found[p.info["pid"]] = "Ollama tray app (updates; not inference)"
    return found


class Watcher(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.seen: dict[tuple[str, str, int], int] = defaultdict(int)  # (process, ip, port) -> hits

    def run(self) -> None:
        while not self.stop.is_set():
            procs = helpmate_processes()  # re-scan: the model runner starts on demand
            for conn in psutil.net_connections(kind="inet"):
                if conn.pid in procs and conn.raddr:
                    self.seen[(procs[conn.pid], conn.raddr.ip, conn.raddr.port)] += 1
            time.sleep(0.05)


def classify(ip: str, host: str | None) -> str:
    address = ipaddress.ip_address(ip)
    if address.is_loopback:
        return "loopback"
    if address.version == 4 and address in TAILSCALE:
        return "Tailscale (own devices)"
    if host and host.rstrip(".").endswith(PUSH_SUFFIXES):
        return "push service"
    return "UNEXPECTED"


def reverse_dns(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return None


def workload(client: httpx.Client) -> list[str]:
    steps: list[str] = []
    health = client.get(f"{API}/health").json()["adapters"]
    steps.append(f"health: llm={health['llm']['name']}, stt={health['stt']['name']}")
    session = client.post(f"{API}/chat/sessions", json={}).json()["id"]
    prompts = ("What's the capital of Canada? One sentence.", "remind me to stretch in 5 minutes")
    for text in prompts:
        with client.stream(
            "POST", f"{API}/chat/sessions/{session}/messages", json={"text": text}
        ) as r:
            body = "".join(r.iter_text())
        steps.append(f"chat {text!r}: {'proposal' if 'proposal.created' in body else 'reply'}")
    wav = client.post(f"{API}/voice/speak", json={"text": "Remind me to call mom."}).content
    heard = client.post(
        f"{API}/voice/transcribe", content=wav, headers={"Content-Type": "audio/wav"}
    ).json()
    steps.append(f"voice round trip: {heard.get('text')!r}")
    push = client.post(f"{API}/push/test")
    steps.append(f"test push: {push.json().get('detail') if push.is_success else push.status_code}")
    return steps


def main() -> None:
    with httpx.Client(timeout=120) as client:
        try:
            client.get(f"{API}/health").raise_for_status()
        except httpx.HTTPError as exc:
            sys.exit(f"The API isn't reachable at {API} ({exc}). Start it first.")
        if client.get(f"{API}/me").status_code == 401:
            sys.exit("The API wants a sign-in. Run this check with HELPMATE_AUTH=dev.")
        processes = sorted(set(helpmate_processes().values()))
        watcher = Watcher()
        watcher.start()
        started = time.perf_counter()
        steps = workload(client)
        time.sleep(1.0)  # let late connections show up
        watcher.stop.set()
        watcher.join()
    seconds = time.perf_counter() - started

    rows = []
    unexpected = 0
    for (proc, ip, port), hits in sorted(watcher.seen.items()):
        host = None if ipaddress.ip_address(ip).is_loopback else reverse_dns(ip)
        kind = classify(ip, host)
        inference = "not inference" not in proc
        if kind == "UNEXPECTED" and inference:
            unexpected += 1
        rows.append((proc, f"{ip}:{port}", host or "", kind, hits))

    verdict = (
        "PASS: during the workload, HelpMate's processes talked only to this machine, your own "
        "Tailscale devices and push services."
        if not unexpected
        else f"FAIL: {unexpected} unexpected remote endpoint(s), see the table."
    )
    host = platform.node() or "unknown-host"
    lines = [
        f"# Privacy check: {host}",
        "",
        f"- Date: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Watched: {', '.join(processes)} (connections sampled every 50 ms for {seconds:.0f} s)",
        f"- **{verdict}**",
        "",
        "## Workload",
        "",
        *[f"- {s}" for s in steps],
        "",
        "## Remote endpoints seen",
        "",
        "| Process | Remote | Reverse DNS | Class | Samples |",
        "|---|---|---|---|---|",
        *[f"| {p} | {r} | {h} | {k} | {n} |" for p, r, h, k, n in rows],
        "",
        "Loopback = API <-> Ollama / speech service. Push services receive only the encrypted "
        "notification payload (title/body, or generic text with private previews on).",
        "Sampling can miss sub-50 ms connections; for a formal run also capture with Wireshark or "
        "pktmon during the same workload.",
        "",
    ]
    out = ROOT / "docs" / "privacy" / f"{host.lower()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("\n".join(lines))
    print(f"wrote {out}")
    sys.exit(0 if not unexpected else 1)


if __name__ == "__main__":
    main()
