import { useId, useState } from "react";
import { useEmail, useHealth } from "../../api/queries";
import type { EmailSummary } from "../../api/types";

const clock = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const shortDay = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/** "Sam Lee <sam@example.com>" -> "Sam Lee"; a bare address stays as it is. */
const senderName = (from: string) => from.replace(/\s*<[^>]+>\s*$/, "").replace(/^"(.*)"$/, "$1") || from;

/** Today: the time; earlier: the date. */
function received(iso: string): string {
  const d = new Date(iso);
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return d >= start ? clock.format(d) : shortDay.format(d);
}

/** Plain-text mail often has runs of blank lines and trailing spaces; keep one blank line. */
const tidy = (body: string) =>
  body
    .replace(/[ \t]+$/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

/** The emails behind a chat reply ("show me the last mail"), as cards: who, when, the subject and
 *  the first line, newest first, with a link to the message in Gmail when Gmail is connected. */
export function EmailCards({ emails }: { emails: EmailSummary[] }) {
  const gmail = useHealth().data?.adapters.mail?.name === "gmail";
  return (
    <ul className="email-cards" aria-label={emails.length === 1 ? "1 email" : `${emails.length} emails`}>
      {emails.map((m) => (
        <EmailCard key={m.id} email={m} gmail={gmail} />
      ))}
    </ul>
  );
}

/** One card. "Show full email" fetches the whole message (plain text: the sender's words are
 *  shown as text, never as HTML, so nothing in an email can run or restyle the page). */
function EmailCard({ email: m, gmail }: { email: EmailSummary; gmail: boolean }) {
  const [open, setOpen] = useState(false);
  const full = useEmail(m.id, open);
  const bodyId = useId();
  return (
    <li className={m.unread ? "email-card email-card--unread" : "email-card"}>
      <div className="email-card__top">
        <strong className="email-card__from">
          {m.unread && <span className="visually-hidden">Unread, from </span>}
          {senderName(m.sender)}
        </strong>
        <time className="email-card__when" dateTime={m.received_at}>
          {received(m.received_at)}
        </time>
      </div>
      <p className="email-card__subject">{m.subject || "(no subject)"}</p>
      {!open && m.snippet && <p className="email-card__snippet">{m.snippet}</p>}
      {open && (
        <div id={bodyId} className="email-card__body">
          {full.isPending && (
            <p className="muted" role="status">
              Opening the email…
            </p>
          )}
          {full.isError && (
            <p className="error" role="alert">
              Couldn't open this email: {full.error.message}
            </p>
          )}
          {full.data && (full.data.body ? tidy(full.data.body) : <span className="muted">This email has no text.</span>)}
        </div>
      )}
      <div className="email-card__actions">
        <button
          type="button"
          className="email-card__toggle"
          aria-expanded={open}
          aria-controls={open ? bodyId : undefined}
          onClick={() => setOpen((shown) => !shown)}
        >
          {open ? "Show less" : "Show full email"}
        </button>
        {gmail && (
          <a
            className="email-card__open"
            href={`https://mail.google.com/mail/u/0/#inbox/${m.id}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open in Gmail<span className="visually-hidden"> (opens Gmail)</span>
          </a>
        )}
      </div>
    </li>
  );
}
