import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import {
  motion,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
  type MotionValue,
} from "framer-motion";
import {
  ArrowDown,
  ArrowRight,
  Check,
  Clipboard,
  FileUp,
  Moon,
  RotateCcw,
  Sun,
  Upload,
  X,
} from "lucide-react";
import { FolderScan, type DeckCard } from "./FolderScan";
import { scanImagesWithProgress } from "@/lib/live-batch";
import { analyzeImage, formatBytes, sniffImage, type ImageAnalysis } from "./analyzeImage";
import { publishDesk } from "@/lib/report-desk";
import { publishScan, readScan, selectScan, subscribeScan } from "@/lib/stillframe-store";
import { folderLabel, runDemoBatch, scanFolderPath, previewSrc } from "@/lib/stillframe";
import {
  cleanCase,
  reportFromAnalysis,
  statusLabel,
  suspiciousCase,
  type CheckStatus,
  type ScanReport,
} from "@/lib/scan-report";

type RecordItem = {
  id: string;
  file: File;
  preview: string;
  status: "working" | "ready" | "error";
  result?: ImageAnalysis;
  error?: string;
};

type ScanState = {
  open: boolean;
  kind: "demo" | "upload";
  name: string;
  preview: string | null;
  progress: number;
  stage: string;
  done: boolean;
};

const demo: ImageAnalysis = {
  fileName: "mountain_scene_042.jpg",
  fileSize: 3984589,
  format: "JPEG",
  mimeType: "image/jpeg",
  width: 3024,
  height: 4032,
  sha256: "Sample case · no real file fingerprint",
  fileModified: "Oct 17, 2026 · 11:25 AM",
  capturedAt: "Oct 15, 2026 · 4:42 PM",
  gps: { lat: 38.8977, lon: -77.0365 },
  score: 74,
  flags: [
    "18.4 KB appears after the JPEG end marker.",
    "A blue-channel pixel pattern merits closer review.",
  ],
  metadata: [
    { label: "Dimensions", value: "3024 × 4032", detail: "Illustrative sample value" },
    { label: "Camera", value: "Canon EOS R6", detail: "Illustrative EXIF value" },
    { label: "Capture time", value: "Oct 15, 2026 · 4:42 PM", detail: "Illustrative EXIF value" },
    {
      label: "GPS coordinates",
      value: "38.89770, -77.03650",
      detail: "Illustrative EXIF value; location is not verified",
    },
    { label: "File size", value: "3.80 MB", detail: "Illustrative sample value" },
  ],
  structure: [
    { label: "File signature", value: "JPEG", detail: "Illustrative sample value" },
    { label: "Filename extension", value: "JPEG", detail: "Matches the sample file signature" },
    { label: "Data after image end", value: "18.4 KB", detail: "Illustrative trailing data" },
  ],
  pixels: [
    { label: "Blue channel", value: "Unusual pattern", detail: "Illustrative finding only" },
    {
      label: "Interpretation",
      value: "Needs review",
      detail: "Pixel statistics alone cannot prove hidden content",
    },
  ],
  summary:
    "Sample case for the scroll story. The report below uses the same short layout as a real check.",
  exifNotes: ["Software tag is oversized."],
  payload: { kind: "text", text: "Meet at the side door." },
  isDemo: true,
};

function Paper({ small = false }: { small?: boolean }) {
  return (
    <div
      className={`paper-art sample-image-art${small ? " paper-art-small" : ""}`}
      role="img"
      aria-label="Black and white picture of a waterfront building"
    >
      <svg viewBox="0 0 360 480" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <rect width="360" height="480" fill="#ececec" />
        <rect width="360" height="280" fill="#f7f7f7" />
        <circle cx="286" cy="78" r="28" fill="#fff" />
        <rect x="36" y="118" width="96" height="188" rx="4" fill="#2f2f2f" />
        <g fill="#f4f4f4">
          <rect x="50" y="136" width="18" height="22" rx="2" />
          <rect x="78" y="136" width="18" height="22" rx="2" />
          <rect x="106" y="136" width="14" height="22" rx="2" />
          <rect x="50" y="170" width="18" height="22" rx="2" />
          <rect x="78" y="170" width="18" height="22" rx="2" />
          <rect x="106" y="170" width="14" height="22" rx="2" />
          <rect x="50" y="204" width="18" height="22" rx="2" />
          <rect x="78" y="204" width="18" height="22" rx="2" />
          <rect x="106" y="204" width="14" height="22" rx="2" />
          <rect x="50" y="238" width="18" height="22" rx="2" />
          <rect x="78" y="238" width="18" height="22" rx="2" />
          <rect x="106" y="238" width="14" height="22" rx="2" />
        </g>
        <rect x="156" y="176" width="168" height="130" rx="4" fill="#6a6a6a" />
        <g fill="#f7f7f7">
          <rect x="174" y="194" width="28" height="28" rx="3" />
          <rect x="214" y="194" width="28" height="28" rx="3" />
          <rect x="254" y="194" width="28" height="28" rx="3" />
          <rect x="174" y="236" width="28" height="28" rx="3" />
          <rect x="214" y="236" width="28" height="28" rx="3" />
          <rect x="254" y="236" width="28" height="28" rx="3" />
        </g>
        <rect y="300" width="360" height="180" fill="#141414" />
        <rect x="0" y="292" width="210" height="14" fill="#3a3a3a" />
        <rect y="348" width="360" height="5" fill="#f3f3f3" />
        <rect y="392" width="360" height="3" fill="#8d8d8d" />
      </svg>
    </div>
  );
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

const IMAGE_CAP = 10000;

async function readEntry(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject),
    );
    return [file];
  }
  if (!entry.isDirectory) return [];
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const children: FileSystemEntry[] = [];
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject),
    );
    if (!batch.length) break;
    children.push(...batch);
  }
  const nested = await Promise.all(children.map((child) => readEntry(child)));
  return nested.flat();
}

