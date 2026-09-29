import { useRef, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { useCreateItem, useFolders, useItems } from "../../api/queries";
import type { Folder } from "../../api/types";
import { FieldInput } from "./FieldInput";
import { formatValue, readFields } from "./fields";

export function FolderPage() {
  const { folderId = "" } = useParams();
  const folders = useFolders();
  const folder = folders.data?.find((f) => f.id === folderId);

  if (folders.isPending) return <p className="muted">Loading…</p>;
  if (!folder) {
    return (
      <section className="page">
        <h1>Folder not found</h1>
        <Link to="/folders">Back to folders</Link>
      </section>
    );
  }
  return <FolderView folder={folder} />;
}

function FolderView({ folder }: { folder: Folder }) {
  const items = useItems(folder.id);
  const create = useCreateItem(folder.id);
  const formRef = useRef<HTMLFormElement>(null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate(
      { title: String(form.get("title")).trim(), fields: readFields(folder.fields, form) },
      { onSuccess: () => formRef.current?.reset() },
    );
  }

  return (
    <section className="page" aria-labelledby="folder-heading">
      <p>
        <Link to="/folders">← Folders</Link>
      </p>
      <h1 id="folder-heading">{folder.name}</h1>

      {items.data?.length === 0 && <p className="muted">Empty. Add the first item below.</p>}
      {!!items.data?.length && (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">Items in {folder.name}</caption>
            <thead>
              <tr>
                <th scope="col">Title</th>
                {folder.fields.map((f) => (
                  <th key={f.key} scope="col">
                    {f.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.data.map((item) => (
                <tr key={item.id}>
                  <th scope="row">{item.title}</th>
                  {folder.fields.map((f) => (
                    <td key={f.key}>{formatValue(f, item.fields[f.key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form ref={formRef} className="card form" onSubmit={onSubmit} aria-labelledby="add-item-heading">
        <h2 id="add-item-heading">Add to {folder.name}</h2>
        <label>
          Title
          <input name="title" required />
        </label>
        {folder.fields.map((f) => (
          <FieldInput key={f.key} field={f} />
        ))}
        {create.isError && (
          <p className="error" role="alert">
            {create.error.message}
          </p>
        )}
        <button type="submit" className="btn btn--primary" disabled={create.isPending}>
          Add
        </button>
      </form>
    </section>
  );
}
