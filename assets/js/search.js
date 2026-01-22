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
        { name: 'album_title', weight: 3 },
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
  searchCount.textContent = `Found ${results.length} result${results.length === 1 ? '' : 's'}`;

  // Limit to first 50 results for performance
  const displayResults = results.slice(0, 50);

  const html = displayResults.map(result => {
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

    return `
      <div class="search-result">
        <div class="result-album-title">${highlightedTitle}</div>
        <div class="result-page-title">
          <a href="${linkUrl}">${escapeHtml(item.page_filename || item.album)}</a>
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

  searchResults.innerHTML = html;

  // Add "showing X of Y" message if results were limited
  if (results.length > 50) {
    searchResults.innerHTML += `
      <div class="search-limit-notice">
        Showing first 50 of ${results.length} results. Try refining your search.
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
