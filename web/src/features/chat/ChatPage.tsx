import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ProposalCard } from "../approvals/ProposalCard";
import { useChat, type Turn } from "./useChat";

const SUGGESTIONS = [
  "remind me to stretch in 1 minute",
  "remind me to call mom at 5pm",
  "add task read chapter 3 this term",
  "what are my reminders?",
];

export function ChatPage() {
  const { turns, busy, send, stop } = useChat();
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [turns]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!draft.trim() || busy) return;
    void send(draft);
    setDraft("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) submit(event);
  }

  return (
    <section className="page chat" aria-labelledby="chat-heading">
      <h1 id="chat-heading" className="visually-hidden">
        Chat
      </h1>
      <h2 className="visually-hidden">Conversation</h2>

      <div className="chat__log" role="log" aria-live="polite" aria-relevant="additions text">
        {turns.length === 0 && (
          <div className="chat__empty">
            <p>Ask HelpMate something, or try:</p>
            <ul className="chips">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button type="button" className="chip" onClick={() => void send(s)}>
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {turns.map((turn) => (
          <Message key={turn.id} turn={turn} />
        ))}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={submit}>
        <label htmlFor="composer-input" className="visually-hidden">
          Message
        </label>
        <textarea
          id="composer-input"
          rows={1}
          value={draft}
          placeholder="Message HelpMate…"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {/* Phase 5: <PushToTalkButton onTranscript={(t) => send(t, "voice")} /> goes here */}
        {busy ? (
          <button type="button" className="btn" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="btn btn--primary" disabled={!draft.trim()}>
            Send
          </button>
        )}
      </form>
    </section>
  );
}

function Message({ turn }: { turn: Turn }) {
  return (
    <div className={`msg msg--${turn.role}`}>
      <p className="msg__who visually-hidden">{turn.role === "user" ? "You" : "HelpMate"}</p>
      {(turn.text || turn.streaming) && (
        <div className="msg__bubble">
          {turn.text}
          {turn.streaming && (
            <span className="typing">
              <span className="visually-hidden">HelpMate is typing</span>
            </span>
          )}
          {turn.source === "voice" && <span className="msg__tag">voice</span>}
        </div>
      )}
      {turn.notes.map((note, i) => (
        <p key={i} className="msg__note">
          {note}
        </p>
      ))}
      {turn.proposals.map((p) => (
        <ProposalCard key={p.id} proposal={p} />
      ))}
      {turn.error && (
        <p className="error" role="alert">
          {turn.error}
        </p>
      )}
      {turn.ttftMs !== undefined && <p className="msg__meta">first word in {turn.ttftMs} ms</p>}
    </div>
  );
}
