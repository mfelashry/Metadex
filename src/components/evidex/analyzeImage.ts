export type Finding = { label: string; value: string; detail: string };

export type ImageAnalysis = {
  fileName: string;
  fileSize: number;
  format: string;
  mimeType: string;
  width: number | null;
  height: number | null;
  sha256: string;
  fileModified: string | null;
  metadata: Finding[];
  structure: Finding[];
  pixels: Finding[];
  flags: string[];
  score: number;
  summary: string;
  gps: { lat: number; lon: number } | null;
  capturedAt: string | null;
  exifNotes: string[];
  payload: FilePayload;
  isDemo?: boolean;
};

export type PayloadKind = "none" | "padding" | "text" | "encoded" | "locked" | "binary";

export type FilePayload = {
  kind: PayloadKind;
  text: string | null;
};

export const MAX_IMAGE_BYTES = 40 * 1024 * 1024;
const TRAILING_FLAG_BYTES = 32;
const PIXEL_SAMPLE_EDGE = 480;

const decoder = new TextDecoder("utf-8", { fatal: false });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

type FlagCode = "trailing" | "extension" | "missing-end" | "png-text";

const FLAG_WEIGHT: Record<FlagCode, number> = {
  trailing: 40,
  extension: 30,
  "missing-end": 25,
  "png-text": 20,
};

type ExifValues = {
  make?: string | undefined;
  model?: string | undefined;
  software?: string | undefined;
  capturedAt?: string | undefined;
  gps?: { lat: number; lon: number };
  notes?: string[];
};

function bytesToHex(bytes: Uint8Array) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatExifDate(value: string) {
  const match = value
    .trim()
    .match(/^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!match) return value.trim();
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59) return value.trim();
  const clockHour = hour % 12 || 12;
  const suffix = hour >= 12 ? "PM" : "AM";
  return `${MONTHS[month - 1]} ${day}, ${year} · ${clockHour}:${String(minute).padStart(2, "0")} ${suffix}`;
}

export function detectFormat(bytes: Uint8Array) {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "JPEG";
  if (bytes.length >= 8 && bytesToHex(bytes.subarray(0, 8)) === "89504e470d0a1a0a") return "PNG";
  if (bytes.length >= 6 && decoder.decode(bytes.subarray(0, 3)) === "GIF") return "GIF";
  if (
    bytes.length >= 12 &&
    decoder.decode(bytes.subarray(0, 4)) === "RIFF" &&
    decoder.decode(bytes.subarray(8, 12)) === "WEBP"
  )
    return "WebP";
  if (bytes.length >= 2 && decoder.decode(bytes.subarray(0, 2)) === "BM") return "BMP";
  return "Unknown";
}

function extensionFormat(name: string) {
  const extension = name.split(".").pop()?.toLowerCase() ?? "";
  if (["jpg", "jpeg", "jpe"].includes(extension)) return "JPEG";
  if (extension === "png") return "PNG";
  if (extension === "gif") return "GIF";
  if (extension === "webp") return "WebP";
  if (extension === "bmp") return "BMP";
  if (["heic", "heif", "avif"].includes(extension)) return "HEIF";
  return "Unknown";
}

async function blobBytes(blob: Blob) {
  if (typeof blob.arrayBuffer === "function") return new Uint8Array(await blob.arrayBuffer());
  const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the file."));
    reader.readAsArrayBuffer(blob);
  });
  return new Uint8Array(buffer);
}

export async function sniffImage(file: File) {
  if (file.type.startsWith("image/")) return true;
  const head = await blobBytes(file.slice(0, 16));
  if (detectFormat(head) !== "Unknown") return true;
  return extensionFormat(file.name) !== "Unknown";
}

function hasExif(exif: ExifValues) {
  return Boolean(exif.make || exif.model || exif.software || exif.capturedAt || exif.gps);
}

