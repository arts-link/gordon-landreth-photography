# Search Implementation Analysis & Improvement Plan

## Current Search Implementation - Detailed Breakdown

### Overview
The site uses **client-side fuzzy search** powered by Fuse.js v7.0.0 with high OCR error tolerance. The search is designed to handle imperfect caption text from Tesseract OCR processing.

---

## How Search Currently Works

### 1. Search Type: **Fuzzy Matching (NOT Boolean)**

**Library:** Fuse.js (Bitap algorithm)
**Configuration:**
```javascript
fuse = new Fuse(searchIndex, {
  keys: [
    { name: 'album_title', weight: 3 },      // Album titles prioritized 3x
    { name: 'searchable_text', weight: 1 }   // Caption text baseline weight
  ],
  threshold: 0.4,          // 40% error tolerance (VERY permissive for OCR)
  ignoreLocation: true,    // Search entire text, not positional
  minMatchCharLength: 2,
  includeMatches: true,
  includeScore: true
});
```

**What this means:**
- Your query is treated as a **single fuzzy string**, NOT individual words with boolean AND/OR logic
- The search tolerates up to 40% character-level errors (designed for OCR mistakes)
- Results are ranked by weighted fuzzy-match score (lower = better match)
- Album titles get 3x priority over caption text

---

### 2. Fields Searched

**Only TWO fields are actually searched:**

1. **`album_title`** (weight: 3)
   - Example: `"1931 - 1939 courting & marriage"`
   - Matches here appear first in results

2. **`searchable_text`** (weight: 1)
   - Concatenated caption text + filename
   - Example: `"TRIP TO FLORIDA, via the GREAT SMOKIES\nGordon Landreth and Paul Kreider ... 1931-1939 courting&marriage_Page 01.jpg"`

**Fields NOT searched:**
- `album` (folder name) - not indexed
- `page_filename` alone - only as part of `searchable_text`
- `captions` array - only the joined `searchable_text`
- `page_path` - not indexed

---

### 3. Query Processing

**Current behavior:**

```javascript
// User types: "florida trip"
const results = fuse.search("florida trip");
// Fuse.js treats "florida trip" as ONE fuzzy string
// Matches: "Florida Trip", "florida trippp" (typos), "floridda trip"
// Does NOT require BOTH words to be present (fuzzy matching, not boolean AND)
```

**Highlighting logic:**
```javascript
// Query: "florida trip"
// Highlighting splits by whitespace and treats as OR
const terms = ["florida", "trip"];  // Simple split
const pattern = /(florida|trip)/gi;  // Regex OR
// Wraps ANY matching word in <mark> tags
```

**Issue:** Highlighting doesn't respect Fuse.js's actual fuzzy match positions - it just highlights any word from the query.

---

### 4. Search Index Structure

**Location:** `static/search/search-index.json`

**Two entry types per album:**

**Type 1: Album Entry**
```json
{
  "type": "album",
  "album": "1931-1939 courting & marriage",
  "album_title": "1931 - 1939 courting & marriage",
  "album_url_slug": "1931-1939-courting--marriage",
  "searchable_text": "1931 - 1939 courting & marriage"
}
```

**Type 2: Page Entry** (one per scanned page with captions)
```json
{
  "type": "page",
  "album": "1931-1939 courting & marriage",
  "album_title": "1931 - 1939 courting & marriage",
  "album_url_slug": "1931-1939-courting--marriage",
  "page_filename": "1931-1939 courting&marriage_Page 01.jpg",
  "image_index": 0,
  "captions": [
    "TRIP TO FLORIDA, via the GREAT SMOKIES\nGordon Landreth...",
    "CROSSING THE GREAT SMOKIES from Gatlinburg..."
  ],
  "searchable_text": "TRIP TO FLORIDA, via the GREAT SMOKIES\nGordon Landreth... CROSSING THE GREAT SMOKIES... 1931-1939 courting&marriage_Page 01.jpg"
}
```

**Index size:** 3,461 total entries (46 albums + ~3,415 pages)

---

### 5. Result Ranking & Display

**Ranking:** By Fuse.js score (lower = better)
- Weighted by field (album_title: 3x, searchable_text: 1x)
- Character-level fuzzy matching distance
- No page ranking or relevance tuning beyond Fuse.js defaults

