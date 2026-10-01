import { Fragment, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useAskDocuments, useDeleteDocument, useDocuments, useUploadDocument } from "../../api/queries";
import type { AnswerOut, DocumentInfo } from "../../api/types";

const day = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** "...per day [1]." -> text with [1] as a link to source 1 in the list below. */
function withCitations(answer: string, known: Set<number>): ReactNode[] {
  return answer.split(/(\[\d+\])/g).map((part, i) => {
    const n = /^\[(\d+)\]$/.exec(part)?.[1];
    if (n && known.has(Number(n))) {
      return (
        <a key={i} href={`#source-${n}`} className="cite" aria-label={`source ${n}`}>
          [{n}]
        </a>
      );
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

/** The file vault: upload documents, ask about them, get answers that cite their sources. */
export function DocumentsPage() {
  const documents = useDocuments();
  const upload = useUploadDocument();
  const ask = useAskDocuments();
  const fileRef = useRef<HTMLInputElement>(null);
  const [answer, setAnswer] = useState<AnswerOut | null>(null);
  const [noFile, setNoFile] = useState(false);
  const has = (documents.data?.length ?? 0) > 0;

  async function onUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget; // gone from the event once the await below finishes
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setNoFile(true);
      return;
    }
    await upload.mutateAsync(file);
    form.reset();
  }

  async function onAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = String(new FormData(event.currentTarget).get("question") ?? "").trim();
    if (question.length < 2) return;
    setAnswer(await ask.mutateAsync(question));
  }

  return (
    <section className="page documents" aria-labelledby="documents-heading">
      <h1 id="documents-heading">Documents</h1>
      <p className="muted">
        Upload PDFs, Word or text files, then ask about them. Files stay on this computer; answers come from the
        local model and cite the passages they use.
      </p>

      <div className="brief">
        <section className="card brief__card" aria-labelledby="documents-ask">
          <h2 id="documents-ask">Ask your documents</h2>
          <form className="form" onSubmit={(e) => void onAsk(e).catch(() => undefined)}>
            <label>
              Question
              <input name="question" required minLength={2} maxLength={500} placeholder="What's the late penalty?" />
            </label>
            <button type="submit" className="btn btn--primary" disabled={ask.isPending || !has}>
              {ask.isPending ? "Reading…" : "Ask"}
            </button>
            {!has && <p className="muted">Upload a document first.</p>}
          </form>
          {ask.isError && (
            <p className="error" role="alert">
              Couldn't answer: {ask.error.message}
            </p>
          )}
          {answer && (
            <div className="answer" role="status">
              <p className="answer__text">{withCitations(answer.answer, new Set(answer.sources.map((s) => s.n)))}</p>
              {answer.sources.length > 0 && (
                <>
                  <h3 className="answer__heading">{answer.cited ? "Sources" : "Closest passages"}</h3>
                  <ol className="sources">
                    {answer.sources.map((s) => (
                      <li key={s.n} id={`source-${s.n}`} value={s.n}>
                        <a href={`/api/documents/${s.document_id}/file`} target="_blank" rel="noopener noreferrer">
                          {s.document_name}
                        </a>
                        {s.page && <span className="muted"> · page {s.page}</span>}
                        <blockquote>{s.excerpt}</blockquote>
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </div>
          )}
        </section>

        <section className="card brief__card" aria-labelledby="documents-files">
          <h2 id="documents-files">Your files</h2>
          <form className="row" onSubmit={(e) => void onUpload(e).catch(() => undefined)}>
            <label className="visually-hidden" htmlFor="document-file">
              File to upload
            </label>
            <input
              id="document-file"
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.txt,.md,.markdown"
              onChange={() => setNoFile(false)}
            />
            <button type="submit" className="btn btn--small" disabled={upload.isPending}>
              {upload.isPending ? "Reading and indexing…" : "Upload"}
            </button>
          </form>
          {noFile && (
            <p className="error" role="alert">
              Choose a file first.
            </p>
          )}
          {upload.isError && (
            <p className="error" role="alert">
              Couldn't add it: {upload.error.message}
            </p>
          )}
          {documents.data?.length === 0 && <p className="muted">No documents yet.</p>}
          <ul className="list">
            {documents.data?.map((d) => (
              <DocumentRow key={d.id} document={d} />
            ))}
          </ul>
        </section>
      </div>
    </section>
  );
}

function DocumentRow({ document }: { document: DocumentInfo }) {
  const remove = useDeleteDocument();
  const [confirming, setConfirming] = useState(false);
  const details = [
    size(document.size),
    document.pages ? `${document.pages} page${document.pages === 1 ? "" : "s"}` : null,
    day.format(new Date(document.created_at)),
  ].filter(Boolean);

  return (
    <li className="list__row document">
      <span className="mail__text">
        <a href={`/api/documents/${document.id}/file`} target="_blank" rel="noopener noreferrer">
          {document.name}
        </a>
        <span className="muted">{details.join(" · ")}</span>
        {document.note && <span className="muted">{document.note}</span>}
      </span>
      {confirming ? (
        <span className="row" role="group" aria-label={`Delete “${document.name}”?`}>
          <button type="button" className="btn btn--small btn--danger" disabled={remove.isPending} onClick={() => remove.mutate(document.id)}>
            Delete
          </button>
          <button type="button" className="btn btn--small" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </span>
      ) : (
        <button type="button" className="btn btn--small" aria-label={`Delete ${document.name}`} onClick={() => setConfirming(true)}>
          Delete
        </button>
      )}
    </li>
  );
}
