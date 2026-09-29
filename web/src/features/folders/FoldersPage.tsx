import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useCreateFolder, useFolders } from "../../api/queries";
import type { FieldDef, FieldType, Folder } from "../../api/types";

const FIELD_TYPES: { value: FieldType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "select", label: "Choice" },
  { value: "rating", label: "Rating (1–5)" },
  { value: "bool", label: "Yes / no" },
];

export function FoldersPage() {
  const folders = useFolders();
  const para = folders.data?.filter((f) => f.kind === "para") ?? [];
  const custom = folders.data?.filter((f) => f.kind === "custom") ?? [];

  return (
    <section className="page" aria-labelledby="folders-heading">
      <h1 id="folders-heading">Folders</h1>
      <p className="muted">Projects, Areas, Resources and Archive, plus any folder you invent.</p>
      <h2>PARA</h2>
      <FolderGrid folders={para} />
      <h2>Your folders</h2>
      {custom.length === 0 && <p className="muted">No custom folders yet.</p>}
      <FolderGrid folders={custom} />
      <NewFolderForm />
    </section>
  );
}

function FolderGrid({ folders }: { folders: Folder[] }) {
  return (
    <ul className="grid">
      {folders.map((f) => (
        <li key={f.id}>
          <Link className="card tile" to={`/folders/${f.id}`}>
            <strong>{f.name}</strong>
            {f.fields.length > 0 && <span className="muted">{f.fields.map((x) => x.label).join(" · ")}</span>}
          </Link>
        </li>
      ))}
    </ul>
  );
}

type DraftField = { label: string; type: FieldType; options: string };

const keyOf = (label: string) =>
  label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^(\d)/, "f_$1")
    .slice(0, 40) || "field";

function NewFolderForm() {
  const create = useCreateFolder();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [fields, setFields] = useState<DraftField[]>([]);

  const setField = (i: number, change: Partial<DraftField>) =>
    setFields((all) => all.map((f, j) => (j === i ? { ...f, ...change } : f)));

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const used = new Set<string>();
    const uniqueKey = (label: string) => {
      const base = keyOf(label);
      let key = base;
      for (let n = 2; used.has(key); n++) key = `${base.slice(0, 37)}_${n}`;
      used.add(key);
      return key;
    };
    const defs: FieldDef[] = fields
      .filter((f) => f.label.trim())
      .map((f) => ({
        key: uniqueKey(f.label),
        label: f.label.trim(),
        type: f.type,
        options: f.type === "select" ? f.options.split(",").map((o) => o.trim()).filter(Boolean) : null,
      }));
    create.mutate(
      { name: name.trim(), fields: defs },
      {
        onSuccess: () => {
          setName("");
          setFields([]);
          setOpen(false);
        },
      },
    );
  }

  if (!open) {
    return (
      <button type="button" className="btn" onClick={() => setOpen(true)}>
        New folder
      </button>
    );
  }
  return (
    <form className="card form" onSubmit={onSubmit} aria-labelledby="new-folder-heading">
      <h3 id="new-folder-heading">New folder</h3>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="e.g. Books" />
      </label>
      {fields.map((f, i) => (
        <fieldset key={i} className="row field-def">
          <legend className="visually-hidden">Field {i + 1}</legend>
          <label>
            Field name
            <input value={f.label} onChange={(e) => setField(i, { label: e.target.value })} />
          </label>
          <label>
            Type
            <select value={f.type} onChange={(e) => setField(i, { type: e.target.value as FieldType })}>
              {FIELD_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          {f.type === "select" && (
            <label>
              Choices (comma separated)
              <input value={f.options} onChange={(e) => setField(i, { options: e.target.value })} />
            </label>
          )}
          <button
            type="button"
            className="btn btn--small"
            aria-label={`Remove field ${f.label || i + 1}`}
            onClick={() => setFields((all) => all.filter((_, j) => j !== i))}
          >
            Remove
          </button>
        </fieldset>
      ))}
      <div className="row">
        <button
          type="button"
          className="btn btn--small"
          onClick={() => setFields((all) => [...all, { label: "", type: "text", options: "" }])}
        >
          Add field
        </button>
      </div>
      {create.isError && (
        <p className="error" role="alert">
          {create.error.message}
        </p>
      )}
      <div className="row">
        <button type="submit" className="btn btn--primary" disabled={!name.trim() || create.isPending}>
          Create folder
        </button>
        <button type="button" className="btn" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
