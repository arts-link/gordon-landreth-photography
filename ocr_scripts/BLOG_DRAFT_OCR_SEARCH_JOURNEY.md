# Building OCR-Powered Search for a Family Photo Gallery

*Draft article - January 2026*

The technical journey of adding search to 3,400+ scanned photo album pages.

---

## Introduction

I inherited a problem that probably sounds familiar to anyone who's digitized family photos: I had 48 photo albums, 3,416 scanned pages, and absolutely no way to find anything. Each album page had typed captions with names, places, and dates, but they were just pixels in JPG files. If you wanted to find photos from a specific trip or featuring a particular person, you had to manually flip through hundreds of pages.

This is the story of how I built a search engine for those captions using OCR, client-side JavaScript, and a philosophy of "good enough is better than perfect."

---

## Part 1: The Problem & Architecture Decisions

### The Setup

The Gordon Landreth Photography site is a Hugo-based static gallery hosting my grandfather's photography from 1931-1990s. When I started this project, the site had:

- 46 albums spanning 6 decades
- 3,416 scanned album pages (each page contains multiple photos)
- Typed captions on most pages with names, dates, locations
- Zero search capability

Each album page was professionally scanned as a high-resolution JPG. The captions were clearly readable to a human, but to a computer, they were just pixels. The site was essentially a digital photo album you could only browse sequentially.

### What I Wanted

I wanted family members to be able to search for:
- **Names**: "Show me all photos of Louise"
- **Places**: "Where are the Big Bend photos?"
- **Events**: "Find the wedding pictures"
- **Dates**: "What do we have from 1947?"

Pretty standard search stuff. But there were some constraints.

### The Constraints

**1. Static Site Architecture**

This is a Hugo static site deployed to AWS CloudFront. No backend, no database, no server-side code. Everything had to run in the browser.

**2. Privacy & Copyright**

These are family photos, not public domain. The site is configured with `noindex, nofollow` robots tags and uses privacy-focused Plausible analytics. I didn't want to send caption text to any third-party search services.

**3. OCR Quality**

These are 1940s-1980s photos with typed captions. The type quality varies:
- Some captions are crisp typewriter text
- Others are faded, skewed, or have poor contrast
- Map labels and photo borders create OCR noise
- Occasional handwritten annotations

Perfect transcription wasn't realistic. I needed something that was "searchable enough."

### Architecture Decision: Client-Side Search

I decided early on to use **client-side search** with a pre-generated JSON index. Here's why:

**Pros:**
- No backend infrastructure (fits static site architecture)
- No database to maintain
- No hosting costs beyond static file storage
- Privacy-focused (all searching happens in browser)
- Fast search on modern browsers

**Cons:**
- User has to download the full search index (~400KB)
- No server-side analytics on what people search for
- Can't dynamically update index without rebuilding site

With only 3,416 pages, client-side search was totally viable. If I had 50,000+ pages, I'd probably need a different approach.

### Technology Choices

**OCR Engine: Tesseract + OpenCV**

https://toon-beerten.medium.com/ocr-comparison-tesseract-versus-easyocr-vs-paddleocr-vs-mmocr-a362d9c79e66
https://huggingface.co/spaces/Loren/Streamlit_OCR_comparator?source=post_page-----a362d9c79e66---------------------------------------


