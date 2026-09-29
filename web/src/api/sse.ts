import { ApiError, origin } from "./client";
import type { ChatEvent, Source } from "./types";

/**
 * POST a chat message and read the reply as server-sent events.
 * EventSource can't send a POST body, so this reads the fetch body stream and splits frames.
 * Resolves when the server closes the stream; rejects with AbortError if `signal` aborts.
 */
export async function streamChat(
  sessionId: string,
  body: { text: string; source: Source },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(
    `${origin}/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      credentials: "same-origin",
      signal,
    },
  );
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, await response.text());
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const event = parseFrame(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (event) onEvent(event);
    }
  }
}

/** One SSE frame -> ChatEvent. Comment-only frames (`: ping` heartbeats) return null. */
export function parseFrame(frame: string): ChatEvent | null {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  return data ? (JSON.parse(data) as ChatEvent) : null;
}
