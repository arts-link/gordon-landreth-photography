#!/usr/bin/env python3
"""
ocr_pages.py

Detect candidate light rectangular regions, OCR likely caption areas, and write a single JSON array (one object per page).
"""

import json
import re
from pathlib import Path
import argparse
import base64

import cv2
import numpy as np
import pytesseract
import yaml
from openai import OpenAI

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
DEBUG_FILTERS = False  # set False to disable verbose filter logging


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


def has_excessive_repetition(text: str) -> bool:
    """Detect LLM hallucinations with excessive character repetition.

    Returns True if text has too many repeated characters (e.g., "Nannnnnccceeee").
    Allows reasonable patterns like "...", "---", etc.
    """
    # Count sequences of 4+ repeated characters (excluding common patterns)
    repetition_pattern = r'([a-zA-Z])\1{3,}'  # Same letter 4+ times in a row
    matches = re.findall(repetition_pattern, text)

    if len(matches) >= 3:  # Multiple sequences of repeated chars
        return True

    # Check for very long repetition sequences
    long_repetition = r'([a-zA-Z])\1{6,}'
    if re.search(long_repetition, text):
        return True

    return False


def detect_llm_duplication(text: str) -> str:
    """Detect and truncate LLM output when it starts repeating with errors.

    Example: "Large farm... Large ffararm..." -> "Large farm..."
    """
    # Split into sentences
    sentences = re.split(r'([.!?]\s+)', text)

    if len(sentences) < 3:
        return text

    # Reconstruct sentences with their delimiters
    reconstructed = []
    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        delimiter = sentences[i+1] if i+1 < len(sentences) else ""

        # Check if this sentence looks like a corrupted version of a previous sentence
        for prev_idx in range(len(reconstructed)):
            prev_sent = reconstructed[prev_idx]
            # If sentences are similar length and share many words, likely duplication
            words_curr = set(re.findall(r'\b[a-zA-Z]{4,}\b', sentence.lower()))
            words_prev = set(re.findall(r'\b[a-zA-Z]{4,}\b', prev_sent.lower()))

            if words_curr and words_prev:
                overlap = len(words_curr & words_prev) / max(len(words_curr), len(words_prev))
                if overlap > 0.5:  # More than 50% word overlap
                    # Likely hallucination started - truncate here
                    return "".join(reconstructed).strip()

        reconstructed.append(sentence + delimiter)

    return "".join(reconstructed).strip()


# Helper: filter noisy OCR lines from text blocks
def filter_text_lines(text: str) -> str:
    """Keep only lines that look like real caption text; drop noisy OCR lines."""
    # First, clean up LLM hallucinations by detecting sentence duplication
    text = detect_llm_duplication(text)

    lines = [ln.strip() for ln in text.splitlines()]
    kept: list[str] = []

    for ln in lines:
        if not ln:
            continue

        # Reject lines with excessive character repetition (LLM hallucination)
        if has_excessive_repetition(ln):
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

        # Date/header exception: allow valid-looking short captions
        # Examples: "November, 1947", "Eden Mill", "Lancaster County"
        is_valid_short = False
        if len(words3) >= 1 and total >= 8 and total <= 50:
            # Has proper capitalization and reasonable punctuation
            has_capital = any(ch.isupper() for ch in ln)
            punct_ratio = sym / max(1, total)
            if has_capital and punct_ratio < 0.20:
                is_valid_short = True

        if strict_ok or is_valid_short:
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


def init_llm_client(port: int) -> OpenAI | None:
    """Initialize OpenAI client pointing to LM Studio."""
    try:
        client = OpenAI(
            base_url=f"http://localhost:{port}/v1",
            api_key="not-needed"  # LM Studio doesn't require API key
        )

        # Test connection
        models = client.models.list()
        model_ids = [m.id for m in models.data]
        print(f"Connected to LM Studio. Available models: {model_ids}")
        return client
    except Exception as e:
        print(f"Failed to connect to LM Studio: {e}")
        print("Make sure LM Studio is running with server started.")
        return None


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