For OCR, I used [Tesseract](https://github.com/tesseract-ocr/tesseract) via Python's `pytesseract` wrapper:
- Free and open source
- Runs locally (no API costs)
- Good enough for typed text
- Fast (1-2 seconds per image)

I used OpenCV for image preprocessing:
- Thresholding to detect light text regions
- Resizing crops for better OCR accuracy
- Gaussian blur to reduce noise

**Search Library: Fuse.js**

For the search UI, I chose [Fuse.js](https://fusejs.io/):
- Lightweight (~60KB minified)
- Fuzzy matching (handles OCR typos)
- No dependencies
- Works great with 3,000-5,000 entries

Alternatives I considered:
- **Algolia/Typesense**: Overkill for this use case, requires backend
- **Lunr.js**: Popular but heavier, no fuzzy matching
- **Custom regex search**: Too simple, wouldn't handle typos

Fuse.js was the perfect middle ground: simple enough to integrate, smart enough to handle OCR errors.

### The Search Index Structure

I designed a two-level JSON structure:

**Level 1: Per-Album JSON** (`content/album-name/ocr_captions.json`)
```json
{
  "album": "1947 Nov. '47- May '48 covered bridges+",
  "album_title": "1947 Nov. '47 - May '48 covered bridges+",
  "pages": [
    {
      "filename": "album_Page-01.jpg",
      "path": "album-name/album_Page-01.jpg",
      "captions": [
        "An Amish wagon emerges\nfrom covered bridge near\nSoudersburg,",
        "Neighbors help an Amish\nfarmer rebuild his home"
      ],
      "caption_text": "An Amish wagon emerges...\n\nNeighbors help..."
    }
  ]
}
```

**Level 2: Site-Wide Search Index** (`static/search/search-index.json`)
```json
[
  {
    "type": "album",
    "album_title": "1947 Nov. '47 - May '48 covered bridges+",
    "album_url_slug": "1947-nov.-47--may-48-covered-bridges+",
    "searchable_text": "1947 Nov. '47 - May '48 covered bridges+"
  },
  {
    "type": "page",
    "album_title": "1947 Nov. '47 - May '48 covered bridges+",
    "album_url_slug": "1947-nov.-47--may-48-covered-bridges+",
    "page_filename": "album_Page-01.jpg",
    "image_index": 0,
    "captions": ["Caption 1", "Caption 2"],
    "searchable_text": "Caption 1 Caption 2 album_Page-01.jpg"
  }
]
```

The merged index combines 46 albums + 3,416 pages = 3,462 searchable entries.

### Why This Structure?

**Per-album JSONs** let me:
- Rebuild individual albums without reprocessing everything
- Display captions on album pages in the future
- Track processing history per album

**Site-wide index** gives me:
- Fast client-side search (load once, search instantly)
- Album and page results in one search
- Clean separation: OCR data lives in content, search lives in static files

---

## Part 2: The OCR Processing Journey

### Setting Up the OCR Pipeline

The core OCR pipeline has four stages:

```
Scanned JPG → OpenCV preprocessing → Tesseract OCR → Caption filtering → JSON
```

Let me walk through each stage.

### Stage 1: Detect Candidate Caption Regions

Most album pages have:
- 4-6 photos arranged in a grid
- White space between photos
- Typed caption text in those white spaces

My first task was to detect those caption regions without OCR'ing the photos themselves.

**Algorithm:**
1. Convert page to grayscale
2. Apply adaptive thresholding to find light regions
3. Use connected components to find rectangular regions
4. Filter by geometry:
   - Minimum area: 0.08% of page (drops tiny specs)
   - Maximum area: 35% of page (drops full photos)
   - Minimum aspect ratio: 1.15 (captions are wider than tall)

This gave me bounding boxes around likely caption areas.

### Stage 2: OCR Each Region

For each candidate region, I:

```python
def ocr_crop(img_bgr: np.ndarray) -> str:
    """Extract text from cropped image region."""
    # Convert to grayscale
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # Resize 2x for better OCR accuracy
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0,
                     interpolation=cv2.INTER_CUBIC)

    # Gaussian blur to reduce noise
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # Otsu thresholding for clean black/white
    _, bw = cv2.threshold(gray, 0, 255,
                          cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Run Tesseract with PSM 6 (uniform block of text)
    config = f"--psm 6 -c preserve_interword_spaces=1"
    text = pytesseract.image_to_string(bw, lang='eng', config=config)

    return clean_text(text)
```

**Key preprocessing steps:**
- **2x resize**: Tesseract works better on larger images
- **Gaussian blur**: Reduces speckle noise
- **Otsu thresholding**: Automatic contrast adjustment
- **PSM 6**: Tells Tesseract to expect uniform text blocks

### Stage 3: The Caption Filtering Challenge

Here's where things got interesting. Tesseract returns text from every region, including:
- ✅ Real captions: `"Trip to Florida via the Smokies"`
- ❌ Map labels: `"ROAD JUNCTION EXIT 42B INTERSTATE"`
- ❌ Photo borders: `"||||| .... ----"`
- ❌ Noise: `"xx ## !!"`

I needed to filter out the garbage while keeping real captions. And here's the philosophical decision that shaped the entire system:

**Optimize for discovery, not perfection.**

### The Conservative Filtering Philosophy

I could have written aggressive filters to catch every bit of noise:

```python
# ❌ DON'T DO THIS
if len(text.split()) < 3:  # Drop short captions
    discard

if not looks_like_proper_sentence(text):  # Drop incomplete sentences
    discard
```

But these rules would destroy valid captions like:
- `"Soudersburg,"`  (place name continuation)
- `"November, 1947"` (date header)
- `"Eden Mill"` (short place name)

Instead, I used **conservative filtering**: prefer keeping questionable text over losing real captions.

```python
def filter_text_lines(text: str) -> str:
    """Keep lines that look like real caption text."""
    lines = [ln.strip() for ln in text.splitlines()]
    kept = []

    for ln in lines:
        if not ln:
            continue

        # Require some real letters
        alpha = sum(ch.isalpha() for ch in ln)
        if alpha < 4:
            continue

        # Captions are mostly words, not symbols
        total = len(ln)
        if (alpha / total) < 0.25:
            continue

        # Require multiple real words OR valid short caption
        words3 = re.findall(r"[A-Za-z]{3,}", ln)
        words4 = [w for w in words3 if len(w) >= 4]

        strict_ok = (len(words4) >= 2) or (len(words3) >= 3)

        # Exception: allow valid-looking short captions
        is_valid_short = False
        if len(words3) >= 1 and 8 <= total <= 50:
            has_capital = any(ch.isupper() for ch in ln)
            sym = sum((not ch.isalnum()) and (not ch.isspace()) for ch in ln)
            punct_ratio = sym / total
            if has_capital and punct_ratio < 0.20:
                is_valid_short = True

        if strict_ok or is_valid_short:
            kept.append(ln)
            continue

        # Allow short continuation lines after kept lines
        if kept:
            prev = kept[-1].rstrip()
            if not prev.endswith('.!?'):
                is_continuation = (len(words3) <= 2 and total <= 24)
                if is_continuation:
                    kept.append(ln)
                    continue

    return "\n".join(kept).strip()
```

**What this does:**
1. Drop obvious noise (mostly symbols, very short, no words)
2. Keep strict captions (multiple real words)
3. Keep valid short captions (dates, place names with proper capitalization)
4. Keep continuation lines (place name follows "near", "from", etc.)

### Why Line Breaks Matter

One critical decision: **preserve multi-line caption structure**.

Many captions span multiple lines:
```
An Amish wagon emerges
from covered bridge near
Soudersburg,
```

Flattening this to a single line loses semantic meaning. Line breaks indicate:
- Natural reading flow
- Continuation across lines
- Place name groupings

So the output preserves them:

```json
{
  "captions": [
    "An Amish wagon emerges\nfrom covered bridge near\nSoudersburg,"
  ]
}
```

For search, I create a flattened `searchable_text` field, but the structured `captions` array preserves the original formatting for display.

### Known Limitations (Accepted Trade-Offs)

**1. Map Noise**

Pages with maps (like road trip albums) produce noisy OCR from map labels:
```
"INTERSTATE 95 EXIT 42B PENNSYLVANIA TURNPIKE"
```

**Accepted:** These pass basic text filters. Fixable with better detection, but not worth the effort. Maps are rare, and the actual captions on those pages still get extracted correctly.

**2. OCR Errors**

Common mistakes:
- `"yillanova"` → `"Villanova"` (v/y confusion)
- `"Gordan"` → `"Gordon"` (typo)
- `"1unch"` → `"lunch"` (1/l confusion)

**Accepted:** Fuzzy search will handle these. We're optimizing for discoverability, not archival transcription.

**3. Handwritten Annotations**

Tesseract struggles with handwriting:
```
Expected: "Added by Mom in 1985"
Actual:   "7%%#ed ky Mow %% 7985"
```

**Accepted:** Handwritten captions are rare. When they matter, I'll explore vision models (more on that later).

### Batch Processing: The Overnight Run

Processing 3,416 images takes time. The full batch command:

```bash
python3 ocr_scripts/ocr_pages.py \
  --batch content/ \
  --search-index static/search/search-index.json
```

**Performance:**
- **Per image:** 1-2 seconds (detection + OCR + filtering)
- **Total time:** 1-2 hours for 3,416 images
- **Output:** 46 per-album JSONs + 1 merged search index

I ran this overnight and woke up to a fully searchable photo gallery.

### The Fast Rebuild Trick

After the initial OCR run, I discovered bugs in my URL slug generation. But I didn't want to rerun OCR for 8+ hours just to fix URLs.

Solution: **separate index rebuild script** (`rebuild_search_index.py`)

```bash
python3 ocr_scripts/rebuild_search_index.py
```

**What it does:**
1. Reads existing `ocr_captions.json` files from each album
2. Extracts album metadata from `index.md` frontmatter
3. Regenerates URL slugs with fixed logic
4. Combines into new `search-index.json`

**Performance:** 3-5 seconds (no image processing!)

This became invaluable for:
- Testing search functionality
- Fixing metadata bugs
- Updating album titles
- Development iteration

---

## Part 3: Building the Search Interface

### The User Experience Vision

I wanted search to feel instant and natural:
- Type → see results immediately (no "submit" button)
- Handle typos gracefully (OCR errors + user errors)
- Show relevant context (album title + captions + page link)
- Work on mobile and desktop

### Fuse.js Integration

Loading the search index and initializing Fuse.js:

```javascript
// Load search index from static file
const response = await fetch('/search/search-index.json');
searchIndex = await response.json();
console.log(`Search index loaded: ${searchIndex.length} entries`);

// Initialize Fuse.js with OCR-optimized config
fuse = new Fuse(searchIndex, {
  keys: [
    { name: 'album_title', weight: 2 },        // Prioritize album titles
    { name: 'caption_text', weight: 1.5 },     // Caption content (primary search target)
    { name: 'searchable_text', weight: 0.5 }   // Fallback for filenames
  ],
  threshold: 0.4,          // 40% error tolerance (high for OCR)
  ignoreLocation: true,    // Search entire text, not just beginning
  minMatchCharLength: 2,   // Minimum query length
  includeMatches: true,    // Return match positions for highlighting
  includeScore: true       // Return relevance scores
});
```

**Configuration decisions:**

**1. Threshold: 0.4 (very permissive)**

This allows up to 40% character-level errors. Why so high?
- OCR mistakes: `"yillanova"` → `"Villanova"`
- User typos: `"Gordan"` → `"Gordon"`
- Fuzzy matching: `"trip"` matches `"trips"`, `"tripp"`

**2. Field weights: album_title=2, caption_text=1.5, searchable_text=0.5**

- **album_title** gets 2x weight so album names appear first when you search "1947" or "covered bridges"
- **caption_text** gets 1.5x weight since it's the primary search target (actual photo captions)
- **searchable_text** gets 0.5x weight as a low-priority fallback for filenames

**3. ignoreLocation: true**

Search anywhere in the text, not just at the beginning. Captions might mention "Florida" at the end of a sentence.

### Search-As-You-Type

No submit button. Results appear as you type:

```javascript
searchInput.addEventListener('input', debounce((e) => {
  const query = e.target.value;

  // Show/hide clear button
  searchClear.style.display = query ? 'flex' : 'none';

  // Perform search
  if (query.trim().length >= 2) {
    const results = fuse.search(query.trim());
    displayResults(results, query);
  } else {
    showInitialState();
  }
}, 300)); // 300ms debounce
```

**Debouncing** prevents search from running on every keystroke. It waits 300ms after you stop typing.

### Result Rendering

Each search result shows:
1. **Album title** (highlighted)
2. **Page link** ("Page 5")
3. **Caption preview** (first 3 captions, highlighted)
4. **View Page** button (links to gallery page)

```javascript
function displayResults(results, query) {
  const displayResults = results.slice(0, 100); // Limit to 100

  const html = displayResults.map(result => {
    const item = result.item;

    // Get first 3 captions
    const excerpt = item.captions.slice(0, 3).join('\n\n');

    // Highlight search terms
    const highlightedExcerpt = highlightSearchTerms(excerpt, query);
    const highlightedTitle = highlightSearchTerms(item.album_title, query);

    // Build link with image index (for direct navigation)
    const linkUrl = `/${item.album_url_slug}/#${item.image_index}`;

    return `
      <div class="search-result">
        <div class="result-album-title">${highlightedTitle}</div>
        <div class="result-page-title">
          <a href="${linkUrl}">${escapeHtml(item.page_filename)}</a>
        </div>
        <div class="result-excerpt">${highlightedExcerpt}</div>
        <div class="result-footer">
          <a href="${linkUrl}" class="result-link">View Page →</a>
        </div>
      </div>
    `;
  }).join('');

  searchResults.innerHTML = html;
}
```

### Highlighting Matches

Simple regex-based highlighting:

```javascript
function highlightSearchTerms(text, query) {
  // Split query into words
  const terms = query.trim().split(/\s+/).map(term =>
    term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') // Escape regex chars
  );

  // Create pattern: (term1|term2|term3)
  const pattern = new RegExp(`(${terms.join('|')})`, 'gi');

  // Split text by pattern and wrap matches
  const parts = text.split(pattern);
  return parts.map((part, index) => {
    if (index % 2 === 1) { // Odd indices are matches
      return `<mark class="search-highlight">${escapeHtml(part)}</mark>`;
    }
    return escapeHtml(part);
  }).join('');
}
```

Matches are wrapped in `<mark>` tags with CSS styling.

### Performance Characteristics

**Search index size:** ~400KB JSON (gzipped to ~100KB by CloudFront)

**Load time:**
- First visit: Download index + Fuse.js (~160KB total)
- Return visits: Cached by browser (instant)

**Search speed:**
- 3,400+ entries search in <50ms
- Results render instantly
- No perceptible lag on modern browsers

**Mobile experience:**
- Touch-friendly search input
- Responsive result cards
- Works offline after first load (due to caching)

### Styling the Search UI

Clean, minimal design matching the photo gallery aesthetic:

```css
.search-container {
  max-width: 800px;
  margin: 2rem auto;
  padding: 0 1rem;
}

