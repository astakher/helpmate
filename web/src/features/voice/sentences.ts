/**
 * Split a reply into sentences so the first one can be spoken while the rest are synthesised.
 * Keeps "e.g." / times like "5:30 p.m." / decimals together well enough for short replies, and
 * merges very short fragments into the previous sentence so TTS isn't called for "Okay."
 */
export function splitSentences(text: string, minLength = 12): string[] {
  const parts = text
    .replace(/\s+/g, " ")
    .trim()
    .split(/(?<=[.!?])\s+(?=[A-Z0-9"'(])/);
  const sentences: string[] = [];
  for (const part of parts) {
    const piece = part.trim();
    if (!piece) continue;
    if (sentences.length && (piece.length < minLength || sentences[sentences.length - 1].length < minLength)) {
      sentences[sentences.length - 1] += ` ${piece}`;
    } else {
      sentences.push(piece);
    }
  }
  return sentences;
}

const CLAUSE = /(?<=[:;,—])\s+/; // "I've prepared this: Reminder: …" -> "I've prepared this:" | "Reminder: …"

/**
 * What the speaker actually sends to TTS, chunk by chunk. Kokoro's time grows with the text, and
 * the owner hears nothing until the first chunk is ready, so a long first sentence is cut at its
 * first clause break (measured on the XPS: 0.6 s for "I've prepared this:" vs 2.1 s for the whole
 * sentence). Very long later sentences are cut the same way.
 */
export function speakableChunks(text: string, firstMax = 40, max = 160, minLength = 12): string[] {
  const chunks: string[] = [];
  for (const sentence of splitSentences(text, minLength)) {
    const limit = chunks.length === 0 ? firstMax : max;
    if (sentence.length <= limit) {
      chunks.push(sentence);
      continue;
    }
    const clauses = sentence.split(CLAUSE).filter(Boolean);
    let current = "";
    for (const clause of clauses) {
      if (chunks.length === 0) {
        // the very first chunk: cut at the first clause break once it's long enough to say
        current = current ? `${current} ${clause}` : clause;
        if (current.length >= minLength) {
          chunks.push(current);
          current = "";
        }
        continue;
      }
      const joined = current ? `${current} ${clause}` : clause;
      if (current && current.length >= minLength && joined.length > max) {
        chunks.push(current);
        current = clause;
      } else {
        current = joined;
      }
    }
    if (current) chunks.push(current);
  }
  return chunks;
}
