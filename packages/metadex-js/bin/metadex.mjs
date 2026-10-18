#!/usr/bin/env node
// metadex for Node. Talks to the local checker started with the Python command `metadex serve`.
//
//   metadex                 scan the folder you are in, and every folder inside it
//   metadex ~/Pictures      scan that folder (or one photo)
//   metadex --all           scan the whole computer
//
// `scan` is still accepted as a first word, so `metadex scan ~/Pictures` works too.
import { existsSync } from "node:fs";
import { readdir, readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const api = (process.env.METADEX_API || "http://127.0.0.1:8741").replace(/\/$/, "");
const images = new Set([".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"]);

const raw = process.argv.slice(2);
const flags = { json: false, recursive: true, explain: false, all: false };
const positionals = [];
for (let index = 0; index < raw.length; index += 1) {
  const arg = raw[index];
  if (arg === "--json") flags.json = true;
  else if (arg === "--no-recursive") flags.recursive = false;
  else if (arg === "--explain") flags.explain = true;
  else if (arg === "--all") flags.all = true;
  else if (arg === "--sensors") {
    // Removed option. Old commands still run, with a note.
    console.error("metadex: --sensors is no longer needed and was ignored.");
    if (raw[index + 1] && !raw[index + 1].startsWith("--")) index += 1;
  } else if (arg === "-h" || arg === "--help") help(0);
  else if (arg.startsWith("--")) {
    console.error(`metadex: unknown option ${arg}`);
    help(1);
  } else positionals.push(arg);
}
if (positionals[0] === "scan" && !existsSync("scan")) positionals.shift();
if (positionals[0] === "serve" && !existsSync("serve")) {
  console.error("metadex: the checker is started from the Python package. Run the Python `metadex serve`.");
  process.exit(1);
}
if (flags.all && positionals.length) {
  console.error("metadex: use either --all or a path, not both");
  process.exit(1);
}

function help(code) {
  console.log(`metadex [path ...]

  (no path)        scan the folder you are in and every folder inside it
  path             a folder or a photo
  --all            scan the whole computer (Ctrl+C stops and shows results so far)
  --explain        ask Gemini to explain the top finding
  --json           print the full result
  --no-recursive   only the top folder
  METADEX_API      checker address, default http://127.0.0.1:8741`);
  process.exit(code);
}

let stopRequested = false;
const progress = makeProgress(process.stderr.isTTY && !flags.json);

async function scan(input) {
  const target = path.resolve(expandHome(input));
  const info = await stat(target);
  if (info.isDirectory()) {
    return postFolder(target, flags.recursive, true);
  }
  if (!images.has(path.extname(target).toLowerCase())) {
    throw new Error(`Not an image: ${path.basename(target)}`);
  }
  const form = new FormData();
  const bytes = await readFile(target);
  form.append("images", new Blob([bytes]), path.basename(target));
  const response = await fetch(`${api}/api/analyze-batch`, { method: "POST", body: form });
  return readBody(response);
}

async function postFolder(folder, recursive, includeReports) {
  const response = await fetch(`${api}/api/scan-folder?include_reports=${includeReports}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: folder, recursive }),
  });
  return readBody(response);
}

async function readBody(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body?.detail?.message || `The scanner said no (${response.status}).`);
  }
  return body;
}

// Whole computer: walk every folder here, and ask the checker to scan each folder that holds files.
// The checker reads each file's first bytes, so a photo renamed to .txt is still found.

const SKIP_NAMES = new Set([
  "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv", "site-packages",
  ".cache", ".npm", ".gradle", ".m2", "caches", "system volume information",
]);
const KEEP_HIDDEN = new Set([".trash", ".trashes", "$recycle.bin"]);
const SKIP_SUFFIXES = [".app", ".framework", ".bundle", ".kext", ".plugin", ".appex", ".xpc"];

async function wholeComputerRoots() {
  if (process.platform !== "win32") return ["/"];
  const roots = [];
  for (const letter of "ABCDEFGHIJKLMNOPQRSTUVWXYZ") {
    const root = `${letter}:\\`;
    if (existsSync(root)) roots.push(root);
  }
  return roots;
}

function systemPrefixes(roots) {
  const home = os.homedir();
  let items;
  if (process.platform === "darwin") {
    items = ["/System", "/Library", "/private", "/dev", "/Volumes", "/cores", "/usr", "/bin", "/sbin", "/opt",
      "/etc", "/var", "/tmp", "/Applications", "/Network", "/net", "/home", path.join(home, "Library")];
  } else if (process.platform === "win32") {
    items = roots.flatMap((root) =>
      ["Windows", "Program Files", "Program Files (x86)", "ProgramData", "Recovery", "PerfLogs", "$WinREAgent"]
        .map((name) => path.join(root, name)));
    items.push(path.join(home, "AppData"));
  } else {
    items = ["/proc", "/sys", "/dev", "/run", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc",
      "/var", "/boot", "/snap", "/opt", "/tmp", "/lost+found"];
  }
  const norm = (p) => (process.platform === "win32" ? path.resolve(p).toLowerCase() : path.resolve(p));
  return { list: items.map(norm), norm };
}

function skipDir(full, name, prefixes) {
  const lowered = name.toLowerCase();
  if (KEEP_HIDDEN.has(lowered)) return false;
  if (SKIP_NAMES.has(lowered) || SKIP_SUFFIXES.some((s) => lowered.endsWith(s))) return true;
  if (name.startsWith(".") || name.startsWith("$")) return true;
  const target = prefixes.norm(full);
  return prefixes.list.some((p) => target === p || target.startsWith(p + path.sep));
}

async function scanEverything(roots) {
  const prefixes = systemPrefixes(roots);
  const ranking = [];
  const problems = [];
  const counts = { folders: 0, files: 0, images: 0, other: 0, flagged: 0, problems: 0 };
  const stack = [...roots].reverse();
  while (stack.length && !stopRequested) {
    const folder = stack.pop();
    let children;
    try {
      children = await readdir(folder, { withFileTypes: true });
    } catch (error) {
      counts.problems += 1;
      if (problems.length < 200) problems.push({ filename: folder, reason: error.code === "EACCES" || error.code === "EPERM" ? "Permission denied" : `Could not open: ${error.code}` });
      continue;
    }
    children.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    const subfolders = [];
    let hasFiles = false;
    for (const child of children) {
      if (child.isSymbolicLink()) continue;
      if (child.isDirectory()) {
        const full = path.join(folder, child.name);
        if (!skipDir(full, child.name, prefixes)) subfolders.push(full);
      } else if (child.isFile() && !child.name.startsWith(".")) {
        hasFiles = true;
        counts.files += 1;
      }
    }
    stack.push(...subfolders.reverse());
    if (!hasFiles) continue;
    counts.folders += 1;
    progress.update(counts, folder);
    let body;
    try {
      body = await postFolder(folder, false, false);
    } catch (error) {
      if (String(error?.message || error).includes("fetch failed")) throw error;
      counts.problems += 1;
      if (problems.length < 200) problems.push({ filename: folder, reason: String(error.message || error) });
      continue;
    }
    for (const entry of body.ranking ?? []) {
      counts.images += 1;
      entry.path = path.join(folder, entry.path || entry.filename);
      if ((entry.score ?? 0) > 0) counts.flagged += 1;
      ranking.push(entry);
    }
    for (const item of body.skipped ?? []) {
      if (item.reason === "Not a PNG, JPEG, or BMP file") counts.other += 1;
      else if (item.reason === "Symbolic link not followed") continue;
      else {
        counts.problems += 1;
        if (problems.length < 200) problems.push({ filename: path.join(folder, item.filename), reason: item.reason });
      }
    }
  }
  const order = { high: 3, suspicious: 2, low: 1, none: 0 };
  ranking.sort((a, b) => (b.score ?? 0) - (a.score ?? 0) || (order[b.level] ?? 0) - (order[a.level] ?? 0) || a.path.localeCompare(b.path));
  ranking.forEach((entry, index) => { entry.rank = index + 1; });
  let headline = ranking.length
    ? `${counts.flagged} of ${ranking.length} images show hidden-data indicators`
    : "No supported images were found";
  if (stopRequested) headline += " (stopped early)";
  return {
    source: { type: "computer", roots, skipped_system_folders: true },
    summary: {
      headline,
      scanned: ranking.length,
      with_indicators: counts.flagged,
      files_checked: counts.files,
      other_files: counts.other,
      problems: counts.problems,
      interrupted: stopRequested,
    },
    ranking,
    skipped: problems,
  };
}

function makeProgress(enabled) {
  let last = 0;
  let shown = false;
  const width = () => Math.max(40, (process.stderr.columns || 100) - 1);
  return {
    update(counts, current) {
      if (!enabled) return;
      const now = Date.now();
      if (now - last < 200) return;
      last = now;
      const head = `${counts.folders.toLocaleString()} folders, ${counts.images.toLocaleString()} images, ${counts.flagged.toLocaleString()} flagged  `;
      const room = width() - head.length;
      let tail = current;
      if (tail.length > room) tail = room > 3 ? "..." + tail.slice(-(room - 3)) : "";
      process.stderr.write("\r" + (head + tail).padEnd(width()));
      shown = true;
    },
    clear() {
      if (shown) process.stderr.write("\r" + " ".repeat(width()) + "\r");
      shown = false;
    },
  };
}

function expandHome(input) {
  return input === "~" || input.startsWith("~/") || input.startsWith("~\\") ? path.join(os.homedir(), input.slice(1)) : input;
}

const detailWords = ["make", "model", "date", "time", "gps", "software", "artist", "lens", "iso", "captured"];
const structureWords = ["byte", "trailer", "pixel", "lsb", "file type", "extension", "end of", "extra"];

function fieldsOf(item) {
  return item.report?.image_analysis?.metadata_messages?.fields ?? [];
}

function groupsOf(item) {
  const details = [];
  const structure = [];
  for (const field of fieldsOf(item)) {
    const name = String(field.field || "").toLowerCase();
    const value = String(field.decoded || field.preview || "").trim();
    if (!value) continue;
    const line = `${field.field}: ${value}`;
    if (detailWords.some((word) => name.includes(word))) details.push(line);
    else if (structureWords.some((word) => name.includes(word))) structure.push(line);
  }
  for (const reason of item.top_reasons ?? []) {
    if (structureWords.some((word) => reason.toLowerCase().includes(word))) structure.push(reason);
  }
  const hidden = (item.messages ?? item.report?.messages_found ?? [])
    .map((message) => message.text)
    .filter(Boolean);
  return [
    ["File details", details.slice(0, 4)],
    ["Hidden text clues", hidden.slice(0, 3)],
    ["Image structure", structure.slice(0, 3)],
  ].filter(([, lines]) => lines.length);
}

function printReport(report, onlyFlagged) {
  const summary = report.summary ?? {};
  if (summary.headline) {
    const extra = [];
    if (summary.other_files) extra.push(`${summary.other_files.toLocaleString()} other file${summary.other_files === 1 ? "" : "s"} checked`);
    if (summary.problems) extra.push(`${summary.problems.toLocaleString()} could not be read`);
    console.log(`${summary.headline}${extra.length ? ` (${extra.join(", ")})` : ""}\n`);
  }
  const ranking = report.ranking ?? [];
  if (!ranking.length) {
    console.log("No images found there.");
    return;
  }
  const shown = ranking.filter((item) => !onlyFlagged || (item.score ?? 0) > 0);
  for (const item of shown) {
    console.log(`${item.level_label || item.level || "None"}\t${item.path || item.filename}`);
    for (const [title, lines] of groupsOf(item)) {
      console.log(`  ${title}`);
      for (const line of lines) console.log(`    ${line}`);
    }
  }
  const hidden = ranking.length - shown.length;
  if (hidden) console.log(`${shown.length ? "\n" : ""}${hidden.toLocaleString()} other images showed no indicators (not listed).`);
}

function forensicReasons(item) {
  const text = (item.top_reasons ?? []).join(" ").toLowerCase();
  const reasons = [
    (item.messages?.length ?? 0) > 0 ? "Readable content was recovered" : null,
    /after the end|trailer|extra bytes/.test(text) ? "Extra data after the image end" : null,
    /metadata|exif|base64|comment|description/.test(text) ? "Unusual metadata or encoding" : null,
    /pixel|lsb|channel/.test(text) ? "Unusual pixel pattern" : null,
  ].filter(Boolean);
  return reasons.length ? reasons : ["No specific hidden-data indicators were reported"];
}

async function explainReport(report, write) {
  const ranking = report.ranking ?? [];
  if (!ranking.length) return;
  const lead = ranking.reduce((best, item) => ((item.score ?? 0) > (best.score ?? 0) ? item : best), ranking[0]);
  const response = await fetch(`${api}/api/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level: lead.level || "none", reasons: forensicReasons(lead).slice(0, 5), sensor_notes: [] }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    write(`Gemini: ${body?.detail?.message || "Gemini is unavailable right now."}`);
    return;
  }
  write(`\nGemini\n${body.text || "No explanation returned."}`);
}

