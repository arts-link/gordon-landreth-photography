#!/usr/bin/env python3
"""
ocr_pages.py

Detect candidate light rectangular regions, OCR likely caption areas, and write a single JSON array (one object per page).
"""

import json
import re
from pathlib import Path
import argparse

import cv2
import numpy as np
import pytesseract

# -------------------------
# Tunables
# -------------------------
MIN_BOX_AREA_FRAC = 0.0008
MAX_BOX_AREA_FRAC = 0.35        # allow larger light regions; we'll reject photo-ish boxes by geometry/text.
MIN_ASPECT = 1.15

THRESH_METHOD = "adaptive"      # "adaptive" or "otsu"

PSM = 6
LANG = "eng"

LIMIT_PAGES = None  # set None for full run


# -------------------------
# Helpers
# -------------------------
def clean_text(s: str) -> str:
    s = s.replace("\x0c", " ")
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# Helper: filter noisy OCR lines from text blocks
def filter_text_lines(text: str) -> str:
    """Keep only lines that look like real caption text; drop noisy OCR lines."""
    lines = [ln.strip() for ln in text.splitlines()]
    kept: list[str] = []

    for ln in lines:
        if not ln:
            continue

        total = len(ln)
        alpha = sum(ch.isalpha() for ch in ln)
        alnum = sum(ch.isalnum() for ch in ln)
        sym = sum((not ch.isalnum()) and (not ch.isspace()) for ch in ln)

        # Require some real letters
        if alpha < 4:
            continue

        # Captions are mostly words
        if (alpha / max(1, total)) < 0.25:
            continue

        # If it's mostly symbols/punct, drop
        if (sym / max(1, total)) > 0.35:
            continue

        # Word-shape checks.
        # Primary rule (strict): require multiple real words (reduces photo/noise OCR)
        words3 = re.findall(r"[A-Za-z]{3,}", ln)
        if not words3:
            continue

        words4 = [w for w in words3 if len(w) >= 4]
        strict_ok = (len(words4) >= 2) or (len(words3) >= 3)

        if strict_ok:
            kept.append(ln)
            continue

        # Continuation rule (permissive): keep short single-word lines that
        # continue a prior kept line (e.g., place names like "Soudersburg." or "Club.").
        if kept:
            prev = kept[-1].rstrip()
            prev_last = prev[-1] if prev else ""
            prev_terminal = prev_last in ".!?"

            # Single real word (or two at most), short line, mostly letters
            is_short_continuation = (len(words3) <= 2 and total <= 24 and (alpha / max(1, total)) >= 0.50)

            if is_short_continuation:
                # Normal case: previous line doesn't look terminal
                if not prev_terminal:
                    kept.append(ln)
                    continue

                # Recovery case: OCR sometimes adds a period to a line that actually continues.
                # Allow continuation if the previous line looks like it introduces a place/name.
                prev_lc = prev.lower()
                looks_like_intro = any(tok in prev_lc.split()[-4:] for tok in [
                    "near", "from", "in", "at", "to", "of", "by", "with"
                ])

                # Also allow if previous ends with ellipsis (common in these captions)
                looks_like_ellipsis = prev.endswith("...")

                # Allow if the continuation line starts with a capitalized word (place/name)
                starts_cap = ln[:1].isupper()

                if looks_like_intro or looks_like_ellipsis or starts_cap:
                    kept.append(ln)
                    continue

        # Otherwise, drop the line
        continue

    return "\n".join(kept).strip()


def preprocess_for_boxes(img_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    if THRESH_METHOD == "adaptive":
        thr = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 5
        )
    else:
        _, thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return thr


def find_candidate_boxes(thr: np.ndarray) -> list[tuple[int, int, int, int]]:
    h, w = thr.shape[:2]
    page_area = h * w

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(thr, connectivity=8)

    boxes: list[tuple[int, int, int, int]] = []

    for i in range(1, num_labels):
        x, y, bw, bh, area = stats[i]
        area_frac = float(area) / float(page_area)

        if area_frac < MIN_BOX_AREA_FRAC or area_frac > MAX_BOX_AREA_FRAC:
            continue

        aspect = float(bw) / float(max(1, bh))
        if aspect < MIN_ASPECT:
            continue

        pad = int(0.01 * min(w, h))
        x0 = max(0, int(x - pad))
        y0 = max(0, int(y - pad))
        x1 = min(w, int(x + bw + pad))
        y1 = min(h, int(y + bh + pad))

        boxes.append((x0, y0, x1 - x0, y1 - y0))

    boxes.sort(key=lambda b: (b[1], b[0]))

    # IoU suppression
    merged: list[tuple[int, int, int, int]] = []
    for b in boxes:
        x, y, bw, bh = b
        x2, y2 = x + bw, y + bh

        keep = True
        for j, m in enumerate(merged):
            mx, my, mw, mh = m
            mx2, my2 = mx + mw, my + mh

            ix1 = max(x, mx)
            iy1 = max(y, my)
            ix2 = min(x2, mx2)
            iy2 = min(y2, my2)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            if inter == 0:
                continue

            union = bw * bh + mw * mh - inter
            iou = inter / max(1, union)

            if iou > 0.25:
                if bw * bh > mw * mh:
                    merged[j] = b
                keep = False
                break

        if keep:
            merged.append(b)

    return merged