#search-input {
  width: 100%;
  padding: 1rem;
  font-size: 1.2rem;
  border: 2px solid #ddd;
  border-radius: 8px;
  margin-bottom: 2rem;
}

.search-result {
  padding: 1.5rem;
  margin-bottom: 1rem;
  border: 1px solid #eee;
  border-radius: 8px;
  background: var(--background-color);
}

.search-highlight {
  background: #ffd70080;  /* Soft yellow */
  padding: 0 2px;
  border-radius: 2px;
}
```

---

## Part 4: Enhancing the Search Experience

After getting basic search working, I started using it and quickly realized that fuzzy matching alone wasn't enough. The search worked, but the experience felt incomplete. I needed visual context, better organization, and a way to preview results without leaving the search page.

This part is about the features I didn't plan from the start but discovered were essential through actual use.

### The Visual Context Problem

The initial search results looked like this:

```
Album: 1947 Nov. '47 - May '48 covered bridges+
Page: album_Page-01.jpg
Caption: "An Amish wagon emerges from covered bridge..."
[View Page →]
```

Functional? Yes. Helpful? Barely. I found myself clicking through 10-15 results to find the right photo because:
- I couldn't remember what "Page 01" looked like
- Album titles didn't trigger visual memory
- Captions alone weren't enough context

I needed thumbnails.

### Adding Thumbnail Previews

The solution was simple: show a 120px preview of each page in the search results.

**Implementation:**

```javascript
// Build thumbnail URL for pages
let thumbnailUrl = '';
if (item.type === 'page' && item.album_url_slug && item.page_filename) {
  // Construct URL using slug (not path) to avoid space encoding issues
  thumbnailUrl = `/${item.album_url_slug}/${item.page_filename}`;
}
```

**CSS for responsive thumbnails:**

```css
.result-thumbnail {
  flex-shrink: 0;
  width: 120px;
  height: 120px;
  border-radius: 6px;
  overflow: hidden;
  background: #e5e5e5;
  display: block;
}

