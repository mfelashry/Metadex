import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EvidenceSearch } from "@/components/evidex/EvidenceSearch";
import { formatSimilarity, modelStatusLabel, type EvidenceCase, type SearchStatus } from "@/lib/evidence-search";

const cpuStatus: SearchStatus = {
  state: "ready",
  device: "cpu",
  using_gpu: false,
  cuda_available: false,
  model: "ViT-B-32",
  pretrained: "openai",
  error: null,
};

const indexingCase: EvidenceCase = {
  id: "case-demo",
  name: "Technica demo case",
  source: "demo",
  status: "indexing",
  stage: "analyzing",
  progress: { done: 1, total: 4 },
  created_at: "2026-10-18T12:00:00+00:00",
  expires_at: "2026-10-18T18:00:00+00:00",
  device: null,
  using_gpu: false,
  model: null,
  model_error: null,
  indexed_count: 0,
  file_errors: [],
  files: [],
  suggested_queries: ["a red backpack", "a person near a window"],
  disclaimer: "A search match is visual similarity only. It is not evidence that an image is malicious.",
  indicator_disclaimer: "A forensic indicator is a reason to review the file. It is not, by itself, proof of an attack.",
};

const readyCase: EvidenceCase = {
  ...indexingCase,
  status: "ready",
  stage: "ready",
  progress: { done: 4, total: 4 },
  device: "cpu",
  indexed_count: 3,
  file_errors: [{ filename: "notes.txt", reason: "Only PNG, JPEG, and BMP signatures are supported" }],
  files: [],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("model status copy", () => {
  it("names CPU and GPU without mixing them up", () => {
    expect(modelStatusLabel(cpuStatus)).toMatch(/CPU/);
    expect(modelStatusLabel(cpuStatus)).toMatch(/not GPU inference/);
    expect(
      modelStatusLabel({ ...cpuStatus, device: "cpu", using_gpu: false, cuda_available: true }),
    ).toMatch(/not using the GPU/);
    expect(modelStatusLabel({ ...cpuStatus, device: "cuda", using_gpu: true, cuda_available: true })).toMatch(/GPU \(CUDA\)/);
    expect(modelStatusLabel({ ...cpuStatus, state: "failed", device: null, error: "OpenCLIP weights could not be loaded." })).toMatch(
      /weights could not be loaded/,
    );
    expect(formatSimilarity(0.844)).toBe("0.84");
  });
});

describe("evidence search", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("walks demo indexing, repeated search, forensic details, and delete", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/search/status")) return json(cpuStatus);
      if (url.endsWith("/api/cases/demo") && method === "POST") return json(indexingCase);
      if (url.endsWith("/api/cases/case-demo") && method === "GET") return json(readyCase);
      if (url.endsWith("/api/cases/case-demo/search") && method === "POST") {
        const query = JSON.parse(String(init?.body)) as { query: string };
        const backpackFirst = query.query.includes("backpack");
        return json({
          case_id: "case-demo",
          query: query.query,
          device: "cpu",
          using_gpu: false,
          model: "ViT-B-32",
          score_meaning: "Relative cosine similarity. This is not a probability or a danger score.",
          disclaimer: readyCase.disclaimer,
          indicator_disclaimer: readyCase.indicator_disclaimer,
          note: null,
          results: [
            {
              id: backpackFirst ? "i001" : "i002",
              rank: 1,
              filename: backpackFirst ? "red-backpack.png" : "person-by-window.png",
              similarity: 0.91,
              preview_url: "/api/cases/case-demo/items/i001/preview",
              role_label: "Drawn red backpack.",
              forensic_summary: {
                headline: "No hidden-data indicators found",
                level: "none",
                level_label: "No indicators",
                indicator_count: 0,
                statement: "Image-only.",
                metadata_anomalies: [],
                appended: { present: false, trailing_bytes: 0, note: "No bytes were found after the image." },
                lsb: { status: "no_indicator_found", note: "LSB checks did not fire." },
                recovered_payloads: [],
                integrity: { unchanged: true, statement: "The bytes were unchanged." },
                top_reasons: [],
                disclaimer: readyCase.indicator_disclaimer,
              },
            },
            {
              id: "i004",
              rank: 2,
              filename: "locker-note.jpg",
              similarity: 0.12,
              preview_url: "/api/cases/case-demo/items/i004/preview",
              forensic_summary: {
                headline: "Hidden-data indicators found",
                level: "high",
                level_label: "High",
                indicator_count: 2,
                statement: "Image-only.",
                metadata_anomalies: ["JPEG COM segment"],
                appended: { present: true, trailing_bytes: 22, note: "Bytes after the image." },
                lsb: { status: "not_applicable", note: "JPEG does not keep least-significant bits." },
                recovered_payloads: [{ where: "JPEG comment", preview: "Meet at locker 12." }],
                integrity: { unchanged: true, statement: "The bytes were unchanged." },
                top_reasons: ["A JPEG comment was recovered"],
                disclaimer: readyCase.indicator_disclaimer,
              },
            },
          ],
        });
      }
      if (url.endsWith("/api/cases/case-demo/items/i004")) {
        return json({
          id: "i004",
          filename: "locker-note.jpg",
          sha256: "abc123",
          forensic_summary: {
            headline: "Hidden-data indicators found",
            level: "high",
            level_label: "High",
            indicator_count: 2,
            statement: "Image-only.",
            metadata_anomalies: ["JPEG COM segment"],
            appended: { present: true, trailing_bytes: 22, note: "Bytes after the image." },
            lsb: { status: "not_applicable", note: "JPEG does not keep least-significant bits." },
            recovered_payloads: [{ where: "JPEG comment", preview: "Meet at locker 12." }],
            integrity: { unchanged: true, statement: "The bytes were unchanged." },
            top_reasons: [],
            disclaimer: readyCase.indicator_disclaimer,
          },
          messages: [{ where: "JPEG comment", text: "Meet at locker 12. Bring the red key." }],
          findings: [{ name: "Appended data", detail: "Bytes follow the JPEG end marker." }],
          integrity: { unchanged: true, statement: "The bytes were unchanged." },
          limitations: "A clear result does not mean the file is clean.",
        });
      }
      if (method === "DELETE") return new Response(null, { status: 204 });
      return json({ detail: { message: `Unexpected ${method} ${url}` } }, 500);
    });

    render(<EvidenceSearch />);
    expect(await screen.findByRole("status")).toHaveTextContent(/not GPU inference/);
    expect(screen.getByRole("button", { name: "Open the demo case" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Open the demo case" }));
    expect(await screen.findByText(/Indexing images and running forensic analysis/)).toBeInTheDocument();
    expect(await screen.findByLabelText("Describe an image")).toBeInTheDocument();
    expect(screen.getByText(/Some files were not indexed/)).toBeInTheDocument();
    expect(screen.getByText(/notes.txt: Only PNG, JPEG, and BMP/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "a red backpack" }));
    expect(await screen.findByText(/red-backpack.png/)).toBeInTheDocument();
    expect(screen.getAllByText(/Relative similarity 0.91/).length).toBeGreaterThan(0);
    expect(screen.getByText("No hidden-data indicators found")).toBeInTheDocument();
    expect(screen.getByText(/not evidence that an image is malicious/)).toBeInTheDocument();
    expect(screen.getByText(/not, by itself, proof of an attack/)).toBeInTheDocument();
    expect(screen.getByText(/This search ran on the CPU/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Describe an image"), { target: { value: "a person near a window" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/person-by-window.png/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /locker-note.jpg/ }));
    const dialog = await screen.findByRole("dialog", { name: "locker-note.jpg" });
    expect(await within(dialog).findByText(/Meet at locker 12. Bring the red key./)).toBeInTheDocument();
    expect(within(dialog).getByText(/Bytes follow the JPEG end marker./)).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "locker-note.jpg" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete case" }));
    const confirm = await screen.findByRole("dialog", { name: "Delete this case?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Delete case" }));
    expect(await screen.findByText("Drop evidence images here")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });

  it("shows when the forensic service is offline", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    render(<EvidenceSearch />);
    expect(await screen.findByRole("status")).toHaveTextContent("The forensic service is not running.");
  });
});
