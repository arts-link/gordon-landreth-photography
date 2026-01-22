# LM Studio Integration Plan: Enhanced OCR for Photo Album Captions

## Overview
Add optional LM Studio integration to `ocr_scripts/ocr_pages.py` using MiniCPM-V 2.6 for superior caption extraction compared to Tesseract, while keeping Tesseract as the default fallback.

## User Requirements
- **Vision Model:** MiniCPM-V 2.6 (state-of-the-art OCR, handles degraded text well)
- **Integration:** Optional `--use-llm` flag (Tesseract remains default)
- **LM Studio:** Will be started manually before running (default port 1234)
- **Use Case:** One-time run to extract captions from 3,416 scanned album pages

## Current State
- OCR script uses Tesseract via `pytesseract.image_to_string()`
- Located in `ocr_crop()` function (currently line ~200)
- Processes cropped image regions to extract caption text
- Already has batch processing mode from previous updates

## Benefits of LM Studio + MiniCPM-V 2.6

### Why Better Than Tesseract:
1. **Context awareness** - Understands what captions should look like
2. **Better with degraded text** - Handles blur, rotation, poor contrast
3. **Handwriting support** - Can read handwritten annotations
4. **Intelligent filtering** - Less likely to OCR noise/artifacts as text
5. **Multi-line understanding** - Better at preserving caption structure

### Trade-offs:
- **Slower** - Vision models take 2-5 seconds per crop vs <1 second for Tesseract
- **Requires LM Studio running** - Additional setup step
- **More resource intensive** - Uses GPU if available

## Implementation Plan

### Step 1: Add LM Studio Client Setup

**Add to imports:**
```python
import base64
from openai import OpenAI
```

**Add global configuration:**
```python
# LM Studio configuration
USE_LLM = False  # Set via CLI flag
LLM_PORT = 1234  # Default LM Studio port
LLM_MODEL = "MiniCPM-V-2_6"  # Model name in LM Studio
```

**Create LM Studio client initialization:**
```python
def init_llm_client(port: int) -> OpenAI | None:
    """Initialize OpenAI client pointing to LM Studio."""
    try:
        client = OpenAI(
            base_url=f"http://localhost:{port}/v1",
            api_key="not-needed"  # LM Studio doesn't require API key
        )

        # Test connection by listing models
        models = client.models.list()
        print(f"Connected to LM Studio. Available models: {[m.id for m in models.data]}")
        return client
    except Exception as e:
        print(f"Failed to connect to LM Studio: {e}")
        print("Make sure LM Studio is running with the server started.")
        return None
```

### Step 2: Create LLM-Based OCR Function

**New function to replace/augment `ocr_crop()`:**
```python
def ocr_crop_llm(img_bgr: np.ndarray, client: OpenAI, model: str) -> str:
    """
    Use LM Studio vision model to extract caption text from image crop.

    Args:
        img_bgr: OpenCV image (BGR format)
        client: OpenAI client connected to LM Studio
        model: Model name to use

    Returns:
        Extracted caption text
    """
    # Encode image to base64
    # Convert BGR to RGB for proper color representation
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    # Encode as JPEG
    _, buffer = cv2.imencode('.jpg', img_rgb)
    img_base64 = base64.b64encode(buffer).decode('utf-8')

    # Craft prompt optimized for caption extraction
    prompt = """Extract the caption text from this image. This is a scanned page from a photo album.

Rules:
1. Extract ONLY the typed or handwritten caption text
2. Preserve line breaks exactly as they appear
3. Do NOT describe the image content or photos
4. If there is no caption text, respond with an empty string
5. Remove any OCR artifacts or noise
6. Maintain the original formatting and punctuation

Caption text:"""

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
            max_tokens=500,  # Captions are usually short
            temperature=0.1   # Low temperature for more deterministic output
        )

        text = response.choices[0].message.content.strip()
        return clean_text(text)

    except Exception as e:
        print(f"LLM OCR failed: {e}")
        # Fallback to Tesseract
        print("Falling back to Tesseract...")
        return ocr_crop(img_bgr)
```

### Step 3: Update `ocr_crop()` to Support Both Modes

**Modify the existing function:**
```python
def ocr_crop(img_bgr: np.ndarray, llm_client: OpenAI | None = None, llm_model: str | None = None) -> str:
    """
    Extract text from cropped image region.

    Args:
        img_bgr: OpenCV image crop
        llm_client: Optional LM Studio client (if USE_LLM is True)
        llm_model: Optional model name for LLM

    Returns:
        Extracted text
    """
    # Use LLM if available
    if llm_client and llm_model:
        return ocr_crop_llm(img_bgr, llm_client, llm_model)

    # Otherwise use Tesseract (existing code)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    config = f"--psm {PSM} -c preserve_interword_spaces=1"
    text = pytesseract.image_to_string(bw, lang=LANG, config=config)
    return clean_text(text)
```

### Step 4: Update `process_album()` to Use LLM

**Modify function signature and pass LLM client:**
```python
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

        blocks = []
        for (x, y, w, h) in boxes:
            crop = img[y : y + h, x : x + w]

            # ... (existing geometry filtering code) ...

            # UPDATED: Pass LLM client to ocr_crop
            text = ocr_crop(crop, llm_client=llm_client, llm_model=llm_model)

            # ... (rest of existing code) ...
```

### Step 5: Update `process_albums_batch()` to Initialize LLM

