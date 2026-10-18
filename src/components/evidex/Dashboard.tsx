import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowRight, Check, Clock, FileUp, Minus, Moon, Sun, TriangleAlert, Upload } from "lucide-react";
import {
  analyzeImage,
  MAX_IMAGE_BYTES,
  sniffImage,
} from "@/components/evidex/analyzeImage";
import {
  cleanCase,
  reportFromAnalysis,
  statusLabel,
  suspiciousCase,
  type CheckStatus,
  type Evidence,
  type ScanReport,
} from "@/lib/scan-report";

type Phase = "scanning" | "results" | "error";

type Stage = {
  phase: Phase;
  name: string;
  preview: string | null;
  progress: number;
  step: string;
  report: ScanReport | null;
  error: string | null;
  position: number;
  total: number;
};

const steps = ["Appended data", "Pixel bits", "Metadata", "Activity"] as const;

const emptyStage = (): Stage => ({
  phase: "scanning",
  name: "",
  preview: null,
  progress: 0,
  step: steps[0],
  report: null,
  error: null,
  position: 1,
  total: 1,
});

function Paper() {
  return (
    <div className="paper-art sample-image-art dash-paper" role="img" aria-label="Illustrated sample image">
      <svg viewBox="0 0 320 420" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <rect width="320" height="420" fill="#d9d9d9" />
        <rect width="320" height="248" fill="#f3f3f3" />
        <circle cx="246" cy="72" r="26" fill="#fff" />
        <rect x="28" y="96" width="86" height="162" fill="#3c3c3c" />
        <rect x="42" y="114" width="16" height="18" fill="#f3f3f3" />
        <rect x="68" y="114" width="16" height="18" fill="#f3f3f3" />
        <rect x="42" y="146" width="16" height="18" fill="#f3f3f3" />
        <rect x="68" y="146" width="16" height="18" fill="#f3f3f3" />
        <rect x="42" y="178" width="16" height="18" fill="#f3f3f3" />
        <rect x="68" y="178" width="16" height="18" fill="#f3f3f3" />
        <rect x="42" y="210" width="16" height="18" fill="#f3f3f3" />
        <rect x="68" y="210" width="16" height="18" fill="#f3f3f3" />
        <rect x="138" y="146" width="132" height="112" fill="#6e6e6e" />
        <rect x="154" y="164" width="22" height="22" fill="#f3f3f3" />
        <rect x="188" y="164" width="22" height="22" fill="#f3f3f3" />
        <rect x="222" y="164" width="22" height="22" fill="#f3f3f3" />
        <rect x="154" y="200" width="22" height="22" fill="#f3f3f3" />
        <rect x="188" y="200" width="22" height="22" fill="#f3f3f3" />
        <rect x="222" y="200" width="22" height="22" fill="#f3f3f3" />
        <rect y="248" width="320" height="172" fill="#161616" />
        <rect x="18" y="242" width="168" height="12" fill="#2a2a2a" />
        <rect x="168" y="188" width="8" height="66" fill="#111" />
        <circle cx="172" cy="180" r="11" fill="#fff" />
        <rect y="286" width="320" height="4" fill="#f3f3f3" />
        <rect y="328" width="320" height="3" fill="#8a8a8a" />
      </svg>
    </div>
  );
}

function StatusMark({ status }: { status: CheckStatus }) {
  const Icon = status === "clean" ? Check : status === "suspicious" ? TriangleAlert : status === "review" ? Minus : Clock;
  return (
    <span className={`status-mark status-${status}`}>
      <Icon size={14} aria-hidden="true" />
      {statusLabel(status)}
    </span>
  );
}

function EvidenceCard({ item }: { item: Evidence }) {
  return (
    <article className="evidence-card">
      <div className="evidence-card-top">
        <h3>{item.title}</h3>
        <StatusMark status={item.status} />
      </div>
      <strong>{item.finding}</strong>
    </article>
  );
}