const IMAGE_EXTENSIONS = [
  "jpg",
  "jpeg",
  "jpe",
  "png",
  "gif",
  "webp",
  "bmp",
  "heic",
  "heif",
  "avif",
  "tif",
  "tiff",
];

function looksLikeImage(file: File) {
  if (file.type.startsWith("image/")) return true;
  const named = file as File & { webkitRelativePath?: string };
  const source = named.webkitRelativePath || file.name;
  const extension = source.split(".").pop()?.toLowerCase() ?? "";
  return IMAGE_EXTENSIONS.includes(extension);
}

async function collectFiles(list: FileList, items?: DataTransferItemList) {
  const entries = items
    ? Array.from(items)
        .map((item) => item.webkitGetAsEntry?.() ?? null)
        .filter((entry): entry is FileSystemEntry => Boolean(entry))
    : [];
  if (!entries.length) return Array.from(list);
  const groups = await Promise.all(entries.map((entry) => readEntry(entry)));
  const files = groups.flat();
  return files.length ? files : Array.from(list);
}

const storyCaption = {
  label: "Image details",
  title: "The first clues appear.",
  body: "Examples of what a file can carry. A real scan uses the photo you pick.",
};

const checks = [
  { title: "EXIF", text: "Camera, time, place." },
  { title: "GPS", text: "Where it was taken." },
  { title: "Date", text: "When it was captured." },
  { title: "Software", text: "App that edited it." },
  { title: "Author", text: "Name stored in the file." },
  { title: "Comment", text: "Notes inside the file." },
  { title: "Hidden text", text: "Words after the picture." },
  { title: "Encoded", text: "Turns back into words." },
  { title: "Locked", text: "Needs a key." },
  { title: "Extra bytes", text: "After the image." },
  { title: "File type", text: "Name matches." },
  { title: "File name", text: "Chat or odd names." },
  { title: "Pixels", text: "Odd pixel pattern." },
  { title: "Thumbnail", text: "Small inner copy." },
  { title: "Activity", text: "Around the file." },
  { title: "Device", text: "Battery and motion." },
  { title: "Color", text: "Color profile." },
  { title: "Serial", text: "Body number." },
  { title: "Maker note", text: "Camera notes." },
] as const;

function ScanPicture({ scan }: { scan: ScanState }) {
  if (scan.kind === "upload" && scan.preview) return <img src={scan.preview} alt="" />;
  return <Paper />;
}