def ocr_crop(img_bgr: np.ndarray) -> str:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    config = f"--psm {PSM} -c preserve_interword_spaces=1"
    text = pytesseract.image_to_string(bw, lang=LANG, config=config)
    return clean_text(text)


def json_default(o):
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


# Helper to create a caption-only record for a page
def make_caption_record(record: dict) -> dict:
    """Create a caption-only view for a single page record."""
    captions = [b["text"] for b in record.get("blocks", []) if b.get("text")]
    return {
        "filename": record.get("filename"),
        "path": record.get("path"),
        "captions": captions,
        "caption_text": clean_text("\n\n".join(captions)),
    }


def is_real_image_file(p: Path) -> bool:
    name = p.name
    if name.startswith("._"):
        return False
    if name in {".DS_Store", "Thumbs.db"}:
        return False
    return p.suffix.lower() in {".jpg", ".jpeg", ".png"}


def main(in_dir: str, out_path: str, captions_out_path: str | None = None) -> None:
    in_path = Path(in_dir)
    images = sorted([p for p in in_path.rglob("*") if is_real_image_file(p)])

    if LIMIT_PAGES is not None:
        images = images[: int(LIMIT_PAGES)]

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    total_pages = 0

    all_records = []
    caption_records = []

    for p in images:
        img = cv2.imread(str(p))
        if img is None:
            print(f"{p.name}: unreadable (skipped)")
            continue

        thr = preprocess_for_boxes(img)
        boxes = find_candidate_boxes(thr)

        blocks = []
        for (x, y, w, h) in boxes:
            crop = img[y : y + h, x : x + w]

            # Geometry-based rejection: drop likely photo regions
            ih, iw = img.shape[:2]
            area_frac = (w * h) / float(iw * ih)

            # Very large regions are almost never captions
            if area_frac > 0.14:
                continue

            # Photo blocks tend to be tall; caption strips tend to be short.
            # We'll allow tall regions only if OCR text is very dense.
            is_tall = (h / float(ih)) > 0.22 and (w / float(iw)) > 0.40

            text = ocr_crop(crop)

            # Line-level cleanup: drop garbage lines within otherwise-good blocks
            text = filter_text_lines(text)
            if not text:
                continue

            # Block-level guard: require at least a couple substantial words overall
            block_words3 = re.findall(r"[A-Za-z]{3,}", text)
            block_words4 = [w for w in block_words3 if len(w) >= 4]
            if len(block_words4) < 2 and len(block_words3) < 4:
                continue

            # If the region is "tall" (often a photo), require much denser text to keep it
            if is_tall:
                tall_alpha = sum(ch.isalpha() for ch in text)
                tall_total = max(1, len(text))
                if tall_alpha < 80 or (tall_alpha / tall_total) < 0.30:
                    continue

            # Text-based filtering: keep likely captions, drop obvious photo-garbage OCR
            if len(text) < 4:
                continue

            alpha = sum(ch.isalpha() for ch in text)
            alnum = sum(ch.isalnum() for ch in text)
            total = max(1, len(text))

            # Require at least a few letters
            if alpha < 4:
                continue

            # Require a minimal letter/alnum ratio (captions are mostly words)
            if (alpha / total) < 0.12:
                continue
            if (alnum / total) < 0.12:
                continue

            # Word-shape heuristics: captions usually have multiple "real" words
            words = [w for w in re.split(r"\s+", text) if w]
            long_words = [w for w in words if len(re.sub(r"[^A-Za-z]", "", w)) >= 3]
            if len(long_words) < 1 and alpha >= 18:
                continue

            # Drop blocks with too many very short lines (common in noisy OCR)
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines:
                short_lines = sum(1 for ln in lines if len(ln) <= 2)
                if (short_lines / len(lines)) > 0.60:
                    continue

            blocks.append(
                {
                    "bbox": [int(x), int(y), int(x + w), int(y + h)],
                    "text": text,
                }
            )

        blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

        record = {
            "filename": p.name,
            "path": str(p),
            "blocks": blocks,
            "full_text": clean_text("\n\n".join(b["text"] for b in blocks)),
        }

        all_records.append(record)
        caption_records.append(make_caption_record(record))
        print(f"{p.name}: {len(blocks)} text blocks")
        total_pages += 1

    # Write a single JSON array
    out_file.write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )

    if captions_out_path:
        captions_file = Path(captions_out_path)
        captions_file.parent.mkdir(parents=True, exist_ok=True)
        captions_file.write_text(
            json.dumps(caption_records, ensure_ascii=False, indent=2, default=json_default),
            encoding="utf-8",
        )
        print(f"Wrote caption-only view to {captions_file}")

    print(f"Wrote {total_pages} pages to {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OCR album pages to JSON; optionally also write a caption-only view."
    )
    parser.add_argument("input_folder", help="Folder containing page images")
    parser.add_argument("output_json", help="Primary output JSON (array of page records)")
    parser.add_argument(
        "--captions-out",
        dest="captions_out",
        default=None,
        help="Optional: write a caption-only JSON view to this path",
    )

    args = parser.parse_args()
    main(args.input_folder, args.output_json, args.captions_out)