import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { Source } from "../../api/types";
import { ProposalCard } from "../approvals/ProposalCard";
import { PushToTalkButton, type TranscriptInfo } from "../voice/PushToTalkButton";
import { useSpeaker } from "../voice/useSpeaker";
import { useChat, type Turn } from "./useChat";

const AUTO_SEND_KEY = "helpmate.voice.autoSend";

function readAutoSend(): boolean {
  try {
    return localStorage.getItem(AUTO_SEND_KEY) === "1";
  } catch {
    return false;
  }
}

/** One voice exchange, measured the way the spec counts it (without the owner's edit time). */
type VoiceStats = { transcribeMs: number; replyToAudioMs: number };

const SUGGESTIONS = [
  "remind me to stretch in 1 minute",
  "remind me to call mom at 5pm",
  "add task read chapter 3 this term",
  "what are my reminders?",
];

export function ChatPage() {
  const { speak, stop: stopSpeaking, speaking, error: speakError } = useSpeaker();
  const voice = useRef<{ transcribeMs: number; sentAt: number } | null>(null);
  const [voiceStats, setVoiceStats] = useState<VoiceStats | null>(null);

  const onReplyDone = useCallback(
    (reply: string, source: Source) => {
      if (source !== "voice") return; // only answer out loud when the owner spoke
      const pending = voice.current;
      void speak(reply, () => {
        if (pending) {
          setVoiceStats({ transcribeMs: pending.transcribeMs, replyToAudioMs: performance.now() - pending.sentAt });
        }
      });
    },
    [speak],
  );

  const { turns, busy, send, stop } = useChat({ onReplyDone });
  const [draft, setDraft] = useState("");
  const [draftSource, setDraftSource] = useState<Source>("text");
  const [transcribeMs, setTranscribeMs] = useState(0);
  const [autoSend, setAutoSend] = useState(readAutoSend);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [turns]);

  function sendMessage(text: string, source: Source, sttMs = 0) {
    voice.current = source === "voice" ? { transcribeMs: sttMs, sentAt: performance.now() } : null;
    void send(text, source);
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!draft.trim() || busy) return;
    sendMessage(draft, draftSource, transcribeMs);
    setDraft("");
    setDraftSource("text");
  }

  function onTranscript(text: string, info: TranscriptInfo) {
    if (autoSend && !busy) {
      sendMessage(text, "voice", info.roundTripMs);
      return;
    }
    // show the transcript for a quick check/edit; Enter sends it as a voice message
    setDraft(text);
    setDraftSource("voice");
    setTranscribeMs(info.roundTripMs);
    inputRef.current?.focus();
  }

  function toggleAutoSend(on: boolean) {
    setAutoSend(on);
    try {
      localStorage.setItem(AUTO_SEND_KEY, on ? "1" : "0");
    } catch {
      // private mode etc.: the choice just isn't remembered
    }
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
          ref={inputRef}
          rows={1}
          value={draft}
          placeholder="Message HelpMate…"
          onChange={(e) => {
            setDraft(e.target.value);
            if (!e.target.value.trim()) setDraftSource("text");
          }}
          onKeyDown={onKeyDown}
        />
        <PushToTalkButton onTranscript={onTranscript} onStart={stopSpeaking} disabled={busy} />
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
      <div className="voice-bar">
        <label className="inline">
          <input type="checkbox" checked={autoSend} onChange={(e) => toggleAutoSend(e.target.checked)} /> Send
          voice messages right away
        </label>
        {speaking && (
          <button type="button" className="btn btn--small" onClick={stopSpeaking}>
            Stop speaking
          </button>
        )}
        {speakError && (
          <span className="error" role="alert">
            {speakError}
          </span>
        )}
        {voiceStats && <VoiceTiming stats={voiceStats} />}
      </div>
    </section>
  );
}

/** The spec's voice target: owner stops talking -> first audio of the reply in ≤ 4 s. */
function VoiceTiming({ stats }: { stats: VoiceStats }) {
  const total = stats.transcribeMs + stats.replyToAudioMs;
  const s = (ms: number) => `${(ms / 1000).toFixed(1)} s`;
  return (
    <span className="msg__meta" role="status">
      Last voice reply: heard in {s(stats.transcribeMs)} + answered and spoken in {s(stats.replyToAudioMs)} ={" "}
      <strong>{s(total)}</strong> {total <= 4000 ? "(within the 4 s target)" : "(over the 4 s target)"}
    </span>
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
