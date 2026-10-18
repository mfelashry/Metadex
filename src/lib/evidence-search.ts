import { STILLFRAME_API } from "@/lib/stillframe";

export type SearchState = "not_loaded" | "loading" | "ready" | "failed" | string;

export type SearchStatus = {
  state: SearchState;
  device: "cpu" | "cuda" | "mps" | null;
  using_gpu: boolean;
  cuda_available: boolean;
  model: string;
  pretrained: string;
  error: string | null;
};

export type PayloadPreview = {
  method?: string;
  where?: string;
  preview: string;
};

export type ForensicSummary = {
  headline: string;
  level: string;
  level_label: string;
  indicator_count: number;
  statement: string;
  metadata_anomalies: string[];
  appended: { present: boolean; trailing_bytes: number; note: string };
  lsb: { status: string; note: string };
  recovered_payloads: PayloadPreview[];
  integrity: { unchanged: boolean; statement: string };
  top_reasons: string[];
  disclaimer: string;
};

export type CaseFile = {
  id: string;
  filename: string;
  status: string;
  error: string | null;
  format?: string | null;
  width?: number | null;
  height?: number | null;
  role?: string | null;
  role_label?: string | null;
  forensic_summary: ForensicSummary | null;
  preview_url: string | null;
};

export type EvidenceCase = {
  id: string;
  name: string;
  source: string;
  status: "indexing" | "ready" | "failed" | string;
  stage: string;
  progress: { done: number; total: number };
  created_at: string;
  expires_at: string;
  device: string | null;
  using_gpu: boolean;
  model: string | null;
  model_error: string | null;
  indexed_count: number;
  file_errors: { filename: string; reason: string }[];
  files: CaseFile[];
  suggested_queries: string[];
  disclaimer: string;
  indicator_disclaimer: string;
};

export type SearchHit = {
  id: string;
  rank: number;
  filename: string;
  similarity: number;
  preview_url: string;
  role?: string | null;
  role_label?: string | null;
  forensic_summary: ForensicSummary;
};

export type SearchResponse = {
  case_id: string;
  query: string;
  device: string | null;
  using_gpu: boolean;
  model: string | null;
  score_meaning: string;
  disclaimer: string;
  indicator_disclaimer: string;
  note: string | null;
  results: SearchHit[];
};

export type Finding = { name?: string | null; result?: string | null; detail?: string | null };

export type ItemDetail = {
  id: string;
  filename: string;
  sha256?: string | null;
  forensic_summary: ForensicSummary;
  messages?: { text?: string; where?: string; method?: string }[];
  findings?: Finding[];
  image_analysis?: {
    structure?: { note?: string | null; trailing_bytes?: number | null };
    metadata?: { explanation?: string | null; clues?: string[] };
    appended_data?: { explanation?: string | null; trailing_bytes?: number | null };
    lsb?: { status?: string | null; explanation?: string | null };
  };
  integrity?: { unchanged?: boolean; statement?: string };
  limitations?: string | null;
  disclaimer?: string;
  match_disclaimer?: string;
};

export class SearchApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "SearchApiError";
    this.status = status;
  }
}

export function modelStatusLabel(status: SearchStatus | null, offline = false): string {
  if (offline) return "The forensic service is not running.";
  if (!status || status.state === "not_loaded") return "The search model loads with the first case.";
  if (status.state === "loading") return "Loading the search model.";
  if (status.state === "failed") return status.error || "The search model could not be loaded.";
  if (status.using_gpu && status.device === "cuda") return "Search is running on the GPU (CUDA).";
  if (status.using_gpu && status.device === "mps") return "Search is running on the GPU (Apple MPS).";
  if (status.device === "cpu") {
    return status.cuda_available
      ? "Search is running on the CPU. CUDA is visible, but this process is not using the GPU."
      : "Search is running on the CPU. This is not GPU inference.";
  }
  return "Search device is still unknown.";
}

export function formatSimilarity(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(2);
}

/** Photos that sit with the best visual match. The case API ranks every image; the report keeps this cluster. */
export function selectVisualMatches<T extends { similarity: number }>(results: T[]): T[] {
  const ranked = [...results].sort((left, right) => right.similarity - left.similarity);
  if (!ranked.length) return [];
  const best = ranked[0]!.similarity;
  const floor = Math.max(0.2, best - 0.04);
  const kept = ranked.filter((hit) => hit.similarity >= floor && hit.similarity > 0);
  return kept.length ? kept : ranked.slice(0, 1);
}

export function previewUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${STILLFRAME_API}${path}`;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: { message?: string } | string };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail?.message) return body.detail.message;
  } catch {
    return `The server returned ${response.status}.`;
  }
  return `The server returned ${response.status}.`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${STILLFRAME_API}${path}`, init);
  } catch {
    throw new SearchApiError("The forensic service is not running.", 0);
  }
  if (!response.ok) throw new SearchApiError(await readError(response), response.status);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function fetchSearchStatus() {
  return request<SearchStatus>("/api/search/status");
}

export function listCases() {
  return request<EvidenceCase[]>("/api/cases");
}

export function createCase(files: File[], name: string) {
  const form = new FormData();
  form.set("name", name);
  for (const file of files) form.append("images", file, file.name);
  return request<EvidenceCase>("/api/cases", { method: "POST", body: form });
}

export function createDemoCase() {
  return request<EvidenceCase>("/api/cases/demo", { method: "POST" });
}

export function fetchCase(id: string) {
  return request<EvidenceCase>(`/api/cases/${id}`);
}

export function searchCase(id: string, query: string) {
  return request<SearchResponse>(`/api/cases/${id}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
}

export function fetchItem(caseId: string, itemId: string) {
  return request<ItemDetail>(`/api/cases/${caseId}/items/${itemId}`);
}

export function deleteCase(id: string) {
  return request<void>(`/api/cases/${id}`, { method: "DELETE" });
}
