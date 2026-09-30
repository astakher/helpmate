import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { ChatPage } from "../chat/ChatPage";
import { PushToTalkButton } from "./PushToTalkButton";

/** jsdom has no microphone, MediaRecorder or audio playback: install small stand-ins.
 *  The clock advances 500 ms per reading, so every recording is long enough unless `frozen`. */
function installMedia({ micAllowed = true, frozenClock = false } = {}) {
  let now = 0;
  vi.spyOn(performance, "now").mockImplementation(() => (frozenClock ? now : (now += 500)));
  const track = { stop: vi.fn() };
  const getUserMedia = vi.fn(async () => {
    if (!micAllowed) throw new DOMException("denied", "NotAllowedError");
    return { getTracks: () => [track] } as unknown as MediaStream;
  });
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });

  class FakeRecorder {
    static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
    state: "inactive" | "recording" = "inactive";
    mimeType: string;
    stream: MediaStream;
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    constructor(stream: MediaStream, options?: { mimeType?: string }) {
      this.stream = stream;
      this.mimeType = options?.mimeType ?? "";
    }
    start() {
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["opus-bytes"], { type: this.mimeType }) });
      this.onstop?.();
    }
  }
  vi.stubGlobal("MediaRecorder", FakeRecorder);

  const played: string[] = [];
  class FakeAudio {
    onplaying: (() => void) | null = null;
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onpause: (() => void) | null = null;
    constructor(public src: string) {}
    play() {
      played.push(this.src);
      setTimeout(() => {
        this.onplaying?.();
        setTimeout(() => this.onended?.(), 0);
      }, 0);
      return Promise.resolve();
    }
    pause() {
      this.onpause?.();
    }
  }
  vi.stubGlobal("Audio", FakeAudio);
  URL.createObjectURL = vi.fn(() => `blob:${played.length}`);
  URL.revokeObjectURL = vi.fn();
  return { getUserMedia, track, played };
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  delete (navigator as { mediaDevices?: unknown }).mediaDevices;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PushToTalkButton", () => {
  it("tap to start, tap to stop: records webm/opus and uploads it as a raw body", async () => {
    const { track } = installMedia();
    const onTranscript = vi.fn();
    renderWithProviders(<PushToTalkButton onTranscript={onTranscript} />);
    const button = screen.getByRole("button", { name: /hold to talk/ });

    fireEvent.pointerDown(button, { button: 0 });
    fireEvent.pointerUp(button); // a quick tap: keep recording
    expect(await screen.findByRole("button", { name: /Recording/ })).toHaveAttribute("aria-pressed", "true");

    fireEvent.pointerDown(screen.getByRole("button", { name: /Recording/ }), { button: 0 });
    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith("what are my reminders?", expect.anything()));
    expect(db.voiceUploads).toEqual(["audio/webm;codecs=opus"]);
    expect(track.stop).toHaveBeenCalled(); // the mic is released
  });

  it("works from the keyboard (Space/Enter give a click with detail 0)", async () => {
    installMedia();
    const onTranscript = vi.fn();
    renderWithProviders(<PushToTalkButton onTranscript={onTranscript} />);
    fireEvent.click(screen.getByRole("button", { name: /hold to talk/ }), { detail: 0 });
    fireEvent.click(await screen.findByRole("button", { name: /Recording/ }), { detail: 0 });
    await waitFor(() => expect(onTranscript).toHaveBeenCalledOnce());
  });

  it("a too-short tap uploads nothing and says to hold the button", async () => {
    installMedia({ frozenClock: true });
    const onTranscript = vi.fn();
    renderWithProviders(<PushToTalkButton onTranscript={onTranscript} />);
    fireEvent.click(screen.getByRole("button", { name: /hold to talk/ }), { detail: 0 });
    fireEvent.click(await screen.findByRole("button", { name: /Recording/ }), { detail: 0 });
    expect(await screen.findByRole("alert")).toHaveTextContent("Hold the button while you talk");
    expect(db.voiceUploads).toEqual([]);
    expect(onTranscript).not.toHaveBeenCalled();
  });

  it("shows the server's hint when it can't read a recording", async () => {
    installMedia();
    db.voiceTranscript = "";
    const { server } = await import("../../mocks/node");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.post("*/api/voice/transcribe", () =>
        HttpResponse.json({ detail: "Couldn't read the recording. Hold the button while you talk." }, { status: 422 }),
      ),
    );
    renderWithProviders(<PushToTalkButton onTranscript={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /hold to talk/ }), { detail: 0 });
    fireEvent.click(await screen.findByRole("button", { name: /Recording/ }), { detail: 0 });
    expect(await screen.findByRole("alert")).toHaveTextContent(/^Couldn't read the recording/);
  });

  it("explains a blocked microphone", async () => {
    installMedia({ micAllowed: false });
    renderWithProviders(<PushToTalkButton onTranscript={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /hold to talk/ }), { detail: 0 });
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone access is blocked");
  });
});

describe("Chat with voice", () => {
  it("puts the transcript in the box, sends it as voice, speaks the reply and shows the timing", async () => {
    const { played } = installMedia();
    const user = userEvent.setup();
    const { container } = renderWithProviders(<ChatPage />);
    const mic = screen.getByRole("button", { name: /hold to talk/ });
    expect(await axeViolations(container)).toEqual([]);

    fireEvent.click(mic, { detail: 0 });
    fireEvent.click(await screen.findByRole("button", { name: /Recording/ }), { detail: 0 });
    const box = screen.getByLabelText("Message");
    await waitFor(() => expect(box).toHaveValue("what are my reminders?"));
    expect(box).toHaveFocus(); // ready for a quick edit

    await user.type(box, "{Enter}");
    expect(await screen.findByText("voice")).toBeInTheDocument(); // the message is tagged as voice
    await waitFor(() => expect(db.spoken.length).toBeGreaterThan(0)); // the reply goes to TTS
    expect(played.length).toBeGreaterThan(0);
    expect(await screen.findByText(/Last voice reply: heard in/)).toBeInTheDocument();
  });

  it("'Send voice messages right away' skips the edit step", async () => {
    installMedia();
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.click(screen.getByLabelText(/Send voice messages right away/));
    fireEvent.click(screen.getByRole("button", { name: /hold to talk/ }), { detail: 0 });
    fireEvent.click(await screen.findByRole("button", { name: /Recording/ }), { detail: 0 });
    expect(await screen.findByText("voice")).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("");
    expect(localStorage.getItem("helpmate.voice.autoSend")).toBe("1");
  });

  it("typed messages are not spoken", async () => {
    installMedia();
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.type(screen.getByLabelText("Message"), "tell me a joke{Enter}");
    expect(await screen.findByText(/\(mock\) You said/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(db.spoken).toEqual([]);
  });
});
