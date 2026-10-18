import { describe, expect, it } from "vitest";

import {
  classifyPayload,
  detectFormat,
  formatExifDate,
  inspectContainer,
  sniffImage,
} from "@/components/evidex/analyzeImage";
import { reportFromAnalysis, suspicionLevel } from "@/lib/scan-report";
import type { ImageAnalysis } from "@/components/evidex/analyzeImage";

function tiffWithMakeAndDate() {
  const make = new TextEncoder().encode("Canon\0");
  const when = new TextEncoder().encode("2026:10:15 16:42:00\0");
  const stringOffset = 38;
  const bytes = new Uint8Array(stringOffset + make.length + when.length);
  const view = new DataView(bytes.buffer);
  bytes[0] = 0x49;
  bytes[1] = 0x49;
  view.setUint16(2, 42, true);
  view.setUint32(4, 8, true);
  view.setUint16(8, 2, true);
  view.setUint16(10, 0x010f, true);
  view.setUint16(12, 2, true);
  view.setUint32(14, make.length, true);
  view.setUint32(18, stringOffset, true);
  view.setUint16(22, 0x0132, true);
  view.setUint16(24, 2, true);
  view.setUint32(26, when.length, true);
  view.setUint32(30, stringOffset + make.length, true);
  bytes.set(make, stringOffset);
  bytes.set(when, stringOffset + make.length);
  return bytes;
}

function jpegWithExif(trailing = 0) {
  const tiff = tiffWithMakeAndDate();
  const header = new TextEncoder().encode("Exif\0\0");
  const payload = header.length + tiff.length;
  const segment = new Uint8Array(4 + payload);
  segment[0] = 0xff;
  segment[1] = 0xe1;
  segment[2] = (payload + 2) >> 8;
  segment[3] = (payload + 2) & 0xff;
  segment.set(header, 4);
  segment.set(tiff, 4 + header.length);
  const bytes = new Uint8Array(2 + segment.length + 2 + trailing);
  bytes[0] = 0xff;
  bytes[1] = 0xd8;
  bytes.set(segment, 2);
  const eoi = 2 + segment.length;
  bytes[eoi] = 0xff;
  bytes[eoi + 1] = 0xd9;
  bytes.fill(0x22, eoi + 2);
  return bytes;
}

function pngChunk(type: string, data: Uint8Array) {
  const chunk = new Uint8Array(12 + data.length);
  const view = new DataView(chunk.buffer);
  view.setUint32(0, data.length);
  chunk.set(new TextEncoder().encode(type), 4);
  chunk.set(data, 8);
  return chunk;
}

describe("formatExifDate", () => {
  it("prints the clock written in the file", () => {
    expect(formatExifDate("2026:10:15 16:42:00")).toBe("Oct 15, 2026 · 4:42 PM");
    expect(formatExifDate("2026:10:15 00:05:09")).toBe("Oct 15, 2026 · 12:05 AM");
  });
});

