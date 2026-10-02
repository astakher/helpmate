import { useHealth } from "../../api/queries";
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

/** The emails behind a chat reply ("show me the last mail"), as cards: who, when, the subject and
 *  the first line, newest first, with a link to the message in Gmail when Gmail is connected. */
export function EmailCards({ emails }: { emails: EmailSummary[] }) {
  const gmail = useHealth().data?.adapters.mail?.name === "gmail";
  return (
    <ul className="email-cards" aria-label={emails.length === 1 ? "1 email" : `${emails.length} emails`}>
      {emails.map((m) => (
        <li key={m.id} className={m.unread ? "email-card email-card--unread" : "email-card"}>
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
          {m.snippet && <p className="email-card__snippet">{m.snippet}</p>}
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
        </li>
      ))}
    </ul>
  );
}
