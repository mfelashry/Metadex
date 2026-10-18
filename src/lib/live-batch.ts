import { uploadImages, type BatchScan, type RankedImage } from "./stillframe";

// The checker returns a batch only after every file finishes. Small concurrent
// batches let the interface report genuine completed images as they arrive.
export async function scanImagesWithProgress(
  files: File[],
  previews: string[],
  onProgress: (done: number, total: number) => void,
): Promise<BatchScan> {
  const results: RankedImage[] = [];
  const skipped: NonNullable<BatchScan["skipped"]> = [];
  let cursor = 0;
  let done = 0;
  let networkError: TypeError | null = null;
  const batches: BatchScan[] = [];

  async function worker() {
    while (cursor < files.length && !networkError) {
      const index = cursor++;
      const file = files[index]!;
      try {
        const batch = await uploadImages([file]);
        batches.push(batch);
        for (const entry of batch.ranking ?? []) {
          results.push({
            ...entry,
            id: `${index}-${entry.id}`,
            local_preview: previews[index]!,
          });
        }
        skipped.push(...(batch.skipped ?? []));
      } catch (error) {
        if (error instanceof TypeError) {
          networkError = error;
          break;
        }
        skipped.push({
          filename: file.name,
          reason: error instanceof Error ? error.message : "Could not read image",
        });
      }
      onProgress(++done, files.length);
    }
  }

  const concurrency = files.length >= 60 ? 8 : files.length >= 20 ? 6 : 3;
  await Promise.all(Array.from({ length: Math.min(concurrency, files.length) }, worker));
  if (networkError) throw networkError;

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
