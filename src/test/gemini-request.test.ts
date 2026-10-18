import { describe, expect, it, vi } from "vitest";
import { explainFinding } from "@/lib/stillframe";

describe("Gemini explanation request", () => {
  it("sends finding categories without recovered text or image data", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ text: "Review the extra bytes." }), { status: 200 }),
      );
    try {
      await explainFinding({
        id: "one",
        rank: 1,
        filename: "private-photo.jpg",
        score: 60,
        level: "high",
        level_label: "High",
        top_reasons: ["Decoded: private phrase", "12 extra bytes after the end of the image"],
        messages: [{ text: "private phrase" }],
      });
      const body = String(fetchMock.mock.calls[0]?.[1]?.body);
      expect(body).toContain("Extra data after the image end");
      expect(body).not.toContain("private phrase");
      expect(body).not.toContain("private-photo.jpg");
    } finally {
      fetchMock.mockRestore();
    }
  });
});
