import { useState } from "react";
import { useChatSessions } from "../../api/queries";
import { useChat } from "./useChat";

const time = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const day = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const dayAndYear = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" });

/** "14:05" today, "Yesterday", "Sep 30" this year, "Sep 30, 2025" before. */
function when(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (d >= startOfToday) return time.format(d);
  if (d >= new Date(startOfToday.getTime() - 86_400_000)) return "Yesterday";
  return (d.getFullYear() === now.getFullYear() ? day : dayAndYear).format(d);
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-3 6h12l-1 12H7L6 9Zm4 2v8h2v-8h-2Zm4 0v8h2v-8h-2Z"
      />
    </svg>
  );
}

/** The Chat page's sidebar: every chat, newest activity first; open, start or delete one. */
export function ChatList({ id, onPicked }: { id: string; onPicked?: () => void }) {
  const { sessionId, newChat, openChat, deleteChat } = useChat();
  const sessions = useChatSessions();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove(target: string) {
    setDeleting(true);
    setError(null);
    try {
      await deleteChat(target);
      setConfirming(null);
    } catch (e) {
      setError(`Couldn't delete that chat: ${(e as Error).message}`);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <nav id={id} className="chat-list" aria-labelledby={`${id}-heading`}>
      <div className="chat-list__head">
        <h2 id={`${id}-heading`}>Chats</h2>
        <button
          type="button"
          className="btn btn--small btn--primary"
          onClick={() => {
            newChat();
            onPicked?.();
          }}
        >
          New chat
        </button>
      </div>
      {sessions.isPending && <p className="muted">Loading…</p>}
      {sessions.isError && (
        <p className="error" role="alert">
          Couldn't load your chats.
        </p>
      )}
      {sessions.data?.length === 0 && <p className="muted">No chats yet. Your conversations appear here.</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <ul className="chat-list__items">
        {sessions.data?.map((s) => {
          const title = s.title ?? "Untitled chat";
          const current = s.id === sessionId;
          return (
            <li key={s.id} className={`chat-list__item ${current ? "chat-list__item--current" : ""}`}>
              {confirming === s.id ? (
                <div className="chat-list__confirm" role="group" aria-label={`Delete “${title}”?`}>
                  <span>Delete this chat for good?</span>
                  <div className="row">
                    <button
                      type="button"
                      className="btn btn--small btn--danger"
                      disabled={deleting}
                      onClick={() => void remove(s.id)}
                    >
                      Delete
                    </button>
                    <button type="button" className="btn btn--small" onClick={() => setConfirming(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    className="chat-list__open"
                    aria-current={current ? "true" : undefined}
                    onClick={() => {
                      void openChat(s.id);
                      onPicked?.();
                    }}
                  >
                    <span className="chat-list__title">{title}</span>
                    <span className="chat-list__when">{when(s.last_message_at ?? s.created_at)}</span>
                  </button>
                  <button
                    type="button"
                    className="chat-list__delete"
                    aria-label={`Delete chat “${title}”`}
                    title="Delete chat"
                    onClick={() => {
                      setError(null);
                      setConfirming(s.id);
                    }}
                  >
                    <TrashIcon />
                  </button>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
