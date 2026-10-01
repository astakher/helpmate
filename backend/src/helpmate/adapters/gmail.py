# Stand-in for Workstream B - not part of the Part C deliverable
"""Gmail (HELPMATE_MAIL=gmail) over the REST API. Mail is read with gmail.readonly and processed
only on this machine; send() runs only after the owner approves the email card (gmail.send).
"""

from __future__ import annotations

import asyncio
import base64
import html
import re
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import httpx

from helpmate.adapters.google_oauth import GoogleApi
from helpmate.domain.models import EmailDetail, EmailDraft, EmailSummary

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
BODY_CHARS = 6000  # enough to answer an email; longer threads are cut


class GmailMail:
    name = "gmail"
    is_fake = False

    def __init__(self, api: GoogleApi) -> None:
        self._api = api

    async def search(self, query: str, limit: int = 20) -> list[EmailSummary]:
        listing = await self._api.request(
            "GET", f"{GMAIL}/messages", params={"q": query, "maxResults": min(limit, 50)}
        )
        ids = [m["id"] for m in listing.get("messages", [])]
        return list(await asyncio.gather(*(self._summary(i) for i in ids)))

    async def read(self, message_id: str) -> EmailDetail | None:
        try:
            data = await self._api.request(
                "GET", f"{GMAIL}/messages/{message_id}", params={"format": "full"}
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 404):
                return None
            raise
        headers = _headers(data)
        return EmailDetail(
            id=data["id"],
            thread_id=data.get("threadId"),
            sender=headers.get("from", ""),
            subject=headers.get("subject") or "(no subject)",
            body=_text(data.get("payload", {}))[:BODY_CHARS],
            message_id=headers.get("message-id"),
            received_at=datetime.fromtimestamp(int(data["internalDate"]) / 1000, UTC),
            labels=data.get("labelIds", []),
        )

    async def send(self, draft: EmailDraft) -> str:
        message = EmailMessage()
        message["To"] = ", ".join(draft.to)
        if draft.cc:
            message["Cc"] = ", ".join(draft.cc)
        message["Subject"] = draft.subject
        if draft.in_reply_to:
            message["In-Reply-To"] = draft.in_reply_to
            message["References"] = draft.in_reply_to
        message.set_content(draft.body)
        body: dict[str, Any] = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
        if draft.thread_id:
            body["threadId"] = draft.thread_id  # a reply stays in its conversation
        sent = await self._api.request("POST", f"{GMAIL}/messages/send", json=body)
        return str(sent["id"])

    async def _summary(self, message_id: str) -> EmailSummary:
        data = await self._api.request(
            "GET",
            f"{GMAIL}/messages/{message_id}",
            params=[
                ("format", "metadata"),
                ("metadataHeaders", "From"),
                ("metadataHeaders", "Subject"),
            ],
        )
        headers = _headers(data)
        return EmailSummary(
            id=data["id"],
            sender=headers.get("from", ""),
            subject=headers.get("subject") or "(no subject)",
            snippet=html.unescape(data.get("snippet", "")),
            received_at=datetime.fromtimestamp(int(data["internalDate"]) / 1000, UTC),
            unread="UNREAD" in data.get("labelIds", []),
            labels=data.get("labelIds", []),
        )


def _headers(data: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}


def _decode(part: dict[str, Any]) -> str:
    raw = part.get("body", {}).get("data")
    if not raw:
        return ""
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")


def _text(payload: dict[str, Any]) -> str:
    """The message as plain text: its text/plain part, else its HTML with the tags removed."""
    parts: list[dict[str, Any]] = []
    stack = [payload]
    while stack:  # depth-first through multipart/* containers
        part = stack.pop(0)
        stack[:0] = part.get("parts", [])
        parts.append(part)
    for part in parts:
        if part.get("mimeType") == "text/plain" and (text := _decode(part)):
            return text.strip()
    for part in parts:
        if part.get("mimeType") == "text/html" and (markup := _decode(part)):
            markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
            text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
            return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()
    return ""
