import { useState, type ReactNode } from "react";
import { ApiError } from "../../api/client";
import { useMe } from "../../api/queries";
import { LoginPage } from "./LoginPage";

/**
 * Shows the app only to a signed-in owner. With HELPMATE_AUTH=dev the backend answers /api/me
 * straight away; once Workstream B's TOTP auth is plugged in, a 401 here shows the login screen.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();
  const unauthorized = me.error instanceof ApiError && me.error.status === 401;
  // Once signed out, a re-check of /api/me (the app regaining focus, e.g. back from the
  // authenticator app) keeps the sign-in screen up: the splash would throw away the code step.
  const [signedOut, setSignedOut] = useState(false);
  if (unauthorized && !signedOut) setSignedOut(true);
  if (me.isSuccess && signedOut) setSignedOut(false);

  if (me.isPending && signedOut) {
    return <LoginPage />;
  }
  if (me.isPending) {
    return (
      <p className="splash" role="status">
        Loading HelpMate…
      </p>
    );
  }
  if (unauthorized) {
    return <LoginPage />;
  }
  if (me.isError) {
    return (
      <div className="splash" role="alert">
        <p>HelpMate's server isn't reachable.</p>
        <button type="button" className="btn" onClick={() => void me.refetch()}>
          Try again
        </button>
      </div>
    );
  }
  return <>{children}</>;
}
