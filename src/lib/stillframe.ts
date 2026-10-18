export const STILLFRAME_API = "http://127.0.0.1:8741";

export type Level = "high" | "suspicious" | "low" | "none" | string;

export type HiddenMessage = {
  method?: string;
  where?: string;
  encoding?: string;
  text?: string;
  original?: string;
  also_in?: string[];
};

export type RankedImage = {
  id: string;
  rank: number;
  filename: string;
  format?: string;
  size_bytes?: number;
  width?: number | null;
  height?: number | null;
  sha256?: string;
  score: number;
  level: Level;
  level_label: string;
  headline?: string;
  top_reasons?: string[];
  messages?: HiddenMessage[];
  activity_status?: string;
  preview_url?: string | null;
  local_preview?: string | null;
  integrity?: { unchanged?: boolean; statement?: string };
  report?: ImageReport | null;
};

export type ImageReport = {
  narrative?: string;
  limitations?: string;
  suspicion?: { score?: number; level_label?: string; statement?: string };
  conclusions?: {
    hidden_data?: Panel;
    activity?: Panel;
    device_health?: Panel;
  };
  activity_correlation?: {
    headline?: string;
    timeline?: ActivityEvent[];
  };
  sensor_assessment?: {
    headline?: string;
    explanation?: string;
    status?: string;
  };
  messages_found?: HiddenMessage[];
  image_analysis?: {
    metadata_messages?: {
      fields?: MetaField[];
    };
  };
  file?: {
    format?: string;
    size_bytes?: number;
    width?: number | null;
    height?: number | null;
  };
};

export type MetaField = {
  field?: string;
  classification?: string;
  preview?: string;
  decoded?: string | null;
  flagged?: boolean;
  encoding?: string;
};

export type Panel = { status?: string; headline?: string; statement?: string };

export type ActivityEvent = {
  timestamp?: string;
  process_name?: string;
  event_type?: string;
  detail?: string;
  sequence_role?: string;
};

export type BatchScan = {
  scan_id?: string;
  summary?: {
    headline?: string;
    scanned?: number;
    skipped?: number;
    messages_recovered?: number;
    levels?: { high?: number; suspicious?: number; low?: number; none?: number };
  };
  integrity?: { all_unchanged?: boolean; statement?: string };
  source?: { type?: string; title?: string; path?: string };
  ranking?: RankedImage[];
  skipped?: { filename?: string; reason?: string }[];
  statement?: string;
  limitations?: string;
};

async function handle(response: Response): Promise<BatchScan> {
  const body = (await response.json()) as { detail?: { message?: string } };
  if (!response.ok) {
    throw new Error(body.detail?.message ?? `The scanner said no (${response.status}).`);
  }
  return body as BatchScan;
}

export async function runDemoBatch() {
  const response = await fetch(`${STILLFRAME_API}/api/demo-batch`, { method: "POST" });
  return handle(response);
}

export async function scanFolderPath(path: string, recursive = false) {
  const response = await fetch(`${STILLFRAME_API}/api/scan-folder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, recursive }),
  });
  return handle(response);
}

export async function uploadImages(files: File[]) {
  const form = new FormData();
  for (const file of files) {
    const named = file as File & { webkitRelativePath?: string };
    form.append("images", file, named.webkitRelativePath || file.name);
  }
  const response = await fetch(`${STILLFRAME_API}/api/analyze-batch`, {
    method: "POST",
    body: form,
  });
  return handle(response);
}

export async function explainFinding(entry: RankedImage): Promise<string> {
  const reasonText = (entry.top_reasons ?? []).join(" ").toLowerCase();
  const reasons = [
    (entry.messages?.length ?? 0) > 0 ? "Readable content was recovered" : null,
    /after the end|trailer|extra bytes/.test(reasonText) ? "Extra data after the image end" : null,
    /metadata|exif|base64|comment|description/.test(reasonText)
      ? "Unusual metadata or encoding"
      : null,
    /pixel|lsb|channel/.test(reasonText) ? "Unusual pixel pattern" : null,
  ].filter((reason): reason is string => Boolean(reason));
  const response = await fetch(`${STILLFRAME_API}/api/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      level: entry.level,
      reasons: reasons.length ? reasons : ["No specific hidden-data indicators were reported"],
    }),
  });
  const body = (await response.json()) as { text?: string; detail?: string | { message?: string } };
  if (!response.ok) {
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : body.detail?.message || "Gemini is unavailable right now.",
    );
  }
  return body.text || "No explanation returned.";
}

export function previewSrc(entry: RankedImage) {
  if (entry.local_preview) return entry.local_preview;
  if (!entry.preview_url) return null;
  return `${STILLFRAME_API}${entry.preview_url}`;
}

export function withLocalPreviews(batch: BatchScan, files: File[]) {
  const previews = new Map<string, string>();
  for (const file of files) previews.set(file.name, URL.createObjectURL(file));
  for (const entry of batch.ranking ?? []) {
    const preview = previews.get(entry.filename);
    if (preview) entry.local_preview = preview;
  }
  return batch;
}

export function levelMark(level: string) {
  if (level === "high") return "▲ High";
  if (level === "suspicious") return "◆ Suspicious";
  if (level === "low") return "● Low";
  return "○ None";
}

const nameHints: [RegExp, string][] = [
  [
    /whatsapp|telegram|signal|imessage|messenger|discord|slack|snapchat/i,
    "Name looks like a chat app",
  ],
  [/conversation|messages|inbox|\bchat\b|\bdm\b/i, "Name looks like a conversation"],
  [/screenshot|screen[-_ ]?shot/i, "Name looks like a screenshot"],
  [/\.(exe|js|html|htm|zip|scr)(\.|$)/i, "Name hides another file type"],
];

export function nameHint(filename: string) {
  const base = filename.split(/[/\\]/).pop() ?? filename;
  return nameHints.find(([pattern]) => pattern.test(base))?.[1] ?? null;
}

export function folderLabel(path: string) {
  const parts = path.split(/[/\\]/).filter(Boolean);
  return parts.at(-1) || path || "This scan";
}