function Magnifier({ children }: { children: ReactNode }) {
  return (
    <div className="mag-rig" aria-hidden="true">
      <div className="mag-lens">
        <div className="mag-zoom">{children}</div>
      </div>
      <svg className="mag-frame" viewBox="0 0 160 160">
        <circle cx="64" cy="64" r="40" fill="none" stroke="currentColor" strokeWidth="8" />
        <path
          d="M89.5 89.5 L130 130"
          fill="none"
          stroke="currentColor"
          strokeWidth="15"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}

function OrbitClue({
  index,
  total,
  label,
  value,
  progress,
}: {
  index: number;
  total: number;
  label: string;
  value: string;
  progress: MotionValue<number>;
}) {
  const reduceMotion = useReducedMotion();
  const angle = (index / Math.max(total, 1)) * 360;
  const start = index / Math.max(total, 1);
  const opacity = useTransform(progress, [start, Math.min(1, start + 0.06)], [0, 1]);
  return (
    <div className="orbit-slot" style={{ ["--a" as string]: `${angle}deg` }}>
      <div className="orbit-face">
        <motion.article className="orbit-card" style={{ opacity: reduceMotion ? 1 : opacity }}>
          <h3>{label}</h3>
          <p>{value}</p>
        </motion.article>
      </div>
    </div>
  );
}

const orbitNotes = [
  { label: "Make", value: "Canon" },
  { label: "Model", value: "EOS R6" },
  { label: "Captured", value: "Oct 15 · 4:42 PM" },
  { label: "GPS", value: "38.8977, -77.0365" },
  { label: "Lens", value: "24mm" },
  { label: "ISO", value: "100" },
  { label: "Software", value: "Photoshop 25.1" },
  { label: "Author", value: "Not in the file" },
  { label: "Comment", value: "96 KB of text" },
  { label: "Hidden text", value: "meet at dock 4" },
  { label: "Encoded", value: "base64" },
  { label: "Locked", value: "No key" },
  { label: "File", value: "JPEG · 3.80 MB" },
  { label: "Size", value: "3024 × 4032" },
] as const;

function GithubMark() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 2C6.5 2 2 6.6 2 12.2c0 4.5 2.9 8.3 6.9 9.6.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.2-3.4-1.2-.5-1.1-1.1-1.4-1.1-1.4-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.4 1.1 3 .9.1-.7.4-1.1.7-1.4-2.2-.3-4.6-1.1-4.6-5 0-1.1.4-2 1-2.7-.1-.3-.4-1.3.1-2.7 0 0 .8-.3 2.8 1a9.6 9.6 0 0 1 5.1 0c2-1.3 2.8-1 2.8-1 .5 1.4.2 2.4.1 2.7.6.7 1 1.6 1 2.7 0 3.9-2.3 4.7-4.6 5 .4.3.7 1 .7 1.9v2.8c0 .3.2.6.7.5A10.2 10.2 0 0 0 22 12.2C22 6.6 17.5 2 12 2z"
      />
    </svg>
  );
}

function CommandBlock({ text, live }: { text: string; live: boolean }) {
  const reduceMotion = useReducedMotion();
  const [count, setCount] = useState(0);
  const [copied, setCopied] = useState(false);
  const started = useRef(false);
  useEffect(() => {
    if (!live || started.current) return;
    started.current = true;
    if (reduceMotion) {
      setCount(text.length);
      return;
    }
    let index = 0;
    const timer = window.setInterval(() => {
      index += 1;
      setCount(index);
      if (index >= text.length) window.clearInterval(timer);
    }, 26);
    return () => window.clearInterval(timer);
  }, [live, reduceMotion, text]);
  return (
    <div className="copy-block">
      <pre className={count < text.length ? "is-typing" : undefined}>
        {text.slice(0, count)}
        {count < text.length ? <i /> : null}
      </pre>
      <button
        type="button"
        aria-label={copied ? "Copied" : "Copy"}
        onClick={() => {
          void navigator.clipboard.writeText(text).then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
          });
        }}
      >
        <span className={`copy-swap${copied ? " is-copied" : ""}`}>
          <Clipboard size={15} />
          <Check size={15} />
        </span>
      </button>
    </div>
  );
}

function InlineScan({ scan }: { scan: ScanState }) {
  return (
    <div className="inline-scan">
      <div className="inline-scan-visual mag-stage">
        <div className={`mag-photo${scan.done ? " is-done" : ""}`}>
          <ScanPicture scan={scan} />
          <Magnifier>
            <ScanPicture scan={scan} />
          </Magnifier>
        </div>
      </div>
      <p className="scan-progress">
        {scan.stage} · {scan.progress}%
      </p>
    </div>
  );
}

function StatusMark({ status }: { status: CheckStatus }) {
  return <span className={`status-mark status-${status}`}>{statusLabel(status)}</span>;
}

