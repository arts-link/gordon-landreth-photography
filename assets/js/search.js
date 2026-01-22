/**
 * Client-Side Search for Gordon Landreth Photography
 * Uses Fuse.js for fuzzy search with OCR error tolerance
 */

let searchIndex = null;
let fuse = null;

// DOM elements
const searchInput = document.getElementById('search-input');
const searchClear = document.getElementById('search-clear');
const searchResults = document.getElementById('search-results');
const searchMeta = document.getElementById('search-meta');
const searchCount = document.getElementById('search-count');
const searchEmpty = document.getElementById('search-empty');
const searchInitial = document.getElementById('search-initial');
const searchLoading = document.getElementById('search-loading');

// Debounce helper
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Load search index and initialize Fuse.js
async function initializeSearch() {
  try {
    searchLoading.style.display = 'block';
    searchInitial.style.display = 'none';

    const response = await fetch('/search/search-index.json');
    if (!response.ok) {
      throw new Error(`Failed to load search index: ${response.status}`);
    }

    searchIndex = await response.json();
    console.log(`Search index loaded: ${searchIndex.length} entries`);

    // Wait for Fuse.js to load from CDN
    await loadFuseJS();

    // Initialize Fuse.js with OCR-optimized configuration
    fuse = new Fuse(searchIndex, {
      keys: [
        { name: 'album_title', weight: 2 },
        { name: 'searchable_text', weight: 1 }
      ],
      threshold: 0.4, // Permissive for OCR errors
      ignoreLocation: true, // Search entire text
      minMatchCharLength: 2,
      includeMatches: true, // For highlighting
      includeScore: true
    });

    searchLoading.style.display = 'none';
    searchInitial.style.display = 'block';
    searchInput.disabled = false;
    searchInput.focus();

  } catch (error) {
    console.error('Search initialization failed:', error);
    searchLoading.style.display = 'none';
    searchResults.innerHTML = `
      <div class="search-error">
        <p>Failed to load search index. Please try refreshing the page.</p>
        <p class="error-details">${error.message}</p>
      </div>
    `;
  }
}

