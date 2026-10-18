import { useEffect, useId, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check } from "lucide-react";

export type DeckCard = {
  name: string;
  preview: string;
};

const samples = ["mountains", "coast", "architecture", "desert"].map((name) => ({
  name: `${name}.jpg`,
  preview: `/scan-previews/${name}.svg`,
}));
const lensX = [340, 378, 312, 340];
const lensY = [128, 148, 164, 128];
const PHOTO_MS = 2000;
const loop = { duration: PHOTO_MS / 1000, ease: "easeInOut" as const, repeat: Infinity };

export function FolderScan({
  cards,
  label,
  count,
  settled = false,
}: {
  cards: DeckCard[] | null;
  label: string;
  count: { done: number; total: number } | null;
  settled?: boolean;
}) {
  const reduced = useReducedMotion();
  const id = useId().replace(/:/g, "");
  const dialog = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState(0);
  const [shown, setShown] = useState(0);
  const list = cards?.length ? cards : samples;
  const total = count?.total ?? 0;
  const target = count?.done ?? 0;
  const scanDone = count !== null && total > 0 && target >= total;
  const displayed = settled || reduced ? target : shown;
  const complete = settled && scanDone && displayed >= total;
  const current = list[cursor % list.length]!;
  const previewNumber = (cursor % list.length) + 1;

  useEffect(() => {
    if (reduced || complete) return;
    const timer = window.setInterval(() => setCursor((value) => value + 1), PHOTO_MS);
    return () => window.clearInterval(timer);
  }, [reduced, complete]);

  useEffect(() => {
    if (!total) return;
    if (reduced || settled) {
      setShown(target);
      return;
    }
    const fillMs = 7000;
    const tickMs = 50;
    const step = total / (fillMs / tickMs);
    const timer = window.setInterval(() => {
      setShown((prev) => (prev >= target ? prev : Math.min(target, prev + step)));
    }, tickMs);
    return () => window.clearInterval(timer);
  }, [target, total, reduced, settled]);

  useEffect(() => {
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
      previousFocus?.focus();
    };
  }, []);

  const still = reduced || complete;
  return (
    <div
      ref={dialog}
      tabIndex={-1}
      className="folder-scan"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-subtitle`}
    >
      <div className="scan-loader-brand">
        <span /> METADEX
      </div>
      <div className="scan-loader-content">
        <div className="folder-stage" aria-hidden="true">
          <svg viewBox="0 0 640 380" className="scan-scene">
            <defs>
              <linearGradient id={`${id}-folder-gradient`} x1="0" y1="0" x2="0.8" y2="1">
                <stop offset="0" className="scan-folder-gradient-start" />
                <stop offset="1" className="scan-folder-gradient-end" />
              </linearGradient>
              <clipPath id={`${id}-photo`}>
                <rect x="215" y="50" width="210" height="154" rx="5" />
              </clipPath>
              <clipPath id={`${id}-lens`}>
                <circle r="49" />
              </clipPath>
            </defs>
            <ellipse cx="320" cy="350" rx="155" ry="10" fill="currentColor" opacity=".045" />
            <path
              d="M154 217v-59q0-18 18-18h104q8 0 14 7l13 16h163q19 0 19 19v152H154Z"
              className="scan-folder-back"
            />
            {[-1, 1].map((side) => {
              const item = list[(cursor + (side === -1 ? 1 : 2)) % list.length]!;
              return (
                <motion.g
                  key={side}
                  initial={false}
                  animate={
                    still ? {} : { y: [9, -3, 9], rotate: [side * 13, side * 16, side * 13] }
                  }
                  transition={{ ...loop, delay: side === 1 ? 0.35 : 0 }}
                  style={{ transformOrigin: `${320 + side * 114}px 200px` }}
                >
                  <rect
                    x={222 + side * 114}
                    y="97"
                    width="196"
                    height="155"
                    rx="10"
                    className="scan-photo-frame"
                  />
                  <image
                    href={item.preview}
                    x={230 + side * 114}
                    y="105"
                    width="180"
                    height="123"
                    preserveAspectRatio="xMidYMid slice"
                  />
                  <path d={`M${235 + side * 114} 240h48`} className="scan-photo-rule" />
                </motion.g>
              );
            })}
            <AnimatePresence initial={false}>
              <motion.g
                key={cursor}
                initial={reduced ? false : { x: 0, y: 150, rotate: -6, opacity: 0, scale: 0.72 }}
                animate={{ x: 0, y: 0, rotate: 0, opacity: 1, scale: 1 }}
                exit={{ x: 70, y: -20, rotate: 6, opacity: 0 }}
                transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
                style={{ transformOrigin: "320px 240px" }}
              >
                <rect
                  x="205"
                  y="40"
                  width="230"
                  height="193"
                  rx="12"
                  className="scan-photo-frame"
                />
                <g clipPath={`url(#${id}-photo)`}>
                  <image
                    href={current.preview}
                    x="215"
                    y="50"
                    width="210"
                    height="154"
                    preserveAspectRatio="xMidYMid slice"
                  />
                </g>
                <text x="220" y="221" className="scan-photo-caption">
                  IMAGE {String(previewNumber).padStart(2, "0")}
                </text>
                <circle cx="416" cy="218" r="3" fill="#80917b" />
              </motion.g>
            </AnimatePresence>
            <path
              d="M164 232q2-17 20-17h272q19 0 20 17l-8 95q-2 17-21 17H193q-20 0-22-17Z"
              className="scan-folder-front"
              fill={`url(#${id}-folder-gradient)`}
            />
            <path d="M185 238h270" className="scan-folder-highlight" />
            <path d="M183 230h274" className="scan-folder-seam" />
            <motion.g
              key={`lens-${cursor}`}
              initial={false}
              animate={{ x: still ? 340 : lensX, y: still ? 128 : lensY }}
              transition={loop}
            >
              <path d="m38 38 46 46" className="scan-lens-handle" />
              <circle r="57" className="scan-lens-rim" />
              <g clipPath={`url(#${id}-lens)`}>
                <circle r="50" fill="var(--bg)" />
                {/* Inverse movement keeps the 2× crop aligned with the image beneath the lens. */}
                <motion.image
                  href={current.preview}
                  width="420"
                  height="308"
                  preserveAspectRatio="xMidYMid slice"
                  animate={{
                    x: still ? -250 : lensX.map((x) => (215 - x) * 2),
                    y: still ? -156 : lensY.map((y) => (50 - y) * 2),
                  }}
                  transition={loop}
                />
                <path
                  d="M-33-19a38 38 0 0 1 23-17"
                  fill="none"
                  stroke="white"
                  strokeOpacity=".65"
                  strokeWidth="4"
                  strokeLinecap="round"
                />
              </g>
              <circle r="49" fill="none" stroke="var(--bg)" strokeWidth="2" />
            </motion.g>
          </svg>
        </div>
        <h1 id={`${id}-title`}>
          {complete ? "All looked through." : "Looking through your photos."}
        </h1>
        <p className="scan-loader-subtitle" id={`${id}-subtitle`}>
          {complete ? "Opening your report now." : "Checking details one image at a time."}
        </p>
        <div className="scan-loader-progress">
          <div className="scan-loader-count-row">
            <span className="scan-loader-source">
              <span>{label || "Image analysis"}</span>
            </span>
            <span className="scan-loader-counter">
              {complete ? <Check size={16} /> : null}
              <strong>
                {String(total ? Math.min(total, Math.round(displayed)) : previewNumber).padStart(2, "0")}
              </strong>
              <span>/ {String(total || list.length).padStart(2, "0")}</span>
            </span>
          </div>
          <div
            className={`scan-loader-track${complete ? " is-complete" : ""}`}
            role="progressbar"
            aria-label="Image analysis"
            aria-valuemin={0}
            aria-valuemax={100}
            {...(total && displayed > 0
              ? { "aria-valuenow": Math.round((Math.min(total, displayed) / total) * 100) }
              : {})}
            aria-valuetext={complete ? "Analysis complete" : "Analysis in progress"}
          >
            <span
              style={
                total && displayed > 0
                  ? { width: `${Math.round((Math.min(total, displayed) / total) * 100)}%` }
                  : undefined
              }
            />
          </div>
          <div className="visually-hidden" role="status">
            {complete ? "Analysis complete" : `${Math.round(displayed)} images processed`}
          </div>
        </div>
      </div>
    </div>
  );
}
