import { createContext, useContext, useEffect } from "react";
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

/** Called with the full reply when it finishes; voice uses this to speak the answer. */
export type ReplyListener = (reply: string, source: Source) => void;

export type ChatSession = {
  turns: Turn[];
  busy: boolean;
  /** true while a reload brings back the earlier conversation */
  restoring: boolean;
  send: (text: string, source?: Source) => Promise<void>;
  stop: () => void;
  /** forget the current conversation and start an empty one */
  newChat: () => void;
  setReplyListener: (listener: ReplyListener | null) => void;
};

/** The current session id, so a reload (or reopening the PWA) brings the conversation back. */
export const SESSION_KEY = "helpmate.chat.session";

export const ChatContext = createContext<ChatSession | null>(null);

type Options = { onReplyDone?: ReplyListener };

/**
 * The one conversation, kept by <ChatProvider> above the pages: going to Memory and back, or
 * leaving while a reply is still streaming, doesn't lose it. `onReplyDone` only fires while the
 * calling page is mounted (the chat page speaks replies; elsewhere they just arrive).
 */
export function useChat({ onReplyDone }: Options = {}): ChatSession {
  const chat = useContext(ChatContext);
  if (!chat) throw new Error("useChat needs a <ChatProvider> above it");
  const { setReplyListener } = chat;
  useEffect(() => {
    if (!onReplyDone) return;
    setReplyListener(onReplyDone);
    return () => setReplyListener(null);
  }, [onReplyDone, setReplyListener]);
  return chat;
}
