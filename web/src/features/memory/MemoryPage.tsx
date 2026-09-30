import { useState } from "react";
import {
  fetchExport,
  useDecideSuggestion,
  useDeleteFact,
  useFacts,
  useSuggestions,
  useUpdateFact,
} from "../../api/queries";
import type { MemoryFact } from "../../api/types";

const when = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

/** Where a memory came from, e.g. "chat:abc" -> "a chat". Suggestions always explain themselves. */
function describeSource(source: string): string {
  const [kind] = source.split(":");
  return { chat: "a chat", email: "an email", doc: "a document", manual: "you" }[kind] ?? source;
}

export function MemoryPage() {
  const suggestions = useSuggestions();
  const facts = useFacts();
  const decide = useDecideSuggestion();

  return (
    <section className="page" aria-labelledby="memory-heading">
      <h1 id="memory-heading">Memory</h1>
      <p className="muted">
        HelpMate only remembers what you approve. Everything here stays on your computer.
      </p>

      <h2>Suggested</h2>
      {suggestions.data?.length === 0 && <p className="muted">No suggestions waiting.</p>}
      <ul className="list">
        {suggestions.data?.map((s) => (
          <li key={s.id} className="list__row">
            <span>
              {s.text}
              <span className="muted"> · noticed in {describeSource(s.source)}</span>
            </span>
            <span className="row">
              <button
                type="button"
                className="btn btn--small btn--primary"
                aria-label={`Remember: ${s.text}`}
                disabled={decide.isPending}
                onClick={() => decide.mutate({ id: s.id, decision: "approve" })}
              >
                Remember
              </button>
              <button
                type="button"
                className="btn btn--small"
                aria-label={`Discard: ${s.text}`}
                disabled={decide.isPending}
                onClick={() => decide.mutate({ id: s.id, decision: "reject" })}
              >
                Discard
              </button>
            </span>
          </li>
        ))}
      </ul>

      <h2>Remembered</h2>
      {facts.data?.length === 0 && <p className="muted">Nothing remembered yet. Try "remember that …" in chat.</p>}
      <ul className="list">
        {facts.data?.map((f) => (
          <FactRow key={f.id} fact={f} />
        ))}
      </ul>

      <h2>Your data</h2>
      <ExportButton />
    </section>
  );
}

function FactRow({ fact }: { fact: MemoryFact }) {
  const remove = useDeleteFact();
  const [mode, setMode] = useState<"view" | "edit" | "confirm">("view");
  if (mode === "edit") return <FactEditor fact={fact} onDone={() => setMode("view")} />;
  return (
    <li className="list__row">
      <span>
        {fact.text}
        <span className="muted">
          {" "}
          · from {describeSource(fact.source)}, {when.format(new Date(fact.created_at))}
        </span>
      </span>
      {mode === "confirm" ? (
        <span className="row">
          <button type="button" className="btn btn--small btn--danger" onClick={() => remove.mutate(fact.id)}>
            Forget it
          </button>
          <button type="button" className="btn btn--small" onClick={() => setMode("view")}>
            Keep
          </button>
        </span>
      ) : (
        <span className="row">
          <button
            type="button"
            className="btn btn--small"
            aria-label={`Edit: ${fact.text}`}
            onClick={() => setMode("edit")}
          >
            Edit
          </button>
          <button
            type="button"
            className="btn btn--small"
            aria-label={`Forget: ${fact.text}`}
            onClick={() => setMode("confirm")}
          >
            Forget
          </button>
        </span>
      )}
    </li>
  );
}

/** Correct a remembered fact in place. A direct edit by the owner, so no approval card. */
function FactEditor({ fact, onDone }: { fact: MemoryFact; onDone: () => void }) {
  const update = useUpdateFact();
  const [draft, setDraft] = useState(fact.text);
  const inputId = `fact-edit-${fact.id}`;
  const text = draft.trim();
  return (
    <li className="list__row">
      <form
        className="row fact-edit"
        onSubmit={(event) => {
          event.preventDefault();
          if (text) update.mutate({ id: fact.id, text }, { onSuccess: onDone });
        }}
      >
        <label htmlFor={inputId} className="visually-hidden">
          Edit memory
        </label>
        <input
          id={inputId}
          value={draft}
          maxLength={500}
          required
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => event.key === "Escape" && onDone()}
        />
        <button type="submit" className="btn btn--small btn--primary" disabled={!text || update.isPending}>
          Save
        </button>
        <button type="button" className="btn btn--small" onClick={onDone}>
          Cancel
        </button>
      </form>
      {update.isError && (
        <p className="error" role="alert">
          Couldn't save that change. Please try again.
        </p>
      )}
    </li>
  );
}

function ExportButton() {
  const [busy, setBusy] = useState(false);
  async function download() {
    setBusy(true);
    try {
      const data = await fetchExport();
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = Object.assign(document.createElement("a"), {
        href: url,
        download: `helpmate-export-${new Date().toISOString().slice(0, 10)}.json`,
      });
      link.click();
      URL.revokeObjectURL(url);
    } finally {
      setBusy(false);
    }
  }
  return (
    <button type="button" className="btn" onClick={() => void download()} disabled={busy}>
      Download everything (JSON)
    </button>
  );
}