function parseTiff(bytes: Uint8Array, tiff: number, end: number): ExifValues {
  if (tiff + 8 > end) return {};
  const little = bytes[tiff] === 0x49 && bytes[tiff + 1] === 0x49;
  const big = bytes[tiff] === 0x4d && bytes[tiff + 1] === 0x4d;
  if (!little && !big) return {};
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const inBounds = (offset: number, size: number) => offset >= tiff && offset + size <= end;
  const u16 = (offset: number) => (inBounds(offset, 2) ? view.getUint16(offset, little) : 0);
  const u32 = (offset: number) => (inBounds(offset, 4) ? view.getUint32(offset, little) : 0);
  if (u16(tiff + 2) !== 42) return {};
  const typeSize: Record<number, number> = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8 };
  const entries = (relative: number) => {
    const offset = tiff + relative;
    if (!inBounds(offset, 2))
      return [] as { tag: number; type: number; count: number; value: number }[];
    const count = Math.min(u16(offset), 256);
    const result = [] as { tag: number; type: number; count: number; value: number }[];
    for (let i = 0; i < count; i++) {
      const entry = offset + 2 + i * 12;
      if (!inBounds(entry, 12)) break;
      result.push({
        tag: u16(entry),
        type: u16(entry + 2),
        count: u32(entry + 4),
        value: entry + 8,
      });
    }
    return result;
  };
  const valueOffset = (entry: { type: number; count: number; value: number }) => {
    const size = (typeSize[entry.type] ?? 0) * entry.count;
    if (!size || size > 1024 * 1024) return null;
    const offset = size <= 4 ? entry.value : tiff + u32(entry.value);
    return inBounds(offset, size) ? offset : null;
  };
  const ascii = (entry?: { type: number; count: number; value: number }) => {
    if (!entry || entry.type !== 2) return undefined;
    const offset = valueOffset(entry);
    return offset === null
      ? undefined
      : decoder.decode(bytes.subarray(offset, offset + entry.count)).replace(/\0/g, "").trim() ||
          undefined;
  };
  const rational = (entry: { type: number; count: number; value: number }, index: number) => {
    if (entry.type !== 5 || index >= entry.count) return null;
    const offset = valueOffset(entry);
    if (offset === null) return null;
    const numerator = u32(offset + index * 8);
    const denominator = u32(offset + index * 8 + 4);
    return denominator ? numerator / denominator : null;
  };
  const ifd0 = entries(u32(tiff + 4));
  const find = (list: typeof ifd0, tag: number) => list.find((entry) => entry.tag === tag);
  const exifPointer = find(ifd0, 0x8769);
  const gpsPointer = find(ifd0, 0x8825);
  const exif = exifPointer ? entries(u32(exifPointer.value)) : [];
  const gps = gpsPointer ? entries(u32(gpsPointer.value)) : [];
  const capturedRaw = ascii(find(exif, 0x9003)) ?? ascii(find(ifd0, 0x0132));
  const result: ExifValues = {
    make: ascii(find(ifd0, 0x010f)),
    model: ascii(find(ifd0, 0x0110)),
    software: ascii(find(ifd0, 0x0131)),
    capturedAt: capturedRaw ? formatExifDate(capturedRaw) : undefined,
  };
  const latEntry = find(gps, 2);
  const lonEntry = find(gps, 4);
  if (latEntry && lonEntry) {
    const latParts = [0, 1, 2].map((index) => rational(latEntry, index));
    const lonParts = [0, 1, 2].map((index) => rational(lonEntry, index));
    if (latParts.every((part) => part !== null) && lonParts.every((part) => part !== null)) {
      const lat = latParts[0]! + latParts[1]! / 60 + latParts[2]! / 3600;
      const lon = lonParts[0]! + lonParts[1]! / 60 + lonParts[2]! / 3600;
      const latRef = ascii(find(gps, 1));
      const lonRef = ascii(find(gps, 3));
      const signedLat = latRef === "S" ? -lat : lat;
      const signedLon = lonRef === "W" ? -lon : lon;
      if (Math.abs(signedLat) <= 90 && Math.abs(signedLon) <= 180)
        result.gps = { lat: signedLat, lon: signedLon };
    }
  }
  const notes: string[] = [];
  const oversized = [...ifd0, ...exif].some((entry) => entry.type === 2 && entry.count > 256);
  if (oversized) notes.push("An EXIF text field is oversized.");
  if (!oversized && (result.software?.length ?? 0) > 80) notes.push("Software tag is oversized.");
  if (!oversized && ((result.make?.length ?? 0) > 80 || (result.model?.length ?? 0) > 80))
    notes.push("Camera tag is oversized.");
  if (capturedRaw) {
    const match = capturedRaw.trim().match(/^(\d{4}):(\d{2}):(\d{2})/);
    const year = match ? Number(match[1]) : 0;
    if (!match || year < 1990 || year > new Date().getFullYear() + 1) notes.push("Capture time looks odd.");
  }
  if (result.gps && Math.abs(result.gps.lat) < 0.0001 && Math.abs(result.gps.lon) < 0.0001)
    notes.push("Location is 0, 0.");
  if (notes.length) result.notes = notes;
  return result;
}

