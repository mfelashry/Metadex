import { describe, expect, it } from "vitest";
import { collectScanEvidence, localAnswer, localScanSummary } from "@/lib/scan-summary";
import type { RankedImage } from "@/lib/stillframe";

function photo(filename: string, text: string, level: RankedImage["level"] = "suspicious"): RankedImage {
  return {
    id: filename,
    rank: 1,
    filename,
    score: 80,
    level,
    level_label: "Suspicious",
    top_reasons: ["Readable text in EXIF ImageDescription", "Score 88"],
    messages: [{ text, where: "EXIF ImageDescription" }],
  };
}

describe("scan summary", () => {
  it("paraphrases the recovered thread without speaker labels or scores", () => {
    const evidence = collectScanEvidence([
      photo("cat-002.jpg", "Sam: Yes. I just left the apartment."),
      photo("cat-001.jpg", "Alex: Hey, are you still coming to the waterfront?"),
      photo("cat-150.jpg", "Sam: Agreed. See you there. I will bring the photo."),
      photo("cat-010.jpg", "A clean landscape.", "none"),
    ]);
    expect(evidence.lines[0]).toBe("Hey, are you still coming to the waterfront?");
    expect(evidence.lines).not.toContain("A clean landscape.");
    expect(evidence.clues.join(" ")).not.toMatch(/score/i);
    const summary = localScanSummary(evidence);
    expect(summary).toMatch(/waterfront/i);
    expect(summary).toMatch(/photo/i);
    expect(summary).not.toMatch(/Alex:|Sam:/);
    expect(summary).not.toMatch(/score/i);
  });

  it("describes the joke thread when the notes are about tuna", () => {
    const summary = localScanSummary({
      lines: ["the package is the tuna", "box is meowing"],
      clues: ["EXIF UserComment"],
    });
    expect(summary).toMatch(/joke/i);
    expect(summary).toMatch(/tuna/);
    expect(summary).toMatch(/meow/);
    expect(summary).toMatch(/the package is the tuna/);
    expect(summary).toMatch(/box is meowing/);
  });

  it("lists every encoded comment instead of offering a menu", () => {
    const evidence = {
      lines: ["Meet behind the pet shop at 4.", "The cats come with us."],
      clues: ["XPComment"],
      encoded: [
        { filename: "cat-001.jpg", decoded: "Hi, how are you?", encoded: "SGksIGhvdyBhcmUgeW91Pw==" },
        { filename: "cat-002.jpg", decoded: "Good. Are you free later?", encoded: "R29vZC4=" },
      ],
    };
    const listed = localAnswer(evidence, "look at all the encoded comments tell me all of them");
    const okay = localAnswer(evidence, "ohh ok");
    expect(listed).not.toBe(okay);
    expect(listed).toContain("cat-001.jpg");
    expect(listed).toContain("Hi, how are you?");
    expect(listed).toContain("SGksIGhvdyBhcmUgeW91Pw==");
    expect(listed).toContain("cat-002.jpg");
    expect(listed).not.toMatch(/Which one do you want/);
    expect(okay).toBe("Okay.");
  });

  it("names the highest photo when asked for the file", () => {
    const evidence = {
      lines: ["Meet behind the pet shop at 4.", "The cats come with us."],
      clues: [],
      files: [
        { filename: "cat-009.jpg", level: "high", line: "Meet behind the pet shop at 4." },
        { filename: "cat-010.jpg", level: "suspicious", line: "The cats come with us." },
      ],
    };
    const important = localAnswer(evidence, "whats the most important photo of the 250 ones that got detected??");
    const name = localAnswer(evidence, "name of the photo?");
    expect(important).toBe("cat-009.jpg. It says Meet behind the pet shop at 4.");
    expect(name).toBe(important);
    expect(important).not.toMatch(/The important part is the meetup/);
  });

  it("answers a greeting and an importance question differently", () => {
    const evidence = {
      lines: ["We should take the pet shop.", "The cats come with us.", "Meet behind the pet shop at 4."],
      clues: ["EXIF UserComment", "base64"],
    };
    const hello = localAnswer(evidence, "uhh hi");
    const important = localAnswer(evidence, "whats the most important thing though");
    expect(hello).not.toBe(important);
    expect(hello.toLowerCase()).toMatch(/hey/);
    expect(important.toLowerCase()).toMatch(/meetup behind the pet shop at 4/);
    expect(important.toLowerCase()).toMatch(/cats/);
  });

  it("stays quiet when no conversation was recovered", () => {
    expect(localScanSummary({ lines: [], clues: [] })).toMatch(/No readable conversation/);
  });
});