// Load Fuse.js from CDN
function loadFuseJS() {
  return new Promise((resolve, reject) => {
    // Check if Fuse is already loaded
    if (window.Fuse) {
      resolve();
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/fuse.js@7.0.0/dist/fuse.min.js';
    script.onload = resolve;
    script.onerror = () => reject(new Error('Failed to load Fuse.js'));
    document.head.appendChild(script);
  });
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Get first N captions from captions array
function getExcerptCaptions(captions, maxCaptions = 3) {
  if (!captions || !Array.isArray(captions) || captions.length === 0) return '';

  // Join first N captions with double newlines
  return captions.slice(0, maxCaptions).join('\n\n');
}

// Perform search
function performSearch(query) {
  if (!query || query.trim().length < 2) {
    showInitialState();
    return;
  }

  if (!fuse) {
    console.error('Search not initialized');
    return;
  }

  const results = fuse.search(query.trim());
  displayResults(results, query);
}

// Highlight search terms in text (simple regex-based highlighting)
function highlightSearchTerms(text, query) {
  if (!text || !query) return escapeHtml(text);

  // Split query into words and escape special regex characters
  const terms = query.trim().split(/\s+/).map(term =>
    term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  );

  // Create regex pattern for all terms
  const pattern = new RegExp(`(${terms.join('|')})`, 'gi');

  // Split text by pattern and wrap matches
  const parts = text.split(pattern);
  return parts.map((part, index) => {
    // Odd indices are captured groups (matches)
    if (index % 2 === 1) {
      return `<mark class="search-highlight">${escapeHtml(part)}</mark>`;
    }
    return escapeHtml(part);
  }).join('');
}

// Extract page number from filename (e.g., "_Page 01" or "_Page-01" → 1)
function extractPageNumber(filename) {
  if (!filename) return null;
  const match = filename.match(/_Page[-\s]?(\d+)/i);
  if (match) {
    return parseInt(match[1], 10);
  }
  return null;
}

// Format page title as "Album Title: Page #"
function formatPageTitle(albumTitle, filename) {
  const pageNum = extractPageNumber(filename);
  if (pageNum) {
    return `${albumTitle}: Page ${pageNum}`;
  }
  return filename; // Fallback if pattern doesn't match
}

// Categorize results by match type (album title vs caption)
function categorizeResults(results) {
  const albumMatches = [];
  const captionMatches = [];
  const albumTitlesMatched = new Set();

  results.forEach(result => {
    const item = result.item;
    const matches = result.matches || [];

    // Determine which field matched
    const albumTitleMatched = matches.some(m => m.key === 'album_title');
    const captionMatched = matches.some(m => m.key === 'searchable_text');

    if (albumTitleMatched) {
      // Track which album titles have matched
      if (item.type === 'album') {
        albumTitlesMatched.add(item.album_title);
        albumMatches.push(result);
      } else if (item.type === 'page') {
        // Only include page if we haven't seen the album title match
        if (!albumTitlesMatched.has(item.album_title)) {
          albumMatches.push(result);
        }
      }
    } else if (captionMatched) {
      captionMatches.push(result);
    }
  });

  // Second pass: remove page-level entries if album-level entry exists
  const finalAlbumMatches = albumMatches.filter(result => {
    if (result.item.type === 'page') {
      // Check if an album entry exists for this album_title
      const hasAlbumEntry = albumMatches.some(r =>
        r.item.type === 'album' && r.item.album_title === result.item.album_title
      );
      return !hasAlbumEntry;
    }
    return true;
  });

  return {
    albumMatches: finalAlbumMatches,
    captionMatches
  };
}

// Render a single result card
function renderResult(result, query, matchType) {
  const item = result.item;

  // Get excerpt with first few captions
  const excerpt = getExcerptCaptions(item.captions, 3);

  // Highlight search terms in excerpt and title
  const highlightedExcerpt = excerpt ? highlightSearchTerms(excerpt, query) : '';
  const highlightedTitle = highlightSearchTerms(item.album_title, query);

  // Build link URL: album URL + optional hash for specific image
  const linkUrl = item.album_url_slug
    ? `/${item.album_url_slug}/${item.image_index !== undefined ? '#' + item.image_index : ''}`
    : `/${item.page_path || item.album_path}`;

  // Determine display title
  let displayTitle;
  if (item.type === 'page') {
    // For pages: use formatted "Album: Page #" title
    displayTitle = formatPageTitle(item.album_title, item.page_filename);
  } else {
    // For albums: use album title
    displayTitle = item.album_title;
  }

  // Build thumbnail URL for pages
  let thumbnailUrl = '';
  if (item.type === 'page' && item.album_url_slug && item.page_filename) {
    // Construct URL using slug (not path) to avoid space encoding issues
    thumbnailUrl = `/${item.album_url_slug}/${item.page_filename}`;
  }

  return `
    <div class="search-result ${thumbnailUrl ? 'search-result--with-thumbnail' : ''}">
      ${thumbnailUrl ? `
        <a href="${linkUrl}" class="result-thumbnail">
          <img src="${thumbnailUrl}" alt="${escapeHtml(displayTitle)}" loading="lazy">
        </a>
      ` : ''}
      <div class="result-content">
        ${item.type === 'album' ? `<div class="result-album-title">${highlightedTitle}</div>` : ''}
        <div class="result-page-title">
          <a href="${linkUrl}">${item.type === 'page' ? escapeHtml(displayTitle) : highlightedTitle}</a>
        </div>
        ${highlightedExcerpt ? `
          <div class="result-excerpt">${highlightedExcerpt}</div>
        ` : ''}
        <div class="result-footer">
          <a href="${linkUrl}" class="result-link">View ${item.type === 'album' ? 'Album' : 'Page'} →</a>
        </div>
      </div>
    </div>
  `;
}

// Display search results
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

  // Limit to first 100 results for performance
  const limitedResults = results.slice(0, 100);

  // Categorize results
  const { albumMatches, captionMatches } = categorizeResults(limitedResults);

  // Update count display with breakdown
  searchCount.textContent = `Found ${results.length} result${results.length === 1 ? '' : 's'} (${albumMatches.length} album, ${captionMatches.length} caption)`;

  let html = '';

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

  searchResults.innerHTML = html;

  // Add "showing X of Y" message if results were limited
  if (results.length > 100) {
    searchResults.innerHTML += `
      <div class="search-limit-notice">
        Showing first 100 of ${results.length} results. Try refining your search.
      </div>
    `;
  }
}

// Show initial state
function showInitialState() {
  searchResults.innerHTML = '';
  searchMeta.style.display = 'none';
  searchEmpty.style.display = 'none';
  searchInitial.style.display = 'flex';
}

// Handle clear button
function clearSearch() {
  searchInput.value = '';
  searchClear.style.display = 'none';
  showInitialState();
  searchInput.focus();
}

// Event listeners
searchInput.addEventListener('input', debounce((e) => {
  const query = e.target.value;

  // Show/hide clear button
  searchClear.style.display = query ? 'flex' : 'none';

  performSearch(query);
}, 300));

searchClear.addEventListener('click', clearSearch);

// Handle Enter key
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    performSearch(searchInput.value);
  }
});

// Initialize search on page load
document.addEventListener('DOMContentLoaded', () => {
  searchInput.disabled = true;
  initializeSearch();
});