function readExifBlob(bytes: Uint8Array, start: number, length: number) {
  const end = Math.min(bytes.length, start + length);
  if (end - start >= 6 && decoder.decode(bytes.subarray(start, start + 4)) === "Exif")
    return parseTiff(bytes, start + 6, end);
  return parseTiff(bytes, start, end);
}

function findJpegEnd(bytes: Uint8Array, from: number) {
  for (let i = from; i < bytes.length - 1; i++) {
    if (bytes[i] !== 0xff) continue;
    const marker = bytes[i + 1];
    if (marker === 0x00) {
      i += 1;
      continue;
    }
    if (marker === 0xff) continue;
    if (marker === 0xd9) return i + 2;
  }
  return -1;
}

function inspectJpeg(bytes: Uint8Array) {
  let exif: ExifValues = {};
  let xmpBytes = 0;
  let offset = 2;
  let endMarker = -1;
  while (offset < bytes.length && bytes[offset] === 0xff) {
    while (offset < bytes.length && bytes[offset] === 0xff) offset++;
    if (offset >= bytes.length) break;
    const marker = bytes[offset++];
    if (marker === undefined) break;
    if (marker === 0xd9) {
      endMarker = offset;
      break;
    }
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
    if (offset + 2 > bytes.length) break;
    const size = (bytes[offset] ?? 0) * 256 + (bytes[offset + 1] ?? 0);
    if (size < 2 || offset + size > bytes.length) break;
    if (marker === 0xda) {
      endMarker = findJpegEnd(bytes, offset + size);
      break;
    }
    if (marker === 0xe1) {
      const payload = offset + 2;
      const header = decoder.decode(bytes.subarray(payload, Math.min(bytes.length, payload + 29)));
      if (!hasExif(exif) && header.startsWith("Exif")) exif = readExifBlob(bytes, payload, size - 2);
      if (header.includes("http://ns.adobe.com/xap")) xmpBytes += size - 2;
    }
    offset += size;
  }
  return {
    exif,
    xmpBytes,
    trailing: endMarker < 0 ? null : bytes.length - endMarker,
    trailingBytes: endMarker < 0 ? null : bytes.subarray(endMarker),
    hasEnd: endMarker >= 0,
  };
}

function inspectPng(bytes: Uint8Array) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 8;
  let endMarker = -1;
  let textBytes = 0;
  let exif: ExifValues = {};
  const textFields: string[] = [];
  while (offset + 12 <= bytes.length) {
    const length = view.getUint32(offset);
    if (length > bytes.length - offset - 12) break;
    const type = decoder.decode(bytes.subarray(offset + 4, offset + 8));
    const data = offset + 8;
    if (["tEXt", "iTXt", "zTXt"].includes(type)) {
      textBytes += length;
      const text = bytes.subarray(data, Math.min(data + length, data + 79));
      const name = (decoder.decode(text).split("\0")[0] ?? "").trim();
      if (name) textFields.push(name);
    }
    if (type === "eXIf" && !hasExif(exif)) exif = readExifBlob(bytes, data, length);
    offset += length + 12;
    if (type === "IEND") {
      endMarker = offset;
      break;
    }
  }
  return {
    exif,
    trailing: endMarker < 0 ? null : bytes.length - endMarker,
    trailingBytes: endMarker < 0 ? null : bytes.subarray(endMarker),
    hasEnd: endMarker >= 0,
    textBytes,
    textFields,
  };
}

function inspectWebp(bytes: Uint8Array) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 12;
  let exif: ExifValues = {};
  let xmpBytes = 0;
  while (offset + 8 <= bytes.length) {
    const type = decoder.decode(bytes.subarray(offset, offset + 4));
    const size = view.getUint32(offset + 4, true);
    const data = offset + 8;
    if (size > bytes.length - data) break;
    if (type === "EXIF" && !hasExif(exif)) exif = readExifBlob(bytes, data, size);
    if (type === "XMP ") xmpBytes += size;
    offset = data + size + (size & 1);
  }
  return { exif, xmpBytes };
}

