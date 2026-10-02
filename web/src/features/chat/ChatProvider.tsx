import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, api, unwrap } from "../../api/client";
import { deleteChatSession, keys } from "../../api/queries";
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
    emails: m.emails ?? [],
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

async function fetchHistory(sessionId: string): Promise<Turn[]> {
  const [messages, proposals] = await Promise.all([
    api.GET("/api/chat/sessions/{session_id}/messages", { params: { path: { session_id: sessionId } } }).then(unwrap),
    api.GET("/api/proposals").then(unwrap),
  ]);
  return toTurns(
    messages,
    proposals.filter((p) => p.session_id === sessionId),
  );
}

/** Holds the conversation above the routes, so it lives as long as the app does. */
export function ChatProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(() => readSession() !== null);
  const sessionRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const loadingRef = useRef<Promise<void> | null>(null);
  const loadToken = useRef(0); // only the latest load may fill the conversation
  const listenerRef = useRef<ReplyListener | null>(null);

  const refreshList = useCallback(() => void queryClient.invalidateQueries({ queryKey: keys.chats }), [queryClient]);

  const select = useCallback((id: string | null) => {
    sessionRef.current = id;
    setSessionId(id);
    writeSession(id);
  }, []);

  /** Load a chat's history into the (just cleared) conversation; messages sent meanwhile stay after it. */
  const load = useCallback(
    (id: string) => {
      const token = ++loadToken.current;
      setRestoring(true);
      loadingRef.current = (async () => {
        try {
          const history = await fetchHistory(id);
          if (loadToken.current === token) setTurns((current) => [...history, ...current]);
        } catch (error) {
          if (loadToken.current !== token) return;
          if (error instanceof ApiError && error.status === 404) {
            select(null); // deleted elsewhere, or a fresh database: start a new chat
            refreshList();
          }
          // otherwise (API unreachable) stay in this chat, so new messages still join it
        } finally {
          if (loadToken.current === token) setRestoring(false);
        }
      })();
      return loadingRef.current;
    },
    [refreshList, select],
  );

  // After a reload: bring back the stored session.
  useEffect(() => {
    const stored = readSession();
    if (!stored) return;
    sessionRef.current = stored;
    setSessionId(stored);
    void load(stored); // StrictMode runs this twice in dev; the second load wins (loadToken)
  }, [load]);

  /** Cancel a reply still streaming: it belongs to the conversation being left. */
  const leave = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    loadToken.current++; // and ignore a history load still in flight
    loadingRef.current = null;
    setRestoring(false);
    setTurns([]);
  }, []);

  const send = useCallback(
    async (text: string, source: Source = "text") => {
      const trimmed = text.trim();
      if (!trimmed || abortRef.current) return;

      const replyId = crypto.randomUUID();
      setTurns((all) => [
        ...all,
        { id: crypto.randomUUID(), role: "user", text: trimmed, source, proposals: [], notes: [], emails: [], streaming: false },
        { id: replyId, role: "assistant", text: "", proposals: [], notes: [], emails: [], streaming: true },
      ]);
      const update = (change: (turn: Turn) => Turn) =>
        setTurns((all) => all.map((t) => (t.id === replyId ? change(t) : t)));

      const controller = new AbortController();
      abortRef.current = controller;
      setBusy(true);
      let reply = "";
      try {
        await loadingRef.current; // the chat's history first, so this joins the same session
        if (!sessionRef.current) select(unwrap(await api.POST("/api/chat/sessions", { body: {} })).id);
        await streamChat(
          sessionRef.current!,
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
                // emails become cards under the reply, which already says what they are
                update((t) =>
                  event.emails?.length
                    ? { ...t, emails: [...t.emails, ...event.emails] }
                    : { ...t, notes: [...t.notes, event.summary] },
                );
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
          // not if the owner already moved to another chat
          abortRef.current = null;
          setBusy(false);
        }
        refreshList(); // a new chat's title, and the list order
      }
    },
    [queryClient, refreshList, select],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const newChat = useCallback(() => {
    leave();
    select(null);
  }, [leave, select]);

  const openChat = useCallback(
    async (id: string) => {
      if (id === sessionRef.current && !restoring) return;
      leave();
      select(id);
      await load(id);
    },
    [leave, load, restoring, select],
  );

  const deleteChat = useCallback(
    async (id: string) => {
      await deleteChatSession(id);
      if (id === sessionRef.current) newChat();
      queryClient.setQueryData(keys.chats, (list: { id: string }[] | undefined) => list?.filter((s) => s.id !== id));
      refreshList();
    },
    [newChat, queryClient, refreshList],
  );

  const setReplyListener = useCallback((listener: ReplyListener | null) => {
    listenerRef.current = listener;
  }, []);

  const value = useMemo(
    () => ({ turns, busy, sessionId, restoring, send, stop, newChat, openChat, deleteChat, setReplyListener }),
    [turns, busy, sessionId, restoring, send, stop, newChat, openChat, deleteChat, setReplyListener],
  );
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}
