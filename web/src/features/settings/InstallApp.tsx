import { useEffect, useState } from "react";

type InstallPromptEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

const isStandalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true;

const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent);

/** Chrome/Android: a real install button. iPhone: instructions, since Safari has no install API,
 *  and on iOS push notifications only work once the app is on the Home Screen. */
export function InstallApp() {
  const [prompt, setPrompt] = useState<InstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(isStandalone);

  useEffect(() => {
    const onPrompt = (event: Event) => {
      event.preventDefault();
      setPrompt(event as InstallPromptEvent);
    };
    const onInstalled = () => setInstalled(true);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (installed) return <p>HelpMate is installed on this device.</p>;
  if (prompt) {
    return (
      <button
        type="button"
        className="btn btn--primary"
        onClick={() => {
          void prompt.prompt();
          setPrompt(null);
        }}
      >
        Install HelpMate on this device
      </button>
    );
  }
  if (isIos()) {
    return (
      <p>
        On iPhone: tap <strong>Share</strong>, then <strong>Add to Home Screen</strong>. Open HelpMate
        from the Home Screen to get notifications.
      </p>
    );
  }
  return <p className="muted">Open HelpMate in Chrome or Edge over HTTPS to install it as an app.</p>;
}