function CaseBoard({ report }: { report: ScanReport }) {
  return (
    <div className="case-board">
      <p className={`verdict verdict-${report.level.toLowerCase()}`}>
        <strong>{report.level}</strong>
        <span>{report.line}</span>
      </p>
      <dl className="report-rows">
        {report.evidence.map((item) => (
          <div key={item.id}>
            <dt>{item.title}</dt>
            <dd>
              <StatusMark status={item.status} />
              <span>{item.finding}</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function HistoryStrip() {
  const history = useSyncExternalStore(
    subscribeScan,
    () => readScan().history,
    () => readScan().history,
  );
  const navigate = useNavigate();
  if (!history.length) {
    return (
      <section className="history-band">
        <div className="history-copy">
          <h2>Recent photos</h2>
          <p>Photos you scan show up here.</p>
        </div>
      </section>
    );
  }
  const loop = [...history, ...history];
  return (
    <section className="history-band">
      <div className="history-copy">
        <h2>Recent photos</h2>
        <p>Open one to see its report.</p>
      </div>
      <div className="history-marquee">
        <div className="history-row">
          {loop.map((item, index) => (
            <button
              key={`${item.filename}-${item.id}-${index}`}
              type="button"
              onClick={() => {
                selectScan(item.id);
                void navigate({ to: "/report" });
              }}
            >
              {item.preview ? <img src={item.preview} alt="" /> : <span />}
              <strong>{item.filename}</strong>
              <small>{item.level}</small>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

export function ScrollStory() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showDemo, setShowDemo] = useState(true);
  const [demoKind, setDemoKind] = useState<"clean" | "suspicious">("clean");
  const [isProcessing, setIsProcessing] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [folderPath, setFolderPath] = useState("~/Pictures");
  const [scannerBusy, setScannerBusy] = useState(false);
  const [loadLabel, setLoadLabel] = useState("");
  const [loadCount, setLoadCount] = useState<{ done: number; total: number } | null>(null);
  const [loadSettled, setLoadSettled] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [scan, setScan] = useState<ScanState>({
    open: false,
    kind: "demo",
    name: "Sample case",
    preview: null,
    progress: 0,
    stage: "Preparing",
    done: false,
  });
  const navigate = useNavigate();
  const uploadInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const storyRef = useRef<HTMLElement>(null);
  const urls = useRef<string[]>([]);
  const runId = useRef(0);
  const loadStarted = useRef(0);
  const reduceMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: storyRef, offset: ["start start", "end end"] });
  const smoothProgress = useSpring(scrollYProgress, { stiffness: 120, damping: 32, mass: 0.3 });
  const paperFlip = useTransform(smoothProgress, [0.1, 0.22], [0, 180]);
  const introOpacity = useTransform(smoothProgress, [0, 0.04, 0.1], [1, 1, 0]);
  const introEvents = useTransform(smoothProgress, (value) => (value < 0.08 ? "auto" : "none"));
  const cluesOpacity = useTransform(smoothProgress, [0.1, 0.16, 0.24, 0.3], [0, 1, 1, 0]);
  const cluesEvents = useTransform(smoothProgress, (value) =>
    value > 0.16 && value < 0.28 ? "auto" : "none",
  );
  const cardX = useTransform(smoothProgress, [0.26, 0.34], [0, -220]);
  const cardOpacity = useTransform(smoothProgress, [0.26, 0.34], [1, 0]);
  const circleOpacity = useTransform(smoothProgress, [0.36, 0.42, 0.62, 0.7], [0, 1, 1, 0]);
  const circleX = useTransform(smoothProgress, [0.62, 0.7], [0, 0]);
  const circleProgress = useTransform(smoothProgress, [0.42, 0.56], [0, 1]);
  const docsOpacity = useTransform(smoothProgress, [0.74, 0.78, 0.92, 0.96], [0, 1, 1, 0]);
  const docsEvents = useTransform(smoothProgress, (value) =>
    value > 0.78 && value < 0.93 ? "auto" : "none",
  );
  const uploadOpacity = useTransform(smoothProgress, [0.95, 1], [0, 1]);
  const uploadEvents = useTransform(smoothProgress, (value) => (value > 0.97 ? "auto" : "none"));
  const [deck, setDeck] = useState<DeckCard[] | null>(null);
  const [docsLive, setDocsLive] = useState(false);
  useMotionValueEvent(smoothProgress, "change", (value) => {
    if (value > 0.76) setDocsLive(true);
  });
  const circleEvents = useTransform(smoothProgress, (value) =>
    value > 0.4 && value < 0.66 ? "auto" : "none",
  );

  const activeRecord = records.find((record) => record.id === activeId);
  const storyPreview = showDemo ? null : (activeRecord?.preview ?? records.at(-1)?.preview ?? null);
  const dashReport = showDemo
    ? demoKind === "suspicious"
      ? suspiciousCase
      : cleanCase
    : activeRecord?.result
      ? reportFromAnalysis(activeRecord.result, activeRecord.preview)
      : null;
  const goReport = (
    latest = records,
    demoOn = showDemo,
    kind: "clean" | "suspicious" = demoKind,
    currentId: string | null = activeId,
  ) => {
    publishDesk({
      items: latest.map((record) => ({
        id: record.id,
        name: record.file.name,
        preview: record.preview,
        status: record.status,
        ...(record.error ? { error: record.error } : {}),
        report: record.result ? reportFromAnalysis(record.result, record.preview) : null,
      })),
      activeId: demoOn ? null : currentId,
      demo: demoOn ? (kind === "suspicious" ? suspiciousCase : cleanCase) : null,
    });
    const leave = () => {
      void navigate({ to: "/report" });
    };
    if (!reduceMotion && typeof document.startViewTransition === "function") {
      document.startViewTransition(leave);
    } else {
      leave();
    }
  };
  const openReport = () => goReport();
  const openStory = () =>
    window.scrollTo({
      top: (storyRef.current?.offsetTop ?? 0) + (storyRef.current?.offsetHeight ?? 0) * 0.28,
      behavior: reduceMotion ? "instant" : "smooth",
    });
  const revealDashboard = async (
    thisRun: number,
    latest = records,
    demoOn = showDemo,
    currentId: string | null = activeId,
    kind: "clean" | "suspicious" = demoKind,
  ) => {
    await sleep(reduceMotion ? 80 : 420);
    if (thisRun !== runId.current) return;
    setScan((current) => ({ ...current, open: false }));
    goReport(latest, demoOn, kind, currentId);
  };
  const openUpload = () => uploadInput.current?.click();
  const openFolder = () => folderInput.current?.click();
  const beginLoad = (label: string, total: number) => {
    loadStarted.current = Date.now();
    setLoadSettled(false);
    setLoadLabel(label);
    setLoadCount({ done: 0, total });
  };
  const finishLoad = async (total: number) => {
    setLoadCount({ done: total, total });
    const elapsed = Date.now() - loadStarted.current;
    const cinematicMs = 7000;
    const hold = reduceMotion ? 0 : Math.max(0, cinematicMs - elapsed);
    await sleep(hold);
    setLoadSettled(true);
    await sleep(reduceMotion ? 0 : 700);
  };
  const openScannerReport = (batch: Awaited<ReturnType<typeof runDemoBatch>>, title: string) => {
    publishScan(batch, title);
    const leave = () => {
      void navigate({ to: "/report" });
    };
    if (!reduceMotion && typeof document.startViewTransition === "function") {
      document.startViewTransition(leave);
    } else {
      leave();
    }
  };
  const runScannerDemo = async () => {
    setScannerBusy(true);
    setUploadError(null);
    beginLoad("Demo", 11);
    try {
      const batch = await runDemoBatch();
      setDeck(
        (batch.ranking ?? [])
          .filter((entry) => previewSrc(entry))
          .slice(0, 12)
          .map((entry) => ({
            name: entry.filename,
            preview: previewSrc(entry)!,
          })),
      );
      await sleep(reduceMotion ? 0 : 1100);
      await finishLoad(batch.summary?.scanned ?? batch.ranking?.length ?? 11);
      setDeck(null);
      openScannerReport(batch, "Demo");
    } catch (error) {
      setDeck(null);
      setLoadCount(null);
      setUploadError(error instanceof Error ? error.message : "Start the checker, then try again.");
    } finally {
      setScannerBusy(false);
    }
  };
  const runFolderPath = async () => {
    const title = folderLabel(folderPath);
    setScannerBusy(true);
    setUploadError(null);
    beginLoad(title, 0);
    try {
      const batch = await scanFolderPath(folderPath, true);
      const total = batch.summary?.scanned ?? batch.ranking?.length ?? 0;
      await finishLoad(total);
      openScannerReport(batch, title);
    } catch (error) {
      setLoadCount(null);
      setUploadError(error instanceof Error ? error.message : "That folder could not be scanned.");
    } finally {
      setScannerBusy(false);
    }
  };
  const sendToScanner = async (list: FileList | File[] | null, items?: DataTransferItemList) => {
    const incoming = Array.isArray(list)
      ? list
      : await collectFiles(list ?? new DataTransfer().files, items);
    const images = incoming.filter(looksLikeImage);
    if (!images.length) {
      setUploadError("No readable images were found in that selection.");
      return;
    }
    const named = images[0] as File & { webkitRelativePath?: string };
    const title =
      named.webkitRelativePath?.split("/")[0] ||
      (images.length === 1 ? images[0]!.name : `${images.length} photos`);
    const previews = images.map((file) => URL.createObjectURL(file));
    const cards: DeckCard[] = images
      .slice(0, 8)
      .map((file, index) => ({ name: file.name, preview: previews[index]! }));
    setDeck(cards);
    setScannerBusy(true);
    setUploadError(null);
    beginLoad(title, images.length);
    try {
      const batch = await scanImagesWithProgress(images, previews, (done, total) =>
        setLoadCount({ done, total }),
      );
      const previewByPath = new Map(
        images.map((file, index) => [
          (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
          previews[index]!,
        ]),
      );
      for (const entry of batch.ranking ?? []) {
        const matched =
          previewByPath.get(entry.filename) ??
          previewByPath.get(entry.filename.split("/").pop() || "");
        if (!entry.local_preview && matched) entry.local_preview = matched;
      }
      if (!batch.ranking?.length)
        throw new Error(batch.skipped?.[0]?.reason || "The images could not be read.");
      await finishLoad(images.length);
      setDeck(null);
      openScannerReport(batch, title);
    } catch (error) {
      setDeck(null);
      setUploadError(error instanceof Error ? error.message : "The images could not be read.");
    } finally {
      setScannerBusy(false);
    }
  };
  const startDemo = async (kind: "clean" | "suspicious") => {
    if (isProcessing) return;
    const thisRun = ++runId.current;
    const sample = kind === "suspicious" ? suspiciousCase : cleanCase;
    setDemoKind(kind);
    setShowDemo(true);
    setActiveId(null);
    window.scrollTo({ top: 0, behavior: reduceMotion ? "instant" : "smooth" });
    setScan({
      open: true,
      kind: "demo",
      name: sample.fileName,
      preview: null,
      progress: 0,
      stage: "Looking at the picture",
      done: false,
    });
    const timer = window.setInterval(
      () =>
        setScan((current) => {
          const progress = Math.min(92, current.progress + 3);
          const stage =
            progress < 30
              ? "Looking at the picture"
              : progress < 55
                ? "Checking for extra data on the end"
                : progress < 80
                  ? "Reading notes stored in the file"
                  : "Reading notes in the file";
          return { ...current, progress, stage };
        }),
      70,
    );
    await sleep(reduceMotion ? 400 : 2300);
    window.clearInterval(timer);
    if (thisRun !== runId.current) return;
    setScan((current) => ({ ...current, progress: 100, stage: "Opening the report", done: true }));
    await revealDashboard(thisRun, records, true, null, kind);
  };

  const processRecords = async (newRecords: RecordItem[]) => {
    const thisRun = ++runId.current;
    setIsProcessing(true);
    for (const record of newRecords) {
      if (thisRun !== runId.current) break;
      setActiveId(record.id);
      setShowDemo(false);
      setScan({
        open: true,
        kind: "upload",
        name: record.file.name,
        preview: record.preview,
        progress: 0,
        stage: "Reading file bytes",
        done: false,
      });
      const timer = window.setInterval(
        () => setScan((current) => ({ ...current, progress: Math.min(92, current.progress + 2) })),
        50,
      );
      try {
        const [analysis] = await Promise.all([
          analyzeImage(record.file, (stage) =>
            setScan((current) => ({
              ...current,
              stage: stage.includes("pixel")
                ? "Looking at the picture"
                : stage.includes("fingerprint")
                  ? "Making a fingerprint of this file"
                  : stage.includes("metadata")
                    ? "Checking the end of the file and its notes"
                    : "Reading the file",
            })),
          ),
          sleep(reduceMotion ? 200 : 2300),
        ]);
        window.clearInterval(timer);
        if (thisRun !== runId.current) break;
        let ready: RecordItem[] = [];
        setRecords((current) => {
          ready = current.map((item) =>
            item.id === record.id ? { ...item, result: analysis, status: "ready" as const } : item,
          );
          return ready;
        });
        setScan((current) => ({
          ...current,
          progress: 100,
          stage: "Opening the report",
          done: true,
        }));
        if (record.id === newRecords[newRecords.length - 1]?.id)
          await revealDashboard(thisRun, ready, false, record.id);
      } catch (error) {
        window.clearInterval(timer);
        if (thisRun !== runId.current) break;
        const message = error instanceof Error ? error.message : "This image could not be read.";
        let failed: RecordItem[] = [];
        setRecords((current) => {
          failed = current.map((item) =>
            item.id === record.id ? { ...item, error: message, status: "error" as const } : item,
          );
          return failed;
        });
        setScan((current) => ({
          ...current,
          progress: 100,
          stage: "Could not read this image",
          done: true,
        }));
        if (record.id === newRecords[newRecords.length - 1]?.id)
          await revealDashboard(thisRun, failed, false, record.id);
      }
      if (newRecords.length > 1) await sleep(700);
    }
    if (thisRun === runId.current) setIsProcessing(false);
  };

  const addFiles = async (list: FileList | null, items?: DataTransferItemList) => {
    if ((!list || !list.length) && !items?.length) return;
    if (isProcessing) {
      setUploadError("Wait for the current scan to finish.");
      return;
    }
    const incoming = await collectFiles(list ?? new DataTransfer().files, items);
    const images: File[] = [];
    for (const file of incoming) {
      if (await sniffImage(file)) images.push(file);
    }
    if (!images.length) {
      setUploadError("No images in that drop.");
      return;
    }
    const unique = images.filter(
      (file) =>
        !records.some(
          (item) =>
            item.file.name === file.name &&
            item.file.size === file.size &&
            item.file.lastModified === file.lastModified,
        ),
    );
    if (records.length + unique.length > IMAGE_CAP) {
      setUploadError(`Up to ${IMAGE_CAP} images.`);
      return;
    }
    if (!unique.length) {
      setUploadError("Already added.");
      return;
    }
    const next = unique.map((file) => {
      const preview = URL.createObjectURL(file);
      urls.current.push(preview);
      return { id: crypto.randomUUID(), file, preview, status: "working" as const };
    });
    setUploadError(null);
    setRecords((current) => [...current, ...next]);
    setActiveId(next[0]!.id);
    setShowDemo(false);
    void processRecords(next);
  };

  const removeRecord = (id: string) => {
    const removed = records.find((record) => record.id === id);
    if (removed) {
      URL.revokeObjectURL(removed.preview);
      urls.current = urls.current.filter((url) => url !== removed.preview);
    }
    const remaining = records.filter((record) => record.id !== id);
    setRecords(remaining);
    if (removed?.preview === scan.preview) setScan((current) => ({ ...current, open: false }));
    if (activeId === id) {
      setActiveId(remaining[0]?.id ?? null);
      setShowDemo(!remaining.length);
    }
  };
  const restart = () => {
    runId.current++;
    urls.current.forEach((url) => URL.revokeObjectURL(url));
    urls.current = [];
    setRecords([]);
    setActiveId(null);
    setShowDemo(true);
    setIsProcessing(false);
    setUploadError(null);
    setScan((current) => ({ ...current, open: false }));
    window.scrollTo({ top: 0, behavior: reduceMotion ? "instant" : "smooth" });
  };

  const slide = (x: number, y = 0) =>
    reduceMotion
      ? {}
      : {
          initial: { opacity: 0, x, y },
          whileInView: { opacity: 1, x: 0, y: 0 },
          viewport: { once: true, amount: 0.45 },
          transition: { duration: 0.65, ease: [0.16, 1, 0.3, 1] as const },
        };

  return (
    <div className="app-shell" data-theme={theme}>
      <header className="site-nav">
        <a href="#top" className="brand" aria-label="Metadex">
          METADEX
        </a>
        <div className="nav-controls">
          <Link to="/search" className="nav-link">
            Image search
          </Link>
          <a
            className="theme-toggle"
            href="https://github.com/mfelashry/Metadex"
            target="_blank"
            rel="noreferrer"
            aria-label="GitHub"
          >
            <GithubMark />
          </a>
          <button
            className="theme-toggle"
            type="button"
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
        </div>
      </header>

      <main id="top">
        <section
          className="story-section"
          ref={storyRef}
          aria-label="Scroll through the layers of an image"
        >
          <div className="story-sticky">
            <motion.div
              className="stage-card"
              style={{ opacity: cardOpacity, x: reduceMotion ? 0 : cardX }}
            >
              <div className="story-visual">
                <div className={`story-artwork${scan.open ? " is-scanning" : ""}`}>
                  {scan.open ? (
                    <InlineScan scan={scan} />
                  ) : (
                    <motion.div
                      className="flip-card"
                      style={{ rotateY: reduceMotion ? 0 : paperFlip }}
                    >
                      <div className="flip-face flip-front demo-photo">
                        {storyPreview ? (
                          <img src={storyPreview} alt="Your uploaded image" />
                        ) : (
                          <Paper />
                        )}
                        <Magnifier>
                          {storyPreview ? (
                            <img src={storyPreview} alt="" />
                          ) : (
                            <Paper />
                          )}
                        </Magnifier>
                      </div>
                      <div className="flip-face flip-back">
                        <p>Inside the file</p>
                        <ul>
                          {orbitNotes.map((note) => (
                            <li key={note.label}>
                              <span>{note.label}</span>
                              <strong>{note.value}</strong>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </motion.div>
                  )}
                </div>
              </div>
            </motion.div>
            <motion.div
              className="stage-checks"
              style={{
                opacity: circleOpacity,
                x: reduceMotion ? 0 : circleX,
                pointerEvents: circleEvents,
              }}
            >
              <div className="orbit">
                <p>Checks</p>
                <div className="orbit-spin">
                  {checks.map((item, index) => (
                    <OrbitClue
                      key={item.title}
                      index={index}
                      total={checks.length}
                      label={item.title}
                      value={item.text}
                      progress={circleProgress}
                    />
                  ))}
                </div>
              </div>
            </motion.div>
            <motion.div
              className="stage-docs docs-block"
              id="docs"
              style={{
                opacity: docsOpacity,
                x: 0,
                pointerEvents: docsEvents,
              }}
            >
              <h2>From the terminal</h2>
              <p>Install the checker from this repo, then scan a photo or a folder.</p>
              <CommandBlock
                live={docsLive}
                text={"python3 -m pip install -e packages/metadex-py"}
              />
              <div className="terminal-examples">
                <p>One file</p>
                <CommandBlock live={docsLive} text={"metadex ./photo.jpg"} />
                <p>A folder</p>
                <CommandBlock live={docsLive} text={"metadex ~/Pictures"} />
              </div>
            </motion.div>
            <motion.div
              className="stage-upload"
              style={{ opacity: uploadOpacity, pointerEvents: uploadEvents }}
            >
              <h2>Scan photos</h2>
              <p>Choose images or a folder. See each photo as it is checked.</p>
              <div className="hero-actions">
                <button
                  className="primary-action"
                  type="button"
                  onClick={openUpload}
                  disabled={scannerBusy}
                >
                  <Upload size={17} /> Choose images
                </button>
                <button
                  className="secondary-action"
                  type="button"
                  onClick={openFolder}
                  disabled={scannerBusy}
                >
                  Choose a folder
                </button>
              </div>
              <button
                className="scan-demo-link"
                type="button"
                onClick={() => void runScannerDemo()}
                disabled={scannerBusy}
              >
                Try the suspicious sample scan →
              </button>
              {uploadError ? <p className="error-message">{uploadError}</p> : null}
            </motion.div>
            <div className="story-content">
              <motion.div
                className="story-panel story-panel-intro"
                style={{ opacity: introOpacity, pointerEvents: introEvents }}
              >
                <h1>
                  Look closer<span>.</span>
                </h1>
                <p>Drop a photo or a folder. The file stays here.</p>
                <div className="hero-actions">
                  <button
                    className="primary-action"
                    type="button"
                    onClick={openUpload}
                    disabled={isProcessing}
                  >
                    <Upload size={17} /> Choose an image
                  </button>
                  <button
                    className="secondary-action"
                    type="button"
                    onClick={openFolder}
                    disabled={isProcessing}
                  >
                    Choose a folder
                  </button>
                  <button
                    className="secondary-action"
                    type="button"
                    onClick={() => void navigate({ to: "/search" })}
                    disabled={isProcessing}
                  >
                    Search a collection
                  </button>
                </div>
                {uploadError && (
                  <p className="error-message" role="alert">
                    {uploadError}
                  </p>
                )}
                <button className="story-scroll-cue" type="button" onClick={openStory}>
                  Scroll to investigate <ArrowDown size={15} />
                </button>
              </motion.div>
              <motion.div
                className="story-panel story-panel-caption"
                style={{ opacity: cluesOpacity, pointerEvents: "none" }}
              >
                <span className="eyebrow">{storyCaption.label}</span>
                <h2>{storyCaption.title}</h2>
                <p>{storyCaption.body}</p>
              </motion.div>
              <motion.button
                className="story-report-link story-report-cta"
                type="button"
                onClick={openReport}
                style={{ opacity: cluesOpacity, pointerEvents: cluesEvents }}
              >
                Open the case report <ArrowRight size={16} />
              </motion.button>
            </div>
          </div>
        </section>
      </main>
      <footer>
        <span className="brand" aria-label="Metadex">
          METADEX
        </span>
        <p>Look closer. Decide with evidence.</p>
        <button type="button" onClick={restart}>
          Back to top ↑
        </button>
      </footer>
      <input
        ref={uploadInput}
        className="visually-hidden"
        type="file"
        accept="image/*"
        multiple
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          void sendToScanner(files);
        }}
      />
      <input
        ref={folderInput}
        className="visually-hidden"
        type="file"
        multiple
        // @ts-expect-error nonstandard folder picker
        webkitdirectory=""
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          void sendToScanner(files);
        }}
      />
      {(deck || scannerBusy || isProcessing) && (
        <FolderScan cards={deck} label={loadLabel} count={loadCount} settled={loadSettled} />
      )}
    </div>
  );
}
