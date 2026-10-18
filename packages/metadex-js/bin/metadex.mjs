#!/usr/bin/env node
import { readFile, stat } from "node:fs/promises";
import path from "node:path";

const api = (process.env.METADEX_API || "http://127.0.0.1:8741").replace(/\/$/, "");
const images = new Set([".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"]);

const raw = process.argv.slice(2);
const command = raw.shift();
const args = raw.filter((arg) => arg !== "--json" && arg !== "--no-recursive");
const asJson = process.argv.includes("--json");
const recursive = !process.argv.includes("--no-recursive");

if (command === "-h" || command === "--help" || args.includes("-h") || args.includes("--help") || command !== "scan" || !args.length) {
  console.log(`metadex scan <image-or-folder>...

  --json           print the full result
  --no-recursive   stay in the top folder
  METADEX_API      checker address, default http://127.0.0.1:8741`);
  process.exit(command === "-h" || command === "--help" ? 0 : 1);
}

try {
  const reports = [];
  for (const item of args) reports.push(await scan(item));
  if (asJson) {
    console.log(JSON.stringify(reports.length === 1 ? reports[0] : reports, null, 2));
  } else {
    for (const report of reports) printReport(report);
  }
} catch (error) {
  const refused = error?.cause?.code === "ECONNREFUSED" || error?.code === "ECONNREFUSED";
  const offline = refused || String(error?.message || error).includes("fetch failed");
  const message = offline
    ? "The checker is not running. Start it on 127.0.0.1:8741, then try again."
    : error instanceof Error
      ? error.message
      : error;
  console.error(`metadex: ${message}`);
  process.exit(1);
}

async function scan(input) {
  const target = path.resolve(input);
  const info = await stat(target);
  if (info.isDirectory()) {
    const response = await fetch(`${api}/api/scan-folder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: target, recursive }),
    });
    return readBody(response);
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

async function readBody(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body?.detail?.message || `The scanner said no (${response.status}).`);
  }
  return body;
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

function printReport(report) {
  const headline = report.summary?.headline;
  if (headline) console.log(`${headline}\n`);
  const ranking = report.ranking ?? [];
  if (!ranking.length) {
    console.log("No images in that scan.");
    return;
  }
  for (const item of ranking) {
    console.log(`${item.level_label || item.level || "None"}\t${item.filename}`);
    for (const [title, lines] of groupsOf(item)) {
      console.log(`  ${title}`);
      for (const line of lines) console.log(`    ${line}`);
    }
  }
}