async function main() {
  try {
    let reports;
    if (flags.all) {
      process.once("SIGINT", () => {
        stopRequested = true;
      });
      const roots = await wholeComputerRoots();
      if (!flags.json) {
        console.log(`Scanning the whole computer (${roots.join(", ")}). System and app folders are skipped.`);
        console.log("Press Ctrl+C to stop early and see what was found so far.\n");
      }
      reports = [await scanEverything(roots)];
    } else {
      reports = [];
      for (const item of positionals.length ? positionals : ["."]) reports.push(await scan(item));
    }
    progress.clear();
    if (flags.json) {
      console.log(JSON.stringify(reports.length === 1 ? reports[0] : reports, null, 2));
    } else {
      for (const report of reports) printReport(report, flags.all);
    }
    if (flags.explain) {
      for (const report of reports) await explainReport(report, flags.json ? console.error : console.log);
    }
  } catch (error) {
    progress.clear();
    const refused = error?.cause?.code === "ECONNREFUSED" || error?.code === "ECONNREFUSED";
    const offline = refused || String(error?.message || error).includes("fetch failed");
    const message = offline
      ? "The checker is not running. Start it with the Python command `metadex serve`, then try again."
      : error?.code === "ENOENT"
        ? `No such file or folder: ${error.path}`
        : error instanceof Error
          ? error.message
          : error;
    console.error(`metadex: ${message}`);
    process.exit(1);
  }
}

await main();
