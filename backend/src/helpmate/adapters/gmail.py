# Stand-in for Workstream B - not part of the Part C deliverable
"""Gmail (HELPMATE_MAIL=gmail) over the REST API. Mail is read with gmail.readonly and processed
only on this machine; send() runs only after the owner approves the email card (gmail.send).
"""

from __future__ import annotations

import asyncio
import base64
import html
from datetime import UTC, datetime
from email.message import EmailMessage

from helpmate.adapters.google_oauth import GoogleApi
from helpmate.domain.models import EmailDraft, EmailSummary

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"


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
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = await self._api.request("POST", f"{GMAIL}/messages/send", json={"raw": raw})
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
        headers = {h["name"].lower(): h["value"] for h in data["payload"].get("headers", [])}
        return EmailSummary(
            id=data["id"],
            sender=headers.get("from", ""),
            subject=headers.get("subject") or "(no subject)",
            snippet=html.unescape(data.get("snippet", "")),
            received_at=datetime.fromtimestamp(int(data["internalDate"]) / 1000, UTC),
            unread="UNREAD" in data.get("labelIds", []),
        )