.result-thumbnail img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.2s ease;
}

/* Responsive sizing */
@media (max-width: 768px) {
  .result-thumbnail {
    width: 100px;
    height: 100px;
  }
}

@media (max-width: 480px) {
  .result-thumbnail {
    width: 80px;
    height: 80px;
  }
}
```

**The slug-based URL bug fix:**

Initially, I tried building URLs from the `page_path` field, which included the raw album name with spaces:

```
/1947 Nov. '47 - May '48 covered bridges+/album_Page-01.jpg
```

Browsers encoded this as:

```
/1947%20Nov.%20%2747%20-%20May%20%2748%20covered%20bridges%2B/album_Page-01.jpg
```

Which resulted in 404 errors. The fix was using `album_url_slug` instead:

```javascript
thumbnailUrl = `/${item.album_url_slug}/${item.page_filename}`;
// Result: /1947-nov.-47--may-48-covered-bridges+/album_Page-01.jpg
```

**Impact:**

Thumbnails transformed the search experience. I could now:
- Recognize photos instantly by visual appearance
- Skip irrelevant results without clicking
- Find the right page in seconds instead of minutes

But clicking a thumbnail just navigated to the album page. I wanted more.

### The PhotoSwipe Integration

Once I had thumbnails, the next obvious step was: what if clicking a thumbnail opened a full-screen lightbox?

**Why PhotoSwipe:**

The gallery already used PhotoSwipe for album pages. Reusing it for search results meant:
- Consistent UX (same lightbox, same controls)
- Full keyboard navigation (arrow keys, escape)
- Swipe gestures on mobile
- Caption display in lightbox
- No new dependencies

**Implementation challenge:**

PhotoSwipe expects a data source of slides with dimensions. But search results don't include image dimensions (only the search index JSON does, and it doesn't have that data either).

**Solution: Dynamic dimension loading**

```javascript
async function getImageDimensions(imageUrl) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = () => {
      console.warn(`Failed to load dimensions for ${imageUrl}`);
      resolve({ width: 1600, height: 1200 }); // Fallback for landscape pages
    };
    img.src = imageUrl;
  });
}

