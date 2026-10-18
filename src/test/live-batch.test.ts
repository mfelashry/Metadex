import { describe, expect, it, vi } from "vitest";
import { scanImagesWithProgress } from "@/lib/live-batch";

describe("live checker progress", () => {
  it("reports each completed image and keeps its matching preview", async () => {
    const finished: number[] = [];
    const files = ["one.png", "two.png", "three.png"].map(
      (name) => new File([name], name, { type: "image/png" }),
    );
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, options) => {
      const file = (options?.body as FormData).get("images") as File;
      await new Promise((resolve) => setTimeout(resolve, file.name === "two.png" ? 20 : 5));
      return new Response(
        JSON.stringify({
          ranking: [
            {
              id: "item-1",
              rank: 1,
              filename: file.name,
              score: 12,
              level: "low",
              level_label: "Low",
            },
          ],
          skipped: [],
          integrity: { all_unchanged: true },
        }),
        { status: 200 },
      );
    });
    try {
      const result = await scanImagesWithProgress(files, ["blob:1", "blob:2", "blob:3"], (done) =>
        finished.push(done),
      );
      expect(finished).toEqual([1, 2, 3]);
      expect(result.summary?.scanned).toBe(3);
      expect(result.ranking?.map((entry) => [entry.id, entry.local_preview]).sort()).toEqual([
        ["0-item-1", "blob:1"],
        ["1-item-1", "blob:2"],
        ["2-item-1", "blob:3"],
      ]);
    } finally {
      fetchMock.mockRestore();
    }
  });
});
