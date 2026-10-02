import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { keys, useLogin, useVerifyMfa } from "../../api/queries";

const CHALLENGE_KEY = "helpmate.login.challenge";
const CHALLENGE_MS = 5 * 60_000; // the server's 2FA challenge lifetime (totp_auth.CHALLENGE_TTL)

/** The code step, kept while the owner fetches the code: on an iPhone, going to the authenticator
 *  app can reload the home-screen app, and the step must survive that. Useless without the code. */
function readChallenge(): string | null {
  try {
    const saved = JSON.parse(localStorage.getItem(CHALLENGE_KEY) ?? "null") as { id: string; expires: number } | null;
    if (saved && saved.expires > Date.now()) return saved.id;
    localStorage.removeItem(CHALLENGE_KEY);
  } catch {
    // private mode etc.: a reload just starts the sign-in again
  }
  return null;
}

function writeChallenge(id: string | null) {
  try {
    if (id) localStorage.setItem(CHALLENGE_KEY, JSON.stringify({ id, expires: Date.now() + CHALLENGE_MS }));
    else localStorage.removeItem(CHALLENGE_KEY);
  } catch {
    // as above
  }
}

/** Two steps: password, then the 6-digit code from the authenticator app.
 *  Each step's form has its own key so React never reuses the username <input> for the code. */
export function LoginPage() {
  const queryClient = useQueryClient();
  const login = useLogin();
  const verify = useVerifyMfa();
  const [challenge, setChallengeState] = useState<string | null>(readChallenge);
  const [showPassword, setShowPassword] = useState(false); // "Show" in the field, to check typing

  function setChallenge(id: string | null) {
    writeChallenge(id);
    setChallengeState(id);
  }

  async function onPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const result = await login.mutateAsync({
      username: String(form.get("username")),
      password: String(form.get("password")),
    });
    if (result.mfa_required && result.challenge_id) {
      setChallenge(result.challenge_id);
    } else {
      await queryClient.invalidateQueries({ queryKey: keys.me });
    }
  }

  async function onCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code")).replace(/\s/g, "");
    await verify.mutateAsync({ challenge_id: challenge!, code });
    writeChallenge(null);
  }

  return (
    <main className="login" id="main">
      <h1>HelpMate</h1>
      {challenge === null ? (
        <form key="password" className="card form" onSubmit={(e) => void onPassword(e).catch(() => undefined)}>
          <h2>Sign in</h2>
          <label>
            Username
            <input name="username" autoComplete="username" required />
          </label>
          <div className="field">
            <label htmlFor="login-password">Password</label>
            <div className="password-field">
              <input
                id="login-password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                autoCapitalize="none"
                spellCheck={false}
                required
              />
              <button
                type="button"
                className="password-field__toggle"
                aria-controls="login-password"
                aria-label={showPassword ? "Hide password" : "Show password"}
                onClick={() => setShowPassword((shown) => !shown)}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
          </div>
          {login.isError && (
            <p className="error" role="alert">
              Wrong username or password.
            </p>
          )}
          <button type="submit" className="btn btn--primary" disabled={login.isPending}>
            Continue
          </button>
        </form>
      ) : (
        <form key="code" className="card form" onSubmit={(e) => void onCode(e).catch(() => undefined)}>
          <h2>Two-step verification</h2>
          <label>
            6-digit code from your authenticator app
            <input
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="\s*(\d\s*){6}"
              maxLength={7}
              required
              autoFocus
            />
          </label>
          {verify.isError && (
            <p className="error" role="alert">
              That code didn't work. Codes change every 30 seconds.
            </p>
          )}
          <button type="submit" className="btn btn--primary" disabled={verify.isPending}>
            Verify
          </button>
          <button type="button" className="btn" onClick={() => setChallenge(null)}>
            Start over
          </button>
        </form>
      )}
    </main>
  );
}
