import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, api, unwrap } from "../../api/client";
import { streamChat } from "../../api/sse";
import type { ChatMessage, Proposal, Source } from "../../api/types";
import { ChatContext, SESSION_KEY, type ReplyListener, type Turn } from "./useChat";

function readSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null; // private mode etc.: the conversation just isn't brought back after a reload
  }
}

function writeSession(id: string | null) {
  try {
    if (id) localStorage.setItem(SESSION_KEY, id);
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    // as above
  }
}

/** Stored messages -> turns; each approval card goes with the first reply that finished after it. */
function toTurns(messages: ChatMessage[], proposals: Proposal[]): Turn[] {
  const turns: Turn[] = messages.map((m) => ({
    id: m.id,
    role: m.role,
    text: m.text,
    source: m.source,
    proposals: [],
    notes: [],
    streaming: false,
  }));
  const at = (iso: string) => Date.parse(iso);
  for (const proposal of [...proposals].sort((a, b) => at(a.created_at) - at(b.created_at))) {
    const index = messages.findIndex((m) => m.role === "assistant" && at(m.created_at) >= at(proposal.created_at));
    const target = index >= 0 ? turns[index] : turns.findLast((t) => t.role === "assistant");
    target?.proposals.push(proposal);
  }
  return turns;
}

/** Holds the conversation above the routes, so it lives as long as the app does. */
export function ChatProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(() => readSession() !== null);
  const sessionRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const restoreRef = useRef<Promise<void> | null>(null);
  const listenerRef = useRef<ReplyListener | null>(null);

  // After a reload: bring back the stored session's messages and its approval cards.
  useEffect(() => {
    const stored = readSession();
    if (!stored) return;
    let cancelled = false; // StrictMode runs this twice in dev; only the last run counts
    restoreRef.current = (async () => {
      try {
        const [messages, proposals] = await Promise.all([
          api.GET("/api/chat/sessions/{session_id}/messages", { params: { path: { session_id: stored } } }).then(unwrap),
          api.GET("/api/proposals").then(unwrap),
        ]);
        if (cancelled) return;
        sessionRef.current = stored;
        const history = toTurns(messages, proposals.filter((p) => p.session_id === stored));
        setTurns((current) => [...history, ...current]);
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) writeSession(null); // e.g. a fresh database
        else sessionRef.current = stored; // API unreachable: keep adding to the same conversation
      } finally {
        if (!cancelled) setRestoring(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const send = useCallback(
    async (text: string, source: Source = "text") => {
      const trimmed = text.trim();
      if (!trimmed || abortRef.current) return;

      const replyId = crypto.randomUUID();
      setTurns((all) => [
        ...all,
        { id: crypto.randomUUID(), role: "user", text: trimmed, source, proposals: [], notes: [], streaming: false },
        { id: replyId, role: "assistant", text: "", proposals: [], notes: [], streaming: true },
      ]);
      const update = (change: (turn: Turn) => Turn) =>
        setTurns((all) => all.map((t) => (t.id === replyId ? change(t) : t)));

      const controller = new AbortController();
      abortRef.current = controller;
      setBusy(true);
      let reply = "";
      try {
        await restoreRef.current; // a reload's history first, so this joins the same session
        if (!sessionRef.current) {
          sessionRef.current = unwrap(await api.POST("/api/chat/sessions", { body: {} })).id;
          writeSession(sessionRef.current);
        }
        await streamChat(
          sessionRef.current,
          { text: trimmed, source },
          (event) => {
            switch (event.type) {
              case "message.delta":
                reply += event.text;
                update((t) => ({ ...t, text: t.text + event.text }));
                break;
              case "proposal.created":
                update((t) => ({ ...t, proposals: [...t.proposals, event.proposal] }));
                void queryClient.invalidateQueries({ queryKey: ["proposals"] });
                break;
              case "tool.result":
                update((t) => ({ ...t, notes: [...t.notes, event.summary] }));
                break;
              case "message.done":
                update((t) => ({ ...t, streaming: false, ttftMs: event.ttft_ms ?? undefined }));
                break;
              case "error":
                update((t) => ({ ...t, streaming: false, error: event.message }));
                break;
              case "tool.started":
                break;
            }
          },
          controller.signal,
        );
        if (reply) listenerRef.current?.(reply, source);
      } catch (error) {
        const aborted = error instanceof DOMException && error.name === "AbortError";
        update((t) => ({ ...t, error: aborted ? undefined : String((error as Error).message ?? error) }));
      } finally {
        update((t) => ({ ...t, streaming: false }));
        if (abortRef.current === controller) {
          // not if "New chat" already let the next message start
          abortRef.current = null;
          setBusy(false);
        }
      }
    },
    [queryClient],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const newChat = useCallback(() => {
    abortRef.current?.abort(); // a reply still streaming belongs to the old conversation
    abortRef.current = null;
    setBusy(false);
    sessionRef.current = null;
    writeSession(null);
    setTurns([]);
  }, []);

  const setReplyListener = useCallback((listener: ReplyListener | null) => {
    listenerRef.current = listener;
  }, []);

  const value = useMemo(
    () => ({ turns, busy, restoring, send, stop, newChat, setReplyListener }),
    [turns, busy, restoring, send, stop, newChat, setReplyListener],
  );
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}
