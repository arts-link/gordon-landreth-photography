# Plan: OCR All Albums & Implement Site-Wide Search

## Overview
Update the OCR script to process all 46 albums (3,416 images) and implement a Fuse.js-powered search engine that indexes OCR-extracted captions, album metadata, and image filenames.

## User Preferences
- **OCR Scope:** All 46 albums
- **JSON Structure:** One JSON per album + merged site-wide index
- **Search Scope:** OCR captions + album titles/metadata + image filenames
- **Search Library:** Fuse.js (fuzzy search, ~60KB)

## Current State Analysis

### OCR Script Limitations
- Processes single directory only
- Stores absolute paths (breaks Hugo integration)
- No album-level awareness or metadata
- Outputs one JSON for all processed images
- **Location:** `ocr_scripts/ocr_pages.py`

### Album Structure
- 46 albums in `/content/`
- 3,416 total scanned page images
- Each album: `index.md` + numbered page JPGs
- Consistent frontmatter: title, weight, menus
- **Example:** `content/1931-1939 courting & marriage/`

### Search Capabilities
- No existing search in hugo-theme-gallery
- Empty `/static/` directory (ready for search data)
- Hugo can generate JSON outputs natively
- CloudFront CDN ready to serve JSON files

## Implementation Plan

### Phase 1: Update OCR Script for Multi-Album Processing

**File:** `ocr_scripts/ocr_pages.py`

#### Changes Required:

1. **Add batch processing mode**
   - New CLI argument: `--batch` to process all subdirectories
   - Auto-discover album folders in `/content/`
   - Process each album independently

2. **Fix path handling**
   - Change from absolute paths to relative paths
   - Format: `album-name/image-filename.jpg`
   - Make paths Hugo-compatible (served from `/content/`)

3. **Add album metadata extraction**
   - Read `index.md` frontmatter for each album
   - Extract: title, weight, date range from folder name
   - Include album name in each page record

4. **Per-album JSON output**
   - Generate `content/{album-name}/ocr_captions.json` for each album
   - Structure:
     ```json
     {
       "album": "1931-1939 courting & marriage",
       "album_title": "1931 - 1939 Courting & Marriage",
       "pages": [
         {
           "filename": "page-01.jpg",
           "path": "1931-1939 courting & marriage/page-01.jpg",
           "captions": ["Caption text..."],
           "caption_text": "Flattened caption text"
         }
       ]
     }
     ```

5. **Create merged site-wide index**
   - New output: `static/search/search-index.json`
   - Combines all album JSONs into single searchable file
   - Include album metadata for each entry
   - Structure:
     ```json
     [
       {
         "type": "page",
         "album": "1931-1939 courting & marriage",
         "album_title": "1931 - 1939 Courting & Marriage",
         "page_filename": "page-01.jpg",
         "page_path": "1931-1939 courting & marriage/page-01.jpg",
         "captions": ["Caption 1", "Caption 2"],
         "searchable_text": "Combined text for search"
       },
       {
         "type": "album",
         "album": "1931-1939 courting & marriage",
         "album_title": "1931 - 1939 Courting & Marriage",
         "album_path": "1931-1939 courting & marriage/",
         "searchable_text": "Album title and description"
       }
     ]
     ```

#### New Command Signature:
```bash
# Process all albums in batch
python3 ocr_scripts/ocr_pages.py --batch content/ --search-index static/search/search-index.json

# Process single album (legacy mode)
python3 ocr_scripts/ocr_pages.py content/album-name/ output.json --captions-out captions.json
```

#### Implementation Details:

**Function to add: `process_albums_batch()`**
```python
def process_albums_batch(content_dir: Path, search_index_path: Path) -> None:
    """
    Process all album subdirectories in content_dir.

    For each album:
    1. Find album folder (contains index.md)
    2. Extract album metadata from frontmatter
    3. Run OCR on all images in album
    4. Save per-album JSON: album/ocr_captions.json
    5. Collect data for merged search index

    Finally, write merged search index with:
    - Album entries (searchable by title/date)
    - Page entries (searchable by captions/filenames)
    """
```

**Path normalization:**
```python
def make_relative_path(image_path: Path, content_dir: Path) -> str:
    """Convert absolute path to Hugo-compatible relative path."""
    return str(image_path.relative_to(content_dir))
```

