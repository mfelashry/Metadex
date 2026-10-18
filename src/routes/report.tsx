import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ChevronDown, History, Moon, Sun } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { publishDesk, readDesk, selectDeskItem, subscribeDesk } from "@/lib/report-desk";
import { statusLabel, type CheckStatus } from "@/lib/scan-report";
import { answerQuestion, collectScanEvidence, localScanSummary, summarizeScan } from "@/lib/scan-summary";
import { levelMark, previewSrc, type RankedImage } from "@/lib/stillframe";
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
  const suspicious = ranking.filter((item) => isTextSuspicious(item));
  const normal = ranking.filter((item) => !isTextSuspicious(item));
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
      <div className="scanner-headline-row">
        <p className="scanner-headline">{batch.summary?.headline}</p>
        <button type="button" className="download-json" onClick={() => downloadScan(batch)}>
          Download JSON
        </button>
      </div>
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
        <CaseChat items={ranking} scanId={batch.scan_id ?? batch.summary?.headline ?? ""} />
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
  const fields = (report?.image_analysis?.metadata_messages?.fields ?? []).filter(
    (field) => field.flagged || field.decoded || field.preview,
  );
  const plainFacts = detailFacts(fields, entry);
  const recoveredCards = recoveredFrom(fields, messages);
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
      {plainFacts.length > 0 && (
        <details className="scanner-technical scanner-details">
          <summary>Details</summary>
          <ul className="scanner-facts">
            {plainFacts.map((fact) => (
              <li key={`${fact.label}-${fact.value}`}>
                <span>{fact.label}</span>
                <strong>{fact.value}</strong>
              </li>
            ))}
          </ul>
        </details>
      )}
      {recoveredCards.length > 0 && (
        <section className="scanner-messages">
          <h2>Recovered text</h2>
          {recoveredCards.map((card) => (
            <blockquote key={card.key}>
              <p className="recovered-label">{card.where}</p>
              {card.encoded ? (
                <>
                  <p>Encoded: {card.encoded}</p>
                  <p>Decoded: {card.decoded}</p>
                </>
              ) : (
                <p>{card.decoded}</p>
              )}
            </blockquote>
          ))}
        </section>
      )}
      {(fields.length > 0 ||
        (entry.top_reasons?.length ?? 0) > 1 ||
        (report?.activity_correlation?.timeline?.length ?? 0) > 0) && (
        <details className="scanner-technical">
          <summary>More details</summary>
          {(entry.top_reasons ?? [])
            .filter((reason) => !isPixelNote(reason))
            .slice(0, 4)
            .map((reason) => (
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

const FACT_LABELS: Record<string, string> = {
  DateTime: "Date",
  DateTimeOriginal: "Date",
  DateTimeDigitized: "Date",
  Make: "Camera",
  Model: "Camera",
  Artist: "Author",
  Software: "Software",
  GPS: "Place",
  DocumentName: "Place",
  Copyright: "Copyright",
};

function detailFacts(
  fields: { field?: string; preview?: string; decoded?: string | null; flagged?: boolean }[],
  entry: RankedImage,
) {
  const rows: { label: string; value: string }[] = [];
  const camera = ["Make", "Model"]
    .map((name) => fields.find((field) => field.field === name)?.preview || fields.find((field) => field.field === name)?.decoded)
    .filter(Boolean)
    .join(" ");
  if (camera) rows.push({ label: "Camera", value: camera });
  for (const name of ["DateTimeOriginal", "DateTime", "Artist", "Software", "GPS", "DocumentName"]) {
    const field = fields.find((item) => item.field === name);
    const value = (field?.decoded || field?.preview || "").trim();
    if (!value || rows.some((row) => row.label === FACT_LABELS[name] && row.value === value)) continue;
    if (name === "Make" || name === "Model") continue;
    rows.push({ label: FACT_LABELS[name] || name, value });
  }
  if (entry.width && entry.height) rows.push({ label: "Pixels", value: `${entry.width} × ${entry.height}` });
  return rows;
}

function recoveredFrom(
  fields: { field?: string; preview?: string; decoded?: string | null; flagged?: boolean; encoding?: string }[],
  messages: { text?: string; where?: string; encoding?: string; original?: string }[],
) {
  const flagged = fields.filter((field) => field.flagged && (field.decoded || field.preview));
  if (flagged.length) {
    return flagged.map((field, index) => {
      const coded = /base64|hex/i.test(field.encoding || "");
      return {
        key: `${field.field}-${index}`,
        where: field.field || "Metadata",
        encoded: coded ? field.preview || "" : "",
        decoded: field.decoded || field.preview || "",
      };
    });
  }
  return messages
    .filter((message) => message.text)
    .map((message, index) => {
      const coded = /base64|hex/i.test(message.encoding || "");
      return {
        key: `${message.where}-${index}`,
        where: message.where || "Metadata",
        encoded: coded ? message.original || "" : "",
        decoded: message.text || "",
      };
    });
}

function downloadScan(batch: object) {
  const copy = JSON.parse(JSON.stringify(batch)) as { ranking?: { local_preview?: string }[] };
  for (const entry of copy.ranking ?? []) delete entry.local_preview;
  const blob = new Blob([JSON.stringify(copy, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "metadex-scan.json";
  link.click();
  URL.revokeObjectURL(url);
}

function CaseChat({ items, scanId }: { items: RankedImage[]; scanId: string }) {
  const lineKey = items
    .map((item) =>
      (item.messages ?? item.report?.messages_found ?? [])
        .map((message) => message.text ?? "")
        .join("|"),
    )
    .join("\n");
  const evidence = collectScanEvidence(items);
  const [summary, setSummary] = useState(() => localScanSummary(evidence));
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [turns, setTurns] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  useEffect(() => {
    const nextEvidence = collectScanEvidence(items);
    const local = localScanSummary(nextEvidence);
    setSummary(local);
    let cancel = false;
    void summarizeScan(nextEvidence).then((next) => {
      if (!cancel && next) setSummary(next);
    });
    return () => {
      cancel = true;
    };
  }, [items, lineKey, scanId]);
  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    const history = [...turns, { role: "user" as const, text }];
    setTurns(history);
    setBusy(true);
    try {
      const reply = await answerQuestion(evidence, text, history);
      setTurns((current) => [...current, { role: "assistant", text: reply }]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <aside className="ai-panel ask-chat" aria-label="Scan chat">
      <h2 className="chat-title">
        <GeminiMark />
        Chat
      </h2>
      <div className="ask-log" role="log" aria-live="polite">
        <p className="ask-reply">
          <GeminiMark />
          <TypedText text={summary} />
        </p>
        {turns.map((turn, index) => (
          <p key={`${turn.role}-${index}`} className={turn.role === "user" ? "ask-user" : "ask-reply"}>
            {turn.role === "assistant" ? <GeminiMark /> : null}
            {turn.role === "assistant" ? <TypedText text={turn.text} /> : turn.text}
          </p>
        ))}
        {busy ? (
          <p className="ask-reply ask-typing" aria-label="Gemini is typing">
            <GeminiMark />
            <span>Typing</span>
          </p>
        ) : null}
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask about this scan"
          aria-label="Ask about this scan"
          disabled={busy}
        />
        <button type="submit" disabled={busy || !draft.trim()}>
          Send
        </button>
      </form>
    </aside>
  );
}

function isPixelNote(text: string) {
  return /score|pixel|chi-square|even pairs|last bit|lsb/i.test(text);
}

function isTextSuspicious(entry: RankedImage) {
  const messages = entry.messages ?? entry.report?.messages_found ?? [];
  if (messages.some((message) => message.text)) return true;
  const reasons = (entry.top_reasons ?? []).filter((reason) => !isPixelNote(reason));
  return reasons.length > 0 && (entry.level === "high" || entry.level === "suspicious");
}

function GeminiMark() {
  return (
    <svg className="gemini-mark" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 1.5c.4 3.6 2.2 6.4 5.2 8.3-3 1.9-4.8 4.7-5.2 8.2-.4-3.5-2.2-6.3-5.2-8.2 3-1.9 4.8-4.7 5.2-8.3Z"
      />
    </svg>
  );
}

function TypedText({ text }: { text: string }) {
  const reduced = useReducedMotion();
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (reduced) {
      setCount(text.length);
      return;
    }
    setCount(0);
    let index = 0;
    const timer = window.setInterval(() => {
      index += 2;
      setCount(Math.min(index, text.length));
      if (index >= text.length) window.clearInterval(timer);
    }, 18);
    return () => window.clearInterval(timer);
  }, [text, reduced]);
  return (
    <span>
      {text.slice(0, count)}
      {count < text.length ? <i className="summary-caret" /> : null}
    </span>
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
          <a
            className="theme-toggle"
            href="https://github.com/mfelashry/Metadex"
            target="_blank"
            rel="noreferrer"
            aria-label="GitHub"
          >
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path
                fill="currentColor"
                d="M12 2C6.5 2 2 6.6 2 12.2c0 4.5 2.9 8.3 6.9 9.6.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.2-3.4-1.2-.5-1.1-1.1-1.4-1.1-1.4-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.4 1.1 3 .9.1-.7.4-1.1.7-1.4-2.2-.3-4.6-1.1-4.6-5 0-1.1.4-2 1-2.7-.1-.3-.4-1.3.1-2.7 0 0 .8-.3 2.8 1a9.6 9.6 0 0 1 5.1 0c2-1.3 2.8-1 2.8-1 .5 1.4.2 2.4.1 2.7.6.7 1 1.6 1 2.7 0 3.9-2.3 4.7-4.6 5 .4.3.7 1 .7 1.9v2.8c0 .3.2.6.7.5A10.2 10.2 0 0 0 22 12.2C22 6.6 17.5 2 12 2z"
              />
            </svg>
          </a>
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
