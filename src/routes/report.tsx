import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ChevronDown, History, Moon, Sparkles, Sun } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { publishDesk, readDesk, selectDeskItem, subscribeDesk } from "@/lib/report-desk";
import { statusLabel, type CheckStatus } from "@/lib/scan-report";
import { explainFinding, levelMark, previewSrc, type RankedImage } from "@/lib/stillframe";
import { openSaved, readScan, selectScan, subscribeScan } from "@/lib/stillframe-store";

export const Route = createFileRoute("/report")({
  head: () => ({
    meta: [{ title: "Metadex" }],
  }),
  component: ReportPage,
});

function useScan() {
  return useSyncExternalStore(subscribeScan, readScan, readScan);
}

function fileSize(bytes?: number) {
  if (!bytes) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function ScannerReport() {
  const scan = useScan();
  const batch = scan.batch;
  const ranking = batch?.ranking ?? [];
  const selected = ranking.find((item) => item.id === scan.selectedId) ?? ranking[0] ?? null;
  const suspicious = ranking.filter((item) => item.level === "high" || item.level === "suspicious");
  const normal = ranking.filter((item) => item.level !== "high" && item.level !== "suspicious");
  const [open, setOpen] = useState({ suspicious: true, normal: suspicious.length === 0 });

  useEffect(() => {
    setOpen({ suspicious: true, normal: suspicious.length === 0 });
  }, [batch?.scan_id, suspicious.length]);

  if (!batch) return null;

  return (
    <div className="scanner-report">
      <p className="visually-hidden" aria-live="polite">
        {batch.summary?.headline}
      </p>
      <p className="scanner-headline">{batch.summary?.headline}</p>
      <p className="scanner-meta">
        {batch.source?.type === "browser"
          ? "Checked in your browser"
          : "Checked by the local forensic backend"}
      </p>
      <div className="scanner-split">
        <div className="scanner-groups">
          <ResultGroup
            title="Suspicious"
            items={suspicious}
            open={open.suspicious}
            onToggle={() => setOpen((value) => ({ ...value, suspicious: !value.suspicious }))}
            selectedId={selected?.id}
          />
          <ResultGroup
            title="Normal"
            items={normal}
            open={open.normal}
            onToggle={() => setOpen((value) => ({ ...value, normal: !value.normal }))}
            selectedId={selected?.id}
          />
        </div>
        <AnimatePresence mode="wait" initial={false}>
          {selected && <ImageDetail key={selected.id} entry={selected} />}
        </AnimatePresence>
      </div>
      <details className="scanner-about">
        <summary>About this scan</summary>
        <p>{batch.limitations || "The result is a guide for review, not proof of intent."}</p>
        {(batch.skipped?.length ?? 0) > 0 && (
          <p>{batch.skipped?.length} files could not be read.</p>
        )}
      </details>
    </div>
  );
}

function displayName(entry: RankedImage) {
  return /^[0-9a-f]{8}-[0-9a-f-]{20,}\./i.test(entry.filename)
    ? `Photo ${entry.rank}`
    : entry.filename;
}

function ResultGroup({
  title,
  items,
  open,
  onToggle,
  selectedId,
}: {
  title: "Suspicious" | "Normal";
  items: RankedImage[];
  open: boolean;
  onToggle: () => void;
  selectedId: string | undefined;
}) {
  return (
    <section className="scanner-group">
      <button
        className="scanner-group-toggle"
        type="button"
        aria-expanded={open}
        onClick={onToggle}
      >
        <span>
          {title} <strong>{items.length}</strong>
        </span>
        <ChevronDown size={18} aria-hidden="true" />
      </button>
      {open && (
        <div className="scanner-list" role="listbox" aria-label={title}>
          {items.length === 0 && <p className="empty-files">No {title.toLowerCase()} photos.</p>}
          {items.map((item, index) => (
            <button
              key={item.id}
              type="button"
              role="option"
              aria-selected={item.id === selectedId}
              className={item.id === selectedId ? "active" : ""}
              style={{ animationDelay: `${Math.min(index, 12) * 35}ms` }}
              onClick={() => selectScan(item.id)}
            >
              <Thumb entry={item} />
              <span className="scanner-list-copy">
                <strong>{displayName(item)}</strong>
                <small>{levelMark(item.level)}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function Thumb({ entry }: { entry: RankedImage }) {
  const src = previewSrc(entry);
  return src ? (
    <img className="scanner-thumb" src={src} alt="" />
  ) : (
    <span className="scanner-thumb" />
  );
}

function ImageDetail({ entry }: { entry: RankedImage }) {
  const report = entry.report;
  const messages = entry.messages ?? report?.messages_found ?? [];
  const src = previewSrc(entry);
  const uniqueMessages = [
    ...new Map(
      messages.filter((message) => message.text).map((message) => [message.text!.trim(), message]),
    ).values(),
  ];
  const fields = (report?.image_analysis?.metadata_messages?.fields ?? []).filter(
    (field) => field.flagged || field.decoded || field.preview,
  );
  return (
    <motion.article
      className="scanner-detail"
      aria-busy="false"
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.28 }}
    >
      {src ? <img className="scanner-hero" src={src} alt={entry.filename} /> : null}
      <div className="scanner-detail-heading">
        <h1>{displayName(entry)}</h1>
        <span className={`scanner-level level-${entry.level}`}>{levelMark(entry.level)}</span>
      </div>
      {displayName(entry) !== entry.filename && (
        <p className="scanner-original-name" title={entry.filename}>
          {entry.filename}
        </p>
      )}
      <p className="file-facts">
        {[
          entry.format,
          fileSize(entry.size_bytes),
          entry.width && entry.height ? `${entry.width} × ${entry.height}` : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <section className="scanner-finding">
        <h2>What we found</h2>
        <p>
          {entry.top_reasons?.[0] ||
            (entry.level === "none"
              ? "No hidden-data indicators found in this image."
              : entry.headline || "This image needs a closer look.")}
        </p>
      </section>
      {uniqueMessages.length > 0 && (
        <section className="scanner-messages">
          <h2>Recovered text</h2>
          {uniqueMessages.map((message) => (
            <blockquote key={`${message.where}-${message.text}`}>
              <p>{message.text}</p>
              <footer>
                {message.where}
                {message.encoding && message.encoding !== "utf-8" ? ` · ${message.encoding}` : ""}
              </footer>
            </blockquote>
          ))}
        </section>
      )}
      <GeminiExplanation entry={entry} />
      {(fields.length > 0 ||
        (entry.top_reasons?.length ?? 0) > 1 ||
        (report?.activity_correlation?.timeline?.length ?? 0) > 0) && (
        <details className="scanner-technical">
          <summary>More details</summary>
          {(entry.top_reasons ?? []).slice(1, 5).map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
          {fields.slice(0, 8).map((field) => (
            <p key={field.field}>
              <strong>{field.field}</strong> {field.decoded || field.preview}
            </p>
          ))}
          {(report?.activity_correlation?.timeline ?? []).slice(0, 4).map((event, index) => (
            <p key={`${event.timestamp}-${index}`}>
              {event.process_name} · {event.event_type}
            </p>
          ))}
        </details>
      )}
    </motion.article>
  );
}

function GeminiExplanation({ entry }: { entry: RankedImage }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const explain = async () => {
    setBusy(true);
    setError("");
    try {
      setText(await explainFinding(entry));
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not get an explanation right now.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="scanner-gemini">
      <div>
        <Sparkles size={18} aria-hidden="true" />
        <h2>Plain-language explanation</h2>
      </div>
      <p>
        Ask Gemini to explain these finding labels. Your photo and recovered text stay on this
        computer.
      </p>
      <button type="button" disabled={busy} onClick={() => void explain()}>
        {busy ? "Explaining…" : "Explain with Gemini"}
      </button>
      {text && <p className="scanner-gemini-answer">{text}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

function encodeText(value: string) {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function decodeText(value: string) {
  const binary = atob(value.trim());
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function useDesk() {
  return useSyncExternalStore(subscribeDesk, readDesk, readDesk);
}

function ReportPage() {
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, []);
  const scan = useScan();
  const desk = useDesk();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [historyOpen, setHistoryOpen] = useState(false);
  const navigate = useNavigate();
  const reduceMotion = useReducedMotion();
  const goHome = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return;
    if (reduceMotion || typeof document.startViewTransition !== "function") return;
    event.preventDefault();
    document.documentElement.dataset["nav"] = "back";
    const change = document.startViewTransition(() => navigate({ to: "/" }));
    void change.finished.finally(() => {
      delete document.documentElement.dataset["nav"];
    });
  };
  const [codecIn, setCodecIn] = useState("");
  const [codecOut, setCodecOut] = useState("");
  const [codecNote, setCodecNote] = useState("");
  const selected =
    desk.demo ??
    desk.items.find((item) => item.id === desk.activeId)?.report ??
    desk.items.find((item) => item.report)?.report ??
    null;
  const preview =
    selected?.preview ?? desk.items.find((item) => item.id === desk.activeId)?.preview ?? null;

  return (
    <div className="app-shell report-page" data-theme={theme}>
      <header className="site-nav">
        <div className="nav-start">
          <Link to="/" className="back-link" aria-label="Back" onClick={goHome}>
            ←
          </Link>
          <Link to="/" className="brand" aria-label="Metadex" onClick={goHome}>
            METADEX
          </Link>
        </div>
        {scan.title ? <p className="viewing">{scan.title}</p> : <span />}
        <div className="nav-controls">
          <button
            className="theme-toggle"
            type="button"
            aria-label="Earlier scans"
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen((open) => !open)}
          >
            <History size={20} />
          </button>
          <button
            className="theme-toggle"
            type="button"
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
          {historyOpen ? (
            <div className="history-pop">
              {scan.reports.length === 0 ? <p>No earlier scans yet.</p> : null}
              {scan.reports.map((report) => (
                <button
                  key={report.id}
                  type="button"
                  onClick={() => {
                    openSaved(report.id);
                    setHistoryOpen(false);
                  }}
                >
                  <strong>{report.title}</strong>
                  <small>
                    {report.count} photos · {report.at}
                  </small>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </header>
      <main className="report-page-main">
        {scan.batch ? <ScannerReport /> : null}
        {!scan.batch && (
          <div className="report-page-layout">
            <aside className="sidebar">
              <h2>Images</h2>
              {desk.demo && (
                <button className="file-select sample-select active" type="button">
                  <span>
                    <strong>{desk.demo.fileName}</strong>
                    <small>{desk.demo.level}</small>
                  </span>
                </button>
              )}
              {desk.items.map((item) => (
                <button
                  key={item.id}
                  className={`file-select${desk.activeId === item.id && !desk.demo ? " active" : ""}`}
                  type="button"
                  onClick={() => selectDeskItem(item.id)}
                >
                  {item.preview ? <img src={item.preview} alt="" /> : null}
                  <span>
                    <strong>{item.name}</strong>
                    <small>
                      {item.report?.level ??
                        (item.status === "error" ? "Could not read" : "Reading")}
                    </small>
                  </span>
                </button>
              ))}
              {!desk.demo && !desk.items.length && <p className="empty-files">No image yet.</p>}
            </aside>
            <section className="report-sheet">
              {selected ? (
                <>
                  {preview ? <img className="report-sheet-photo" src={preview} alt="" /> : null}
                  <p className={`verdict verdict-${selected.level.toLowerCase()}`}>
                    <strong>{selected.level}</strong>
                    <span>{selected.line}</span>
                  </p>
                  <h1>{selected.fileName}</h1>
                  <dl className="report-rows">
                    {selected.evidence.map((item) => (
                      <div key={item.id}>
                        <dt>{item.title}</dt>
                        <dd>
                          <span className={`status-mark status-${item.status}`}>
                            {statusLabel(item.status as CheckStatus)}
                          </span>
                          <span>{item.finding}</span>
                        </dd>
                      </div>
                    ))}
                  </dl>
                </>
              ) : (
                <p>Pick an image.</p>
              )}
              <section className="codec">
                <h2>Encode or decode</h2>
                <p>
                  Encoding is not a lock. Anyone can undo it. A real lock needs a key, and this page
                  will not guess one.
                </p>
                <textarea
                  value={codecIn}
                  onChange={(event) => setCodecIn(event.target.value)}
                  rows={4}
                  placeholder="Paste text or encoded text"
                />
                <div className="hero-actions">
                  <button
                    className="primary-action"
                    type="button"
                    onClick={() => {
                      setCodecOut(encodeText(codecIn));
                      setCodecNote("Encoded. This is not a lock.");
                    }}
                  >
                    Encode
                  </button>
                  <button
                    className="secondary-action"
                    type="button"
                    onClick={() => {
                      try {
                        setCodecOut(decodeText(codecIn));
                        setCodecNote("Decoded. No key was needed.");
                      } catch {
                        setCodecOut("");
                        setCodecNote("Not simple encoding. If it is encrypted, it stays locked.");
                      }
                    }}
                  >
                    Decode
                  </button>
                </div>
                {codecNote && <p>{codecNote}</p>}
                {codecOut && (
                  <pre>
                    <code>{codecOut}</code>
                  </pre>
                )}
              </section>
              <button
                className="text-action"
                type="button"
                onClick={() => publishDesk({ items: [], activeId: null, demo: null })}
              >
                Clear
              </button>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