async function inspectPixels(file: File, format: string) {
  try {
    const bitmap = await createImageBitmap(file);
    const width = bitmap.width;
    const height = bitmap.height;
    const longest = Math.max(width, height);
    const sampleWidth =
      longest <= PIXEL_SAMPLE_EDGE ? width : Math.max(1, Math.round((width / longest) * PIXEL_SAMPLE_EDGE));
    const sampleHeight =
      longest <= PIXEL_SAMPLE_EDGE
        ? height
        : Math.max(1, Math.round((height / longest) * PIXEL_SAMPLE_EDGE));
    const sampledDown = sampleWidth !== width || sampleHeight !== height;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, sampleWidth);
    canvas.height = Math.max(1, sampleHeight);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) {
      bitmap.close();
      return { width, height, findings: [] as Finding[] };
    }
    context.imageSmoothingEnabled = false;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let sampled = 0;
    let transparent = 0;
    const lsb = [0, 0, 0];
    let luminance = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i + 3] === 0) {
        transparent++;
        continue;
      }
      sampled++;
      for (let channel = 0; channel < 3; channel++)
        lsb[channel] = (lsb[channel] ?? 0) + ((pixels[i + channel] ?? 0) & 1);
      luminance +=
        0.2126 * (pixels[i] ?? 0) + 0.7152 * (pixels[i + 1] ?? 0) + 0.0722 * (pixels[i + 2] ?? 0);
    }
    const sampleDetail = sampledDown
      ? `Nearest-neighbor sample of original pixels, ${canvas.width} × ${canvas.height}`
      : `Original pixels, ${canvas.width} × ${canvas.height}`;
    const findings: Finding[] = [
      {
        label: "Pixels sampled",
        value: sampled.toLocaleString(),
        detail: sampleDetail,
      },
      {
        label: "Average brightness",
        value: sampled ? `${Math.round(luminance / sampled)} of 255` : "Unavailable",
        detail: "A simple visual measurement",
      },
    ];
    if (transparent)
      findings.push({
        label: "Transparent pixels",
        value: `${Math.round((transparent / (sampled + transparent)) * 100)}%`,
        detail: "Share of sampled pixels with zero opacity",
      });
    if (format === "PNG" || format === "BMP") {
      findings.push({
        label: "Last-bit balance",
        value: lsb
          .map((count) => (sampled ? `${Math.round((count / sampled) * 100)}%` : "—"))
          .join(" · "),
        detail: sampledDown
          ? "Red, green, blue from unsmoothed original pixels. Balance alone does not identify hidden data."
          : "Red, green, blue from the original pixels. Balance alone does not identify hidden data.",
      });
    } else {
      findings.push({
        label: "Hidden-bit check",
        value: "Not conclusive",
        detail: "Decoded pixels cannot prove or rule out steganography.",
      });
    }
    return { width, height, findings };
  } catch {
    return {
      width: null,
      height: null,
      findings: [
        {
          label: "Pixel preview",
          value: "Unavailable",
          detail: "This browser could not decode the image.",
        },
      ],
    };
  }
}

export type ContainerReport = {
  format: string;
  flags: string[];
  score: number;
  structure: Finding[];
  exif: ExifValues;
  exifNotes: string[];
  payload: FilePayload;
  xmpBytes: number;
};

const EMPTY_PAYLOAD: FilePayload = { kind: "none", text: null };

function looksLikeText(bytes: Uint8Array) {
  if (!bytes.length) return null;
  let bad = 0;
  for (const byte of bytes) {
    if (byte === 9 || byte === 10 || byte === 13) continue;
    if (byte < 32 || byte === 127) bad++;
  }
  if (bad / bytes.length > 0.05) return null;
  const text = decoder.decode(bytes).replace(/\0/g, "").trim();
  if (text.length < 4 || !/[A-Za-z]/.test(text)) return null;
  return text.slice(0, 400);
}