**Display limits:**
- First **50 results** shown
- Message displayed if more results exist
- No pagination (just truncation)

**Result card format:**
```
┌─────────────────────────────────────┐
│ Album Title (highlighted)           │
│ Page filename (linked)               │
│ First 3 captions (highlighted)      │
│ [View Page →]                        │
└─────────────────────────────────────┘
```

---

### 6. Search Performance

**Client-side only:** No backend required
- Search index loaded once on page load (~400KB JSON)
- All matching happens in browser
- Debounce: 300ms delay while typing
- Min query: 2 characters

**Works well for:** 3,000-5,000 entries (current size is well within limits)

---

## Potential Issues (What Might Not Work As Expected)

Based on the implementation, here are common issues users might experience:

### Issue 1: **No Boolean AND Logic**

**Example:**
```
Query: "florida bridges"
Expected: Pages with BOTH "florida" AND "bridges"
Actual: Fuzzy matches "florida bridges" as a phrase (could match "florida" OR "bridges" OR variations)
```

**Why:** Fuse.js treats the entire query as a fuzzy string, not individual required terms.

---

### Issue 2: **Overly Permissive Matching (40% Threshold)**

**Example:**
```
Query: "Gordon"
Might match: "Garden", "Gordan", "Jordon" (OCR errors)
```

**Why:** 0.4 threshold is very high to accommodate OCR mistakes, but causes false positives.

---

### Issue 3: **No Phrase Search**

**Example:**
```
Query: "Big Spring Texas"
Expected: Exact phrase match
Actual: Fuzzy matches parts/variations
```

**Why:** No quote-based phrase search implemented.

---

### Issue 4: **Highlighting Mismatch**

**Example:**
```
Query: "Gordan" (typo)
Fuse matches: "Gordon" (fuzzy match)
Highlighting: Nothing (regex only highlights exact "Gordan")
```

**Why:** Highlighting uses simple regex word matching, not Fuse.js's actual match positions.

---

### Issue 5: **Limited Result Set (50 max)**

**Example:**
```
Query: "1947" (common year)
Results: First 50 of 200+ matches
User: Can't see all results
```

**Why:** Hard 50-result limit with no pagination.

---

### Issue 6: **No Multi-Word AND Filtering**

**Example:**
```
Query: "Gordon Amish"
Expected: Pages mentioning BOTH Gordon AND Amish
Actual: Fuzzy matches the phrase "Gordon Amish"
```

**Why:** No token-based AND filtering.

---

## Critical Files

### Search Implementation
- `/Volumes/wanderer/dev/solo/gordon-landreth-photography/layouts/_default/search.html` - Search page template
- `/Volumes/wanderer/dev/solo/gordon-landreth-photography/assets/js/search.js` - Client-side search logic (Fuse.js)
- `/Volumes/wanderer/dev/solo/gordon-landreth-photography/content/search.md` - Search page content

### Search Index
- `/Volumes/wanderer/dev/solo/gordon-landreth-photography/static/search/search-index.json` - Generated index (~400KB)
- `/Volumes/wanderer/dev/solo/gordon-landreth-photography/ocr_scripts/rebuild_search_index.py` - Index generation script

### Styling
- `/Volumes/wanderer/dev/solo/gordon-landreth-photography/assets/css/custom.css` - Search UI styles

---

## Questions for User

To improve the search, I need to understand what's not working for you:

### 1. Search Behavior
- **What search queries are not working as expected?** (Give specific examples)
- **Do you expect boolean AND logic?** (e.g., "Gordon Amish" should require BOTH words)
- **Is fuzzy matching too loose?** (Getting irrelevant results?)
- **Do you want exact phrase search?** (e.g., `"Big Spring Texas"` in quotes)

### 2. Result Quality
- **Are results ranked poorly?** (Relevant pages not appearing first?)
- **Too many results?** (Need better filtering?)
- **Too few results?** (Need more permissive matching?)

### 3. User Experience
- **Is the 50-result limit a problem?** (Want pagination?)
- **Are highlights misleading?** (Showing wrong matches?)
- **Need result grouping?** (e.g., group by album?)

### 4. Specific Use Cases
- **What are your most common search queries?**
- **What information are you typically looking for?** (People, places, dates, events?)