async function resultToPhotoSwipeSlide(result) {
  const item = result.item;
  const imageSrc = `/${item.album_url_slug}/${item.page_filename}`;

  // Load dimensions
  const dimensions = await getImageDimensions(imageSrc);

  return {
    src: imageSrc,
    width: dimensions.width,
    height: dimensions.height,
    alt: `${item.album_title} - Page ${pageNum}`,
    caption: `<h3>${item.album_title}</h3><p>${item.caption_text}</p>`
  };
}
```

**Click handler with PhotoSwipe:**

```javascript
resultsContainer.addEventListener('click', async (e) => {
  const thumbnail = e.target.closest('.result-thumbnail[data-result-index]');
  if (!thumbnail) return;

  e.preventDefault();
  const resultIndex = parseInt(thumbnail.dataset.resultIndex);

  // Build PhotoSwipe data source from current results
  const dataSource = await Promise.all(
    currentPageResults.map(result => resultToPhotoSwipeSlide(result))
  );

  // Create PhotoSwipe instance
  const pswp = new PhotoSwipe({
    dataSource: dataSource,
    index: resultIndex,
    bgOpacity: 1,
    showHideAnimationType: 'zoom',
    imageClickAction: 'close'
  });

  pswp.init();
}, true); // USE CAPTURE PHASE to prevent navigation
```

**Critical detail: Event capture phase**

The `true` parameter in `addEventListener` is crucial. It uses the **capture phase** to intercept clicks before they bubble up and trigger navigation. Without it, the browser would navigate to the album page before PhotoSwipe could open.

**Impact:**

Now clicking a thumbnail:
1. Opens full-screen lightbox
2. Shows the full album page with captions
3. Allows arrow key navigation through results
4. Displays OCR captions in the lightbox
5. Escape or click to close and return to search

This turned search from "find the right page" into "browse your results like a slideshow."

### Grouped Search Results

As I used search more, I noticed confusion: when searching for an album name, both the album itself and individual pages from that album appeared in results. It was hard to tell what matched.

**The categorization solution:**

Split results into two groups:
1. **Album Title Matches** - The album name itself matched
2. **Caption Matches** - The OCR caption text matched

**Implementation:**

```javascript
function categorizeResults(results) {
  const albumMatches = [];
  const captionMatches = [];

  results.forEach(result => {
    const item = result.item;
    const matches = result.matches || [];

    // Determine which field matched
    const albumTitleMatched = matches.some(m => m.key === 'album_title');
    const captionTextMatched = matches.some(m => m.key === 'caption_text');

    // Categorize based on entry type and which field matched
    if (item.type === 'album') {
      albumMatches.push(result);
    } else if (item.type === 'page' && captionTextMatched) {
      // Only show pages if caption_text field matched (not just album title)
      captionMatches.push(result);
    }
  });

  return { albumMatches, captionMatches };
}
```

**Rendering grouped results:**

```javascript
// Section 1: Album Title Matches
if (albumMatches.length > 0) {
  html += '<div class="results-section">';
  html += '<h2 class="results-section-title">Album Title Matches</h2>';
  html += albumMatches.map(result => renderResult(result, query, 'album')).join('');
  html += '</div>';
}

// Section 2: Caption Matches
if (captionMatches.length > 0) {
  html += '<div class="results-section">';
  html += '<h2 class="results-section-title">Caption Matches</h2>';
  html += captionMatches.map(result => renderResult(result, query, 'caption')).join('');
  html += '</div>';
}
```

**Impact:**

Now search results show:

```
Album Title Matches
  1947 Nov. '47 - May '48 covered bridges+

Caption Matches
  1947 Nov. '47 - May '48 covered bridges+: Page 5
    "An Amish wagon emerges from covered bridge..."

  1947 Nov. '47 - May '48 covered bridges+: Page 12
    "Covered bridge over Mill Creek..."
```

Much clearer! You can see at a glance:
- Which albums match your search
- Which specific pages have caption matches
- No duplicate confusion

### Configuration Tuning

Through testing, I refined the search configuration:

**Field weights (final values):**

```javascript
fuse = new Fuse(searchIndex, {
  keys: [
    { name: 'album_title', weight: 2 },        // Prioritize album titles
    { name: 'caption_text', weight: 1.5 },     // Caption content (primary search target)
    { name: 'searchable_text', weight: 0.5 }   // Fallback for filenames
  ],
  threshold: 0.4,  // Permissive for OCR errors
  ignoreLocation: true,
  minMatchCharLength: 2
});
```

**Why these weights:**
- `album_title: 2` - Albums should appear first when searching by name
- `caption_text: 1.5` - Captions are the primary search content
- `searchable_text: 0.5` - Filenames are low-value fallback

**Result limit: 100**

Increased from an initial 50 to accommodate common queries:

```javascript
const limitedResults = results.slice(0, 100);

if (results.length > 100) {
  searchResults.innerHTML += `
    <div class="search-limit-notice">
      Showing first 100 of ${results.length} results. Try refining your search.
    </div>
  `;
}
```

**Why:** Searches like "1947" can return 200+ results. Showing 100 gives better coverage without overwhelming the browser.

### Why Simple Won

Looking back at my notes, I had planned to implement:
- Boolean AND filtering for multi-word queries
- Quoted phrase search
- Query parsing and routing logic

I never built any of that. Why?

**Fuzzy matching was sufficient.**

With a threshold of 0.4 (40% error tolerance), Fuse.js handles:
- OCR errors: `"yillanova"` finds "Villanova"
- Typos: `"Gordan"` finds "Gordon"
- Partial matches: `"trip"` finds "trips"
- Flexible matching: Handles dates, places, names

**Visual enhancements mattered more than search precision.**

Thumbnails and PhotoSwipe integration had bigger UX impact than perfect search logic. Users can scan 10 visual results faster than they can refine a complex query.

**Conservative filtering philosophy paid off.**

By keeping questionable captions (map noise, artifacts), the search index is comprehensive. Fuzzy matching + visual previews let users find what they need even with some noise in results.

### Lessons Learned

**1. Visual Context Beats Perfect Results**

I spent days tuning OCR filters and search relevance. Adding thumbnails had 10x the impact in 2 hours.

**2. Don't Optimize Prematurely**

I thought I'd need Boolean AND, phrase search, and field-specific queries. Turns out fuzzy matching + good UX was enough.

**3. Reuse Existing Components**

PhotoSwipe was already in the project for galleries. Reusing it for search cost almost nothing and gave a polished experience.

**4. Test with Real Use, Not Hypothetical Queries**

I tested search with single words like "Gordon" and "Florida." Real use showed I needed thumbnails and grouping, not better query parsing.

**5. Client-Side Search Keeps Surprising Me**

Even with dynamic image loading, PhotoSwipe initialization, and 100-result rendering, search feels instant. Modern browsers are fast.

---

## Part 5: Exploring Vision Models

After getting search working with Tesseract, I started noticing its limitations. Handwritten annotations were completely unreadable. Faded 1940s captions came through with errors. Some album pages with maps produced way too much noise. I wondered: could modern vision models do better?

Spoiler: yes, dramatically better. But with trade-offs.

### Why I Wanted to Try Vision Models

Tesseract is great for clean typed text, but it struggles with:

**1. Handwritten annotations**

Family members occasionally added handwritten notes like "Added by Mom in 1985" or "Dad's first camera." Tesseract rendered these as complete garbage:
```
Expected: "Added by Mom in 1985"
Tesseract: "7%%#ed ky Mow %% 7985"
```

**2. Degraded or faded text**

These are 1940s-1950s photos with typed captions. Some have yellowed, faded, or low-contrast text. Tesseract sometimes missed words or produced garbled output.

**3. Map label noise**

Pages with maps (road trip albums) produced excessive OCR noise from map labels, exit signs, and highway markers. My caption filters helped, but didn't eliminate the problem.

**4. Context-blind processing**

Tesseract doesn't understand what it's looking at. It OCRs everything equally: photo captions, map labels, photo borders, artifacts. A vision model could potentially distinguish captions from noise based on context.

My goal wasn't perfect transcription (I'd already embraced "good enough"). I wanted to see if vision models could push the quality higher, especially for handwritten text and degraded captions.

### Setting Up LM Studio

I decided to try [LM Studio](https://lmstudio.ai/), a local inference server that runs vision models on your machine. No cloud APIs, no costs, full privacy.

**Installation was dead simple:**
1. Download LM Studio (free desktop app for macOS/Windows/Linux)
2. Search for "MiniCPM-V 2.6" in the model browser
3. Download the model (~8GB)
4. Click "Start Server" (defaults to `http://localhost:1234`)

