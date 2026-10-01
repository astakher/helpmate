import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { useCancelReminder, useHealth, useReminders, useToday } from "../../api/queries";
import type { CalendarEvent, EmailSummary, Reminder, TimeRange } from "../../api/types";

const clock = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const dayTime = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
const shortDay = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/** Re-render every minute, so "now" and past events stay right while the page is open. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

function greeting(now: number): string {
  const hour = new Date(now).getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/** "9:09 – 9:24 AM": the locale's own range format, which states AM/PM once. */
const span = (start: string, end: string) => clock.formatRange(new Date(start), new Date(end));

function duration(range: TimeRange): string {
  const minutes = Math.round((Date.parse(range.end) - Date.parse(range.start)) / 60_000);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} min`;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

function isAllDay(event: CalendarEvent): boolean {
  const start = new Date(event.start);
  const long = Date.parse(event.end) - Date.parse(event.start) >= 86_400_000;
  return long && start.getHours() === 0 && start.getMinutes() === 0;
}

/** "Sam Lee <sam@example.com>" -> "Sam Lee"; a bare address stays as it is. */
const senderName = (from: string) => from.replace(/\s*<[^>]+>\s*$/, "").replace(/^"(.*)"$/, "$1") || from;

/** The daily brief: today's schedule, free time, unread mail, reminders and this week's tasks. */
export function TodayPage() {
  const today = useToday();
  const reminders = useReminders();
  const health = useHealth();
  const cancel = useCancelReminder();
  const now = useNow();
  const upcoming = (reminders.data ?? []).filter((r) => r.status === "scheduled");
  const sent = (reminders.data ?? []).filter((r) => r.status === "sent").slice(-5).reverse();
  const adapters = health.data?.adapters;
  const brief = today.data;

  return (
    <section className="page today" aria-labelledby="today-heading">
      <h1 id="today-heading">Today</h1>
      <p className="muted">
        {greeting(now)}
        {brief && ` · ${new Date(`${brief.date}T12:00:00`).toLocaleDateString(undefined, { dateStyle: "full" })}`}
      </p>

      {!!brief?.pending_proposals.length && (
        <p className="callout">
          <Link to="/approvals">{brief.pending_proposals.length} waiting for your approval</Link>
        </p>
      )}
      {today.isPending && <p className="muted">Getting your day ready…</p>}
      {today.isError && (
        <p className="error" role="alert">
          Couldn't load today: {today.error.message}
        </p>
      )}

      <div className="brief">
        <Card title="Schedule">
          <Schedule
            events={brief?.events ?? []}
            error={brief?.calendar_error}
            connected={adapters?.calendar ? !adapters.calendar.fake : true}
            now={now}
            loaded={!!brief}
          />
        </Card>

        <Card title="Free time left today">
          {brief?.calendar_error ? (
            <p className="muted">Needs your calendar (see Schedule).</p>
          ) : (
            brief?.free_slots?.length === 0 && (
              <p className="muted">No free time of 30 minutes or more left in your day.</p>
            )
          )}
          <ul className="list">
            {brief?.free_slots?.map((slot) => (
              <li key={slot.start} className="list__row">
                <strong>{span(slot.start, slot.end)}</strong>
                <span className="muted">{duration(slot)}</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Unread mail">
          <Unread
            mail={brief?.unread ?? []}
            error={brief?.mail_error}
            gmail={adapters?.mail?.name === "gmail"}
            loaded={!!brief}
          />
        </Card>

        <Card title="Upcoming reminders">
          {upcoming.length === 0 && <p className="muted">No reminders scheduled.</p>}
          <ul className="list">
            {upcoming.map((r) => (
              <ReminderRow key={r.id} reminder={r} onCancel={() => cancel.mutate(r.id)} />
            ))}
          </ul>
        </Card>

        <Card title="This week">
          {brief?.tasks.length === 0 && <p className="muted">No open tasks for this week.</p>}
          <ul className="list">
            {brief?.tasks.map((t) => (
              <li key={t.id} className="list__row">
                {t.title}
              </li>
            ))}
          </ul>
        </Card>

        {sent.length > 0 && (
          <Card title="Recently sent">
            <ul className="list">
              {sent.map((r) => (
                <ReminderRow key={r.id} reminder={r} />
              ))}
            </ul>
          </Card>
        )}
      </div>
    </section>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  const id = `brief-${title.toLowerCase().replaceAll(" ", "-")}`;
  return (
    <section className="card brief__card" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}

function Schedule({
  events,
  error,
  connected,
  now,
  loaded,
}: {
  events: CalendarEvent[];
  error?: string | null;
  connected: boolean;
  now: number;
  loaded: boolean;
}) {
  if (error) {
    return (
      <p className="error" role="alert">
        Couldn't read your calendar: {error}
      </p>
    );
  }
  if (loaded && events.length === 0) {
    return (
      <p className="muted">
        Nothing on your calendar today.
        {!connected && " (Google Calendar isn't connected; see the setup guide.)"}
      </p>
    );
  }
  const allDay = events.filter(isAllDay);
  const timed = events.filter((e) => !isAllDay(e));
  return (
    <ul className="list">
      {[...allDay, ...timed].map((event) => {
        const whole = isAllDay(event);
        const past = !whole && Date.parse(event.end) <= now;
        const current = !whole && Date.parse(event.start) <= now && now < Date.parse(event.end);
        return (
          <li
            key={event.id ?? `${event.title}-${event.start}`}
            className={`list__row event${past ? " event--past" : ""}`}
          >
            <span className="event__when">{whole ? "All day" : span(event.start, event.end)}</span>
            <span className="event__what">
              {event.title}
              {event.location && <span className="muted"> · {event.location}</span>}
            </span>
            {current && <span className="badge">Now</span>}
            {past && <span className="visually-hidden">(finished)</span>}
          </li>
        );
      })}
    </ul>
  );
}

function Unread({
  mail,
  error,
  gmail,
  loaded,
}: {
  mail: EmailSummary[];
  error?: string | null;
  gmail: boolean;
  loaded: boolean;
}) {
  if (error) {
    return (
      <p className="error" role="alert">
        Couldn't read your mail: {error}
      </p>
    );
  }
  if (loaded && mail.length === 0) return <p className="muted">No unread mail.</p>;
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  return (
    <>
      <ul className="list">
        {mail.map((m) => {
          const received = new Date(m.received_at);
          const when = received >= startOfToday ? clock.format(received) : shortDay.format(received);
          return (
            <li key={m.id} className="list__row mail">
              <span className="mail__text">
                <strong>{senderName(m.sender)}</strong>
                <span className="mail__subject">
                  {gmail ? (
                    <a href={`https://mail.google.com/mail/u/0/#inbox/${m.id}`} target="_blank" rel="noopener noreferrer">
                      {m.subject}
                      <span className="visually-hidden"> (opens Gmail)</span>
                    </a>
                  ) : (
                    m.subject
                  )}
                </span>
              </span>
              <span className="muted">{when}</span>
            </li>
          );
        })}
      </ul>
      {mail.length > 0 && (
        <p className="brief__more">
          <Link to="/inbox">Sort it: what needs a reply?</Link>
          {gmail && (
            <>
              {" · "}
              <a href="https://mail.google.com/mail/u/0/#search/is%3Aunread" target="_blank" rel="noopener noreferrer">
                All unread in Gmail<span className="visually-hidden"> (opens Gmail)</span>
              </a>
            </>
          )}
        </p>
      )}
    </>
  );
}

function ReminderRow({ reminder, onCancel }: { reminder: Reminder; onCancel?: () => void }) {
  return (
    <li className="list__row">
      <span>
        <strong>{reminder.text}</strong>
        <span className="muted"> · {dayTime.format(new Date(reminder.due_at))}</span>
      </span>
      {onCancel && (
        <button type="button" className="btn btn--small" onClick={onCancel} aria-label={`Cancel reminder: ${reminder.text}`}>
          Cancel
        </button>
      )}
    </li>
  );
}