function tryBase64(bytes: Uint8Array) {
  const raw = decoder.decode(bytes).replace(/\s+/g, "");
  if (raw.length < 8 || raw.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(raw)) return null;
  try {
    const binary = atob(raw);
    const decoded = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) decoded[i] = binary.charCodeAt(i);
    return looksLikeText(decoded);
  } catch {
    return null;
  }
}

function entropy(bytes: Uint8Array) {
  const counts = new Array<number>(256).fill(0);
  for (const byte of bytes) counts[byte] = (counts[byte] ?? 0) + 1;
  let total = 0;
  for (const count of counts) {
    if (!count) continue;
    const p = count / bytes.length;
    total -= p * Math.log2(p);
  }
  return total;
}

export function classifyPayload(bytes: Uint8Array | null): FilePayload {
  if (!bytes || !bytes.length) return EMPTY_PAYLOAD;
  const text = looksLikeText(bytes);
  const encoded = tryBase64(bytes);
  if (encoded && encoded !== text) return { kind: "encoded", text: encoded };
  if (text) return { kind: "text", text };
  if (bytes.length <= TRAILING_FLAG_BYTES) return { kind: "padding", text: null };
  const unique = new Set(bytes).size;
  const maxEntropy = Math.min(8, Math.log2(bytes.length));
  if (unique >= 16 && entropy(bytes) / maxEntropy >= 0.9) return { kind: "locked", text: null };
  return { kind: "binary", text: null };
}

export function inspectContainer(bytes: Uint8Array, fileName: string): ContainerReport {
  const format = detectFormat(bytes);
  const expected = extensionFormat(fileName);
  const jpeg = format === "JPEG" ? inspectJpeg(bytes) : null;
  const png = format === "PNG" ? inspectPng(bytes) : null;
  const webp = format === "WebP" ? inspectWebp(bytes) : null;
  const exif = jpeg?.exif ?? png?.exif ?? webp?.exif ?? {};
  const trailing = jpeg?.trailing ?? png?.trailing ?? null;
  const payload = classifyPayload(jpeg?.trailingBytes ?? png?.trailingBytes ?? null);
  const xmpBytes = jpeg?.xmpBytes ?? webp?.xmpBytes ?? 0;
  const exifNotes = [...(exif.notes ?? [])];
  const messages: string[] = [];
  const codes: FlagCode[] = [];
  const structure: Finding[] = [
    {
      label: "File signature",
      value: format,
      detail: "Identified from the opening bytes, not the filename",
    },
    {
      label: "Filename extension",
      value: expected,
      detail:
        expected === format ? "Matches the file signature" : "Does not match the detected format",
    },
  ];
  if (expected !== "Unknown" && format !== "Unknown" && expected !== format) {
    messages.push("The filename extension does not match the file signature.");
    codes.push("extension");
    exifNotes.push("Filename does not match the file type.");
  }
  if (trailing !== null) {
    const padding = trailing > 0 && trailing <= TRAILING_FLAG_BYTES;
    structure.push({
      label: "Data after image end",
      value: formatBytes(trailing),
      detail: trailing
        ? padding
          ? "A few padding bytes after the image end. Not treated as a review flag."
          : "Bytes found after the image end marker"
        : "No trailing bytes found",
    });
    if (trailing > TRAILING_FLAG_BYTES) {
      messages.push(`${formatBytes(trailing)} appears after the image end marker.`);
      codes.push("trailing");
    }
  } else {
    structure.push({
      label: "End marker",
      value: format === "JPEG" || format === "PNG" ? "Not found" : "Not checked",
      detail: "Structural end check currently supports JPEG and PNG",
    });
    if ((format === "JPEG" || format === "PNG") && !(jpeg?.hasEnd || png?.hasEnd)) {
      messages.push("The expected image end marker was not found.");
      codes.push("missing-end");
    }
  }
  if (xmpBytes)
    structure.push({
      label: "XMP metadata",
      value: formatBytes(xmpBytes),
      detail: "Embedded description or editing metadata",
    });
  if (png?.textBytes) {
    structure.push({
      label: "PNG text metadata",
      value: formatBytes(png.textBytes),
      detail: png.textFields.length
        ? `Fields: ${png.textFields.slice(0, 5).join(", ")}`
        : "Embedded text chunks",
    });
    if (png.textBytes > 8192) {
      messages.push("PNG text metadata is larger than 8 KB and merits review.");
      codes.push("png-text");
      exifNotes.push("A text field is oversized.");
    }
  }
  if (
    (payload.kind === "text" || payload.kind === "encoded" || payload.kind === "locked" || payload.kind === "binary") &&
    !codes.includes("trailing")
  ) {
    messages.push("Readable or extra data appears after the image end marker.");
    codes.push("trailing");
  }
  return {
    format,
    flags: messages,
    score: Math.min(
      100,
      codes.reduce((total, code) => total + FLAG_WEIGHT[code], 0),
    ),
    structure,
    exif,
    exifNotes,
    payload,
    xmpBytes,
  };
}

