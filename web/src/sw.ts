/// <reference lib="webworker" />
// HelpMate service worker (built by vite-plugin-pwa, injectManifest strategy).
// 1. Precaches the app shell so the PWA opens offline.
// 2. Shows Web Push notifications and acks each one so delivery latency can be measured.
import { clientsClaim } from "workbox-core";
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";

declare const self: ServiceWorkerGlobalScope;

self.skipWaiting();
clientsClaim();
cleanupOutdatedCaches();
precacheAndRoute(self.__WB_MANIFEST);
registerRoute(
  new NavigationRoute(createHandlerBoundToURL("/index.html"), { denylist: [/^\/api\//] }),
);

/** Push payload sent by the backend's WebPushNotifier (keep the two in sync). */
type PushPayload = {
  id: string;
  kind: string;
  title: string;
  body: string;
  url?: string;
  tag?: string | null;
};

self.addEventListener("push", (event) => {
  const payload = readPayload(event.data);
  const ack = fetch("/api/push/ack", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ notification_id: payload.id, received_at: new Date().toISOString() }),
  }).catch(() => undefined); // a failed ack must never block the notification

  event.waitUntil(
    Promise.all([
      self.registration.showNotification(payload.title, {
        body: payload.body,
        tag: payload.tag ?? undefined,
        icon: "/icons/icon-192.png",
        badge: "/icons/badge-72.png",
        data: { url: payload.url ?? "/" },
      }),
      ack,
    ]),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data?.url as string) ?? "/", self.location.origin).href;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const existing = windows[0];
      if (existing) {
        await existing.navigate(url);
        return existing.focus();
      }
      return self.clients.openWindow(url);
    })(),
  );
});

function readPayload(data: PushMessageData | null): PushPayload {
  try {
    const parsed = data?.json() as Partial<PushPayload> | undefined;
    if (parsed?.id && parsed.title) return parsed as PushPayload;
  } catch {
    // fall through to a generic notification
  }
  return { id: "unknown", kind: "system", title: "HelpMate", body: data?.text() ?? "" };
}
