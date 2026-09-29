import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../mocks/node";
import { parseFrame, streamChat } from "./sse";
import type { ChatEvent } from "./types";

describe("parseFrame", () => {
  it("parses data lines and ignores heartbeats", () => {
    expect(parseFrame('event: message.delta\ndata: {"type":"message.delta","text":"hi"}')).toEqual({
      type: "message.delta",
      text: "hi",
    });
    expect(parseFrame(": ping")).toBeNull();
  });
});

describe("streamChat", () => {
  it("reassembles frames split across network chunks", async () => {
    const wire =
      ': ping\n\nevent: message.delta\ndata: {"type":"message.delta","text":"Hel"}\n\n' +
      'event: message.delta\ndata: {"type":"message.delta","text":"lo"}\n\n' +
      'event: message.done\ndata: {"type":"message.done","message_id":"m1","ttft_ms":5,"tokens":2}\n\n';
    const chunks = [wire.slice(0, 7), wire.slice(7, 60), wire.slice(60, 61), wire.slice(61)];
    server.use(
      http.post("*/api/chat/sessions/:id/messages", () => {
        const encoder = new TextEncoder();
        const stream = new ReadableStream({
          start(controller) {
            chunks.forEach((c) => controller.enqueue(encoder.encode(c)));
            controller.close();
          },
        });
        return new HttpResponse(stream, { headers: { "Content-Type": "text/event-stream" } });
      }),
    );

    const events: ChatEvent[] = [];
    await streamChat("s1", { text: "hi", source: "text" }, (e) => events.push(e));
    expect(events.map((e) => e.type)).toEqual(["message.delta", "message.delta", "message.done"]);
  });

  it("throws on an HTTP error", async () => {
    server.use(http.post("*/api/chat/sessions/:id/messages", () => HttpResponse.json({ detail: "nope" }, { status: 404 })));
    await expect(streamChat("s1", { text: "hi", source: "text" }, () => {})).rejects.toMatchObject({ status: 404 });
  });
});
