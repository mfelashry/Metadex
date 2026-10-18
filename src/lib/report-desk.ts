import type { ScanReport } from "@/lib/scan-report";

export type DeskItem = {
  id: string;
  name: string;
  preview: string | null;
  status: "working" | "ready" | "error";
  error?: string;
  report: ScanReport | null;
};

export type Desk = {
  items: DeskItem[];
  activeId: string | null;
  demo: ScanReport | null;
};

const empty: Desk = { items: [], activeId: null, demo: null };
let desk: Desk = empty;
const listeners = new Set<() => void>();

export function readDesk() {
  return desk;
}

export function publishDesk(next: Desk) {
  desk = next;
  listeners.forEach((listener) => listener());
}

export function selectDeskItem(id: string) {
  desk = { ...desk, activeId: id, demo: null };
  listeners.forEach((listener) => listener());
}

export function subscribeDesk(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
