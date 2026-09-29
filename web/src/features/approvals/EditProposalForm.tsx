import type { FormEvent } from "react";
import type { Proposal, ToolInfo } from "../../api/types";
import { schemaFields, toLocalInput } from "./schemaFields";

/** Edit-then-approve: the form is generated from the tool's argument schema. */
export function EditProposalForm({
  proposal,
  tool,
  busy,
  onSave,
  onCancel,
}: {
  proposal: Proposal;
  tool: ToolInfo;
  busy: boolean;
  onSave: (args: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const fields = schemaFields(tool.parameters);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const args: Record<string, unknown> = {};
    for (const f of fields) {
      const raw = form.get(f.name);
      if (f.kind === "bool") args[f.name] = raw === "on";
      else if (raw === null || raw === "") args[f.name] = null;
      else if (f.kind === "number") args[f.name] = Number(raw);
      else if (f.kind === "datetime") args[f.name] = new Date(String(raw)).toISOString();
      else args[f.name] = String(raw);
    }
    onSave(args);
  }

  return (
    <form className="form edit" onSubmit={onSubmit} aria-label={`Edit ${proposal.title}`}>
      {fields.map((f) => {
        const value = proposal.args[f.name];
        const common = { name: f.name, required: f.required };
        if (f.kind === "bool") {
          return (
            <label key={f.name} className="inline">
              <input name={f.name} type="checkbox" defaultChecked={Boolean(value)} /> {f.label}
            </label>
          );
        }
        return (
          <label key={f.name}>
            {f.label}
            {f.kind === "enum" ? (
              <select {...common} defaultValue={String(value ?? "")}>
                {!f.required && <option value="">—</option>}
                {f.options!.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : f.kind === "datetime" ? (
              <input {...common} type="datetime-local" defaultValue={toLocalInput(value)} />
            ) : (
              <input
                {...common}
                type={f.kind === "number" ? "number" : "text"}
                defaultValue={value == null ? "" : String(value)}
              />
            )}
          </label>
        );
      })}
      <div className="row">
        <button type="submit" className="btn btn--primary" disabled={busy}>
          Save and approve
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Back
        </button>
      </div>
    </form>
  );
}
