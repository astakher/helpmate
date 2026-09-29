import { Link } from "react-router";
import { useCancelReminder, useReminders, useToday } from "../../api/queries";
import type { Reminder } from "../../api/types";

const time = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });

export function TodayPage() {
  const today = useToday();
  const reminders = useReminders();
  const cancel = useCancelReminder();
  const upcoming = (reminders.data ?? []).filter((r) => r.status === "scheduled");
  const sent = (reminders.data ?? []).filter((r) => r.status === "sent").slice(-5).reverse();

  return (
    <section className="page" aria-labelledby="today-heading">
      <h1 id="today-heading">Today</h1>
      {today.data && (
        <p className="muted">
          {new Date(`${today.data.date}T12:00:00`).toLocaleDateString(undefined, { dateStyle: "full" })}
        </p>
      )}

      {!!today.data?.pending_proposals.length && (
        <p className="callout">
          <Link to="/approvals">{today.data.pending_proposals.length} waiting for your approval</Link>
        </p>
      )}

      <h2>Upcoming reminders</h2>
      {upcoming.length === 0 && <p className="muted">No reminders scheduled.</p>}
      <ul className="list">
        {upcoming.map((r) => (
          <ReminderRow key={r.id} reminder={r} onCancel={() => cancel.mutate(r.id)} />
        ))}
      </ul>

      <h2>This week</h2>
      {today.data?.tasks.length === 0 && <p className="muted">No open tasks for this week.</p>}
      <ul className="list">
        {today.data?.tasks.map((t) => (
          <li key={t.id} className="list__row">
            {t.title}
          </li>
        ))}
      </ul>

      {sent.length > 0 && (
        <>
          <h2>Recently sent</h2>
          <ul className="list">
            {sent.map((r) => (
              <ReminderRow key={r.id} reminder={r} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function ReminderRow({ reminder, onCancel }: { reminder: Reminder; onCancel?: () => void }) {
  return (
    <li className="list__row">
      <span>
        <strong>{reminder.text}</strong>
        <span className="muted"> · {time.format(new Date(reminder.due_at))}</span>
      </span>
      {onCancel && (
        <button type="button" className="btn btn--small" onClick={onCancel} aria-label={`Cancel reminder: ${reminder.text}`}>
          Cancel
        </button>
      )}
    </li>
  );
}
