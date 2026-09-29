import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useCreateTask, useTasks, useUpdateTask } from "../../api/queries";
import type { Horizon, Task } from "../../api/types";
import { HORIZONS } from "./horizons";

export function TasksPage() {
  const [horizon, setHorizon] = useState<Horizon>("week");
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  // Arrow keys move between tabs (WAI-ARIA tabs pattern)
  function onTabKey(event: KeyboardEvent, index: number) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    const next = (index + step + HORIZONS.length) % HORIZONS.length;
    setHorizon(HORIZONS[next].value);
    tabs.current[next]?.focus();
  }

  return (
    <section className="page" aria-labelledby="tasks-heading">
      <h1 id="tasks-heading">Tasks</h1>
      <div role="tablist" aria-label="Horizon" className="tabs">
        {HORIZONS.map((h, i) => (
          <button
            key={h.value}
            ref={(el) => {
              tabs.current[i] = el;
            }}
            role="tab"
            id={`tab-${h.value}`}
            aria-selected={horizon === h.value}
            aria-controls="tasks-panel"
            tabIndex={horizon === h.value ? 0 : -1}
            className="tab"
            onClick={() => setHorizon(h.value)}
            onKeyDown={(e) => onTabKey(e, i)}
          >
            {h.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="tasks-panel" aria-labelledby={`tab-${horizon}`}>
        <AddTask horizon={horizon} />
        <TaskList horizon={horizon} />
      </div>
    </section>
  );
}

function AddTask({ horizon }: { horizon: Horizon }) {
  const create = useCreateTask();
  const [title, setTitle] = useState("");

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    create.mutate({ title: title.trim(), horizon }, { onSuccess: () => setTitle("") });
  }

  return (
    <form className="row add" onSubmit={onSubmit}>
      <label htmlFor="new-task" className="visually-hidden">
        New task
      </label>
      <input id="new-task" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Add a task…" />
      <button type="submit" className="btn btn--primary" disabled={!title.trim() || create.isPending}>
        Add
      </button>
    </form>
  );
}

function TaskList({ horizon }: { horizon: Horizon }) {
  const tasks = useTasks(horizon);
  if (tasks.isPending) return <p className="muted">Loading…</p>;
  const open = tasks.data?.filter((t) => !t.done) ?? [];
  const done = tasks.data?.filter((t) => t.done) ?? [];
  return (
    <>
      {open.length === 0 && <p className="muted">Nothing here yet.</p>}
      <ul className="list">
        {open.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
      </ul>
      {done.length > 0 && (
        <>
          <h2>Done</h2>
          <ul className="list">
            {done.map((t) => (
              <TaskRow key={t.id} task={t} />
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function TaskRow({ task }: { task: Task }) {
  const update = useUpdateTask();
  return (
    <li className={`list__row ${task.done ? "is-done" : ""}`}>
      <label className="inline grow">
        <input
          type="checkbox"
          checked={task.done}
          onChange={(e) => update.mutate({ id: task.id, done: e.target.checked })}
        />
        <span>{task.title}</span>
      </label>
      <label className="visually-hidden" htmlFor={`horizon-${task.id}`}>
        Move {task.title} to
      </label>
      <select
        id={`horizon-${task.id}`}
        value={task.horizon}
        onChange={(e) => update.mutate({ id: task.id, horizon: e.target.value as Horizon })}
      >
        {HORIZONS.map((h) => (
          <option key={h.value} value={h.value}>
            {h.label}
          </option>
        ))}
      </select>
    </li>
  );
}
