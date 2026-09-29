import type { ReactNode } from "react";
import { ApiError } from "../../api/client";
import { useMe } from "../../api/queries";
import { LoginPage } from "./LoginPage";

/**
 * Shows the app only to a signed-in owner. With HELPMATE_AUTH=dev the backend answers /api/me
 * straight away; once Workstream B's TOTP auth is plugged in, a 401 here shows the login screen.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();

  if (me.isPending) {
    return (
      <p className="splash" role="status">
        Loading HelpMate…
      </p>
    );
  }
  if (me.error instanceof ApiError && me.error.status === 401) {
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
