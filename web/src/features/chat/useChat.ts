import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { api, unwrap } from "../../api/client";
import { streamChat } from "../../api/sse";
import type { Proposal, Source } from "../../api/types";

export type Turn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  source?: Source;
  proposals: Proposal[];
  notes: string[]; // results of read-only tools
  streaming: boolean;
  error?: string;
  ttftMs?: number;
};

type Options = {
  /** Called with the full reply when it finishes; voice uses this to speak the answer. */
  onReplyDone?: (reply: string, source: Source) => void;
};

export function useChat({ onReplyDone }: Options = {}) {
  const queryClient = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

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
        if (!sessionRef.current) {
          sessionRef.current = unwrap(await api.POST("/api/chat/sessions", { body: {} })).id;
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
        if (reply) onReplyDone?.(reply, source);
      } catch (error) {
        const aborted = error instanceof DOMException && error.name === "AbortError";
        update((t) => ({ ...t, error: aborted ? undefined : String((error as Error).message ?? error) }));
      } finally {
        update((t) => ({ ...t, streaming: false }));
        abortRef.current = null;
        setBusy(false);
      }
    },
    [onReplyDone, queryClient],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  return { turns, busy, send, stop };
}
