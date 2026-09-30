import QRCode from "qrcode";
import { useState, type FormEvent } from "react";
import { useConfirmMfa, useEnrollMfa, useHealth } from "../../api/queries";

/**
 * Two-step verification enrolment: QR code (Google Authenticator, Aegis, 1Password, …) and then
 * the first 6-digit code to confirm. Nothing is on until the code is accepted.
 *
 * With the dev login (auth adapter is a fake) there is nothing to protect, since every request is
 * signed in automatically, so the card says so instead of offering a setup that would do nothing.
 * (Sep 30: it used to show the dev login's example QR code, which looked like 2FA was set up.)
 */
export function MfaSetup() {
  const auth = useHealth().data?.adapters.auth;
  const enroll = useEnrollMfa();
  const confirm = useConfirmMfa();
  const [qr, setQr] = useState<{ image: string; secret: string } | null>(null);
  const [code, setCode] = useState("");

  if (!auth) return <p className="muted">Checking…</p>;
  if (auth.fake) {
    return (
      <div role="note" className="mfa-note">
        <p>
          <strong>Not available yet.</strong> HelpMate is using the development login, which signs
          everyone in automatically, so a code from your phone would protect nothing.
        </p>
        <p className="muted">
          Two-step verification arrives with the real password login (Workstream B,{" "}
          <code>HELPMATE_AUTH=totp</code>). Until then, keep HelpMate private: <code>tailscale serve</code>{" "}
          only, never <code>funnel</code>.
        </p>
      </div>
    );
  }

  async function start() {
    const { otpauth_uri } = await enroll.mutateAsync();
    const image = await QRCode.toDataURL(otpauth_uri, { margin: 1, width: 220 });
    setQr({ image, secret: new URL(otpauth_uri).searchParams.get("secret") ?? "" });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (/^\d{6}$/.test(code)) confirm.mutate(code);
  }

  if (!qr) {
    return (
      <>
        <p className="muted">Protects HelpMate when it's reachable from your phone over the internet.</p>
        <button type="button" className="btn" onClick={() => void start().catch(() => undefined)} disabled={enroll.isPending}>
          Set up authenticator app
        </button>
        {enroll.isError && (
          <p className="error" role="alert">
            Couldn't start setup: {enroll.error.message}
          </p>
        )}
      </>
    );
  }
  return (
    <div className="mfa">
      <img src={qr.image} width={220} height={220} alt="QR code to scan with your authenticator app" />
      <p>
        1. Scan it with your authenticator app, or enter this key manually:
        <br />
        <code className="secret">{qr.secret.replace(/(.{4})/g, "$1 ").trim()}</code>
      </p>
      <form className="row" onSubmit={submit}>
        <label>
          2. Enter the 6-digit code it shows
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          />
        </label>
        <button type="submit" className="btn btn--primary" disabled={code.length !== 6 || confirm.isPending}>
          Turn on
        </button>
      </form>
      {confirm.isError && (
        <p className="error" role="alert">
          {confirm.error.message}
        </p>
      )}
      <p className="muted">Two-step verification stays off until the code is accepted.</p>
    </div>
  );
}