**Why MiniCPM-V 2.6?**

It's a state-of-the-art vision model specifically trained for OCR and image understanding. It's:
- Small enough to run locally (8GB model)
- Fast enough for batch processing (2-5 seconds per image)
- Good at both typed and handwritten text
- OpenAI-compatible API (easy integration)

Within 10 minutes, I had a local vision model server running. No API keys, no authentication, just a simple HTTP endpoint.

### Implementation Details

I designed the vision model integration as an **optional enhancement**, not a replacement for Tesseract.

**Command line flags:**
```bash
python3 ocr_scripts/ocr_pages.py \
  --batch content/ \
  --use-llm \
  --llm-port 1234 \
  --llm-model minicpm-v-2.6
```

**Architecture:**
- Default: Use Tesseract (fast, good for typed text)
- With `--use-llm`: Use vision model (slower, better quality)
- Fallback: If vision model fails, fall back to Tesseract

**Connecting to LM Studio:**

```python
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
```

Simple! The OpenAI Python SDK works with any OpenAI-compatible API, including local servers.

**Vision model OCR implementation:**

```python
def ocr_crop_llm(img_bgr: np.ndarray, client: OpenAI, model: str) -> str:
    """Use LM Studio vision model to extract caption text."""
    # Convert BGR to RGB for proper encoding
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    # Encode as JPEG base64
    _, buffer = cv2.imencode('.jpg', img_rgb)
    img_base64 = base64.b64encode(buffer).decode('utf-8')

    # Prompt with strict instructions (see next section)
    prompt = """Extract the typed or handwritten caption text.

Output ONLY the raw caption text. DO NOT describe photos or add notes.
If no caption, respond with: .

Caption:"""

    # Send to vision model
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{img_base64}"
                }}
            ]
        }],
        max_tokens=500,
        temperature=0.1  # Low temperature for deterministic output
    )

    return clean_text(response.choices[0].message.content)
```

The key difference from Tesseract: instead of image preprocessing → OCR engine, we just send the image to the vision model and ask it to extract captions.

### The Prompt Engineering Challenge

Here's where it got interesting. Vision models are **chatty**. They want to be helpful, describe things, add context. But I needed them to **just transcribe the caption text**.

**First attempt prompt:**
```
Extract the caption text from this image.
```

**Result:**
```
This photo shows an Amish wagon emerging from a covered bridge.
The caption reads: "An Amish wagon emerges from covered bridge near Soudersburg."
The bridge appears to be from the 1940s era based on its construction.
```

**Not what I wanted!** I needed just the caption, not a description of the photo.

**Second attempt prompt:**
```
Output ONLY the caption text. Do not describe the photo.
```

**Result:**
```
"An Amish wagon emerges from covered bridge near Soudersburg."
```

Better! But still wrapped in quotes. And sometimes it would add:
```
(No visible caption)
```

Instead of just returning empty when there's no caption.

**Final prompt (after iteration):**
```python
prompt = """You are an OCR assistant. Extract the typed or handwritten caption text.

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
```

This worked **much better**. The model learned to:
- Output just the caption text (no descriptions)
- Return `.` when there's no caption (easy to filter)
- Skip explanatory text

**Filtering LLM chattiness:**

Even with a good prompt, vision models occasionally get chatty. I added post-processing filters:

```python
# Filter out common LLM explanation patterns
refusal_patterns = [
    "there is no",
    "no visible",
    "caption text:",
    "the image appears",
    "however,",
]

text_lower = text.lower()
if any(pattern in text_lower for pattern in refusal_patterns):
    # If the whole response is just an explanation, return empty
    if len(text) < 200 and text.count('\n') < 3:
        return ""
```

**LLM hallucination detection:**

Vision models sometimes hallucinate by repeating characters or duplicating sentences with errors:

```python
def has_excessive_repetition(text: str) -> bool:
    """Detect LLM hallucinations with excessive character repetition."""
    # Count sequences of 4+ repeated characters
    repetition_pattern = r'([a-zA-Z])\1{3,}'  # Same letter 4+ times
    matches = re.findall(repetition_pattern, text)

    if len(matches) >= 3:  # Multiple sequences
        return True

    # Check for very long repetition
    long_repetition = r'([a-zA-Z])\1{6,}'
    if re.search(long_repetition, text):
        return True

    return False
```

This caught hallucinations like `"Nannnnncy"` or `"yillllanova"`.

### Results: Quality Improvements

After running MiniCPM-V 2.6 on a test batch of albums, the improvements were **dramatic**.

**1. Handwritten text: From garbage to readable**

Tesseract completely failed on handwritten annotations. The vision model handled them beautifully. Where Tesseract produced `"7%%#ed ky Mow"`, the vision model correctly transcribed handwritten notes.

**2. Degraded/faded text: Much cleaner**

