import { Fragment } from "react";
import { paragraphs } from "./emailParagraphs";

/** The email, readable. Links name the site they really go to (an email can't disguise one as
 *  something else), open in a new tab, and carry no referrer. Everything else is plain text. */
export function EmailText({ body }: { body: string }) {
  const paras = paragraphs(body);
  if (paras.length === 0) return <p className="muted">This email has no text.</p>;
  return (
    <>
      {paras.map((pieces, i) => (
        <p key={i}>
          {pieces.map((piece, j) =>
            typeof piece === "string" ? (
              <Fragment key={j}>{piece}</Fragment>
            ) : (
              <a
                key={j}
                className="email-link"
                href={piece.url}
                title={piece.url}
                target="_blank"
                rel="noopener noreferrer nofollow"
              >
                {piece.host}
                <span aria-hidden="true"> ↗</span>
                <span className="visually-hidden"> (link, opens in a new tab)</span>
              </a>
            ),
          )}
        </p>
      ))}
    </>
  );
}
