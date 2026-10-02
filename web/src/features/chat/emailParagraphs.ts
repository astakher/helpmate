/** A run of text, or a link shown by the site it goes to. */
export type Piece = string | { url: string; host: string };

// "<https://…>" (how plain-text mail writes a link) or a bare https:// address
const LINK = /<?(https?:\/\/[^\s<>]+)>?/g;
// plain-text mail is hard-wrapped near 72-78 columns: a line this long continues on the next
const WRAPPED = 60;
// zero-width spaces/joiners, word joiner, BOM, combining grapheme joiner, soft hyphen: marketing
// mail pads its preview with these, and they show up as odd gaps
const INVISIBLE = /[\u200B-\u200D\u2060\uFEFF\u00AD]|\u034F/g;

/** An email's plain text as paragraphs of text and links: no raw tracking URLs, no padding, and
 *  hard-wrapped lines joined again (short lines such as "Thanks,\nSam" keep their break). */
export function paragraphs(body: string): Piece[][] {
  const text = body
    .replace(/\r\n?/g, "\n")
    .replace(INVISIBLE, "")
    .replace(/\u00A0/g, " ")
    .replace(/<>/g, "") // an empty link
    .replace(/[ \t]*\n[ \t]*(<https?:\/\/[^\s>]+>)/g, " $1") // a link on its own line follows its label
    .replace(/[ \t]+/g, " ")
    .replace(/^ +| +$/gm, "");
  return text
    .split(/\n{2,}/)
    .map((paragraph) => unwrap(paragraph.trim()))
    .filter(Boolean)
    .map(linkify);
}

function unwrap(paragraph: string): string {
  const lines = paragraph.split("\n");
  return lines.reduce((out, line, i) => (i === 0 ? line : out + (lines[i - 1].length >= WRAPPED ? " " : "\n") + line), "");
}

function linkify(paragraph: string): Piece[] {
  const pieces: Piece[] = [];
  let last = 0;
  for (const match of paragraph.matchAll(LINK)) {
    const trailing = /[.,;:!?)\]]+$/.exec(match[1])?.[0] ?? ""; // "see https://x.com." ends the sentence
    const url = match[1].slice(0, match[1].length - trailing.length);
    let host: string;
    try {
      host = new URL(url).hostname.replace(/^www\./, "");
    } catch {
      continue; // not a usable address: leave the text as it is
    }
    if (match.index > last) pieces.push(paragraph.slice(last, match.index));
    pieces.push({ url, host });
    if (trailing) pieces.push(trailing);
    last = match.index + match[0].length;
  }
  if (last < paragraph.length) pieces.push(paragraph.slice(last));
  return pieces;
}
