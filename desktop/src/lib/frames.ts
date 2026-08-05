import type { Frame } from "@/lib/api";

export type TextSource = "a11y" | "ocr" | "none";

export function textOf(f: Frame): string {
    return (f.a11y_text || "").trim() || (f.ocr_text || "").trim() || "";
}

export function srcOf(f: Frame): TextSource {
    return (f.a11y_text || "").trim() ? "a11y" : (f.ocr_text || "").trim() ? "ocr" : "none";
}