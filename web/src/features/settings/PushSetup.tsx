import { useCallback, useEffect, useState } from "react";
import {
  fetchDeliveries,
  removeSubscription,
  saveSubscription,
  sendTestPush,
  useVapidKey,
} from "../../api/queries";
import { base64UrlToBytes } from "./vapid";

type Status =
  | "checking"
  | "unsupported" // no service worker / Push API (e.g. iPhone Safari before Add to Home Screen)
  | "no-worker" // the dev server: the PWA service worker only exists in the production build
  | "not-configured" // the server has no VAPID keys
  | "denied" // the owner blocked notifications for this site
  | "off"
  | "on";

const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent);

async function registration(): Promise<ServiceWorkerRegistration | undefined> {
  return navigator.serviceWorker.getRegistration();
}

/** The server's copy of this browser's subscription (it's stored per device, idempotently). */
async function register(sub: PushSubscription) {
  const json = sub.toJSON();
  await saveSubscription({
    endpoint: json.endpoint ?? sub.endpoint,
    keys: { p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" },
    user_agent: navigator.userAgent.slice(0, 500),
  });
}

async function waitForAck(notificationId: string, timeoutMs = 15000): Promise<number | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const delivery = (await fetchDeliveries()).find((d) => d.notification_id === notificationId);
    if (delivery?.received_at) {
      return new Date(delivery.received_at).getTime() - new Date(delivery.sent_at).getTime();
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return null;
}

/**
 * Settings > Notifications: turn Web Push on for this device, send a test, turn it off.
 * The permission prompt must come from a click (browsers block it otherwise).
 */
export function PushSetup() {
  const vapid = useVapidKey();
  const [status, setStatus] = useState<Status>("checking");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const detect = useCallback(async (): Promise<Status> => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      return "unsupported";
    }
    const reg = await registration();
    if (!reg) return "no-worker";
    if (vapid.data === null) return "not-configured";
    if (Notification.permission === "denied") return "denied";
    const sub = await reg.pushManager.getSubscription();
    if (!sub) return "off";
    await register(sub); // re-send: the testbed's in-memory server forgets devices on restart
    return "on";
  }, [vapid.data]);

  useEffect(() => {
    if (vapid.isPending) return;
    let live = true;
    detect()
      .then((next) => live && setStatus(next))
      .catch((e: unknown) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [detect, vapid.isPending]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const enable = () =>
    run(async () => {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setStatus(permission === "denied" ? "denied" : "off");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const key = base64UrlToBytes(vapid.data ?? "");
      let sub = await reg.pushManager.getSubscription();
      if (sub) await sub.unsubscribe(); // a stale subscription may use an old server key
      sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      await register(sub);
      setStatus("on");
      setMessage("Notifications are on for this device.");
    });

  const disable = () =>
    run(async () => {
      const sub = await (await registration())?.pushManager.getSubscription();
      if (sub) {
        await removeSubscription(sub.endpoint);
        await sub.unsubscribe();
      }
      setStatus("off");
      setMessage("Notifications are off for this device.");
    });

  const test = () =>
    run(async () => {
      const result = await sendTestPush();
      if (!result.delivered) {
        setError(`Not sent: ${result.detail ?? "no devices"}.`);
        return;
      }
      setMessage(`Sent to ${result.delivered} device(s). Waiting for it to arrive…`);
      const ms = await waitForAck(result.notification_id);
      setMessage(
        ms === null
          ? "Sent, but this device hasn't confirmed it yet. Check that notifications are allowed for your browser in Windows settings."
          : `Arrived after ${(ms / 1000).toFixed(1)} s.`,
      );
    });

  return (
    <section className="card push-setup" aria-labelledby="push-heading">
      <h3 id="push-heading">Phone and desktop notifications</h3>
      {status === "checking" && <p className="muted">Checking this browser…</p>}
      {status === "unsupported" && (
        <p>
          This browser can't receive push notifications.
          {isIos() && " On iPhone, first add HelpMate to your Home Screen (Share > Add to Home Screen), then open it from there."}
        </p>
      )}
      {status === "no-worker" && (
        <p>
          Notifications need the installed app, which the dev server doesn't include. Run{" "}
          <code>./scripts/dev.ps1 -Prod</code> and open <code>http://127.0.0.1:8000</code>.
        </p>
      )}
      {status === "not-configured" && (
        <p>
          Push isn't set up on the server yet. From <code>backend/</code>, run{" "}
          <code>uv run python ../scripts/gen_vapid.py --write</code>, set{" "}
          <code>HELPMATE_NOTIFIER=webpush</code> in <code>.env</code> and restart the API.
        </p>
      )}
      {status === "denied" && (
        <p>
          Notifications are blocked for this site. Allow them in the browser's site settings (the
          icon left of the address bar), then reload this page.
        </p>
      )}
      {status === "off" && (
        <>
          <p>Get reminders on this device even when HelpMate isn't open.</p>
          <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void enable()}>
            Enable notifications
          </button>
        </>
      )}
      {status === "on" && (
        <>
          <p>
            <span className="badge badge--ok">On</span> for this device.
          </p>
          <div className="row">
            <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void test()}>
              Send a test notification
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => void disable()}>
              Turn off
            </button>
          </div>
        </>
      )}
      <p role="status" className="muted">
        {message}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
