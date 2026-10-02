import { useState } from "react";
import { useAudit } from "../../api/queries";
import type { AuditEntry } from "../../api/types";
import { lookupLabel } from "./toolLabels";

const PAGE = 100;
const clock = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const longDay = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric" });

const text = (value: unknown) => (typeof value === "string" ? value : undefined);
const isLookup = (e: AuditEntry) => e.action === "tool.executed" && e.detail.read_only === true;

/** A change that ran with no approval behind it. The agent only runs lookups and pre-approved
 *  actions itself; everything else runs from an approval ("system"), so this should never match. */
const unapproved = (e: AuditEntry) =>
  e.action === "tool.executed" && e.actor === "agent" && e.detail.read_only !== true && e.detail.pre_approved !== true;

/** One audit entry as a sentence. */
function describe(e: AuditEntry): string {
  const tool = text(e.detail.tool) ?? e.target ?? "";
  const title = text(e.detail.title) ?? tool.replaceAll("_", " ");
  switch (e.action) {
    case "proposal.created":
      return `HelpMate asked to: ${title}`;
    case "proposal.approved":
      return `You approved: ${title}`;
    case "proposal.edited":
      return `You edited and approved: ${title}`;
    case "proposal.rejected":
      return `You declined: ${title}`;
    case "tool.executed":
      if (e.detail.read_only === true) return `HelpMate ${lookupLabel(tool)}`;
      if (e.detail.pre_approved === true) return `Done without asking (you pre-approved it): ${title}`;
      return `Done: ${title}`;
    case "tool.failed":
      return `Failed: ${title}${text(e.detail.error) ? ` (${text(e.detail.error)})` : ""}`;
    case "tool.rejected":
      return `HelpMate's request was refused: ${text(e.detail.reason) ?? "not allowed"}`;
    default:
      return e.action;
  }
}

function dayLabel(d: Date): string {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const yesterday = new Date(start.getTime() - 86_400_000);
  if (d >= start) return "Today";
  if (d >= yesterday) return "Yesterday";
  return longDay.format(d);
}

/** Everything HelpMate did or asked to do (the audit log), newest first, in plain words, with a
 *  check that no change ran without your approval or pre-approval. */
export function HistoryPage() {
  const [limit, setLimit] = useState(PAGE);
  const [lookups, setLookups] = useState(false);
  const audit = useAudit(limit);
  const all = audit.data ?? [];
  const shown = lookups ? all : all.filter((e) => !isLookup(e));
  const changes = all.filter((e) => e.action === "tool.executed" && e.detail.read_only !== true);
  const bad = all.filter(unapproved);

  const days: { label: string; entries: AuditEntry[] }[] = [];
  for (const entry of shown) {
    const label = dayLabel(new Date(entry.at));
    if (days.at(-1)?.label !== label) days.push({ label, entries: [] });
    days.at(-1)!.entries.push(entry);
  }

  return (
    <section className="page history" aria-labelledby="history-heading">
      <h1 id="history-heading">History</h1>
      <p className="muted">
        Everything HelpMate did or asked to do, newest first. Nothing that changes your data or leaves this
        computer runs without your approval, or your pre-approval in Settings.
      </p>
      {audit.isPending && <p className="muted">Loading the history…</p>}
      {audit.isError && (
        <p className="error" role="alert">
          Couldn't load the history: {audit.error.message}
        </p>
      )}
      {audit.data &&
        (bad.length === 0 ? (
          <p className="card history__check" role="status">
            {changes.length === 0
              ? "No changes made yet."
              : `${changes.length === 1 ? "1 change" : `${changes.length} changes`} below, each one approved by you or pre-approved.`}
          </p>
        ) : (
          <p className="card history__check history__check--bad" role="alert">
            {bad.length === 1 ? "1 change" : `${bad.length} changes`} ran without an approval record. Check the entries
            marked below.
          </p>
        ))}
      {audit.data && (
        <label className="inline">
          <input type="checkbox" checked={lookups} onChange={(e) => setLookups(e.target.checked)} /> Also show lookups
          (email searches, calendar checks)
        </label>
      )}
      {audit.data && shown.length === 0 && <p className="muted">Nothing here yet.</p>}
      {days.map((day) => (
        <section key={day.label} className="history__day" aria-label={day.label}>
          <h2>{day.label}</h2>
          <ul className="list">
            {day.entries.map((e) => (
              <li key={e.id} className={`list__row history__row${unapproved(e) ? " history__row--bad" : ""}`}>
                <span>
                  {describe(e)}
                  {unapproved(e) && <strong> (no approval on record)</strong>}
                </span>
                <time className="muted" dateTime={e.at}>
                  {clock.format(new Date(e.at))}
                </time>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {audit.data && all.length >= limit && (
        <button type="button" className="btn" onClick={() => setLimit(limit * 3)} disabled={audit.isFetching}>
          Show older
        </button>
      )}
    </section>
  );
}
