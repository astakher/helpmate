import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from "react";
import { ApiError } from "../../api/client";
import { transcribeAudio } from "../../api/queries";

/** What each browser records natively: Chrome/Firefox/Safari 18.4+ webm/opus, older Safari mp4. */
const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const MAX_SECONDS = 60;
const HOLD_MS = 350; // pressed longer than this = hold-to-talk; shorter = tap to start, tap to stop
// Shorter than this can't contain a word, and the browser may only have written a bare container
// header, which the server can't decode (seen on the XPS as a speech-service 500 before the fix).
const MIN_RECORDING_MS = 400;
const TOO_SHORT = "That was too short to hear. Hold the button while you talk.";

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

export type TranscriptInfo = { sttMs: number; roundTripMs: number };

type Props = {
  onTranscript: (text: string, info: TranscriptInfo) => void;
  /** e.g. stop speaking the previous reply as soon as the owner starts talking */
  onStart?: () => void;
  disabled?: boolean;
};

type State = "idle" | "starting" | "recording" | "transcribing";

/**
 * Push-to-talk. Mouse/touch: hold to talk and release, or tap to start and tap again to stop.
 * Keyboard/screen reader: Space or Enter starts, again stops. Audio goes to the server as a raw
 * body and is never stored.
 */
export function PushToTalkButton({ onTranscript, onStart, disabled }: Props) {
  const [state, setState] = useState<State>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const pressedAt = useRef(0);
  const recordingSince = useRef(0);
  const stopWhenReady = useRef(false);
  const supported =
    typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

  useEffect(() => {
    if (state !== "recording") return;
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [state]);

  useEffect(() => {
    if (state === "recording" && seconds >= MAX_SECONDS) stop();
  }, [seconds, state]);

  useEffect(() => () => recorder.current?.stream.getTracks().forEach((t) => t.stop()), []);

  async function start() {
    setError(null);
    setSeconds(0);
    stopWhenReady.current = false;
    setState("starting");
    onStart?.();
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setState("idle");
      setError(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "Microphone access is blocked. Allow it in the site settings (icon left of the address bar)."
          : "No microphone found.",
      );
      return;
    }
    const mimeType = pickMimeType();
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    rec.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      if (performance.now() - recordingSince.current < MIN_RECORDING_MS) {
        setState("idle");
        setError(TOO_SHORT); // nothing is uploaded
        return;
      }
      void upload(new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" }));
    };
    recorder.current = rec;
    recordingSince.current = performance.now();
    rec.start();
    setState("recording");
    if (stopWhenReady.current) stop(); // released before the mic was ready
  }

  function stop() {
    const rec = recorder.current;
    if (!rec) {
      stopWhenReady.current = true;
      return;
    }
    recorder.current = null;
    if (rec.state !== "inactive") rec.stop();
  }

  async function upload(audio: Blob) {
    setState("transcribing");
    const sentAt = performance.now();
    try {
      const result = await transcribeAudio(audio);
      const text = result.text.trim();
      if (text) onTranscript(text, { sttMs: result.stt_ms, roundTripMs: Math.round(performance.now() - sentAt) });
      else setError("I didn't catch that. Try again a little closer to the mic.");
    } catch (e) {
      // 422 = the server couldn't use the audio; its message already says what to do
      setError(
        e instanceof ApiError && e.status === 422
          ? e.message
          : `Couldn't transcribe: ${e instanceof Error ? e.message : e}`,
      );
    } finally {
      setState("idle");
    }
  }

  function toggle() {
    if (state === "idle") void start();
    else if (state === "starting" || state === "recording") stop();
  }

  function onPointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return;
    pressedAt.current = performance.now();
    toggle();
  }

  function onPointerUp() {
    const held = performance.now() - pressedAt.current > HOLD_MS;
    if (held && (state === "starting" || state === "recording")) stop(); // released a hold
  }

  function onClick(event: MouseEvent<HTMLButtonElement>) {
    if (event.detail === 0) toggle(); // keyboard (Space/Enter) or screen reader; pointers use the handlers above
  }

  if (!supported) {
    return (
      <button type="button" className="btn ptt" disabled title="This browser can't record audio">
        <span aria-hidden="true">🎤</span>
        <span className="visually-hidden">Voice input isn't available in this browser</span>
      </button>
    );
  }

  const recording = state === "recording" || state === "starting";
  const label =
    state === "transcribing"
      ? "Transcribing…"
      : recording
        ? `Recording ${formatSeconds(seconds)}. Release, or tap again, to send`
        : "Voice: hold to talk, or tap to start and stop";

  return (
    <>
      <button
        type="button"
        className={`btn ptt${recording ? " ptt--recording" : ""}`}
        aria-label={label}
        aria-pressed={recording}
        title={label}
        disabled={disabled || state === "transcribing"}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onClick={onClick}
        onContextMenu={(event) => event.preventDefault()} // long-press on phones
      >
        <span aria-hidden="true">{state === "transcribing" ? "…" : recording ? `● ${formatSeconds(seconds)}` : "🎤"}</span>
      </button>
      {error && (
        <p className="error ptt__error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

function formatSeconds(total: number) {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
