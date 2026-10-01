import { useState, type FormEvent } from "react";
import { useLogout, useMe, useNotificationSettings, useSaveNotificationSettings } from "../../api/queries";
import type { NotificationSettings } from "../../api/types";
import { InstallApp } from "./InstallApp";
import { MfaSetup } from "./MfaSetup";
import { PushSetup } from "./PushSetup";

export function SettingsPage() {
  const me = useMe();
  const logout = useLogout();

  return (
    <section className="page" aria-labelledby="settings-heading">
      <h1 id="settings-heading">Settings</h1>

      <h2>Account</h2>
      <div className="card row">
        <span>
          Signed in as <strong>{me.data?.display_name}</strong>
        </span>
        <button type="button" className="btn btn--small" onClick={() => logout.mutate()}>
          Sign out
        </button>
      </div>

      <h2>Two-step verification</h2>
      <div className="card">
        {me.data?.mfa_enabled ? <p>On. You'll be asked for a code when you sign in.</p> : <MfaSetup />}
      </div>

      <h2>Notifications</h2>
      <PushSetup />
      <NotificationSettingsForm />

      <h2>Install</h2>
      <div className="card">
        <InstallApp />
      </div>
    </section>
  );
}

export function NotificationSettingsForm() {
  const settings = useNotificationSettings();
  const save = useSaveNotificationSettings();
  const [saved, setSaved] = useState(false);

  if (!settings.data) return <p className="muted">Loading…</p>;
  const current = settings.data;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const quiet = form.get("quiet") === "on";
    const next: NotificationSettings = {
      timezone: current.timezone,
      max_per_hour: Number(form.get("max_per_hour")),
      private_previews: form.get("private_previews") === "on",
      quiet_hours: quiet
        ? { start: `${form.get("quiet_start")}:00`, end: `${form.get("quiet_end")}:00` }
        : null,
      checkin_at: form.get("checkin") === "on" ? `${form.get("checkin_at")}:00` : null,
    };
    setSaved(false);
    await save.mutateAsync(next);
    setSaved(true);
  }

  return (
    <form className="card form" onSubmit={(e) => void onSubmit(e).catch(() => undefined)}>
      <fieldset>
        <legend>Quiet hours</legend>
        <label className="inline">
          <input type="checkbox" name="quiet" defaultChecked={!!current.quiet_hours} /> Hold non-urgent
          notifications during quiet hours
        </label>
        <div className="row">
          <label>
            From
            <input type="time" name="quiet_start" defaultValue={current.quiet_hours?.start.slice(0, 5) ?? "22:00"} />
          </label>
          <label>
            Until
            <input type="time" name="quiet_end" defaultValue={current.quiet_hours?.end.slice(0, 5) ?? "07:00"} />
          </label>
        </div>
      </fieldset>
      <fieldset>
        <legend>Evening check-in</legend>
        <label className="inline">
          <input type="checkbox" name="checkin" defaultChecked={!!current.checkin_at} /> Send me a short summary
          each evening: tasks left this week, and tomorrow's events and reminders
        </label>
        <label>
          At
          <input type="time" name="checkin_at" defaultValue={current.checkin_at?.slice(0, 5) ?? "20:00"} />
        </label>
      </fieldset>
      <label>
        At most this many notifications per hour
        <input type="number" name="max_per_hour" min={1} max={60} defaultValue={current.max_per_hour} />
      </label>
      <label className="inline">
        <input type="checkbox" name="private_previews" defaultChecked={current.private_previews} /> Private
        previews: the phone shows "You have a reminder" instead of the text
      </label>
      <p className="muted">Times are in {current.timezone}.</p>
      <div className="row">
        <button type="submit" className="btn btn--primary" disabled={save.isPending}>
          Save
        </button>
        {saved && <span role="status">Saved</span>}
        {save.isError && (
          <span className="error" role="alert">
            {save.error.message}
          </span>
        )}
      </div>
    </form>
  );
}
