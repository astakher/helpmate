import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { db, MOCK_VAPID_KEY } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { PushSetup } from "./PushSetup";
import { base64UrlToBytes } from "./vapid";

const ENDPOINT = "https://push.example.com/send/abc";

/** jsdom has no service worker or Push API: install small stand-ins for them. */
function installPush({ worker = true, permission = "default", subscribed = false } = {}) {
  const subscription = {
    endpoint: ENDPOINT,
    unsubscribe: vi.fn(async () => true),
    toJSON: () => ({ endpoint: ENDPOINT, keys: { p256dh: "p256dh-key", auth: "auth-secret" } }),
  };
  let current: typeof subscription | null = subscribed ? subscription : null;
  const pushManager = {
    getSubscription: vi.fn(async () => current),
    subscribe: vi.fn(async (options: PushSubscriptionOptionsInit) => {
      void options;
      current = subscription;
      return subscription;
    }),
  };
  const registration = { pushManager };
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { getRegistration: vi.fn(async () => (worker ? registration : undefined)), ready: Promise.resolve(registration) },
  });
  vi.stubGlobal("PushManager", function PushManager() {});
  const requestPermission = vi.fn(async () => "granted");
  vi.stubGlobal("Notification", Object.assign(function Notification() {}, { permission, requestPermission }));
  return { pushManager, subscription, requestPermission };
}

afterEach(() => {
  delete (navigator as { serviceWorker?: unknown }).serviceWorker;
  vi.unstubAllGlobals();
});

describe("PushSetup", () => {
  it("explains when the browser can't do push at all", async () => {
    renderWithProviders(<PushSetup />);
    expect(await screen.findByText(/can't receive push notifications/)).toBeInTheDocument();
  });

  it("points to the production build on the dev server", async () => {
    installPush({ worker: false });
    renderWithProviders(<PushSetup />);
    expect(await screen.findByText(/dev server doesn't include/)).toBeInTheDocument();
  });

  it("explains how to configure the server when it has no VAPID keys", async () => {
    installPush();
    db.vapidKey = null;
    renderWithProviders(<PushSetup />);
    expect(await screen.findByText(/gen_vapid.py --write/)).toBeInTheDocument();
  });

  it("explains how to unblock notifications", async () => {
    installPush({ permission: "denied" });
    renderWithProviders(<PushSetup />);
    expect(await screen.findByText(/Notifications are blocked for this site/)).toBeInTheDocument();
  });

  it("enables push on a click, sends a test that reports its latency, and turns off", async () => {
    const { pushManager, subscription, requestPermission } = installPush();
    const user = userEvent.setup();
    const { container } = renderWithProviders(<PushSetup />);

    await user.click(await screen.findByRole("button", { name: "Enable notifications" }));
    expect(requestPermission).toHaveBeenCalledOnce();
    const options = pushManager.subscribe.mock.calls[0][0];
    expect(options.userVisibleOnly).toBe(true);
    expect(Array.from(options.applicationServerKey as Uint8Array)).toEqual(Array.from(base64UrlToBytes(MOCK_VAPID_KEY)));
    expect(db.subscriptions).toEqual([
      { endpoint: ENDPOINT, keys: { p256dh: "p256dh-key", auth: "auth-secret" }, user_agent: navigator.userAgent },
    ]);
    expect(await screen.findByText("Notifications are on for this device.")).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Send a test notification" }));
    expect(await screen.findByText(/Arrived after \d+\.\d s\./)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Turn off" }));
    expect(await screen.findByText("Notifications are off for this device.")).toBeInTheDocument();
    expect(subscription.unsubscribe).toHaveBeenCalled();
    expect(db.subscriptions).toEqual([]);
  });

  it("re-registers an existing subscription (the in-memory server forgets on restart)", async () => {
    installPush({ permission: "granted", subscribed: true });
    renderWithProviders(<PushSetup />);
    expect(await screen.findByRole("button", { name: "Send a test notification" })).toBeInTheDocument();
    expect(db.subscriptions.map((s) => s.endpoint)).toEqual([ENDPOINT]);
  });

  it("decodes the base64url server key into the 65-byte P-256 point browsers expect", () => {
    const bytes = base64UrlToBytes(MOCK_VAPID_KEY);
    expect(bytes.length).toBe(65);
    expect(bytes[0]).toBe(0x04); // uncompressed point
  });
});
