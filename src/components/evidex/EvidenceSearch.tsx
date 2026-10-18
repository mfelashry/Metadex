import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { FileUp, Search, Trash2, Upload } from "lucide-react";
import {
  createCase,
  createDemoCase,
  deleteCase,
  fetchCase,
  fetchItem,
  fetchSearchStatus,
  formatSimilarity,
  modelStatusLabel,
  previewUrl,
  searchCase,
  type EvidenceCase,
  type ItemDetail,
  type SearchHit,
  type SearchResponse,
  type SearchStatus,
} from "@/lib/evidence-search";

function payloadText(message: { text?: string; preview?: string }) {
  return message.text || message.preview || "";
}

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function expiryLabel(iso: string) {
  const delta = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(delta) || delta <= 0) return "This case has expired.";
  const hours = Math.max(1, Math.round(delta / 3_600_000));
  return hours === 1 ? "Expires in about an hour." : `Expires in about ${hours} hours.`;
}

export function EvidenceSearch() {
  const fileId = useId();
  const queryId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [model, setModel] = useState<SearchStatus | null>(null);
  const [offline, setOffline] = useState(false);
  const [evidence, setEvidence] = useState<EvidenceCase | null>(null);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [selected, setSelected] = useState<SearchHit | null>(null);
  const [detail, setDetail] = useState<ItemDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    let stop = false;
    void fetchSearchStatus()
      .then((status) => {
        if (!stop) {
          setModel(status);
          setOffline(false);
        }
      })
      .catch(() => {
        if (!stop) setOffline(true);
      });
    return () => {
      stop = true;
    };
  }, [evidence?.id, evidence?.status]);

  useEffect(() => {
    if (!evidence || evidence.status !== "indexing") return;
    let stop = false;
    const timer = window.setInterval(() => {
      void fetchCase(evidence.id)
        .then((next) => {
          if (!stop) setEvidence(next);
        })
        .catch((reason: unknown) => {
          if (!stop) setError(messageFrom(reason));
        });
    }, 400);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [evidence]);

  const indexing = evidence?.status === "indexing";
  const ready = evidence?.status === "ready";
  const failed = evidence?.status === "failed";

  const openFiles = async (list: FileList | null) => {
    const files = list ? Array.from(list) : [];
    if (!files.length || busy) return;
    setBusy(true);
    setError(null);
    setResults(null);
    setSelected(null);
    try {
      setEvidence(await createCase(files, "Evidence case"));
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusy(false);
    }
  };

  const openDemo = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setResults(null);
    setSelected(null);
    try {
      setEvidence(await createDemoCase());
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusy(false);
    }
  };

  const runSearch = async (text: string) => {
    if (!evidence || evidence.status !== "ready") return;
    const cleaned = text.trim();
    if (!cleaned) {
      setError("Enter a description to search.");
      return;
    }
    setSearching(true);
    setError(null);
    setQuery(cleaned);
    try {
      setResults(await searchCase(evidence.id, cleaned));
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setSearching(false);
    }
  };

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    void runSearch(query);
  };

  const openHit = async (hit: SearchHit) => {
    if (!evidence) return;
    setSelected(hit);
    setDetail(null);
    setDetailError(null);
    try {
      setDetail(await fetchItem(evidence.id, hit.id));
    } catch (reason) {
      setDetailError(messageFrom(reason));
    }
  };

  const removeCase = async () => {
    if (!evidence) return;
    setBusy(true);
    setError(null);
    try {
      await deleteCase(evidence.id);
      setEvidence(null);
      setResults(null);
      setSelected(null);
      setConfirmDelete(false);
      setQuery("");
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusy(false);
    }
  };

  const live = indexing
    ? `Indexing and forensic analysis. ${evidence?.progress.done ?? 0} of ${evidence?.progress.total ?? 0} images.`
    : ready
      ? `${evidence?.indexed_count ?? 0} images are ready to search.`
      : failed
        ? evidence?.model_error || "This case could not be indexed."
        : modelStatusLabel(model, offline);

  return (
    <main className="dash es" aria-busy={busy || indexing || searching}>
      <p className="visually-hidden" aria-live="polite">
        {live}
      </p>
      <section className="dash-intro" aria-labelledby="search-title">
        <span className="eyebrow">Evidence search</span>
        <h1 id="search-title">
          Find the image<span>.</span>
        </h1>
        <p>
          Describe what you remember. Metadex ranks this case by visual similarity, then shows the forensic findings
          for each file. A match is not a verdict.
        </p>
        <p className="es-device" role="status">
          {evidence?.status === "failed" && evidence.model_error
            ? evidence.model_error
            : evidence?.status === "ready" && evidence.using_gpu && evidence.device === "cuda"
              ? "Search is running on the GPU (CUDA)."
              : evidence?.status === "ready" && evidence.device === "mps"
                ? "Search is running on the GPU (Apple MPS)."
                : evidence?.status === "ready" && evidence.device === "cpu"
                  ? "Search is running on the CPU. This is not GPU inference."
                  : modelStatusLabel(model, offline)}
        </p>
        <div className="dash-actions">
          <button className="primary-action" type="button" onClick={() => fileRef.current?.click()} disabled={busy || indexing}>
            <Upload size={16} aria-hidden="true" /> Upload images
          </button>
          <button className="secondary-action" type="button" onClick={() => void openDemo()} disabled={busy || indexing}>
            Open the demo case
          </button>
          {evidence ? (
            <button className="secondary-action es-danger" type="button" onClick={() => setConfirmDelete(true)} disabled={busy}>
              <Trash2 size={16} aria-hidden="true" /> Delete case
            </button>
          ) : null}
        </div>
        <p className="dash-note">
          Only images you select are analyzed. Nothing else on this computer is scanned. PNG, JPEG, and BMP, up to 10 MB
          each.
        </p>
        {error ? (
          <p className="error-message" role="alert">
            {error}
          </p>
        ) : null}
      </section>

      {!evidence ? (
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
            void openFiles(event.dataTransfer.files);
          }}
        >
          <FileUp size={22} strokeWidth={1.5} aria-hidden="true" />
          <strong>Drop evidence images here</strong>
          <span>or choose them from your device</span>
          <button type="button" onClick={() => fileRef.current?.click()} disabled={busy}>
            Choose images
          </button>
        </div>
      ) : null}

      <input
        ref={fileRef}
        id={fileId}
        className="visually-hidden"
        type="file"
        accept="image/png,image/jpeg,image/bmp,.png,.jpg,.jpeg,.bmp"
        multiple
        aria-label="Evidence images"
        onChange={(event) => {
          void openFiles(event.target.files);
          event.target.value = "";
        }}
      />

      {evidence ? (
        <section className="es-case" aria-labelledby="case-title">
          <div className="dash-report-heading">
            <div>
              <span className="eyebrow">{evidence.source === "demo" ? "Built-in demo case" : "Uploaded case"}</span>
              <h2 id="case-title">{evidence.name}</h2>
            </div>
            <p className="es-expiry">{expiryLabel(evidence.expires_at)}</p>
          </div>

          {indexing ? (
            <div className="es-progress">
              <p>Indexing images and running forensic analysis. Search opens when both finish.</p>
              <div
                className="scan-meter"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={Math.max(evidence.progress.total, 1)}
                aria-valuenow={evidence.progress.done}
                aria-label="Indexing and forensic analysis"
              >
                <i
                  style={{
                    width: `${evidence.progress.total ? Math.round((evidence.progress.done / evidence.progress.total) * 100) : 8}%`,
                  }}
                />
              </div>
            </div>
          ) : null}

          {failed ? (
            <p className="error-message" role="alert">
              {evidence.model_error || "This case could not be indexed."}
            </p>
          ) : null}

          {evidence.files.some((file) => file.status !== "error") ? (
            <ul className="es-file-list">
              {evidence.files
                .filter((file) => file.status !== "error")
                .map((file) => (
                  <li key={file.id}>
                    <strong>{file.filename}</strong>
                    <span>{file.forensic_summary?.headline ?? "Waiting for the forensic check"}</span>
                    {file.role_label ? <span>{file.role_label}</span> : null}
                    {file.forensic_summary ? (
                      <button
                        type="button"
                        onClick={() =>
                          void openHit({
                            id: file.id,
                            rank: 0,
                            filename: file.filename,
                            similarity: 0,
                            preview_url: file.preview_url ?? "",
                            role_label: file.role_label ?? null,
                            forensic_summary: file.forensic_summary as SearchHit["forensic_summary"],
                          })
                        }
                      >
                        Forensic details
                      </button>
                    ) : null}
                  </li>
                ))}
            </ul>
          ) : null}

          {evidence.file_errors.length ? (
            <div className="es-errors">
              <strong>Some files were not indexed.</strong>
              <ul>
                {evidence.file_errors.map((item) => (
                  <li key={`${item.filename}-${item.reason}`}>
                    {item.filename}: {item.reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {ready ? (
            <form className="es-search" onSubmit={onSearch}>
              <label htmlFor={queryId}>Describe an image</label>
              <div className="es-search-row">
                <input
                  id={queryId}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="a red backpack"
                  autoComplete="off"
                  disabled={searching}
                />
                <button className="primary-action" type="submit" disabled={searching || evidence.indexed_count === 0}>
                  <Search size={16} aria-hidden="true" /> {searching ? "Searching" : "Search"}
                </button>
              </div>
              {evidence.suggested_queries.length ? (
                <div className="es-suggestions">
                  {evidence.suggested_queries.map((suggestion) => (
                    <button key={suggestion} type="button" onClick={() => void runSearch(suggestion)} disabled={searching}>
                      {suggestion}
                    </button>
                  ))}
                </div>
              ) : null}
            </form>
          ) : null}

          {evidence.source === "demo" && ready ? (
            <p className="es-guide">
              This case was drawn on the server. Try “a red backpack” or “a person near a window”. The meadow is clean.
              The locker photo carries a synthetic comment and trailing bytes so the forensic panel has a known
              indicator.
            </p>
          ) : null}

          {results ? (
            <section className="es-results" aria-labelledby="results-title">
              <h3 id="results-title">Ranked by visual similarity</h3>
              <p>{results.score_meaning}</p>
              <p className="es-disclaimer">{results.disclaimer}</p>
              <p className="es-disclaimer">{results.indicator_disclaimer}</p>
              {results.device === "mps" ? (
                <p className="es-device">This search ran on the GPU (Apple MPS).</p>
              ) : results.device === "cpu" || !results.using_gpu ? (
                <p className="es-device">This search ran on the CPU. It was not GPU inference.</p>
              ) : (
                <p className="es-device">This search ran on the GPU (CUDA).</p>
              )}
              {results.note ? <p>{results.note}</p> : null}
              {results.results.length ? (
                <ol className="es-grid">
                  {results.results.map((hit) => (
                    <li key={hit.id}>
                      <article className="es-card">
                        <button type="button" onClick={() => void openHit(hit)}>
                          {previewUrl(hit.preview_url) ? (
                            <img src={previewUrl(hit.preview_url) ?? ""} alt="" />
                          ) : (
                            <span className="es-missing">No preview</span>
                          )}
                          <span className="es-card-copy">
                            <strong>
                              {hit.rank}. {hit.filename}
                            </strong>
                            <span>Relative similarity {formatSimilarity(hit.similarity)}</span>
                            <span>{hit.forensic_summary.headline}</span>
                            {hit.role_label ? <span className="es-role">{hit.role_label}</span> : null}
                          </span>
                        </button>
                        <ForensicChips summary={hit.forensic_summary} />
                      </article>
                    </li>
                  ))}
                </ol>
              ) : (
                <p>No images were indexed for this case.</p>
              )}
            </section>
          ) : null}
        </section>
      ) : null}

      {selected ? (
        <DetailDialog
          hit={selected}
          detail={detail}
          error={detailError}
          onClose={() => {
            setSelected(null);
            setDetail(null);
          }}
        />
      ) : null}

      {confirmDelete ? (
        <div className="es-modal" role="dialog" aria-modal="true" aria-labelledby="delete-title">
          <div className="es-modal-card">
            <h2 id="delete-title">Delete this case?</h2>
            <p>Images, previews, and embeddings are removed. This cannot be undone.</p>
            <div className="dash-actions">
              <button className="primary-action es-danger" type="button" onClick={() => void removeCase()} disabled={busy}>
                Delete case
              </button>
              <button className="secondary-action" type="button" onClick={() => setConfirmDelete(false)}>
                Keep the case
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}

function ForensicChips({ summary }: { summary: SearchHit["forensic_summary"] }) {
  const chips = [
    summary.level_label,
    summary.appended.present ? `Appended data, ${summary.appended.trailing_bytes} bytes` : null,
    summary.lsb.status === "indicator" ? "LSB indicator" : null,
    summary.metadata_anomalies.length ? `Metadata notes, ${summary.metadata_anomalies.length}` : null,
    summary.recovered_payloads.length ? `Recovered payload, ${summary.recovered_payloads.length}` : null,
    summary.integrity.unchanged ? "Integrity unchanged" : "Integrity note",
  ].filter((chip): chip is string => Boolean(chip));
  return (
    <ul className="es-chips" aria-label="Forensic summary">
      {chips.map((chip) => (
        <li key={chip}>{chip}</li>
      ))}
    </ul>
  );
}

function DetailDialog({
  hit,
  detail,
  error,
  onClose,
}: {
  hit: SearchHit;
  detail: ItemDetail | null;
  error: string | null;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
  }, []);
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const items = [...dialogRef.current.querySelectorAll<HTMLElement>("button, a[href], input, textarea")].filter(
      (item) => !item.hasAttribute("disabled"),
    );
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  const summary = detail?.forensic_summary ?? hit.forensic_summary;
  return (
    <div
      ref={dialogRef}
      className="es-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="detail-title"
      onKeyDown={onKeyDown}
    >
      <div className="es-modal-card es-detail">
        <div className="dash-report-heading">
          <h2 id="detail-title">{hit.filename}</h2>
          <button ref={closeRef} className="secondary-action" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        {hit.rank > 0 ? (
          <p>Relative similarity {formatSimilarity(hit.similarity)}. This is not a danger score.</p>
        ) : (
          <p>Forensic record for this file. It is not a danger score, and it is not proof of an attack.</p>
        )}
        <p className="es-disclaimer">{summary.disclaimer}</p>
        {error ? (
          <p className="error-message" role="alert">
            {error}
          </p>
        ) : null}
        {!detail && !error ? <p>Loading forensic details.</p> : null}
        <dl className="es-facts">
          <div>
            <dt>Hidden data</dt>
            <dd>{summary.headline}</dd>
          </div>
          <div>
            <dt>Appended data</dt>
            <dd>
              {summary.appended.present
                ? `${summary.appended.trailing_bytes} trailing bytes. ${summary.appended.note}`
                : "No trailing bytes."}
            </dd>
          </div>
          <div>
            <dt>LSB</dt>
            <dd>
              {summary.lsb.status}. {summary.lsb.note}
            </dd>
          </div>
          <div>
            <dt>Metadata</dt>
            <dd>{summary.metadata_anomalies.length ? summary.metadata_anomalies.join(" ") : "No metadata anomaly listed."}</dd>
          </div>
          <div>
            <dt>Integrity</dt>
            <dd>{summary.integrity.statement || (summary.integrity.unchanged ? "Unchanged." : "See the hash note.")}</dd>
          </div>
          {detail?.sha256 ? (
            <div>
              <dt>SHA256</dt>
              <dd className="es-hash">{detail.sha256}</dd>
            </div>
          ) : null}
        </dl>
        {summary.recovered_payloads.length ? (
          <div>
            <h3>Recovered payloads</h3>
            <ul>
              {(detail?.messages?.length ? detail.messages : summary.recovered_payloads).map((message, index) => (
                <li key={`${message.where ?? "payload"}-${index}`}>
                  <strong>{message.where || message.method || "Payload"}.</strong> {payloadText(message)}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p>No recovered payload.</p>
        )}
        {detail?.findings?.length ? (
          <div>
            <h3>Findings</h3>
            <ul>
              {detail.findings.map((finding, index) => (
                <li key={`${finding.name ?? "finding"}-${index}`}>
                  {finding.name}: {finding.detail}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {detail?.limitations ? <p className="es-guide">{detail.limitations}</p> : null}
      </div>
    </div>
  );
}
