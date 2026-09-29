import QRCode from "qrcode";
import { useState } from "react";
import { useEnrollMfa } from "../../api/queries";

/** Shows the otpauth:// URI as a QR code for Google Authenticator, Aegis, 1Password, etc. */
export function MfaSetup() {
  const enroll = useEnrollMfa();
  const [qr, setQr] = useState<{ image: string; secret: string } | null>(null);

  async function start() {
    const { otpauth_uri } = await enroll.mutateAsync();
    const image = await QRCode.toDataURL(otpauth_uri, { margin: 1, width: 220 });
    setQr({ image, secret: new URL(otpauth_uri).searchParams.get("secret") ?? "" });
  }

  if (!qr) {
    return (
      <>
        <p className="muted">Protects HelpMate when it's reachable from your phone over the internet.</p>
        <button type="button" className="btn" onClick={() => void start()} disabled={enroll.isPending}>
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
        Scan it with your authenticator app, or enter this key manually:
        <br />
        <code className="secret">{qr.secret.replace(/(.{4})/g, "$1 ").trim()}</code>
      </p>
    </div>
  );
}
