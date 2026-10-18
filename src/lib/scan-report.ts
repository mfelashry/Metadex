import type { ImageAnalysis } from "@/components/evidex/analyzeImage";

export type CheckStatus = "clean" | "review" | "suspicious";

export type Evidence = {
  id: "exif" | "hidden" | "encrypted";
  title: string;
  status: CheckStatus;
  finding: string;
};

export type ScanReport = {
  fileName: string;
  source: "demo" | "browser";
  level: "Clean" | "Review" | "Suspicious";
  line: string;
  evidence: Evidence[];
  preview: string | null;
};

export function suspicionLevel(score: number): ScanReport["level"] {
  if (score >= 70) return "Suspicious";
  if (score >= 30) return "Review";
  return "Clean";
}

export function statusLabel(status: CheckStatus) {
  if (status === "clean") return "Clean";
  if (status === "review") return "Review";
  return "Suspicious";
}

function levelFrom(evidence: Evidence[]): ScanReport["level"] {
  if (evidence.some((item) => item.status === "suspicious")) return "Suspicious";
  if (evidence.some((item) => item.status === "review")) return "Review";
  return "Clean";
}

function lineFor(evidence: Evidence[]): string {
  const hidden = evidence.find((item) => item.id === "hidden");
  const encrypted = evidence.find((item) => item.id === "encrypted");
  const exif = evidence.find((item) => item.id === "exif");
  if (hidden?.status === "suspicious") return "A readable message is in the file.";
  if (encrypted?.status === "suspicious") return "Something after the picture is locked.";
  if (exif?.status === "review" || hidden?.status === "review")
    return "Something looks odd. It is a claim, not proof.";
  return "No odd EXIF, hidden text, or locked data.";
}

function rowsFromAnalysis(analysis: ImageAnalysis): Evidence[] {
  const notes = analysis.exifNotes ?? [];
  const payload = analysis.payload ?? { kind: "none" as const, text: null };
  const exif: Evidence = notes.length
    ? {
        id: "exif",
        title: "EXIF",
        status: "review",
        finding: `${notes.slice(0, 2).join(" ")} A claim, not proof.`,
      }
    : {
        id: "exif",
        title: "EXIF",
        status: "clean",
        finding: "Nothing odd. Tags are claims, not proof.",
      };
  const hidden: Evidence =
    payload.kind === "text" || payload.kind === "encoded"
      ? {
          id: "hidden",
          title: "Hidden message",
          status: "suspicious",
          finding: payload.text ?? "Readable text was found.",
        }
      : payload.kind === "binary"
        ? {
            id: "hidden",
            title: "Hidden message",
            status: "review",
            finding: "Extra bytes, not readable text.",
          }
        : {
            id: "hidden",
            title: "Hidden message",
            status: "clean",
            finding: "None.",
          };
  const encrypted: Evidence =
    payload.kind === "locked"
      ? {
          id: "encrypted",
          title: "Encrypted",
          status: "suspicious",
          finding: "Locked. Not decrypted.",
        }
      : {
          id: "encrypted",
          title: "Encrypted",
          status: "clean",
          finding: "None.",
        };
  return [exif, hidden, encrypted];
}

export function reportFromAnalysis(analysis: ImageAnalysis, preview: string | null): ScanReport {
  const evidence = rowsFromAnalysis(analysis);
  return {
    fileName: analysis.fileName,
    source: "browser",
    level: levelFrom(evidence),
    line: lineFor(evidence),
    evidence,
    preview,
  };
}

export const cleanCase: ScanReport = {
  fileName: "lobby-photo.jpg",
  source: "demo",
  level: "Clean",
  line: "No odd EXIF, hidden text, or locked data.",
  evidence: [
    {
      id: "exif",
      title: "EXIF",
      status: "clean",
      finding: "Nothing odd. Tags are claims, not proof.",
    },
    { id: "hidden", title: "Hidden message", status: "clean", finding: "None." },
    { id: "encrypted", title: "Encrypted", status: "clean", finding: "None." },
  ],
  preview: null,
};

export const suspiciousCase: ScanReport = {
  fileName: "q3-export.png",
  source: "demo",
  level: "Suspicious",
  line: "A readable message is in the file.",
  evidence: [
    {
      id: "exif",
      title: "EXIF",
      status: "review",
      finding: "Software tag is oversized. A claim, not proof.",
    },
    {
      id: "hidden",
      title: "Hidden message",
      status: "suspicious",
      finding: "Meet at the side door.",
    },
    { id: "encrypted", title: "Encrypted", status: "clean", finding: "None." },
  ],
  preview: null,
};