function ReportBody({ report }: { report: ScanReport }) {
  return (
    <div className="report-board">
      <div className="suspicion-block">
        <strong>{report.level}</strong>
        <p>{report.line}</p>
      </div>
      <div className="evidence-grid">
        {report.evidence.map((item) => (
          <EvidenceCard key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

export function Dashboard() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [report, setReport] = useState<ScanReport | null>(null);
  const [stage, setStage] = useState<Stage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);
  const urls = useRef<string[]>([]);
  const runId = useRef(0);
  const releaseRef = useRef<(() => void) | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const reduceMotion = useReducedMotion();

  useEffect(
    () => () => {
      urls.current.forEach((url) => URL.revokeObjectURL(url));
      releaseRef.current?.();
    },
    [],
  );

  const dismiss = () => {
    const release = releaseRef.current;
    releaseRef.current = null;
    release?.();
  };

  const waitForDismiss = () =>
    new Promise<void>((resolve) => {
      releaseRef.current = resolve;
    });

  const playSteps = async (thisRun: number, preview: string | null, name: string, position: number, total: number) => {
    setStage({
      ...emptyStage(),
      name,
      preview,
      position,
      total,
      step: steps[0],
    });
    const ticks = reduceMotion ? 4 : 24;
    for (let tick = 1; tick <= ticks; tick++) {
      if (thisRun !== runId.current) return false;
      const progress = Math.round((tick / ticks) * 100);
      const step = steps[Math.min(steps.length - 1, Math.floor(((tick - 1) / ticks) * steps.length))]!;
      setStage((current) =>
        current ? { ...current, progress, step, name, preview, position, total } : current,
      );
      await sleep(reduceMotion ? 40 : 70);
    }
    return thisRun === runId.current;
  };

  const showReport = async (next: ScanReport, thisRun: number) => {
    if (thisRun !== runId.current) return;
    setReport((current) => {
      if (current?.preview && current.preview !== next.preview) {
        URL.revokeObjectURL(current.preview);
        urls.current = urls.current.filter((url) => url !== current.preview);
      }
      return next;
    });
    setStage((current) =>
      current
        ? { ...current, phase: "results", progress: 100, step: "Report ready", report: next }
        : current,
    );
    await waitForDismiss();
  };

  const openDemo = async (sample: ScanReport, opener: HTMLElement | null) => {
    if (busy) return;
    openerRef.current = opener;
    const thisRun = ++runId.current;
    setBusy(true);
    setError(null);
    const finished = await playSteps(thisRun, sample.preview, sample.fileName, 1, 1);
    if (finished) await showReport(sample, thisRun);
    if (thisRun === runId.current) {
      setBusy(false);
      setStage(null);
      openerRef.current?.focus();
    }
  };

  const addFiles = async (list: FileList | null) => {
    if (!list?.length || busy) {
      if (busy) setError("Wait for the current scan to finish.");
      return;
    }
    openerRef.current = uploadInput.current;
    const incoming = Array.from(list);
    const accepted: File[] = [];
    const skipped: string[] = [];
    for (const file of incoming) {
      if (file.size > MAX_IMAGE_BYTES) {
        skipped.push(`${file.name} is over 40 MB`);
        continue;
      }
      if (await sniffImage(file)) accepted.push(file);
      else skipped.push(file.name);
    }
    if (!accepted.length) {
      setError(skipped.length ? `Skipped ${skipped.join(", ")}.` : "Choose an image file.");
      return;
    }
    setError(skipped.length ? `Skipped ${skipped.join(", ")}.` : null);
    const thisRun = ++runId.current;
    setBusy(true);
    for (let index = 0; index < accepted.length; index++) {
      const file = accepted[index]!;
      if (thisRun !== runId.current) break;
      const preview = URL.createObjectURL(file);
      urls.current.push(preview);
      let failure: unknown = null;
      const analysisPromise = analyzeImage(file).catch((reason: unknown) => {
        failure = reason;
        return null;
      });
      const played = await playSteps(thisRun, preview, file.name, index + 1, accepted.length);
      if (!played || thisRun !== runId.current) break;
      const analysis = await analysisPromise;
      if (thisRun !== runId.current) break;
      if (!analysis) {
        const message = failure instanceof Error ? failure.message : "This image could not be read.";
        setStage((current) =>
          current
            ? { ...current, phase: "error", progress: 100, step: "Could not read image", error: message }
            : current,
        );
        await waitForDismiss();
        continue;
      }
      await showReport(reportFromAnalysis(analysis, preview), thisRun);
    }
    if (thisRun === runId.current) {
      setBusy(false);
      setStage(null);
      openerRef.current?.focus();
    }
  };

  return (
    <div className="app-shell" data-theme={theme}>
      <header className="site-nav">
        <a href="#top" className="brand" aria-label="Metadex">
          METADEX
        </a>
        <div className="nav-controls">
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
      <main id="top" className="dash">
        <section className="dash-intro" aria-labelledby="dash-title">
          <span className="eyebrow">Local image check</span>
          <h1 id="dash-title">
            Look closer<span>.</span>
          </h1>
          <p>
            Choose a photo. The file stays on this computer. The report is a claim check, not proof.
          </p>
          <div className="dash-actions">
            <button className="primary-action" type="button" onClick={() => uploadInput.current?.click()} disabled={busy}>
              <Upload size={16} aria-hidden="true" /> Upload an image
            </button>
            <button className="secondary-action" type="button" onClick={(event) => void openDemo(cleanCase, event.currentTarget)} disabled={busy}>
              Clean demo
            </button>
            <button className="secondary-action" type="button" onClick={(event) => void openDemo(suspiciousCase, event.currentTarget)} disabled={busy}>
              Suspicious demo
            </button>
          </div>
          <p className="dash-note">Images stay on this computer. Up to 40 MB. JPEG, PNG, WebP, and other image files.</p>
          {error && (
            <p className="error-message" role="alert">
              {error}
            </p>
          )}
        </section>

        <div
          className="upload-drop dash-drop"
          data-dragging={dragging}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void addFiles(event.dataTransfer.files);
          }}
        >
          <FileUp size={22} strokeWidth={1.5} aria-hidden="true" />
          <strong>Drop an image here</strong>
          <span>or choose one from your device</span>
          <button type="button" onClick={() => uploadInput.current?.click()} disabled={busy}>
            Choose image
          </button>
        </div>

        {report && (
          <section className="dash-report" aria-labelledby="report-heading">
            <div className="dash-report-heading">
              <div>
                <span className="eyebrow">{report.source === "demo" ? "Demo case" : "Your image · browser preview"}</span>
                <h2 id="report-heading">{report.fileName}</h2>
              </div>
              {report.source === "demo" && (
                <button
                  className="text-action"
                  type="button"
                  onClick={(event) =>
                    void openDemo(
                      report.fileName === suspiciousCase.fileName ? suspiciousCase : cleanCase,
                      event.currentTarget,
                    )
                  }
                  disabled={busy}
                >
                  Play again <ArrowRight size={15} aria-hidden="true" />
                </button>
              )}
            </div>
            <div className="dash-report-layout">
              <div className="dash-visual">{report.preview ? <img src={report.preview} alt="" /> : <Paper />}</div>
              <ReportBody report={report} />
            </div>
          </section>
        )}
      </main>
      <input
        ref={uploadInput}
        className="visually-hidden"
        type="file"
        accept="image/*,.jpg,.jpeg,.png,.gif,.webp,.bmp,.heic,.heif,.avif"
        multiple
        onChange={(event) => {
          void addFiles(event.target.files);
          event.target.value = "";
        }}
      />
      <AnimatePresence>
        {stage && (
          <Reveal
            key={`${stage.name}-${stage.position}`}
            stage={stage}
            reduceMotion={Boolean(reduceMotion)}
            onAdvance={dismiss}
            onCancel={() => {
              runId.current += 1;
              dismiss();
              setBusy(false);
              setStage(null);
              openerRef.current?.focus();
            }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

function Reveal({
  stage,
  reduceMotion,
  onAdvance,
  onCancel,
}: {
  stage: Stage;
  reduceMotion: boolean;
  onAdvance: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const results = stage.phase === "results" && stage.report;
  const failed = stage.phase === "error";

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  useEffect(() => {
    if (results || failed) closeRef.current?.focus();
    else dialogRef.current?.focus();
  }, [results, failed]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const root = dialogRef.current;
    if (!root) return;
    const items = [...root.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea")].filter(
      (item) => !item.hasAttribute("disabled"),
    );
    if (!items.length) return;
    const first = items[0]!;
    const last = items[items.length - 1]!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const closeLabel = failed ? "Close" : stage.position < stage.total ? "Next image" : "Back to the dashboard";

  return (
    <motion.div
      ref={dialogRef}
      className="reveal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reveal-title"
      tabIndex={-1}
      onKeyDown={onKeyDown}
      initial={reduceMotion ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.28 }}
    >
      <div className="reveal-bar">
        <span className="brand" aria-label="Metadex">
          METADEX
        </span>
        <span>
          {stage.position} of {stage.total}
        </span>
        {(results || failed) && (
          <button ref={closeRef} className="primary-action reveal-close" type="button" onClick={onAdvance}>
            {closeLabel} <ArrowRight size={15} aria-hidden="true" />
          </button>
        )}
      </div>
      <div className={`reveal-layout${results || failed ? " is-open" : ""}`}>
        <motion.div
          className="reveal-visual"
          initial={reduceMotion ? false : { scale: 0.94, opacity: 0.6 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
        >
          {stage.preview ? <img src={stage.preview} alt="" /> : <Paper />}
          {stage.phase === "scanning" && <div className="reveal-scanline" aria-hidden="true" />}
        </motion.div>
        {results && stage.report ? (
          <motion.div
            className="reveal-copy"
            initial="hidden"
            animate="show"
            variants={{
              hidden: {},
              show: { transition: { staggerChildren: reduceMotion ? 0 : 0.06, delayChildren: reduceMotion ? 0 : 0.12 } },
            }}
          >
            <motion.h2 id="reveal-title" variants={tile}>
              {stage.report.fileName}
            </motion.h2>
            <motion.div variants={tile}>
              <ReportBody report={stage.report} />
            </motion.div>
          </motion.div>
        ) : failed ? (
          <div className="reveal-copy">
            <h2 id="reveal-title">This image could not be read.</h2>
            <p role="alert">{stage.error}</p>
          </div>
        ) : (
          <div className="reveal-copy reveal-progress-copy">
            <h2 id="reveal-title" aria-live="polite">
              {stage.step}
            </h2>
            <div
              className="scan-meter"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={stage.progress}
              aria-label={stage.step}
            >
              <i style={{ width: `${stage.progress}%` }} />
            </div>
            <ol className="reveal-steps">
              {steps.map((step) => (
                <li key={step} aria-current={step === stage.step ? "step" : undefined}>
                  {step}
                </li>
              ))}
            </ol>
            <p>Reading on this computer. The file is not uploaded.</p>
          </div>
        )}
      </div>
    </motion.div>
  );
}

const tile = {
  hidden: { opacity: 0, y: 28 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] as const } },
};
