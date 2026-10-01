import { useState } from "react";
import { ApiError } from "../../api/client";
import { useScheduleTask, useWeek } from "../../api/queries";
import type { CalendarEvent, Proposal, Task } from "../../api/types";
import { ProposalCard } from "../approvals/ProposalCard";

const clock = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const dayName = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric" });

const span = (start: string, end: string) => clock.formatRange(new Date(start), new Date(end));

function isAllDay(event: CalendarEvent): boolean {
  const start = new Date(event.start);
  const long = Date.parse(event.end) - Date.parse(event.start) >= 86_400_000;
  return long && start.getHours() === 0 && start.getMinutes() === 0;
}

function freeMinutes(slots: { start: string; end: string }[]): number {
  return slots.reduce((sum, s) => sum + (Date.parse(s.end) - Date.parse(s.start)) / 60_000, 0);
}

const hours = (minutes: number) =>
  minutes >= 60 ? `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ""}` : `${minutes} min`;

/** The week plan: the next 7 days, and this week's tasks that still need a time. */
export function WeekPage() {
  const week = useWeek();
  const data = week.data;

  return (
    <section className="page week" aria-labelledby="week-heading">
      <h1 id="week-heading">Week</h1>
      <p className="muted">The next 7 days: what's booked, where you're free, and what's due.</p>
      {week.isPending && <p className="muted">Planning your week…</p>}
      {week.isError && (
        <p className="error" role="alert">
          Couldn't load the week: {week.error.message}
        </p>
      )}
      {data?.calendar_error && (
        <p className="error" role="alert">
          Couldn't read your calendar: {data.calendar_error}
        </p>
      )}

      {data && (
        <div className="brief">
          <section className="card brief__card" aria-labelledby="week-unscheduled">
            <h2 id="week-unscheduled">To fit in this week</h2>
            {data.unscheduled.length === 0 ? (
              <p className="muted">Every task for this week has a time, or there are none.</p>
            ) : (
              <>
                <p className="muted">"Find an hour" proposes a calendar event; nothing is added until you approve it.</p>
                <ul className="list">
                  {data.unscheduled.map((task) => (
                    <UnscheduledTask key={task.id} task={task} />
                  ))}
                </ul>
              </>
            )}
          </section>

          {data.days.map((day, index) => {
            const label = index === 0 ? "Today" : index === 1 ? "Tomorrow" : dayName.format(new Date(`${day.date}T12:00:00`));
            const id = `week-day-${day.date}`;
            const events = [...day.events.filter(isAllDay), ...day.events.filter((e) => !isAllDay(e))];
            const nothing = !events.length && !day.reminders.length && !day.tasks_due.length;
            return (
              <section key={day.date} className="card brief__card" aria-labelledby={id}>
                <h2 id={id}>
                  {label}
                  {index < 2 && <span className="muted"> · {dayName.format(new Date(`${day.date}T12:00:00`))}</span>}
                </h2>
                {nothing && <p className="muted">Nothing booked.</p>}
                {events.length > 0 && (
                  <ul className="list" aria-label="Events">
                    {events.map((e) => (
                      <li key={e.id ?? `${e.title}-${e.start}`} className="list__row event">
                        <span className="event__when">{isAllDay(e) ? "All day" : span(e.start, e.end)}</span>
                        <span className="event__what">
                          {e.title}
                          {e.location && <span className="muted"> · {e.location}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {(day.reminders.length > 0 || day.tasks_due.length > 0) && (
                  <ul className="list" aria-label="Reminders and tasks due">
                    {day.reminders.map((r) => (
                      <li key={r.id} className="list__row">
                        <span>
                          <strong>Reminder:</strong> {r.text}
                        </span>
                        <span className="muted">{clock.format(new Date(r.due_at))}</span>
                      </li>
                    ))}
                    {day.tasks_due.map((t) => (
                      <li key={t.id} className="list__row">
                        <span>
                          <strong>Due:</strong> {t.title}
                        </span>
                        {t.due_at && <span className="muted">{clock.format(new Date(t.due_at))}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {!data.calendar_error && (
                  <p className="week__free">
                    {day.free_slots.length === 0 ? (
                      "No free time left."
                    ) : (
                      <>
                        <strong>Free {hours(Math.round(freeMinutes(day.free_slots)))}:</strong>{" "}
                        {day.free_slots.map((s) => span(s.start, s.end)).join(", ")}
                      </>
                    )}
                  </p>
                )}
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}

function UnscheduledTask({ task }: { task: Task }) {
  const schedule = useScheduleTask();
  const [card, setCard] = useState<Proposal | null>(null);
  const error = schedule.error instanceof ApiError ? schedule.error.message : schedule.error?.message;

  return (
    <li className="week__task">
      <div className="list__row">
        <span>{task.title}</span>
        {!card && (
          <button
            type="button"
            className="btn btn--small"
            disabled={schedule.isPending}
            aria-label={`Find an hour for ${task.title}`}
            onClick={() => void schedule.mutateAsync({ taskId: task.id }).then(setCard, () => undefined)}
          >
            {schedule.isPending ? "Looking…" : "Find an hour"}
          </button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {card && <ProposalCard proposal={card} />}
    </li>
  );
}