**Frontmatter parsing:**
```python
def parse_album_metadata(index_md_path: Path) -> dict:
    """Extract title, weight, menus from index.md frontmatter."""
    # Use yaml.safe_load() to parse YAML frontmatter
```

### Phase 2: Implement Search Page with Fuse.js

**Files to Create/Modify:**

1. **`content/search.md`** - Search page content
   ```yaml
   ---
   title: "Search Albums"
   menus: main
   weight: 100
   layout: search
   ---
   Search through photo album captions and metadata.
   ```

2. **`layouts/_default/search.html`** - Custom search layout
   - Search input box
   - Results container
   - Fuse.js integration
   - Result rendering with links to albums/pages

3. **`static/search/search-index.json`** - Generated by OCR script (Phase 1)

4. **`layouts/partials/search-scripts.html`** - JavaScript for search
   - Load Fuse.js from CDN
   - Fetch search-index.json
   - Configure Fuse.js options
   - Handle search queries
   - Render results

#### Search Page Layout Structure:

```html
{{ define "main" }}
<div class="search-container">
  <h1>{{ .Title }}</h1>

  <input type="text" id="search-input" placeholder="Search captions, albums, dates..." />

  <div id="search-results">
    <!-- Results populated by JavaScript -->
  </div>
</div>

{{ partial "search-scripts.html" . }}
{{ end }}
```

#### Fuse.js Configuration:

```javascript
// Load Fuse.js from CDN
// https://cdn.jsdelivr.net/npm/fuse.js@7.0.0/dist/fuse.min.js

const fuseOptions = {
  keys: [
    { name: 'searchable_text', weight: 2 },
    { name: 'album_title', weight: 1.5 },
    { name: 'captions', weight: 2 },
    { name: 'page_filename', weight: 0.5 }
  ],
  threshold: 0.3,        // Fuzzy matching tolerance
  includeScore: true,    // Show relevance scores
  minMatchCharLength: 2  // Minimum search term length
};

// Initialize search
fetch('/search/search-index.json')
  .then(response => response.json())
  .then(data => {
    const fuse = new Fuse(data, fuseOptions);

    // Handle search input
    document.getElementById('search-input').addEventListener('input', (e) => {
      const results = fuse.search(e.target.value);
      renderResults(results);
    });
  });
```

#### Result Rendering:

```javascript
function renderResults(results) {
  const container = document.getElementById('search-results');

  if (results.length === 0) {
    container.innerHTML = '<p>No results found.</p>';
    return;
  }

  const html = results.map(result => {
    const item = result.item;

    if (item.type === 'album') {
      return `
        <div class="search-result album-result">
          <h3><a href="/${item.album_path}">${item.album_title}</a></h3>
          <p class="result-type">Album</p>
        </div>
      `;
    } else {
      return `
        <div class="search-result page-result">
          <h3><a href="/${item.album_path}">${item.album_title}</a></h3>
          <p class="page-info">Page: ${item.page_filename}</p>
          <p class="caption-preview">${item.captions.slice(0, 2).join(' • ')}</p>
          <a href="/${item.page_path}" class="view-page">View Page</a>
        </div>
      `;
    }
  }).join('');

  container.innerHTML = html;
}
```

### Phase 3: Styling and UI Polish

**File:** `assets/css/custom.css`

Add search-specific styles:
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

.search-result h3 {
  margin: 0 0 0.5rem 0;
}

.result-type {
  color: #666;
  font-size: 0.9rem;
}

.caption-preview {
  color: #555;
  font-style: italic;
  margin: 0.5rem 0;
}

.view-page {
  color: var(--link-color);
  text-decoration: none;
}
```

### Phase 4: Hugo Configuration Updates

**File:** `config/_default/hugo.toml`

Add JSON output support (optional, for future Hugo-generated indexes):
```toml
[outputs]
  home = ["HTML", "RSS", "JSON"]
  page = ["HTML"]
  section = ["HTML"]
```

No other Hugo changes needed - search is fully client-side.

## Critical Files Summary

### Files to Modify:
1. **`ocr_scripts/ocr_pages.py`** - Add batch mode, fix paths, generate search index
2. **`assets/css/custom.css`** - Add search UI styles
3. **`config/_default/hugo.toml`** (optional) - Add JSON outputs

### Files to Create:
1. **`content/search.md`** - Search page content
2. **`layouts/_default/search.html`** - Search page layout
3. **`layouts/partials/search-scripts.html`** - Fuse.js integration
4. **`static/search/search-index.json`** - Generated by OCR script (not manually created)
5. **`content/{album}/ocr_captions.json`** (×46) - Per-album caption files (generated)

## Execution Steps

### Step 1: Update OCR Script
1. Add batch processing logic
2. Implement path normalization
3. Add frontmatter parsing
4. Generate per-album JSONs
5. Create merged search index
6. Test on single album first

### Step 2: Run OCR on All Albums
```bash
# Create search directory
mkdir -p static/search

