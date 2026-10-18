import { Link } from "@tanstack/react-router";
import { Moon, Sun } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { motion, useMotionValue, useMotionValueEvent, useReducedMotion, useSpring, useTransform, type MotionValue } from "framer-motion";
import { LearnLink } from "./LearnLink";

const SCENES = 9;

export function LearnPage() {
  const reduced = useReducedMotion() ?? false;
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [lesson, setLesson] = useState(1);
  const progress = useMotionValue(0);
  const smooth = useSpring(progress, { stiffness: 90, damping: 28, mass: 0.35 });
  const bar = useTransform(smooth, (value) => `${Math.max(value, 0.03) * 100}%`);

  useMotionValueEvent(smooth, "change", (value) => {
    const next = Math.min(SCENES, Math.max(1, Math.floor(value * SCENES) + 1));
    setLesson((current) => (current === next ? current : next));
  });

  useEffect(() => {
    if (reduced) return;
    const html = document.documentElement;
    const body = document.body;
    const previousHtml = html.style.overflow;
    const previousBody = body.style.overflow;
    html.style.overflow = "hidden";
    body.style.overflow = "hidden";
    let touchY = 0;
    const add = (delta: number) => {
      progress.set(Math.min(1, Math.max(0, progress.get() + delta)));
    };
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const line = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaMode === 2 ? event.deltaY * window.innerHeight : event.deltaY;
      add(line / 1800);
    };
    const onTouchStart = (event: TouchEvent) => {
      touchY = event.touches[0]?.clientY ?? 0;
    };
    const onTouchMove = (event: TouchEvent) => {
      event.preventDefault();
      const y = event.touches[0]?.clientY ?? touchY;
      add((touchY - y) / 640);
      touchY = y;
    };
    const onKey = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (event.key === "ArrowDown" || event.key === "PageDown" || event.key === " ") {
        event.preventDefault();
        add(event.key === "ArrowDown" ? 0.06 : 0.12);
      } else if (event.key === "ArrowUp" || event.key === "PageUp") {
        event.preventDefault();
        add(event.key === "ArrowUp" ? -0.06 : -0.12);
      }
    };
    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("keydown", onKey);
    return () => {
      html.style.overflow = previousHtml;
      body.style.overflow = previousBody;
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("keydown", onKey);
    };
  }, [progress, reduced]);

  const scenes = [
    <Hero key="hero" />,
    <Exif key="exif" />,
    <Reveal key="reveal" reduced={reduced} />,
    <Stego key="stego" reduced={reduced} />,
    <Bytes key="bytes" />,
    <How key="how" />,
    <Privacy key="privacy" />,
    <Quiz key="quiz" reduced={reduced} />,
    <Close key="close" />,
  ];

  return (
    <div className={`app-shell learn${reduced ? " is-still" : ""}`} data-theme={theme}>
      <motion.div className="learn-progress" style={{ width: bar }} aria-hidden="true" />
      <header className="site-nav">
        <Link to="/" className="brand" aria-label="Metadex">
          METADEX
        </Link>
        <div className="nav-controls">
          <LearnLink />
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
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
        </div>
      </header>
      <main className="learn-story">
        {scenes.map((scene, index) => (
          <Placed key={index} index={index} total={SCENES} progress={smooth} reduced={reduced} live={lesson === index + 1}>
            {scene}
          </Placed>
        ))}
        <motion.div className="learn-rail" aria-hidden="true">
          <motion.span style={{ width: bar }} />
        </motion.div>
        <p className="visually-hidden" aria-live="polite">
          Lesson {lesson} of {SCENES}
        </p>
      </main>
    </div>
  );
}