def ocr_crop_llm(img_bgr: np.ndarray, client: OpenAI, model: str, filename: str = "", crop_id: str = "") -> str:
    """Use LM Studio vision model to extract caption text from image crop."""

    # Convert BGR to RGB for proper encoding
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    # Encode as JPEG base64
    _, buffer = cv2.imencode('.jpg', img_rgb)
    img_base64 = base64.b64encode(buffer).decode('utf-8')

    # Include filename in prompt for LM Studio logs visibility
    context = f"[{filename} - {crop_id}] " if filename or crop_id else ""

    # Optimized prompt for caption extraction
    prompt = f"""{context}You are an OCR assistant. Extract the typed or handwritten caption text from this photo album page.

Output ONLY the raw caption text. DO NOT:
- Describe what you see in photos
- Say "no caption" or "no visible text"
- Add explanations or notes
- Write anything except the actual caption text

If you see no caption text, respond with just a period: .

Examples:
- Good: "Trip to Florida, 1932"
- Good: .
- Bad: "There is no caption visible"
- Bad: "(No visible caption)"

Caption:"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_base64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500,
            temperature=0.1  # Low temperature for deterministic output
        )

        text = response.choices[0].message.content.strip()

        # Filter out common LLM chattiness patterns
        if text == ".":
            return ""

        # Remove common refusal/explanation patterns
        refusal_patterns = [
            "there is no",
            "no visible",
            "no discernible",
            "caption text:",
            "the image appears",
            "this photo",
            "however,",
            "therefore,",
            "based on your rules"
        ]

        text_lower = text.lower()
        if any(pattern in text_lower for pattern in refusal_patterns):
            # If the whole response is just an explanation, return empty
            if len(text) < 200 and text.count('\n') < 3:
                return ""

        return clean_text(text)

    except Exception as e:
        print(f"LLM OCR failed: {e}")
        print("Falling back to Tesseract...")
        # Fallback to Tesseract
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        config = f"--psm {PSM} -c preserve_interword_spaces=1"
        text = pytesseract.image_to_string(bw, lang=LANG, config=config)
        return clean_text(text)


def ocr_crop(img_bgr: np.ndarray, llm_client: OpenAI | None = None, llm_model: str | None = None, filename: str = "", crop_id: str = "") -> str:
    """Extract text from cropped image region (Tesseract or LLM)."""

    # Use LLM if available
    if llm_client and llm_model:
        return ocr_crop_llm(img_bgr, llm_client, llm_model, filename, crop_id)

    # Otherwise use Tesseract (existing code)
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


def parse_album_metadata(album_dir: Path) -> dict:
    """Extract title, weight, menus from index.md frontmatter."""
    index_file = album_dir / "index.md"
    if not index_file.exists():
        return {"title": album_dir.name, "weight": 0}

    content = index_file.read_text(encoding='utf-8')

    # Extract YAML frontmatter between --- markers
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1])
                return {
                    "title": frontmatter.get("title", album_dir.name),
                    "weight": frontmatter.get("weight", 0),
                    "menus": frontmatter.get("menus", "")
                }
            except yaml.YAMLError:
                pass

    return {"title": album_dir.name, "weight": 0}


def make_relative_path(image_path: Path, content_dir: Path) -> str:
    """Convert absolute path to Hugo-compatible relative path."""
    try:
        return str(image_path.relative_to(content_dir))
    except ValueError:
        # Fallback if path is not relative to content_dir
        return str(image_path)


def generate_album_slug(album_folder_name: str) -> str:
    """Convert album folder name to Hugo URL slug format.

    Hugo's default URL generation:
    - Converts to lowercase
    - Replaces " & " with double dashes
    - Removes all apostrophe variants (straight and curly quotes)
    - Replaces spaces with hyphens
    - Preserves special chars like periods, plus signs, etc.

    Examples:
      "1931-1939 courting & marriage" → "1931-1939-courting--marriage"
      "1947 Nov. '47- May '48 covered bridges+" → "1947-nov.-47--may-48-covered-bridges+"
      "1968-1969 Louise's marriage" → "1968-1969-louises-marriage"
      "1964-1966 Kathy's marriage" → "1964-1966-kathys-marriage"
    """
    slug = album_folder_name.lower()

    # Replace & with -- (double dash) BEFORE replacing spaces
    slug = slug.replace(' & ', '--')

    # Remove ALL apostrophe variants (ASCII and Unicode)
    # U+0027: APOSTROPHE (straight apostrophe)
    # U+2018: LEFT SINGLE QUOTATION MARK (curly apostrophe)
    # U+2019: RIGHT SINGLE QUOTATION MARK (curly apostrophe)
    # U+201B: SINGLE HIGH-REVERSED-9 QUOTATION MARK (rare variant)
    slug = slug.replace("'", '')           # U+0027
    slug = slug.replace("\u2018", '')      # U+2018
    slug = slug.replace("\u2019", '')      # U+2019
    slug = slug.replace("\u201b", '')      # U+201B

    # Replace spaces with single dashes
    slug = slug.replace(' ', '-')

    return slug


def process_album(album_dir: Path, content_dir: Path, llm_client: OpenAI | None = None, llm_model: str | None = None) -> list[dict]:
    """Process all images in a single album directory and return page records."""
    images = sorted([p for p in album_dir.iterdir() if is_real_image_file(p)])

    if LIMIT_PAGES is not None:
        images = images[: int(LIMIT_PAGES)]

    all_records = []

    for p in images:
        img = cv2.imread(str(p))
        if img is None:
            print(f"{p.name}: unreadable (skipped)")
            continue

        thr = preprocess_for_boxes(img)
        boxes = find_candidate_boxes(thr)

        # Log which image is being processed
        print(f"Processing {p.name} ({len(boxes)} regions detected)...")

        # Additional LLM mode indicator
        if llm_client:
            print(f"  [Using LLM mode]")

        blocks = []
        for crop_idx, (x, y, w, h) in enumerate(boxes, 1):
            crop = img[y : y + h, x : x + w]

            # Geometry-based rejection: drop likely photo regions
            ih, iw = img.shape[:2]
            area_frac = (w * h) / float(iw * ih)

            # Log crop being processed
            crop_id = f"crop_{crop_idx}"
            if llm_client:
                print(f"  -> {crop_id} @ ({x},{y},{w}x{h})")

            # Very large regions are almost never captions
            if area_frac > 0.14:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: area too large ({area_frac:.3f} > 0.14)")
                continue

            # Photo blocks tend to be tall; caption strips tend to be short.
            # We'll allow tall regions only if OCR text is very dense.
            is_tall = (h / float(ih)) > 0.22 and (w / float(iw)) > 0.40

            text = ocr_crop(crop, llm_client=llm_client, llm_model=llm_model, filename=p.name, crop_id=crop_id)

            if DEBUG_FILTERS and text:
                print(f"     [OCR] {crop_id}: \"{text[:80]}{'...' if len(text) > 80 else ''}\"")

            # Line-level cleanup: drop garbage lines within otherwise-good blocks
            text = filter_text_lines(text)
            if not text:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: no text after line filtering")
                continue

            # Block-level guard: require at least a couple substantial words overall
            block_words3 = re.findall(r"[A-Za-z]{3,}", text)
            block_words4 = [w for w in block_words3 if len(w) >= 4]

            # Check if this is a valid short caption (dates, place names, headers)
            is_valid_short_block = False
            if len(text) >= 8 and len(text) <= 50 and len(block_words3) >= 1:
                # Has proper capitalization
                has_capital = any(ch.isupper() for ch in text)
                # Reasonable punctuation ratio
                sym = sum((not ch.isalnum()) and (not ch.isspace()) for ch in text)
                punct_ratio = sym / max(1, len(text))
                if has_capital and punct_ratio < 0.25:
                    is_valid_short_block = True

            if not is_valid_short_block and len(block_words4) < 2 and len(block_words3) < 4:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: insufficient words (words4={len(block_words4)}, words3={len(block_words3)})")
                continue

            # If the region is "tall" (often a photo), require much denser text to keep it
            if is_tall:
                tall_alpha = sum(ch.isalpha() for ch in text)
                tall_total = max(1, len(text))
                if tall_alpha < 80 or (tall_alpha / tall_total) < 0.30:
                    if DEBUG_FILTERS:
                        print(f"     [REJECT] {crop_id}: tall region with sparse text (alpha={tall_alpha}, ratio={tall_alpha/tall_total:.2f})")
                    continue

            # Text-based filtering: keep likely captions, drop obvious photo-garbage OCR
            if len(text) < 4:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: text too short ({len(text)} chars)")
                continue

            alpha = sum(ch.isalpha() for ch in text)
            alnum = sum(ch.isalnum() for ch in text)
            total = max(1, len(text))

            # Require at least a few letters
            if alpha < 4:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: too few letters (alpha={alpha})")
                continue

            # Require a minimal letter/alnum ratio (captions are mostly words)
            if (alpha / total) < 0.12:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: low alpha ratio ({alpha}/{total}={alpha/total:.2f})")
                continue
            if (alnum / total) < 0.12:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: low alnum ratio ({alnum}/{total}={alnum/total:.2f})")
                continue

            # Word-shape heuristics: captions usually have multiple "real" words
            words = [w for w in re.split(r"\s+", text) if w]
            long_words = [w for w in words if len(re.sub(r"[^A-Za-z]", "", w)) >= 3]
            if len(long_words) < 1 and alpha >= 18:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: no long words despite {alpha} letters")
                continue

            # Drop blocks with too many very short lines (common in noisy OCR)
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines:
                short_lines = sum(1 for ln in lines if len(ln) <= 2)
                if (short_lines / len(lines)) > 0.60:
                    if DEBUG_FILTERS:
                        print(f"     [REJECT] {crop_id}: too many short lines ({short_lines}/{len(lines)})")
                    continue

            if DEBUG_FILTERS:
                print(f"     [ACCEPT] {crop_id}: \"{text[:60]}{'...' if len(text) > 60 else ''}\"")

            blocks.append(
                {
                    "bbox": [int(x), int(y), int(x + w), int(y + h)],
                    "text": text,
                }
            )

        blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

        # Create captions array from blocks
        captions = [b["text"] for b in blocks]

        record = {
            "filename": p.name,
            "path": make_relative_path(p, content_dir),
            "blocks": blocks,
            "full_text": clean_text("\n\n".join(b["text"] for b in blocks)),
            "captions": captions,
            "caption_text": clean_text("\n\n".join(captions)),
        }

        all_records.append(record)
        print(f"{p.name}: {len(blocks)} text blocks")

    return all_records


def process_albums_batch(content_dir: Path, search_index_path: Path, use_llm: bool = False, llm_port: int = 1234, llm_model: str = "minicpm-v-2.6") -> None:
    """
    Process all album subdirectories in content_dir.

    For each album:
    1. Find album folder (contains index.md)
    2. Extract album metadata from frontmatter
    3. Run OCR on all images in album
    4. Save per-album JSON: album/ocr_captions.json
    5. Collect data for merged search index

    Finally, write merged search index.
    """
    content_dir = Path(content_dir)
    search_index_path = Path(search_index_path)

    # Initialize LLM client if requested
    llm_client = None
    if use_llm:
        print(f"Initializing LM Studio client (port {llm_port})...")
        llm_client = init_llm_client(llm_port)
        if llm_client:
            print(f"Using LLM model: {llm_model}")
        else:
            print("LLM initialization failed. Falling back to Tesseract.")

    # Ensure output directory exists
    search_index_path.parent.mkdir(parents=True, exist_ok=True)

    # Find all album directories (contain index.md)
    album_dirs = [d for d in content_dir.iterdir()
                  if d.is_dir() and (d / "index.md").exists()]

    album_dirs.sort(key=lambda d: d.name)

    # For testing: limit number of albums if LIMIT_PAGES is set
    if LIMIT_PAGES is not None and LIMIT_PAGES < 10:
        album_dirs = album_dirs[:3]  # Only process first 3 albums when testing
        print(f"[TEST MODE] Processing only {len(album_dirs)} albums")

    print(f"Found {len(album_dirs)} albums to process")

    all_search_entries = []

    for album_dir in album_dirs:
        print(f"\n{'='*60}")
        print(f"Processing album: {album_dir.name}")
        print(f"{'='*60}")

        # Extract metadata
        metadata = parse_album_metadata(album_dir)

        # Process album
        album_records = process_album(album_dir, content_dir, llm_client=llm_client, llm_model=llm_model)

        # Save per-album JSON
        album_json_path = album_dir / "ocr_captions.json"
        album_data = {
            "album": album_dir.name,
            "album_title": metadata.get("title", album_dir.name),
            "album_weight": metadata.get("weight", 0),
            "pages": album_records
        }

        album_json_path.write_text(
            json.dumps(album_data, ensure_ascii=False, indent=2, default=json_default),
            encoding="utf-8"
        )

        print(f"Saved to: {album_json_path}")

        # Generate album URL slug for search index
        album_slug = generate_album_slug(album_dir.name)

        # Add album entry to search index
        all_search_entries.append({
            "type": "album",
            "album": album_dir.name,
            "album_title": metadata.get("title", album_dir.name),
            "album_url_slug": album_slug,
            "album_path": album_dir.name + "/",
            "searchable_text": metadata.get("title", album_dir.name)
        })

        # Sort pages by filename (matches Hugo gallery default sorting)
        sorted_pages = sorted(album_records, key=lambda p: p.get("filename", ""))

        # Add page entries to search index with image indices
        for idx, page in enumerate(sorted_pages):
            captions = page.get("captions", [])
            all_search_entries.append({
                "type": "page",
                "album": album_dir.name,
                "album_title": metadata.get("title", album_dir.name),
                "album_url_slug": album_slug,
                "page_filename": page.get("filename", ""),
                "page_path": page.get("path", ""),
                "image_index": idx,  # 0-based DOM position in gallery
                "captions": captions,
                "searchable_text": " ".join(captions) + " " + page.get("filename", "")
            })

    # Write merged search index
    search_index_path.write_text(
        json.dumps(all_search_entries, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8"
    )

    print(f"\n{'='*60}")
    print(f"Batch processing complete!")
    print(f"Processed {len(album_dirs)} albums")
    print(f"Search index: {search_index_path}")
    print(f"Total entries: {len(all_search_entries)}")
    print(f"{'='*60}")


def main(
    in_dir: str | None = None,
    out_path: str | None = None,
    captions_out_path: str | None = None,
    batch_mode: bool = False,
    search_index_path: str | None = None,
    use_llm: bool = False,
    llm_port: int = 1234,
    llm_model: str = "minicpm-v-2.6",
    llm_client: OpenAI | None = None
) -> None:
    if batch_mode:
        if not in_dir or not search_index_path:
            raise ValueError("Batch mode requires both input directory and search index path")
        process_albums_batch(Path(in_dir), Path(search_index_path), use_llm, llm_port, llm_model)
        return

    # Legacy single-album mode
    if not in_dir or not out_path:
        raise ValueError("Single album mode requires input_folder and output_json")

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
        for crop_idx, (x, y, w, h) in enumerate(boxes, 1):
            crop = img[y : y + h, x : x + w]

            # Geometry-based rejection: drop likely photo regions
            ih, iw = img.shape[:2]
            area_frac = (w * h) / float(iw * ih)

            crop_id = f"crop_{crop_idx}"

            # Very large regions are almost never captions
            if area_frac > 0.14:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: area too large ({area_frac:.3f} > 0.14)")
                continue

            # Photo blocks tend to be tall; caption strips tend to be short.
            # We'll allow tall regions only if OCR text is very dense.
            is_tall = (h / float(ih)) > 0.22 and (w / float(iw)) > 0.40

            text = ocr_crop(crop, llm_client=llm_client, llm_model=llm_model, filename=p.name, crop_id=crop_id)

            if DEBUG_FILTERS and text:
                print(f"     [OCR] {crop_id}: \"{text[:80]}{'...' if len(text) > 80 else ''}\"")

            # Line-level cleanup: drop garbage lines within otherwise-good blocks
            text = filter_text_lines(text)
            if not text:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: no text after line filtering")
                continue

            # Block-level guard: require at least a couple substantial words overall
            block_words3 = re.findall(r"[A-Za-z]{3,}", text)
            block_words4 = [w for w in block_words3 if len(w) >= 4]

            # Check if this is a valid short caption (dates, place names, headers)
            is_valid_short_block = False
            if len(text) >= 8 and len(text) <= 50 and len(block_words3) >= 1:
                # Has proper capitalization
                has_capital = any(ch.isupper() for ch in text)
                # Reasonable punctuation ratio
                sym = sum((not ch.isalnum()) and (not ch.isspace()) for ch in text)
                punct_ratio = sym / max(1, len(text))
                if has_capital and punct_ratio < 0.25:
                    is_valid_short_block = True

            if not is_valid_short_block and len(block_words4) < 2 and len(block_words3) < 4:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: insufficient words (words4={len(block_words4)}, words3={len(block_words3)})")
                continue

            # If the region is "tall" (often a photo), require much denser text to keep it
            if is_tall:
                tall_alpha = sum(ch.isalpha() for ch in text)
                tall_total = max(1, len(text))
                if tall_alpha < 80 or (tall_alpha / tall_total) < 0.30:
                    if DEBUG_FILTERS:
                        print(f"     [REJECT] {crop_id}: tall region with sparse text (alpha={tall_alpha}, ratio={tall_alpha/tall_total:.2f})")
                    continue

            # Text-based filtering: keep likely captions, drop obvious photo-garbage OCR
            if len(text) < 4:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: text too short ({len(text)} chars)")
                continue

            alpha = sum(ch.isalpha() for ch in text)
            alnum = sum(ch.isalnum() for ch in text)
            total = max(1, len(text))

            # Require at least a few letters
            if alpha < 4:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: too few letters (alpha={alpha})")
                continue

            # Require a minimal letter/alnum ratio (captions are mostly words)
            if (alpha / total) < 0.12:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: low alpha ratio ({alpha}/{total}={alpha/total:.2f})")
                continue
            if (alnum / total) < 0.12:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: low alnum ratio ({alnum}/{total}={alnum/total:.2f})")
                continue

            # Word-shape heuristics: captions usually have multiple "real" words
            words = [w for w in re.split(r"\s+", text) if w]
            long_words = [w for w in words if len(re.sub(r"[^A-Za-z]", "", w)) >= 3]
            if len(long_words) < 1 and alpha >= 18:
                if DEBUG_FILTERS:
                    print(f"     [REJECT] {crop_id}: no long words despite {alpha} letters")
                continue

            # Drop blocks with too many very short lines (common in noisy OCR)
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines:
                short_lines = sum(1 for ln in lines if len(ln) <= 2)
                if (short_lines / len(lines)) > 0.60:
                    if DEBUG_FILTERS:
                        print(f"     [REJECT] {crop_id}: too many short lines ({short_lines}/{len(lines)})")
                    continue

            if DEBUG_FILTERS:
                print(f"     [ACCEPT] {crop_id}: \"{text[:60]}{'...' if len(text) > 60 else ''}\"")

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
        description="OCR album pages to JSON. Supports both single-album and batch processing modes."
    )

    # Batch mode arguments
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all albums in the content directory"
    )
    parser.add_argument(
        "--search-index",
        dest="search_index",
        default=None,
        help="Path for merged search index JSON (required with --batch)"
    )

    # Legacy single-album arguments
    parser.add_argument(
        "input_folder",
        nargs="?",
        help="Folder containing page images (single album mode) or content directory (batch mode)"
    )
    parser.add_argument(
        "output_json",
        nargs="?",
        help="Primary output JSON (single album mode only)"
    )
    parser.add_argument(
        "--captions-out",
        dest="captions_out",
        default=None,
        help="Optional: write a caption-only JSON view (single album mode only)"
    )

    # LLM integration arguments
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LM Studio vision model instead of Tesseract for OCR (slower but more accurate)"
    )
    parser.add_argument(
        "--llm-port",
        type=int,
        default=1234,
        help="LM Studio server port (default: 1234)"
    )
    parser.add_argument(
        "--llm-model",
        default="minicpm-v-2.6",
        help="LM Studio model name (default: minicpm-v-2.6)"
    )

    args = parser.parse_args()

    main(
        in_dir=args.input_folder,
        out_path=args.output_json,
        captions_out_path=args.captions_out,
        batch_mode=args.batch,
        search_index_path=args.search_index,
        use_llm=args.use_llm,
        llm_port=args.llm_port,
        llm_model=args.llm_model
    )