describe("inspectContainer", () => {
  it("does not flag a few bytes of JPEG padding", () => {
    const bytes = Uint8Array.from([0xff, 0xd8, 0xff, 0xd9, 1, 2, 3, 4]);
    const report = inspectContainer(bytes, "photo.jpg");
    expect(report.format).toBe("JPEG");
    expect(report.flags).toEqual([]);
    expect(report.score).toBe(0);
    expect(report.structure.find((item) => item.label === "Data after image end")?.value).toBe("4 bytes");
  });

  it("flags a large trailer and ignores a later end marker inside it", () => {
    const bytes = Uint8Array.from([
      0xff, 0xd8, 0xff, 0xda, 0x00, 0x02, 0x11, 0x22, 0xff, 0xd9, ...new Array(40).fill(0x11),
      0xff, 0xd9,
    ]);
    const report = inspectContainer(bytes, "photo.jpg");
    expect(report.structure.find((item) => item.label === "Data after image end")?.value).toBe("42 bytes");
    expect(report.flags.some((flag) => flag.includes("after the image end"))).toBe(true);
    expect(report.score).toBe(40);
  });

  it("flags an extension that disagrees with the bytes", () => {
    const report = inspectContainer(Uint8Array.from([0xff, 0xd8, 0xff, 0xd9]), "photo.png");
    expect(report.flags).toEqual(["The filename extension does not match the file signature."]);
    expect(report.score).toBe(30);
  });

  it("reads JPEG EXIF without treating the thumbnail end as the file end", () => {
    const report = inspectContainer(jpegWithExif(), "shot.jpg");
    expect(report.exif.make).toBe("Canon");
    expect(report.exif.capturedAt).toBe("Oct 15, 2026 · 4:42 PM");
    expect(report.score).toBe(0);
  });

  it("reads EXIF stored in a PNG eXIf chunk", () => {
    const signature = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
    const ihdr = pngChunk("IHDR", new Uint8Array(13));
    const exif = pngChunk("eXIf", tiffWithMakeAndDate());
    const iend = pngChunk("IEND", new Uint8Array(0));
    const bytes = new Uint8Array(signature.length + ihdr.length + exif.length + iend.length);
    bytes.set(signature, 0);
    bytes.set(ihdr, signature.length);
    bytes.set(exif, signature.length + ihdr.length);
    bytes.set(iend, signature.length + ihdr.length + exif.length);
    const report = inspectContainer(bytes, "shot.png");
    expect(detectFormat(bytes)).toBe("PNG");
    expect(report.exif.make).toBe("Canon");
    expect(report.exif.capturedAt).toBe("Oct 15, 2026 · 4:42 PM");
  });

  it("reads a WebP EXIF chunk", () => {
    const tiff = tiffWithMakeAndDate();
    const header = new TextEncoder().encode("Exif\0\0");
    const payload = new Uint8Array(header.length + tiff.length);
    payload.set(header, 0);
    payload.set(tiff, header.length);
    const riffSize = 4 + 8 + payload.length;
    const bytes = new Uint8Array(8 + riffSize);
    const view = new DataView(bytes.buffer);
    bytes.set(new TextEncoder().encode("RIFF"), 0);
    view.setUint32(4, riffSize, true);
    bytes.set(new TextEncoder().encode("WEBP"), 8);
    bytes.set(new TextEncoder().encode("EXIF"), 12);
    view.setUint32(16, payload.length, true);
    bytes.set(payload, 20);
    const report = inspectContainer(bytes, "shot.webp");
    expect(report.format).toBe("WebP");
    expect(report.exif.make).toBe("Canon");
  });
});

describe("sniffImage", () => {
  it("accepts a JPEG when the browser leaves the type blank", async () => {
    const file = new File([Uint8Array.from([0xff, 0xd8, 0xff, 0xd9])], "shot.jpg", { type: "" });
    expect(await sniffImage(file)).toBe(true);
  });

  it("rejects a text file without rejecting the rest of a mixed drop by itself", async () => {
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    expect(await sniffImage(file)).toBe(false);
  });
});

describe("reportFromAnalysis", () => {
  it("keeps the pixel check waiting and does not treat padding as suspicious", () => {
    const analysis = {
      fileName: "photo.jpg",
      fileSize: 4,
      format: "JPEG",
      mimeType: "image/jpeg",
      width: 2,
      height: 2,
      sha256: "abc",
      fileModified: null,
      metadata: [{ label: "Camera EXIF", value: "Not found", detail: "" }],
      structure: [
        { label: "File signature", value: "JPEG", detail: "" },
        { label: "Data after image end", value: "4 bytes", detail: "" },
      ],
      pixels: [],
      flags: [],
      score: 0,
      summary: "",
      gps: null,
      capturedAt: null,
      exifNotes: [],
      payload: { kind: "none", text: null },
    } satisfies ImageAnalysis;
    const report = reportFromAnalysis(analysis, null);
    expect(report.evidence.find((item) => item.id === "hidden")?.status).toBe("clean");
    expect(report.evidence.find((item) => item.id === "exif")?.status).toBe("clean");
    expect(report.level).toBe("Clean");
    expect(suspicionLevel(84)).toBe("Suspicious");
  });
});

describe("classifyPayload", () => {
  it("shows readable text and base64, and locks high-entropy bytes", () => {
    const text = new TextEncoder().encode("Meet at the side door");
    const encoded = new TextEncoder().encode(btoa("Meet at noon"));
    const random = Uint8Array.from({ length: 64 }, (_, index) => (index * 47 + 13) & 255);
    expect(classifyPayload(text)).toEqual({ kind: "text", text: "Meet at the side door" });
    expect(classifyPayload(encoded)).toEqual({ kind: "encoded", text: "Meet at noon" });
    expect(classifyPayload(random).kind).toBe("locked");
    expect(classifyPayload(random).text).toBeNull();

    const jpeg = jpegWithExif(0);
    const withText = new Uint8Array(jpeg.length + text.length);
    withText.set(jpeg);
    withText.set(text, jpeg.length);
    expect(inspectContainer(withText, "note.jpg").payload).toEqual({
      kind: "text",
      text: "Meet at the side door",
    });
  });
});
