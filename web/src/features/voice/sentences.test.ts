import { describe, expect, it } from "vitest";
import { speakableChunks, splitSentences } from "./sentences";

describe("speakableChunks", () => {
  it("cuts a long first sentence at its first clause so the owner hears something sooner", () => {
    expect(
      speakableChunks("I've prepared this: Reminder: call mom (Thu Oct 01 at 17:00). Approve the card to go ahead."),
    ).toEqual(["I've prepared this:", "Reminder: call mom (Thu Oct 01 at 17:00).", "Approve the card to go ahead."]);
  });

  it("keeps short sentences whole and never loses text", () => {
    expect(speakableChunks("You're welcome! Anything else?")).toEqual(["You're welcome!", "Anything else?"]);
    const long = "Ottawa is the capital of Canada, located in Ontario, on the Ottawa River, near Quebec. It has 1 million people.";
    expect(speakableChunks(long).join(" ")).toBe(long);
    expect(speakableChunks(long)[0].length).toBeLessThanOrEqual(40);
  });
});

describe("splitSentences", () => {
  it("splits a reply into sentences for speaking one at a time", () => {
    expect(splitSentences("I've prepared this: Reminder: call mom. Approve the card to go ahead!")).toEqual([
      "I've prepared this: Reminder: call mom.",
      "Approve the card to go ahead!",
    ]);
  });

  it("merges tiny fragments so TTS isn't called for a single word", () => {
    expect(splitSentences("Sure. You have two reminders today: call mom and stretch.")).toEqual([
      "Sure. You have two reminders today: call mom and stretch.",
    ]);
  });

  it("keeps times and decimals together and ignores empty input", () => {
    expect(splitSentences("It's due at 5:30 p.m. tomorrow. That is 2.5 hours after class.")).toEqual([
      "It's due at 5:30 p.m. tomorrow.",
      "That is 2.5 hours after class.",
    ]);
    expect(splitSentences("   ")).toEqual([]);
  });
});
