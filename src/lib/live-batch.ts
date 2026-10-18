import { uploadImages, type BatchScan, type RankedImage } from "./stillframe";

// Stay under the checker's per-request file cap, then keep going until every photo is sent.
const REQUEST_BATCH = 150;

export async function scanImagesWithProgress(
  files: File[],
  previews: string[],
  onProgress: (done: number, total: number) => void,
): Promise<BatchScan> {
  const results: RankedImage[] = [];
  const skipped: NonNullable<BatchScan["skipped"]> = [];
  const batches: BatchScan[] = [];

  for (let start = 0; start < files.length; start += REQUEST_BATCH) {
    const sliceFiles = files.slice(start, start + REQUEST_BATCH);
    const byName = new Map(
      sliceFiles.map((file, offset) => [file.name, { index: start + offset, preview: previews[start + offset] }]),
    );
    try {
      const batch = await uploadImages(sliceFiles);
      batches.push(batch);
      for (const entry of batch.ranking ?? []) {
        const match =
          byName.get(entry.filename) ?? byName.get(entry.filename.split("/").pop() || "");
        results.push({
          ...entry,
          id: `${match?.index ?? start}-${entry.id}`,
          ...(match?.preview ? { local_preview: match.preview } : {}),
        });
      }
      skipped.push(...(batch.skipped ?? []));
    } catch (error) {
      if (error instanceof TypeError) {
        throw new Error(
          "The forensic scanner is not running. Start it at 127.0.0.1:8741, then upload again.",
        );
      }
      const reason = error instanceof Error ? error.message : "Could not read image";
      for (const file of sliceFiles) skipped.push({ filename: file.name, reason });
    }
    onProgress(Math.min(start + sliceFiles.length, files.length), files.length);
  }

  results.sort((a, b) => b.score - a.score);
  results.forEach((entry, index) => {
    entry.rank = index + 1;
  });
  const levels = { high: 0, suspicious: 0, low: 0, none: 0 };
  for (const entry of results) {
    if (entry.level in levels) levels[entry.level as keyof typeof levels]++;
  }
  const first = batches[0];
  return {
    scan_id: crypto.randomUUID(),
    source: {
      type: "upload",
      title: files.length === 1 ? files[0]!.name : `${files.length} images`,
    },
    summary: {
      headline: `${results.length} image${results.length === 1 ? "" : "s"} checked · ${levels.high + levels.suspicious} flagged for review`,
      scanned: results.length,
      skipped: skipped.length,
      messages_recovered: results.reduce((sum, entry) => sum + (entry.messages?.length ?? 0), 0),
      levels,
    },
    ranking: results,
    skipped,
    ...(first?.integrity ? { integrity: first.integrity } : {}),
    ...(first?.statement ? { statement: first.statement } : {}),
    ...(first?.limitations ? { limitations: first.limitations } : {}),
  };
}