function Placed({
  index,
  total,
  progress,
  reduced,
  live,
  children,
}: {
  index: number;
  total: number;
  progress: MotionValue<number>;
  reduced: boolean;
  live: boolean;
  children: ReactNode;
}) {
  const start = index / total;
  const end = (index + 1) / total;
  const span = end - start;
  const handoff = span * 0.42;
  const first = index === 0;
  const last = index === total - 1;
  const opacity = useTransform(
    progress,
    first
      ? [0, end - handoff, end]
      : last
        ? [Math.max(0, start - handoff), start, 1]
        : [Math.max(0, start - handoff), start, end - handoff, end],
    first ? [1, 1, 0] : last ? [0, 1, 1] : [0, 1, 1, 0],
  );
  const x = useTransform(
    progress,
    first ? [0, end - handoff, end] : [Math.max(0, start - handoff), start, end],
    first ? [0, 0, -36] : [42, 0, last ? 0 : -36],
  );
  const events = useTransform(opacity, (value) => (value > 0.55 ? "auto" : "none"));
  return (
    <motion.div
      className={`learn-stage${live ? " is-live" : ""}`}
      style={{ opacity: reduced ? 1 : opacity, x: reduced ? 0 : x, pointerEvents: reduced ? "auto" : events }}
    >
      {children}
    </motion.div>
  );
}

function Frame({
  eyebrow,
  title,
  id,
  text,
  visual,
  heading = "h2",
}: {
  eyebrow: string;
  title: string;
  id: string;
  text: string;
  visual: ReactNode;
  heading?: "h1" | "h2";
}) {
  const Title = heading;
  return (
    <section className="learn-frame" aria-labelledby={id}>
      <div className="learn-copy">
        <p className="eyebrow">{eyebrow}</p>
        <Title id={id}>{title}</Title>
        <p>{text}</p>
      </div>
      {visual}
    </section>
  );
}

function Photo({ chips = false, scan = false }: { chips?: boolean; scan?: boolean }) {
  return (
    <div className="learn-photo" aria-hidden="true">
      <svg viewBox="0 0 320 220" className="learn-scene">
        <rect width="320" height="220" rx="22" fill="var(--soft)" />
        <rect x="16" y="16" width="288" height="188" rx="14" fill="var(--bg)" stroke="var(--line)" />
        <circle cx="246" cy="58" r="16" fill="var(--fg)" opacity="0.12" />
        <path d="M16 150 L96 104 L148 136 L198 92 L304 158 V190 a14 14 0 0 1-14 14 H30 a14 14 0 0 1-14-14Z" fill="var(--fg)" opacity="0.12" />
        <path d="M16 168 L118 124 L176 154 L236 118 L304 172 V190 a14 14 0 0 1-14 14 H30 a14 14 0 0 1-14-14Z" fill="var(--fg)" opacity="0.28" />
      </svg>
      {chips ? (
        <>
          <span className="learn-chip learn-chip-a">GPS</span>
          <span className="learn-chip learn-chip-b">Camera</span>
          <span className="learn-chip learn-chip-c">Time</span>
          <span className="learn-chip learn-chip-d">File</span>
        </>
      ) : null}
      {scan ? <span className="learn-scanline" /> : null}
    </div>
  );
}

function Hero() {
  return (
    <Frame
      heading="h1"
      id="learn-title"
      eyebrow="Learn"
      title="Your images tell more than you think."
      text="A photo is the picture you see. The file can also carry a time, a place, a name, or a note."
      visual={<Photo chips />}
    />
  );
}

function Exif() {
  const notes = [
    ["GPS", "40.73, -73.94"],
    ["Time", "16 Oct 2026"],
    ["Camera", "Canon"],
    ["ISO", "200"],
  ];
  return (
    <Frame
      id="learn-exif"
      eyebrow="EXIF"
      title="The file keeps notes beside the picture."
      text="Exchangeable Image File Format is camera notes: place, time, and settings. Not every file has them, and they can be removed or wrong."
      visual={
        <ul className="learn-notes">
          {notes.map(([label, value], index) => (
            <li key={label} style={{ animationDelay: `${index * 0.35}s` }}>
              <span>{label}</span>
              <strong>{value}</strong>
            </li>
          ))}
        </ul>
      }
    />
  );
}

function Reveal({ reduced }: { reduced: boolean }) {
  return (
    <Frame
      id="learn-reveal"
      eyebrow="One photo"
      title="The picture is one layer. The file can carry another."
      text="A scan line is only a demonstration. These notes are sample metadata, not a real upload, and they cannot prove who took the photo."
      visual={
        <div className="learn-visual">
          <Photo scan={!reduced} />
          <ul className="learn-notes learn-notes-under">
            <li>
              <span>Camera</span>
              <strong>Canon PowerShot</strong>
            </li>
            <li>
              <span>Captured</span>
              <strong>October 2026</strong>
            </li>
            <li>
              <span>Exposure</span>
              <strong>1/125s · ISO 200</strong>
            </li>
          </ul>
        </div>
      }
    />
  );
}