Old 1940s captions with yellowed paper and faded ink came through with:
- Fewer OCR errors (less `"yillanova"` → `"Villanova"` corrections needed)
- Better preservation of punctuation
- Cleaner word boundaries

**3. Less map noise: Context-aware filtering**

This was surprising. The vision model seemed to understand when text was a caption vs a map label. Pages with road maps produced significantly less noise. The model focused on actual photo captions and ignored highway signs and map annotations.

**4. Overall accuracy: Noticeably higher**

Across the board, caption quality improved. Fewer errors, better transcription, cleaner text. The "optimize for discovery" philosophy still applied, but now "good enough" was closer to "actually pretty good."

**Specific examples I noticed:**
- Handwritten dates that Tesseract missed: captured correctly
- Faded captions like "Trip to Big Bend, 1950": clean transcription
- Multi-line captions with line breaks: preserved structure
- Place names with unusual spelling: higher accuracy

### Trade-offs and Costs

Vision models aren't free. The quality improvements came with costs:

**1. Processing time: 2-3x slower**

- **Tesseract:** 1-2 seconds per image (1-2 hours total for 3,416 images)
- **Vision model:** 2-5 seconds per image (3-5 hours total)

Each crop took longer because the model had to:
- Encode image as base64
- Send HTTP request to LM Studio
- Run inference on vision model
- Return result

**Verdict:** Acceptable for a one-time quality run. Not great for rapid iteration during development.

**2. Setup complexity: Requires LM Studio running**

With Tesseract, I just run:
```bash
python3 ocr_scripts/ocr_pages.py --batch content/
```

With vision models, I have to:
1. Open LM Studio
2. Load the model
3. Start the server
4. Run the script with `--use-llm`

**Verdict:** Extra step, but not onerous. LM Studio is easy to use.

**3. Occasional chattiness: Needs filtering**

Even with prompt engineering, the vision model occasionally added explanations like:
- `"(No visible caption)"`
- `"There is no caption text on this page"`
- `"The caption appears to read: ..."`

My filters caught most of this, but it required extra post-processing logic.

**Verdict:** Manageable with good filters and prompt engineering.

**4. Overall verdict: Worth it for this use case**

For a one-time production run of 3,400+ pages where quality matters, the vision model is **absolutely worth it**.

If I were iterating rapidly during development (testing filters, trying different approaches), I'd stick with Tesseract for speed.

### When to Use Which Tool

After working with both, here's my decision framework:

**Use vision model (MiniCPM-V 2.6) for:**
- **Final production run** where quality matters most
- **Albums with handwriting** (dramatic improvement)
- **Degraded/faded text** from old photos
- **Maximum quality** needed for archival purposes
- **One-time processing** where 3-5 hours is acceptable

**Use Tesseract for:**
- **Quick testing and iteration** (2-3x faster)
- **Clean typed text** (Tesseract handles this fine)
- **Fast rebuilds during development** (seconds vs hours)
- **When speed matters** more than perfection
- **Good enough is good enough** philosophy applies