---

## Potential Improvements (Options)

Once I understand your needs, here are possible improvements:

### Option A: **Add Boolean AND Logic**
- Pre-filter results to require ALL query words present
- Keep fuzzy matching but enforce multi-word presence

### Option B: **Tighten Fuzzy Threshold**
- Reduce from 0.4 to 0.2-0.3 for stricter matching
- Reduce false positives at cost of missing OCR errors

### Option C: **Phrase Search Support**
- Detect quoted queries: `"Big Spring Texas"`
- Use exact substring matching for phrases

### Option D: **Better Highlighting**
- Use Fuse.js match positions instead of regex
- Show actual fuzzy-matched text

### Option E: **Result Pagination**
- Remove 50-result limit
- Add "Load More" or pagination UI

### Option F: **Search Field Expansion**
- Index additional fields (dates, locations, people)
- Add field-specific search (e.g., `album:florida`)

### Option G: **Result Grouping**
- Group results by album
- Show # of matches per album

---

## User Requirements - Specific Issues

Based on user feedback:

**Problems:**
1. ❌ Multi-word searches don't require ALL words (e.g., "Gordon Amish" matches pages with only one word)
2. ❌ Too many irrelevant results (fuzzy matching too loose)
3. ❌ Results ranked poorly (relevant pages not appearing first)
4. ❌ Hit the 50 result limit frequently (can't see all matches)

**Example problem queries:**
- Names that also appear in titles: `Louise`, `Kitty`, `Cindy`, `Kathy`
- Place names: `Big Bend`

**Desired behavior:**
- ✅ Boolean AND logic for multi-word queries (all words must be present)
- ✅ Phrase search support with exact quotes (e.g., `"Big Bend"`)
- ✅ Tighter fuzzy matching (fewer false positives)
- ✅ Better ranking (most relevant results first)
- ✅ No artificial result limit (or much higher limit)

---

## Implementation Plan

### Solution: Hybrid Search with AND Logic + Phrase Support

**Strategy:** Add intelligent query processing BEFORE Fuse.js to implement boolean AND and phrase search, while keeping fuzzy matching for individual terms.

### Changes Required

#### **File:** `assets/js/search.js`

---

### 1. Add Query Parser (NEW FUNCTION)

Detect and parse different query types:

```javascript
/**
 * Parse search query into structured format
 *
 * Examples:
 *   parseQuery('Gordon Amish') → { type: 'multi-word', terms: ['Gordon', 'Amish'], original: 'Gordon Amish' }
 *   parseQuery('"Big Bend"') → { type: 'phrase', phrase: 'Big Bend', original: '"Big Bend"' }
 *   parseQuery('Louise') → { type: 'single-word', term: 'Louise', original: 'Louise' }
 */
function parseQuery(query) {
  const trimmed = query.trim();

  // Check for quoted phrase: "exact match"
  const phraseMatch = trimmed.match(/^"(.+)"$/);
  if (phraseMatch) {
    return {
      type: 'phrase',
      phrase: phraseMatch[1],
      original: trimmed
    };
  }

  // Split by whitespace for multi-word queries
  const words = trimmed.split(/\s+/).filter(w => w.length >= 2);

  if (words.length === 1) {
    return {
      type: 'single-word',
      term: words[0],
      original: trimmed
    };
  }

  return {
    type: 'multi-word',
    terms: words,
    original: trimmed
  };
}
```

---

### 2. Implement Boolean AND Filter (NEW FUNCTION)

Pre-filter results to ensure ALL query words are present:

```javascript
/**
 * Filter results to require ALL query terms present (boolean AND)
 *
 * @param {Array} results - Fuse.js search results
 * @param {Array} terms - Query terms that must all be present
 * @returns {Array} Filtered results
 */
function filterByAllTerms(results, terms) {
  return results.filter(result => {
    const item = result.item;
    const searchableText = (
      (item.album_title || '') + ' ' +
      (item.searchable_text || '')
    ).toLowerCase();

    // Check that ALL terms appear in the searchable text
    return terms.every(term =>
      searchableText.includes(term.toLowerCase())
    );
  });
}
```

**How this works:**
- After Fuse.js returns fuzzy matches, we filter to only keep results where ALL query words appear
- Case-insensitive substring matching
- Works on both `album_title` and `searchable_text` fields
- Example: Query "Gordon Amish" → only results containing BOTH "Gordon" AND "Amish"

---

### 3. Implement Phrase Search (NEW FUNCTION)

Exact substring matching for quoted phrases:

```javascript
/**
 * Search for exact phrase match (no fuzzy matching)
 *
 * @param {string} phrase - Exact phrase to find
 * @returns {Array} Results containing the exact phrase
 */
function searchExactPhrase(phrase) {
  if (!searchIndex) return [];

  const phraseLower = phrase.toLowerCase();

  return searchIndex
    .filter(item => {
      const searchableText = (
        (item.album_title || '') + ' ' +
        (item.searchable_text || '')
      ).toLowerCase();

      return searchableText.includes(phraseLower);
    })
    .map((item, index) => ({
      item: item,
      score: 0,  // Perfect match
      refIndex: index
    }));
}
```

**How this works:**
- Bypasses Fuse.js entirely for quoted queries
- Simple case-insensitive substring search
- Returns results in original index order
- Example: Query `"Big Bend"` → only pages with exact phrase "Big Bend"

---

### 4. Update Main Search Function

Replace the simple `performSearch()` function with intelligent query routing:

```javascript
// Perform search (UPDATED)
function performSearch(query) {
  if (!query || query.trim().length < 2) {
    showInitialState();
    return;
  }

  if (!fuse) {
    console.error('Search not initialized');
    return;
  }

  // Parse query to detect type
  const parsed = parseQuery(query);
  let results;

  if (parsed.type === 'phrase') {
    // Exact phrase search (bypass Fuse.js)
    results = searchExactPhrase(parsed.phrase);
    console.log(`Phrase search: "${parsed.phrase}" → ${results.length} results`);

  } else if (parsed.type === 'multi-word') {
    // Multi-word with boolean AND
    // Step 1: Use Fuse.js for fuzzy matching on full query
    const fuseResults = fuse.search(parsed.original);

    // Step 2: Filter to require ALL terms present
    results = filterByAllTerms(fuseResults, parsed.terms);
    console.log(`Multi-word AND search: ${parsed.terms.join(' + ')} → ${results.length} results`);

  } else {
    // Single-word fuzzy search (original behavior)
    results = fuse.search(parsed.term);
    console.log(`Single-word fuzzy search: "${parsed.term}" → ${results.length} results`);
  }

  displayResults(results, query);
}
```

**Query routing logic:**
1. **Quoted phrase** (`"Big Bend"`) → exact substring search
2. **Multi-word** (`Gordon Amish`) → Fuse.js fuzzy search + AND filter
3. **Single word** (`Louise`) → Fuse.js fuzzy search (original behavior)

---

### 5. Tighten Fuzzy Threshold

Reduce false positives while keeping OCR tolerance:

```javascript
// Initialize Fuse.js with OCR-optimized configuration (UPDATED)
fuse = new Fuse(searchIndex, {
  keys: [
    { name: 'album_title', weight: 3 },
    { name: 'searchable_text', weight: 1 }
  ],
  threshold: 0.3,  // CHANGED from 0.4 → 0.3 (tighter matching)
  ignoreLocation: true,
  minMatchCharLength: 2,
  includeMatches: true,
  includeScore: true
});
```

**Impact:**
- 0.4 → 0.3 reduces fuzzy tolerance from 40% to 30%
- Still handles OCR typos (`Gordan` → `Gordon`)
- Reduces false positives (`Garden` no longer matches `Gordon`)

---

### 6. Remove 50 Result Limit

Increase to 200 results with "Load More" functionality:

```javascript
// Display search results (UPDATED)
function displayResults(results, query) {
  if (results.length === 0) {
    searchResults.innerHTML = '';
    searchMeta.style.display = 'none';
    searchEmpty.style.display = 'flex';
    searchInitial.style.display = 'none';
    return;
  }

  searchEmpty.style.display = 'none';
  searchInitial.style.display = 'none';
  searchMeta.style.display = 'block';
  searchCount.textContent = `Found ${results.length} result${results.length === 1 ? '' : 's'}`;

  // Increase limit to 200 (from 50)
  const displayResults = results.slice(0, 200);

  // ... render results HTML ...

  searchResults.innerHTML = html;

  // Update notice for 200+ results
  if (results.length > 200) {
    searchResults.innerHTML += `
      <div class="search-limit-notice">
        Showing first 200 of ${results.length} results. Try refining your search with more specific terms.
      </div>
    `;
  }
}
```

**Alternative:** Add "Load More" button for pagination (can implement if needed)

---

### 7. Fix Page Title Display

Change from showing image filename to "Page #" format:

```javascript
// Display search results (UPDATED - page title section)
function displayResults(results, query) {
  // ... existing code ...

  const html = displayResults.map(result => {
    const item = result.item;

    // Get excerpt with first few captions
    const excerpt = getExcerptCaptions(item.captions, 3);

    // Highlight search terms in excerpt and title
    const highlightedExcerpt = excerpt ? highlightSearchTerms(excerpt, query) : '';
    const highlightedTitle = highlightSearchTerms(item.album_title, query);

    // CHANGED: Format page title as "Page #" instead of filename
    const pageTitle = item.type === 'page' && item.image_index !== undefined
      ? `Page ${item.image_index + 1}`  // image_index is 0-based
      : (item.page_filename || item.album);

    // Build link URL: album URL + optional hash for specific image
    const linkUrl = item.album_url_slug
      ? `/${item.album_url_slug}/${item.image_index !== undefined ? '#' + item.image_index : ''}`
      : `/${item.page_path || item.album_path}`;

    return `
      <div class="search-result">
        <div class="result-album-title">${highlightedTitle}</div>
        <div class="result-page-title">
          <a href="${linkUrl}">${escapeHtml(pageTitle)}</a>
        </div>
        ${highlightedExcerpt ? `
          <div class="result-excerpt">${highlightedExcerpt}</div>
        ` : ''}
        <div class="result-footer">
          <a href="${linkUrl}" class="result-link">View Page →</a>
        </div>
      </div>
    `;
  }).join('');

  // ... rest of function ...
}
```

**Change details:**
- **Old:** `<a href="...">1931-1939 courting&marriage_Page 01.jpg</a>`
- **New:** `<a href="...#0">Page 1</a>`

**Note:** `image_index` is 0-based (0, 1, 2...), so we add 1 for display (Page 1, Page 2, Page 3...)

---

### 8. Improve Highlighting for Phrase Search

Update highlighting to support exact phrases:

```javascript
// Highlight search terms in text (UPDATED)
function highlightSearchTerms(text, query) {
  if (!text || !query) return escapeHtml(text);

  // Check if query is a quoted phrase
  const phraseMatch = query.trim().match(/^"(.+)"$/);

  if (phraseMatch) {
    // Exact phrase highlighting
    const phrase = phraseMatch[1];
    const escapedPhrase = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(`(${escapedPhrase})`, 'gi');

    const parts = text.split(pattern);
    return parts.map((part, index) => {
      if (index % 2 === 1) {
        return `<mark class="search-highlight">${escapeHtml(part)}</mark>`;
      }
      return escapeHtml(part);
    }).join('');
  }

  // Multi-word highlighting (original logic)
  const terms = query.trim().split(/\s+/).map(term =>
    term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  );

  const pattern = new RegExp(`(${terms.join('|')})`, 'gi');
  const parts = text.split(pattern);

  return parts.map((part, index) => {
    if (index % 2 === 1) {
      return `<mark class="search-highlight">${escapeHtml(part)}</mark>`;
    }
    return escapeHtml(part);
  }).join('');
}
```

---

## Expected Behavior After Changes

### Test Case 1: Multi-Word Search (Boolean AND)

**Query:** `Gordon Amish`

**Old behavior:**
- Fuse.js fuzzy matches "Gordon Amish" as a phrase
- Results may have only "Gordon" OR only "Amish"
- ~100+ results

**New behavior:**
- Fuse.js fuzzy matches "Gordon Amish"
- Results filtered to require BOTH "Gordon" AND "Amish"
- ~20-30 results (more relevant)

---

### Test Case 2: Phrase Search (Exact Match)

**Query:** `"Big Bend"`

**Old behavior:**
- Fuse.js fuzzy matches "big bend"
- May match "Big Basin", "Bend Oregon", "bigger bends"
- ~50+ results

**New behavior:**
- Exact substring search for "Big Bend"
- Only pages containing exact phrase
- ~5-10 results (precise)

---

### Test Case 3: Name in Album Title

**Query:** `Louise`

**Old behavior:**
- Matches album title "1968-1969 Louise's marriage" (weight 3x)
- Album title results dominate
- Fuzzy matches "Louis", "Louisa"

**New behavior:**
- Still matches album title (same weight)
- Tighter threshold (0.3) reduces "Louis" matches
- Single-word query still uses fuzzy search
- Better ranking with threshold change

**Improvement:** To specifically search captions only (not titles), user could search `"Louise" Amish` to force caption matches

---

### Test Case 4: Common Term with Many Results

**Query:** `1947`

**Old behavior:**
- ~200+ results
- Only see first 50
- Message: "Showing first 50 of 200 results"

**New behavior:**
- ~200+ results
- See first 200
- Message: "Showing first 200 of 200 results" (or all if under 200)

---

## Summary of Changes

| Feature | Old Behavior | New Behavior |
|---------|--------------|--------------|
| **Multi-word search** | Fuzzy phrase match (OR-like) | Boolean AND (all words required) |
| **Phrase search** | Not supported | Exact match with quotes |
| **Fuzzy threshold** | 0.4 (40% tolerance) | 0.3 (30% tolerance) |
| **Result limit** | 50 results | 200 results |
| **Page titles** | Full filename | "Page #" format |
| **Highlighting** | Word-level regex | Phrase-aware highlighting |

---

## Implementation Files

### File to Modify
**`/Volumes/wanderer/dev/solo/gordon-landreth-photography/assets/js/search.js`**

Changes:
1. Add `parseQuery()` function (lines ~30-60, NEW)
2. Add `filterByAllTerms()` function (lines ~60-80, NEW)
3. Add `searchExactPhrase()` function (lines ~80-100, NEW)
4. Update `performSearch()` function (lines 112-125, REPLACE)
5. Update Fuse.js config threshold: 0.4 → 0.3 (line 55, EDIT)
6. Update `displayResults()` limit: 50 → 200 (line 166, EDIT)
7. Update `displayResults()` page title format: filename → "Page #" (lines 186-187, EDIT)
8. Update `highlightSearchTerms()` for phrases (lines 127-148, REPLACE)

**Estimated changes:** ~120 lines modified/added (mostly new functions)

---

## Verification Plan

### 1. Test Multi-Word Boolean AND

```
Query: "Gordon Amish"
Expected: Pages with BOTH "Gordon" AND "Amish"
Check: Open 3-5 results, verify both terms present
```

### 2. Test Phrase Search

```
Query: "Big Bend"
Expected: Pages with exact phrase "Big Bend"
Check: Results should not include "Big Basin" or "Bend" alone
```

### 3. Test Name Queries

```
Query: "Louise"
Expected: Fewer false positives (no "Louis", "Louisa")
Check: Verify tighter matching works
```

### 4. Test Result Limit

```
Query: "1947"
Expected: See 200 results instead of 50
Check: Scroll to bottom, should see 200 results or message
```

### 5. Test Single-Word Fuzzy

```
Query: "Gordan" (typo)
Expected: Still matches "Gordon" (OCR tolerance)
Check: Fuzzy matching still works for typos
```

### 6. Test Highlighting

```
Query: "Big Bend"
Expected: Exact phrase "Big Bend" highlighted, not individual words
Check: Highlighting should wrap entire phrase
```

---

## Deployment Steps

1. **Edit search.js** with changes above
2. **Test locally:** `hugo server` → http://localhost:1313/search/
3. **Test all 6 verification cases** above
4. **Deploy:** `hugo --minify --gc && hugo deploy`
5. **Test production:** https://gordon-landreth-photography.arts-link.com/search/

---

## Potential Future Enhancements

- **Field-specific search:** `title:Louise` to search only album titles
- **Date range search:** `1947-1950` to filter by years
- **Result grouping:** Group results by album with expandable sections
- **Advanced filters:** Filter by album, year, person name
- **Search history:** Save recent searches in localStorage