function Stego({ reduced }: { reduced: boolean }) {
  return (
    <Frame
      id="learn-stego"
      eyebrow="Hidden in color"
      title="A secret can sit in the smallest bit."
      text="Steganography hides a message in a picture that still looks ordinary. Flipping the least significant bit barely changes the color. A row of those bits can hold a short message. This is a simulation, not a claim about a file you uploaded."
      visual={
        <div className={`learn-bits${reduced ? " is-shown" : ""}`} aria-hidden="true">
          {Array.from({ length: 16 }, (_, index) => (
            <span key={index} style={{ animationDelay: `${0.4 + index * 0.08}s` }} />
          ))}
          <p>
            0110100<b>1</b>
          </p>
        </div>
      }
    />
  );
}

function Bytes() {
  const parts = ["Image header", "Image content", "Image end", "Additional bytes"];
  return (
    <Frame
      id="learn-bytes"
      eyebrow="After the picture"
      title="Sometimes the extra part is not in the pixels."
      text="A file can store bytes after the picture ends. They are worth a look. They are not automatically malicious."
      visual={
        <ol className="learn-stack">
          {parts.map((part, index) => (
            <li key={part} style={{ animationDelay: `${index * 0.28}s` }}>
              {part}
            </li>
          ))}
        </ol>
      }
    />
  );
}

function How() {
  const steps = [
    ["Metadata", "Comments, names, dates, and places."],
    ["Encoded lines", "Base64 is shown as the sentence it was."],
    ["A level word", "High or suspicious means look closer, not a verdict."],
    ["Gemini", "It explains recovered notes. It does not invent findings."],
  ];
  return (
    <Frame
      id="learn-how"
      eyebrow="Metadex"
      title="The checker reads the notes, not a pixel score."
      text="Metadex flags comments, names, dates, places, and encoded lines. It does not decide a photo is suspicious because of pixel patterns."
      visual={
        <ol className="learn-stack">
          {steps.map(([title, body], index) => (
            <li key={title} style={{ animationDelay: `${index * 0.3}s` }}>
              <strong>{title}</strong>
              <span>{body}</span>
            </li>
          ))}
        </ol>
      }
    />
  );
}

function Privacy() {
  const lines = [
    "Sharing a photo can share the notes in the file.",
    "A place in the file is not a live tracker.",
    "Some apps strip EXIF. Some keep it.",
    "Removing those notes does not make the picture fully private.",
  ];
  return (
    <Frame
      id="learn-privacy"
      eyebrow="Privacy"
      title="The footprint is the picture and the file."
      text="Look at both before you send a photo."
      visual={
        <ul className="learn-stack">
          {lines.map((line, index) => (
            <li key={line} style={{ animationDelay: `${index * 0.28}s` }}>
              {line}
            </li>
          ))}
        </ul>
      }
    />
  );
}

function Quiz({ reduced }: { reduced: boolean }) {
  return (
    <Frame
      id="learn-quiz"
      eyebrow="Check"
      title="What is EXIF?"
      text="Notes stored with the image, such as time and camera. Not every file has them, and they can be wrong."
      visual={
        <ul className={`learn-quiz-line${reduced ? " is-shown" : ""}`}>
          <li>A sharpen filter</li>
          <li className="is-answer">Notes stored with the file</li>
          <li>A password in the pixels</li>
        </ul>
      }
    />
  );
}

function Close() {
  return (
    <section className="learn-frame learn-end" aria-labelledby="learn-close">
      <div className="learn-copy">
        <p className="eyebrow">Your turn</p>
        <h2 id="learn-close">Ready to look at a real file?</h2>
        <p>Drop a photo or a folder. The scan stays on this computer.</p>
        <Link to="/" className="primary-action learn-cta">
          Analyze an image
        </Link>
      </div>
      <Photo chips />
    </section>
  );
}