**Hybrid approach (what I'm doing):**
1. Use Tesseract during development (fast iteration)
2. Use vision model for final production run (best quality)
3. Keep Tesseract as fallback (if LM Studio connection fails)

The `--use-llm` flag makes this easy: same script, same logic, just swap the OCR engine.

### What's Next

I'm currently re-running all 46 albums with the vision model to generate the highest-quality captions possible. Once complete, I'll:

1. Rebuild the search index with cleaner captions
2. Compare search effectiveness (old vs new)
3. Document specific examples where vision model excelled
4. Potentially add manual correction tools for remaining errors

The search is already working well with Tesseract captions. Vision model captions should make it even better, especially for handwritten annotations and degraded text.

---

## Part 6: Future Enhancements

The search system is functional and in active use, but there are features I'm considering for the future:

### Potential Enhancements:

**Search Analytics**
- Track what people actually search for (Plausible event tracking)
- Identify common queries that return no results
- Guide future OCR improvements based on search patterns

**Advanced Filters**
- Date range filtering (e.g., "1940-1950")
- Album-specific search (e.g., `album:Louise`)
- Field-specific queries (e.g., `year:1947`)

**Manual Caption Corrections**
- Overlay system for correcting OCR errors
- User-submitted corrections (for family members)
- Version history of caption edits

**Timeline View**
- Extract dates from captions automatically
- Build chronological timeline of photos
- Interactive year/decade navigation

**Quality Improvements**
- Re-run all albums with vision model (MiniCPM-V 2.6) for better caption quality
- Compare search effectiveness: Tesseract vs vision model captions
- Document specific improvement cases

**Enhanced PhotoSwipe Integration**
- Add image zoom controls
- Download button for individual pages
- Share functionality (copy link to specific page)

For now, the system is "good enough" and actively used. These enhancements will come as actual needs emerge from real usage patterns.

---

## Part 7: Lessons Learned & Reflections

### What Worked

**1. Conservative OCR Filtering**

Preferring false positives over false negatives was the right call. I'd rather have some map noise in results than lose real captions.

**2. Client-Side Simplicity**

No backend = no maintenance, no costs, no downtime. The search index is just a static file that updates when I rebuild the site.

**3. Fast Rebuild Capability**

Separating OCR processing from index generation was brilliant. I can iterate on search logic in seconds instead of hours.

**4. Fuzzy Matching for OCR**

Fuse.js's fuzzy matching handles OCR errors beautifully. Queries like "Vilanova" find "Villanova" without manual correction.

### What Surprised Me

**1. How Well Fuzzy Matching Handles OCR Errors**

I expected to need manual correction or autocomplete. But Fuse.js's threshold tuning was sufficient. I never needed complex Boolean AND logic or query parsing.

**2. Client-Side Search Performance**

3,400+ entries search instantly. I was worried about browser performance, but modern JS engines laugh at this dataset size. Even with PhotoSwipe integration and dynamic image loading, everything feels instant.

**3. Visual Context Mattered More Than Search Precision**

I spent days optimizing OCR filtering and search relevance. Adding thumbnail previews had 10x the UX impact in a fraction of the time. Users don't want perfect search—they want to recognize results quickly.

**4. PhotoSwipe Integration Was Simpler Than Expected**

Reusing the existing lightbox component from gallery pages took just a few hours. The hardest part was preventing default navigation (solved with event capture phase).

**5. The Value of Per-Album JSONs**

I initially saw these as just build artifacts. But they've been valuable for:
- Debugging OCR issues
- Iterating on filtering logic
- Potential future features (caption display on pages)

### What I'd Do Differently

**1. Add Thumbnails from Day One**

Visual previews should have been in the initial design. They transformed the search experience more than any algorithmic improvement.

**2. Test with Real Use Cases Earlier**

I tested search with hypothetical single-word queries. Actual use revealed I needed grouping, thumbnails, and lightbox integration—not better query parsing.

**3. Trust Simplicity**

I planned complex Boolean AND logic, phrase search, and query routing. None of it was needed. Fuzzy matching + good UX won.

**4. Set Up Analytics from Day One**

I don't know what people are actually searching for. Adding Plausible event tracking for search queries would guide future improvements.

### Success Stories

**Specific searches that work beautifully:**

- `"1947 covered bridges"` → Finds exact album with visual previews
- `"Amish"` → Shows all Amish-related pages with thumbnails for quick scanning
- `"Big Bend"` → Finds all Big Bend National Park photos; click thumbnail to browse in lightbox
- `"Louise wedding"` → Album title match + individual page matches with captions
- `"yillanova"` (typo) → Fuzzy matching finds "Villanova" photos correctly

**The PhotoSwipe experience:**

Click any search result thumbnail → full-screen lightbox opens → arrow keys navigate through all matching pages → captions visible → escape to close. It feels like browsing a curated slideshow of search results.

### The "Optimize for Discovery" Philosophy

This project reinforced a core belief: **perfect transcription is the enemy of good search**.

If I had waited for 100% OCR accuracy:
- I'd still be tuning filters
- I'd be manually correcting thousands of captions
- The site still wouldn't have search

Instead, I shipped something "good enough":
- 95% caption accuracy (estimated)
- Fuzzy search handles the 5% errors
- Family members can find photos now

Search is for discovery, not archival transcription. That philosophy shaped every decision.

### What's Next

I'm currently exploring vision models (MiniCPM-V 2.6 via LM Studio) for better OCR on:
- Handwritten annotations
- Degraded or faded text
- Unusual fonts

But I'm not replacing Tesseract. Vision models will be an optional enhancement (`--use-llm` flag) for albums where I want higher quality.

The system is designed for incremental improvement, not wholesale replacement.

---

## Conclusion

Building search for 3,400+ scanned photo album pages taught me that "good enough" is often better than "perfect." Here's what I learned:

1. **OCR doesn't need to be perfect** - Fuzzy search handles errors gracefully
2. **Conservative filtering beats aggressive filtering** - Keep questionable text rather than lose real captions
3. **Client-side search scales surprisingly well** - 3,400 entries search instantly, even with PhotoSwipe integration
4. **Visual context beats search precision** - Thumbnail previews had 10x the UX impact of algorithmic improvements
5. **Simple solutions often win** - Fuzzy matching + good UX beat complex Boolean AND logic I never built
6. **Reuse existing components** - PhotoSwipe was already there; reusing it was trivial
7. **Separate OCR from indexing** - Fast rebuilds enable rapid iteration
8. **Test with real use, not hypothetical queries** - Actual usage revealed I needed thumbnails and grouping, not better parsing

The system shipped with features I didn't plan (PhotoSwipe lightbox, thumbnail previews, grouped results) and without features I thought were essential (Boolean AND, phrase search, query parsing). Real use revealed what actually mattered.

Family members are now finding photos they forgot existed. Search isn't just functional—it's delightful. Click a thumbnail, browse results in a full-screen lightbox, navigate with arrow keys, see captions alongside photos.

That's the goal: make family history discoverable and enjoyable.

---

## Technical Appendix

### Code Snippets

**OCR Pipeline:**
- Language: Python 3
- Libraries: OpenCV, Tesseract (pytesseract), PyYAML
- Processing: 1-2 seconds per image
- Batch time: 1-2 hours for 3,416 images

**Search Implementation:**
- Library: Fuse.js 7.0.0
- Index size: ~400KB JSON (~100KB gzipped)
- Search speed: <50ms for 3,400+ entries
- Threshold: 0.4 (40% error tolerance)
- Field weights: album_title=2, caption_text=1.5, searchable_text=0.5
- Result limit: 100 (increased from initial 50)
- Features: PhotoSwipe lightbox integration, thumbnail previews, grouped results

**Repository Links:**
- `ocr_scripts/ocr_pages.py` - OCR implementation (536 lines)
- `assets/js/search.js` - Client-side search with PhotoSwipe (536 lines)
- `assets/css/custom.css` - Search UI styling (412 lines)
- `layouts/_default/search.html` - Search page template (59 lines)
- `ocr_scripts/rebuild_search_index.py` - Fast index rebuild
- Planning docs in `ocr_scripts/` directory

### Performance Metrics

**OCR Processing:**
- Full run: 3,416 images in 1-2 hours
- Index rebuild: 3-5 seconds (no OCR)
- Vision model (optional): 3-5 hours (slower but better quality)

**Search Performance:**
- Index download: ~100KB (gzipped)
- Search latency: <50ms
- Results rendering: <10ms
- Works offline after first load

**Quality Metrics:**
- Estimated caption accuracy: 95%+
- False positives: ~5% (map noise, artifacts)
- False negatives: <1% (missed captions rare)
- User satisfaction: High (anecdotal)

### Acknowledgments

Thanks to:
- The Tesseract OCR team for amazing open-source OCR
- The Fuse.js team for fuzzy search excellence
- Hugo community for static site generator tools
- Family members for testing and feedback

---

*This is a living document. As the project evolves, I'll update this article with new learnings.*

*Last updated: January 2026*
