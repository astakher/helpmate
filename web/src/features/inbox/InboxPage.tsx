import { useState } from "react";
import { useDraftReply, useHealth, useInbox } from "../../api/queries";
import type { Proposal, TriagedEmail } from "../../api/types";
import { ProposalCard } from "../approvals/ProposalCard";

const GROUPS: { category: TriagedEmail["category"]; title: string; empty: string }[] = [
  { category: "reply", title: "Needs a reply", empty: "Nobody is waiting on you." },
  { category: "fyi", title: "For your information", empty: "Nothing here." },
  { category: "low", title: "Low priority", empty: "No newsletters or notifications." },
];

const clock = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const shortDay = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/** "Sam Lee <sam@example.com>" -> "Sam Lee"; a bare address stays as it is. */
const senderName = (from: string) => from.replace(/\s*<[^>]+>\s*$/, "").replace(/^"(.*)"$/, "$1") || from;

function received(iso: string): string {
  const d = new Date(iso);
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return d >= start ? clock.format(d) : shortDay.format(d);
}

/** Unread mail sorted by the local model, with "Draft a reply" for what needs one. */
export function InboxPage() {
  const inbox = useInbox();
  const gmail = useHealth().data?.adapters.mail?.name === "gmail";
  const items = inbox.data?.items ?? [];

  return (
    <section className="page inbox" aria-labelledby="inbox-heading">
      <h1 id="inbox-heading">Inbox</h1>
      <p className="muted">
        Your unread mail from Gmail's Primary tab (no Promotions or Social), sorted on this computer by the
        local model. HelpMate never acts on what an email says: replies are drafts you approve.
      </p>
      {inbox.isPending && (
        <p className="muted" role="status">
          Sorting your unread mail… (about a second per email the first time)
        </p>
      )}
      {inbox.isError && (
        <p className="error" role="alert">
          Couldn't sort your mail: {inbox.error.message}
        </p>
      )}
      {inbox.data?.error && (
        <p className="error" role="alert">
          Couldn't read your mail: {inbox.data.error}
        </p>
      )}
      {inbox.data && !inbox.data.error && items.length === 0 && <p className="muted">No unread mail.</p>}

      {items.length > 0 && (
        <div className="brief">
          {GROUPS.map((group) => {
            const mine = items.filter((i) => i.category === group.category);
            const id = `inbox-${group.category}`;
            return (
              <section key={group.category} className="card brief__card" aria-labelledby={id}>
                <h2 id={id}>
                  {group.title} <span className="muted">({mine.length})</span>
                </h2>
                {mine.length === 0 && <p className="muted">{group.empty}</p>}
                <ul className="list">
                  {mine.map((item) => (
                    <InboxItem key={item.email.id} item={item} gmail={gmail} />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
      {inbox.data && (
        <p className="muted">
          <button type="button" className="btn btn--small" disabled={inbox.isFetching} onClick={() => void inbox.refetch()}>
            {inbox.isFetching ? "Sorting…" : "Check again"}
          </button>
        </p>
      )}
    </section>
  );
}

function InboxItem({ item, gmail }: { item: TriagedEmail; gmail: boolean }) {
  const draft = useDraftReply();
  const [card, setCard] = useState<Proposal | null>(null);
  const { email } = item;

  return (
    <li className="inbox__item">
      <div className="list__row mail">
        <span className="mail__text">
          <strong>{senderName(email.sender)}</strong>
          <span className="mail__subject">
            {gmail ? (
              <a href={`https://mail.google.com/mail/u/0/#inbox/${email.id}`} target="_blank" rel="noopener noreferrer">
                {email.subject}
                <span className="visually-hidden"> (opens Gmail)</span>
              </a>
            ) : (
              email.subject
            )}
          </span>
          <span className="muted inbox__reason">{item.reason}</span>
        </span>
        <span className="muted">{received(email.received_at)}</span>
      </div>
      {item.suspicious && (
        <p className="inbox__warning" role="note">
          Careful: this email contains text aimed at an AI assistant. HelpMate ignored it, but treat its links
          and requests with suspicion.
        </p>
      )}
      {item.category === "reply" && !card && (
        <div className="row">
          <button
            type="button"
            className="btn btn--small"
            disabled={draft.isPending}
            aria-label={`Draft a reply to ${senderName(email.sender)}: ${email.subject}`}
            onClick={() => void draft.mutateAsync(email.id).then(setCard, () => undefined)}
          >
            {draft.isPending ? "Drafting…" : "Draft a reply"}
          </button>
        </div>
      )}
      {draft.isError && (
        <p className="error" role="alert">
          Couldn't draft a reply: {draft.error.message}
        </p>
      )}
      {card && <ProposalCard proposal={card} />}
    </li>
  );
}
