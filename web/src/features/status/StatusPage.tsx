import { useHealth } from "../../api/queries";

// Which workstream plugs a real adapter into each seam (docs/plan.md §3).
const SEAMS: Record<string, { label: string; owner: string }> = {
  agent: { label: "Agent loop", owner: "A" },
  llm: { label: "Language model", owner: "A" },
  embeddings: { label: "Embeddings", owner: "A" },
  repo: { label: "Database", owner: "B" },
  scheduler: { label: "Scheduler", owner: "B" },
  auth: { label: "Login", owner: "B" },
  mail: { label: "Email", owner: "B" },
  calendar: { label: "Calendar", owner: "B" },
  notifier: { label: "Notifications", owner: "C" },
  stt: { label: "Speech-to-text", owner: "C" },
  tts: { label: "Text-to-speech", owner: "C" },
};

export function StatusPage() {
  const health = useHealth();
  const mocked = import.meta.env.VITE_API_MOCK === "1";

  return (
    <section className="page" aria-labelledby="status-heading">
      <h1 id="status-heading">System status</h1>
      <p className="muted">
        Each part of HelpMate runs as a fake until a real one is plugged in.
        {mocked && " This browser is using MSW mocks: there is no backend at all."}
      </p>
      {health.isError && (
        <p className="error" role="alert">
          The API is not reachable. Is the backend running on port 8000?
        </p>
      )}
      {health.data && (
        <table className="table">
          <caption className="visually-hidden">Adapters plugged into each seam</caption>
          <thead>
            <tr>
              <th scope="col">Part</th>
              <th scope="col">Adapter</th>
              <th scope="col">State</th>
              <th scope="col">Owner</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(health.data.adapters).map(([seam, info]) => (
              <tr key={seam}>
                <td>{SEAMS[seam]?.label ?? seam}</td>
                <td>
                  <code>{info.name}</code>
                </td>
                <td>
                  <span className={`badge ${info.fake ? "badge--fake" : "badge--real"}`}>
                    {info.fake ? "FAKE" : "REAL"}
                  </span>
                </td>
                <td>{SEAMS[seam]?.owner ?? "?"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {health.data && <p className="muted">API version {health.data.version}</p>}
    </section>
  );
}