**Add LLM initialization at the start:**
```python
def process_albums_batch(content_dir: Path, search_index_path: Path, use_llm: bool = False, llm_port: int = 1234, llm_model: str = "MiniCPM-V-2_6") -> None:
    """
    Process all album subdirectories in content_dir.
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

    # ... (rest of existing code) ...

    for album_dir in album_dirs:
        # ...
        # UPDATED: Pass LLM parameters
        album_records = process_album(album_dir, content_dir, llm_client=llm_client, llm_model=llm_model)
        # ...
```

### Step 6: Update CLI Arguments

**Add LLM-related flags:**
```python
# In __main__ section:
parser.add_argument(
    "--use-llm",
    action="store_true",
    help="Use LM Studio vision model instead of Tesseract for OCR (slower but more accurate)"
)
parser.add_argument(
    "--llm-port",
    dest="llm_port",
    type=int,
    default=1234,
    help="LM Studio server port (default: 1234)"
)
parser.add_argument(
    "--llm-model",
    dest="llm_model",
    default="MiniCPM-V-2_6",
    help="LM Studio model name (default: MiniCPM-V-2_6)"
)

# Update main() call:
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
```

### Step 7: Update `main()` Function Signature

**Add LLM parameters:**
```python
def main(
    in_dir: str | None = None,
    out_path: str | None = None,
    captions_out_path: str | None = None,
    batch_mode: bool = False,
    search_index_path: str | None = None,
    use_llm: bool = False,
    llm_port: int = 1234,
    llm_model: str = "MiniCPM-V-2_6"
) -> None:
    if batch_mode:
        if not in_dir or not search_index_path:
            raise ValueError("Batch mode requires both input directory and search index path")
        process_albums_batch(Path(in_dir), Path(search_index_path), use_llm, llm_port, llm_model)
        return

    # ... (existing legacy mode code) ...
```

## Usage Instructions

### Setup Steps (One-Time):

1. **Install Python dependency:**
   ```bash
   pip3 install openai
   ```

2. **Start LM Studio:**
   - Launch LM Studio application
   - Download MiniCPM-V-2_6 model if not already installed
   - Load the model
   - Start the local server (Developer > Start Server)
   - Verify it's running on port 1234

3. **Test connection:**
   ```bash
   # Quick test to verify LM Studio is accessible
   curl http://localhost:1234/v1/models
   ```

### Running with LM Studio:

**Batch mode with LM Studio:**
```bash
# Create output directory
mkdir -p static/search

# Run with LM Studio (will take 3-4 hours instead of 1-2 hours)
python3 ocr_scripts/ocr_pages.py \
  --batch content/ \
  --search-index static/search/search-index.json \
  --use-llm
```

**With custom port or model:**
```bash
python3 ocr_scripts/ocr_pages.py \
  --batch content/ \
  --search-index static/search/search-index.json \
  --use-llm \
  --llm-port 8080 \
  --llm-model "your-model-name"
```

**Fallback to Tesseract (default):**
```bash
# Just omit --use-llm flag
python3 ocr_scripts/ocr_pages.py --batch content/ --search-index static/search/search-index.json
```

## Performance Estimates

### With Tesseract (baseline):
- Per image: 1-2 seconds
- Total: 1-2 hours for 3,416 images

### With LM Studio + MiniCPM-V 2.6:
- Per image: 3-5 seconds (depends on GPU)
- Total: **3-5 hours for 3,416 images**
- Better quality, especially for:
  - Handwritten captions
  - Faded or low-contrast text
  - Rotated or skewed text
  - Captions with unusual fonts

## Error Handling

The script includes multiple fallback layers:

1. **LLM connection fails** → Script warns and falls back to Tesseract entirely
2. **Individual LLM request fails** → That specific crop falls back to Tesseract
3. **Model not available** → Connection test catches this before processing starts

## Testing Plan

### Before Full Run:

1. **Test LM Studio connection:**
   ```bash
   python3 -c "from openai import OpenAI; client = OpenAI(base_url='http://localhost:1234/v1', api_key='x'); print(client.models.list())"
   ```

2. **Test on single album with LIMIT_PAGES:**
   ```bash
   # Edit ocr_pages.py: Set LIMIT_PAGES = 5
   python3 ocr_scripts/ocr_pages.py \
     --batch content/ \
     --search-index static/search/search-index.json \
     --use-llm
   ```

3. **Compare results:**
   - Check `content/1931-1939 courting & marriage/ocr_captions.json`
   - Verify caption quality vs Tesseract
   - Verify JSON structure is correct

4. **If satisfied, run full batch:**
   ```bash
   # Edit ocr_pages.py: Set LIMIT_PAGES = None
   python3 ocr_scripts/ocr_pages.py \
     --batch content/ \
     --search-index static/search/search-index.json \
     --use-llm
   ```

## Critical Files

**Files to Modify:**
1. `ocr_scripts/ocr_pages.py` - Add LLM support, update functions

**Dependencies to Install:**
```bash
pip3 install openai  # For LM Studio API client
```

**External Requirements:**
- LM Studio running with MiniCPM-V-2_6 loaded
- Local server started on port 1234 (or custom port)

## Success Criteria

✅ Script accepts `--use-llm` flag
✅ Connects to LM Studio on port 1234
✅ Sends cropped images as base64 to vision model
✅ Extracts captions using MiniCPM-V 2.6
✅ Falls back to Tesseract on errors
✅ Produces same JSON structure as Tesseract mode
✅ Better quality captions for degraded/handwritten text
✅ Compatible with existing batch processing mode

## Advantages of This Approach

1. **No risk** - Tesseract still available as fallback
2. **Flexible** - Can compare both methods easily
3. **Future-proof** - Can swap models in LM Studio without code changes
4. **One-time quality** - Since this is a one-time run, the extra time is worth better results
5. **Local & Private** - No API costs, all processing stays local