# Run batch OCR processing
python3 ocr_scripts/ocr_pages.py --batch content/ --search-index static/search/search-index.json

# This will:
# - Process all 46 albums (3,416 images)
# - Create content/{album}/ocr_captions.json for each album
# - Generate static/search/search-index.json
# - May take 1-2 hours depending on hardware
```

### Step 3: Implement Search Page
1. Create `content/search.md`
2. Create `layouts/_default/search.html`
3. Create `layouts/partials/search-scripts.html`
4. Add Fuse.js integration
5. Test locally with `hugo server`

### Step 4: Style and Polish
1. Update `assets/css/custom.css`
2. Test dark/light theme compatibility
3. Test on mobile devices
4. Optimize result rendering

### Step 5: Deploy
```bash
hugo --minify --gc
./deploy.sh
```

## Verification Plan

### OCR Script Verification:
1. Run on single test album first
2. Verify `ocr_captions.json` has correct relative paths
3. Verify album metadata is extracted correctly
4. Check merged `search-index.json` structure
5. Validate JSON syntax with `jq` or online validator

### Search Functionality Verification:
1. **Test local:** `hugo server` → visit `/search/`
2. **Test search input:** Type partial words (fuzzy matching)
3. **Test result types:** Verify both album and page results appear
4. **Test links:** Click results → should navigate to correct album/page
5. **Test captions:** Search for known caption text from OCR output
6. **Test metadata:** Search album titles, dates, names
7. **Test filenames:** Search for page numbers
8. **Test dark mode:** Verify styling in both themes

### End-to-End Test Cases:
- Search "1931" → should find "1931-1939 courting & marriage" album
- Search known caption text → should find specific pages
- Search "marriage" → should find relevant albums
- Search "page 05" → should find pages numbered 05
- Empty search → should show no results or all results
- Typos → fuzzy matching should still find results

## Performance Considerations

### OCR Processing Time:
- Estimated: 3,416 images × 1-2 seconds/image = **1-2 hours total**
- Can be run overnight or in background
- Consider processing in chunks if needed

### Search Index Size:
- Estimated: 46 albums × 74 images/album × 200 bytes/entry ≈ **680KB JSON**
- Gzipped by CloudFront: ~170KB
- Acceptable for client-side search
- Loads once, cached by browser

### Search Performance:
- Fuse.js handles 3,000+ entries efficiently
- Search is instant on modern browsers
- No backend required (pure client-side)

## Future Enhancements (Optional)

1. **Search result highlighting** - Show matching text snippets
2. **Filter by date range** - Add year/decade filters
3. **Filter by album** - Dropdown to limit search scope
4. **Search history** - Remember recent searches
5. **Share search results** - URL parameters for search queries
6. **Image thumbnails** - Show preview thumbnails in results
7. **Advanced search** - Boolean operators, phrase search
8. **Analytics** - Track popular searches (Plausible events)

## Risks and Mitigations

### Risk: OCR errors produce poor search results
**Mitigation:**
- OCR script already uses conservative filtering
- Fuzzy search tolerates typos
- Multiple search fields (captions + metadata + filenames)

### Risk: Large JSON file slow to load
**Mitigation:**
- CloudFront gzip compression (~75% reduction)
- Browser caching after first load
- Can implement lazy loading if needed

### Risk: Path format breaks image links
**Mitigation:**
- Test path normalization thoroughly
- Verify Hugo serves images correctly
- Use relative paths from content root

### Risk: Search UI doesn't match site theme
**Mitigation:**
- Use CSS variables from theme
- Test in dark/light modes
- Keep design minimal and clean

## Success Criteria

✅ All 46 albums processed with OCR
✅ Per-album JSON files generated with correct relative paths
✅ Merged search index created in `/static/search/`
✅ Search page accessible at `/search/`
✅ Fuse.js search returns relevant results
✅ Result links navigate to correct albums/pages
✅ UI works in both dark and light themes
✅ Search performs well with 3,000+ entries
✅ Deployed to production successfully
