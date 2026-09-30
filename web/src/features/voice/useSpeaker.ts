import { useCallback, useEffect, useRef, useState } from "react";
import { synthesizeSpeech } from "../../api/queries";
import { speakableChunks } from "./sentences";

/**
 * Speaks a reply sentence by sentence with the server's Kokoro TTS: the first sentence starts
 * playing as soon as it is synthesised, and the next one is synthesised while the current one
 * plays. `stop()` (or a new `speak()`) cancels at once, e.g. when the owner starts talking.
 */
export function useSpeaker() {
  const [speaking, setSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useRef(0); // bumping it cancels whatever is playing
  const audio = useRef<HTMLAudioElement | null>(null);
  const mounted = useRef(false);

  const stop = useCallback(() => {
    run.current += 1;
    audio.current?.pause();
    audio.current = null;
    setSpeaking(false);
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      // leaving the chat stops speech, and a reply that finishes afterwards stays silent
      mounted.current = false;
      stop();
    };
  }, [stop]);

  const play = useCallback((blob: Blob, id: number, onStart?: () => void) => {
    return new Promise<void>((resolve) => {
      const url = URL.createObjectURL(blob);
      const element = new Audio(url);
      audio.current = element;
      const done = () => {
        URL.revokeObjectURL(url);
        resolve();
      };
      element.onplaying = () => id === run.current && onStart?.();
      element.onended = done;
      element.onerror = done;
      element.onpause = done; // stop() pauses
      element.play().catch(done);
    });
  }, []);

  const speak = useCallback(
    async (text: string, onFirstAudio?: () => void) => {
      if (!mounted.current) return;
      stop();
      const id = ++run.current;
      const sentences = speakableChunks(text); // short first chunk = sooner first audio
      if (!sentences.length) return;
      setError(null);
      setSpeaking(true);
      let next = synthesizeSpeech(sentences[0]);
      try {
        for (let i = 0; i < sentences.length; i++) {
          const blob = await next;
          if (id !== run.current) return;
          if (i + 1 < sentences.length) {
            next = synthesizeSpeech(sentences[i + 1]);
            next.catch(() => undefined); // surfaced when awaited; avoid an unhandled rejection
          }
          await play(blob, id, i === 0 ? onFirstAudio : undefined);
          if (id !== run.current) return;
        }
      } catch (e) {
        if (id === run.current) setError(`Couldn't speak the reply: ${e instanceof Error ? e.message : e}`);
      } finally {
        if (id === run.current) setSpeaking(false);
      }
    },
    [play, stop],
  );

  return { speak, stop, speaking, error };
}
