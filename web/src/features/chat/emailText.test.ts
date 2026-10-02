import { describe, expect, it } from "vitest";
import { paragraphs } from "./emailParagraphs";

// the shape of a real marketing email's text/plain part (invented content, example domains)
const MARKETING =
  "Complete a visit and earn a $150 reward.\u200C\u034F \u00A0\n\n\n\n" +
  "Rewards - Look At The Calendar  Take a look at your dentist's calendar. See the\n" +
  "available times.\n\n \n\n" +
  " See Available Times\n<https://email.rewards.example/c/Xk29pQmTr7Lw3NvB8sYd4Fh2Ga>\n\n" +
  "Take 2 minutes to check their schedule before the next few weeks start\nfilling up.\n\n" +
  "Rewards Terms & Conditions  <>apply\n\n" +
  "*Restrictions apply, see https://email.rewards.example/c/Hq81zRwe4Vn0Lm6Tq.\n\n" +
  "Thanks,\nSam";

describe("paragraphs (an email's plain text, readable)", () => {
  it("turns tracking links into links by site, and joins a link to the label above it", () => {
    const paras = paragraphs(MARKETING);
    expect(paras[2]).toEqual([
      "See Available Times ",
      { url: "https://email.rewards.example/c/Xk29pQmTr7Lw3NvB8sYd4Fh2Ga", host: "email.rewards.example" },
    ]);
    // a bare address keeps the full stop that ends the sentence outside the link
    expect(paras[5]).toEqual([
      "*Restrictions apply, see ",
      { url: "https://email.rewards.example/c/Hq81zRwe4Vn0Lm6Tq", host: "email.rewards.example" },
      ".",
    ]);
    expect(JSON.stringify(paras)).not.toContain("<https");
  });

  it("joins hard-wrapped lines, keeps short ones, and drops padding and empty links", () => {
    const text = paragraphs(MARKETING).map((p) => p.map((piece) => (typeof piece === "string" ? piece : "[link]")).join(""));
    expect(text).toEqual([
      "Complete a visit and earn a $150 reward.", // invisible padding gone
      "Rewards - Look At The Calendar Take a look at your dentist's calendar. See the available times.",
      "See Available Times [link]",
      "Take 2 minutes to check their schedule before the next few weeks start filling up.",
      "Rewards Terms & Conditions apply", // the empty "<>" link
      "*Restrictions apply, see [link].",
      "Thanks,\nSam", // a short line keeps its break
    ]);
  });

  it("leaves anything that isn't an http(s) address as text", () => {
    expect(paragraphs("Call javascript:alert(1) or mailto:sam@example.com")).toEqual([
      ["Call javascript:alert(1) or mailto:sam@example.com"],
    ]);
    expect(paragraphs("\u200B \n\n\u00A0")).toEqual([]);
  });
});
