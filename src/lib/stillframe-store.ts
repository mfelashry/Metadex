import type { BatchScan } from "@/lib/stillframe";
import { previewSrc } from "@/lib/stillframe";

export type HistoryImage = {
  id: string;
  filename: string;
  level: string;
  preview: string | null;
};

export type SavedReport = {
  id: string;
  title: string;
  headline: string;
  at: string;
  count: number;
  batch: BatchScan;
};

type ScanState = {
  batch: BatchScan | null;
  selectedId: string | null;
  error: string | null;
  history: HistoryImage[];
  title: string;
  reports: SavedReport[];
  searchCases: Record<string, string>;
};

const SEARCH_CASES_KEY = "metadex.searchCases";

function storedSearchCases(): Record<string, string> {
  try {
    if (typeof sessionStorage === "undefined") return {};
    const raw = sessionStorage.getItem(SEARCH_CASES_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(
      Object.entries(parsed).filter((entry): entry is [string, string] => typeof entry[1] === "string" && Boolean(entry[0])),
    );
  } catch {
    return {};
  }
}

function rememberStoredCases(cases: Record<string, string>) {
  try {
    if (typeof sessionStorage === "undefined") return;
    sessionStorage.setItem(SEARCH_CASES_KEY, JSON.stringify(cases));
  } catch {
    // The in-memory map still avoids a second upload in this tab.
  }
}

let state: ScanState = {
  batch: null,
  selectedId: null,
  error: null,
  history: [],
  title: "",
  reports: [],
  searchCases: storedSearchCases(),
};
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

export function readScan() {
  return state;
}

export function publishScan(batch: BatchScan, title = "This scan") {
  const ranking = batch.ranking ?? [];
  const first = ranking.find((item) => item.level && item.level !== "none") ?? ranking[0];
  const seen = new Set(state.history.map((item) => item.filename));
  const added = ranking
    .map((item) => ({
      id: item.id,
      filename: item.filename,
      level: item.level_label || item.level,
      preview: previewSrc(item),
    }))
    .filter((item) => !seen.has(item.filename));
  const saved: SavedReport = {
    id: batch.scan_id || crypto.randomUUID(),
    title,
    headline: batch.summary?.headline || title,
    at: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
    count: batch.summary?.scanned ?? ranking.length,
    batch,
  };
  state = {
    batch,
    selectedId: first?.id ?? null,
    error: null,
    title,
    history: [...added, ...state.history].slice(0, 24),
    reports: [saved, ...state.reports.filter((item) => item.id !== saved.id)].slice(0, 12),
    searchCases: state.searchCases,
  };
  emit();
}

export function openSaved(id: string) {
  const saved = state.reports.find((item) => item.id === id);
  if (!saved) return;
  const ranking = saved.batch.ranking ?? [];
  const first = ranking.find((item) => item.level && item.level !== "none") ?? ranking[0];
  state = { ...state, batch: saved.batch, selectedId: first?.id ?? null, title: saved.title };
  emit();
}

export function rememberSearchCase(scanId: string, caseId: string, force = false) {
  if (!scanId || !caseId) return;
  if (!force && state.searchCases[scanId]) return;
  const searchCases = { ...state.searchCases, [scanId]: caseId };
  state = { ...state, searchCases };
  rememberStoredCases(searchCases);
  emit();
}

export function searchCaseFor(scanId: string | undefined) {
  if (!scanId) return null;
  return state.searchCases[scanId] ?? null;
}

export function selectScan(id: string) {
  state = { ...state, selectedId: id };
  emit();
}

export function failScan(error: string) {
  state = { ...state, error };
  emit();
}

export function subscribeScan(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