function metadataFromExif(exif: ExifValues, file: File): Finding[] {
  const metadata: Finding[] = [
    {
      label: "Browser file type",
      value: file.type || "Not provided",
      detail: "Reported by your device; may be inaccurate",
    },
    { label: "File size", value: formatBytes(file.size), detail: "Size of the selected file" },
  ];
  if (exif.make || exif.model)
    metadata.push({
      label: "Camera",
      value: [exif.make, exif.model].filter(Boolean).join(" "),
      detail: "Claimed by embedded EXIF metadata",
    });
  if (exif.capturedAt)
    metadata.push({
      label: "Capture time",
      value: exif.capturedAt,
      detail: "Claimed by embedded EXIF metadata; timezone may be absent",
    });
  if (exif.software)
    metadata.push({
      label: "Software",
      value: exif.software,
      detail: "Claimed by embedded EXIF metadata",
    });
  if (exif.gps)
    metadata.push({
      label: "GPS coordinates",
      value: `${exif.gps.lat.toFixed(5)}, ${exif.gps.lon.toFixed(5)}`,
      detail: "Claimed by embedded EXIF metadata; verify independently",
    });
  if (!exif.make && !exif.model && !exif.capturedAt && !exif.gps)
    metadata.push({
      label: "Camera EXIF",
      value: "Not found",
      detail: "Checked JPEG, PNG, and WebP metadata. Absence does not mean it was removed.",
    });
  const modified = file.lastModified ? new Date(file.lastModified).toLocaleString() : null;
  if (modified)
    metadata.push({
      label: "Device file date",
      value: modified,
      detail: "Filesystem date, not necessarily capture time",
    });
  return metadata;
}

export async function analyzeImage(
  file: File,
  onStage?: (stage: string) => void,
): Promise<ImageAnalysis> {
  if (file.size > MAX_IMAGE_BYTES) throw new Error("This image is over 40 MB.");
  onStage?.("Reading file bytes");
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  onStage?.("Checking metadata and file structure");
  const container = inspectContainer(bytes, file.name);
  const metadata = metadataFromExif(container.exif, file);
  onStage?.("Measuring visible pixels");
  const image = await inspectPixels(file, container.format);
  if (image.width && image.height)
    metadata.unshift({
      label: "Dimensions",
      value: `${image.width} × ${image.height}`,
      detail: "Decoded image width and height",
    });
  onStage?.("Creating file fingerprint");
  const hash = bytesToHex(new Uint8Array(await crypto.subtle.digest("SHA-256", buffer)));
  const modified = file.lastModified ? new Date(file.lastModified).toLocaleString() : null;
  const summary = container.flags.length
    ? `${file.name} has ${container.flags.length} structural item${container.flags.length === 1 ? "" : "s"} to review: ${container.flags.join(" ")} These findings do not prove hidden content. Keep the original file and examine the flagged bytes or metadata in a dedicated forensic tool.`
    : `${file.name} was opened and measured in this browser. Its basic file structure shows no flagged mismatch or trailing data in the checks available for ${container.format}. That does not rule out editing or hidden content. Keep the original file for further review.`;
  return {
    fileName: file.name,
    fileSize: file.size,
    format: container.format,
    mimeType: file.type || "Unknown",
    width: image.width,
    height: image.height,
    sha256: hash,
    fileModified: modified,
    metadata,
    structure: container.structure,
    pixels: image.findings,
    flags: container.flags,
    score: container.score,
    exifNotes: container.exifNotes,
    payload: container.payload,
    summary,
    gps: container.exif.gps ?? null,
    capturedAt: container.exif.capturedAt ?? null,
  };
}
