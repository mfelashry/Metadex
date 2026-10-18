import { analyzeImage, type ImageAnalysis } from "@/components/evidex/analyzeImage";
import type { BatchScan, RankedImage } from "@/lib/stillframe";

function ranked(analysis: ImageAnalysis, id: string, preview: string): RankedImage {
  const level = analysis.score >= 70 ? "high" : analysis.score >= 30 ? "suspicious" : "none";
  const reasons = analysis.flags.length
    ? analysis.flags
    : ["No structural flags in the available browser checks."];
  return {
    id,
    rank: 0,
    filename: analysis.fileName,
    format: analysis.format,
    size_bytes: analysis.fileSize,
    width: analysis.width,
    height: analysis.height,
    sha256: analysis.sha256,
    score: analysis.score,
    level,
    level_label: level === "none" ? "No flags" : level === "high" ? "High priority" : "Review",
    headline: reasons[0] ?? "No structural flags in the available browser checks.",
    top_reasons: reasons,
    messages: analysis.payload.text
      ? [
          {
            text: analysis.payload.text,
            where: "Image file",
            encoding: analysis.payload.kind === "encoded" ? "encoded text" : "utf-8",
          },
        ]
      : [],
    local_preview: preview,
    report: {
      narrative: analysis.summary,
      limitations:
        "Browser checks can flag structural clues; they cannot prove or rule out hidden content.",
      image_analysis: {
        metadata_messages: {
          fields: analysis.metadata.map((field) => ({
            field: field.label,
            preview: field.value,
            flagged: false,
          })),
        },
      },
    },
  };
}

export async function scanImagesInBrowser(
  files: File[],
  previews: string[],
  onProgress: (done: number, total: number) => void,
): Promise<BatchScan> {
  const results: RankedImage[] = [];
  const skipped: { filename: string; reason: string }[] = [];
  let cursor = 0;
  let done = 0;
  async function worker() {
    while (cursor < files.length) {
      const index = cursor++;
      const file = files[index]!;
      try {
        results.push(ranked(await analyzeImage(file), `${index}-${file.name}`, previews[index]!));
      } catch (error) {
        skipped.push({
          filename: file.name,
          reason: error instanceof Error ? error.message : "Could not read image",
        });
      }
      onProgress(++done, files.length);
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, files.length) }, worker));
  results.sort((a, b) => b.score - a.score);
  results.forEach((item, index) => {
    item.rank = index + 1;
  });
  const high = results.filter((item) => item.level === "high").length;
  const suspicious = results.filter((item) => item.level === "suspicious").length;
  return {
    scan_id: crypto.randomUUID(),
    source: {
      type: "browser",
      title: files.length === 1 ? files[0]!.name : `${files.length} images`,
    },
    summary: {
      headline: `${results.length} image${results.length === 1 ? "" : "s"} checked · ${high + suspicious} flagged for review`,
      scanned: results.length,
      skipped: skipped.length,
      levels: { high, suspicious, low: 0, none: results.length - high - suspicious },
    },
    ranking: results,
    skipped,
    integrity: { all_unchanged: true, statement: "Original files were read without modification." },
    limitations:
      "Browser checks inspect basic metadata, file structure, and sampled pixels. They cannot prove absence of hidden content.",
  };
}
