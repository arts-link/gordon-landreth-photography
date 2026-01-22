

# AI HANDOFF: OCR → Captions → Hugo Search

## Project Summary

This project digitizes typed photo album captions from scanned image pages (1968–1969 Louise’s marriage album, 81 pages total), extracts readable captions via OCR, and prepares them for use in a **static Hugo website search engine**.

The workflow intentionally avoids heavy infrastructure. The result is:
- High-quality caption extraction
- Preserved multi-line caption structure
- A captions-only JSON index
- Client-side search for Hugo

Accuracy is evaluated based on **caption usefulness and discoverability**, not strict character-perfect transcription.

---

## High-Level Pipeline

```
Scanned JPG pages
   ↓
OCR (OpenCV + Tesseract)
   ↓
Text blocks with bounding boxes
   ↓
Caption filtering + line grouping
   ↓
ocr_captions.json (caption-only index)
   ↓
Client-side Hugo search (JavaScript)
```

---

## OCR Script Overview

### File

```
ocr_pages.py
```

### Purpose

- Run OCR on a directory of scanned `.jpg` album pages
- Detect text blocks and preserve spatial grouping
- Filter out non-caption OCR noise (maps, artifacts, background texture)
- Preserve **multi-line captions**, including short continuation lines
- Output structured JSON suitable for static site use

### Outputs

1. **Full OCR output** (blocks + bounding boxes + full text per page)
2. **Caption-only index** (`ocr_captions.json`) for search and browsing

---

## OCR Script Design Principles

### 1. Preserve Line Breaks

Photo captions frequently span multiple lines:

```
An Amish wagon emerges
from covered bridge near
Soudersburg,
```

Line breaks are semantically meaningful and **must not be flattened prematurely**.

---

### 2. Bounding Box Stability

Each OCR block includes a bounding box:

```
[x1, y1, x2, y2]
```

Blocks are:
- Sorted top-to-bottom, left-to-right
- Treated as caption candidates based on geometry and text density

This spatial ordering helps maintain narrative flow.

---

### 3. Conservative Filtering Philosophy

Filtering is intentionally **conservative**:

- Prefer keeping questionable text over deleting real captions
- Single-word lines (e.g., place names like `Club.` or `Soudersburg,`) are valid
- Short continuation lines are preserved when they logically follow a caption

**Avoid aggressive heuristics** such as:

```python
if len(text.split()) < 3:
    discard
```

These rules will destroy valid captions.

---

### 4. JSON Output (Not JSONL)

Final output is a **single JSON array**, not JSONL.

Reasons:
- Easier manual inspection
- Native JavaScript consumption
- Hugo-friendly static usage

---

## Caption-Only Output Format

### File

```
ocr_captions.json
```

### Schema

```json
[
  {
    "filename": "1968-1969 Louise’s marriage._Page-05.jpg",
    "path": "1968-1969 Louise’s marriage/1968-1969 Louise’s marriage._Page-05.jpg",
    "captions": [
      "An Amish wagon emerges\nfrom covered bridge near\nSoudersburg,",
      "Neighbors help an Amish\nfarmer rebuild his home\ndestroyed by fire."
    ],
    "caption_text": "An Amish wagon emerges...\n\nNeighbors help an Amish..."
  }
]
```

### Field Definitions

- `filename`: Page image filename
- `path`: Relative path to image for Hugo/static serving
- `captions[]`: Individual caption blocks (authoritative units)
- `caption_text`: All captions joined with double newlines (convenience field)

**Important:**
- `captions[]` should be used for display and indexing
- `caption_text` exists for simple full-text search

---

## Known OCR Limitations (Accepted)

### Pages with Maps or Dense Graphics

Example: **Page 33**

- OCR produces large noisy text blocks from map labels
- These blocks may pass basic text filters
- Human captions on the same page are still correctly extracted

This behavior is **expected** and acceptable.

---

### OCR Errors

Common, accepted errors:
- Misspellings (e.g., `yillanova` → `Villanova`)
- Hyphenation artifacts
- Minor punctuation errors

The goal is **search discovery**, not archival transcription perfection.

---

## Caption Accuracy Philosophy

Do **not** claim numeric OCR accuracy without ground-truth comparison.

Instead, define success as:
- Captions are discoverable via search
- Names, places, and dates are findable
- Narrative meaning is preserved

This project optimizes for **finding and browsing**, not perfect reading.

---

## Hugo Search Engine Plan

### Recommendation

Use **client-side search** with JSON + JavaScript.

This avoids:
- Databases
- Backend services
- Hosting complexity

81 pages is trivial for in-browser search.

---

## Hugo Integration Steps

### 1. Place JSON Index

```
static/search/ocr_captions.json
```

Served at:

```
/search/ocr_captions.json
```

---

### 2. Create Search Page

```
content/search.md
```

```toml
+++
title = "Search"
slug = "search"
+++
```

---

### 3. JavaScript Search Logic

Core responsibilities:
- Fetch `ocr_captions.json`
- Normalize text (case, punctuation)
- AND-search across query terms
- Highlight matches
- Link results back to page images

Optional upgrades:
- Fuse.js for fuzzy matching
- Phrase search

---

## Fast Search Index Rebuild

When you need to regenerate the search index without re-running OCR (fixing slug bugs, testing, updating metadata):

```bash
python3 ocr_scripts/rebuild_search_index.py
```

**Performance:**
- Full OCR run: 8+ hours (processes images with OpenCV + Tesseract)
- Index rebuild: 3-5 seconds (reads existing JSON files)

**When to use:**
- Fixing URL slug generation bugs
- Testing search functionality
- Updating album titles in `index.md` frontmatter
- Changing search index schema
- Development iteration

**When NOT to use:**
- Adding new albums (need full OCR run first)
- Changing OCR processing logic
- Updating caption extraction

**How it works:**
- Reads existing `ocr_captions.json` files from each album directory
- Extracts album metadata from `index.md` frontmatter
- Regenerates URL slugs with fixed Unicode apostrophe handling
- Combines all data into a new `static/search/search-index.json`
- No image processing, no OCR dependencies required

---

## Image Linking Strategy

Each search result links directly to the image using:

```js
"/" + result.path
```

Assumes:
- Images are served from Hugo `static/`
- Directory names preserved exactly

Adjust if page bundles are introduced.

---

## Why No Database (Yet)

A database is unnecessary unless:
- Albums scale to thousands of pages
- Authentication or privacy is required
- Search analytics or logging is needed

If required later:
- MongoDB Atlas (free tier)
- Serverless search endpoint
- Same JSON schema ports cleanly

---

## What Not To Break

If continuing work:

❌ Do NOT:
- Flatten caption line breaks
- Drop small text blocks blindly
- Aggressively tune OCR filters
- Discard raw OCR data

✅ Do:
- Preserve original caption structure
- Add optional views instead of destructive changes
- Improve search UX, not OCR aggression

---

## Suggested Future Enhancements (Optional)

- Timeline view via date extraction
- Person/place index
- Manual correction overlay
- Per-caption confidence hints

---

## Final Note to Future AI

This system already works **well enough to ship**.

Do not attempt to perfect OCR.

Your responsibility is to:
- Preserve narrative intent
- Respect historical artifacts
- Enhance discovery without data loss

When in doubt, inspect the original image before changing logic.

---

End of handoff.