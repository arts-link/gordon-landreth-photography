/**
 * Client-Side Search for Gordon Landreth Photography
 * Uses Fuse.js for fuzzy search with OCR error tolerance
 */

import PhotoSwipeLightbox from "./photoswipe/photoswipe-lightbox.esm.js";
import PhotoSwipe from "./photoswipe/photoswipe.esm.js";
import PhotoSwipeDynamicCaption from "./photoswipe/photoswipe-dynamic-caption-plugin.esm.min.js";

let searchIndex = null;
let fuse = null;
let currentPageResults = []; // Page results only (not albums) for slideshow

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
        { name: 'caption_text', weight: 1.5 },  // Caption content only
        { name: 'searchable_text', weight: 0.5 } // Fallback for filenames
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

    // Only focus if no URL query parameter (to avoid jumping past results)
    const url = new URL(window.location);
    if (!url.searchParams.has('q')) {
      searchInput.focus();
    }

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

/**
 * Load image dimensions dynamically
 * @param {string} imageUrl - Full image path
 * @returns {Promise<{width: number, height: number}>}
 */
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

/**
 * Convert search result to PhotoSwipe slide data
 * @param {Object} result - Fuse.js result object
 * @returns {Promise<Object>} PhotoSwipe slide data
 */
async function resultToPhotoSwipeSlide(result) {
  const item = result.item;
  const imageSrc = `/${item.album_url_slug}/${item.page_filename}`;

  // Extract page number from filename
  const pageMatch = item.page_filename.match(/[_\s](?:Page|page|PAGE)[\s-]*(\d+)/);
  const pageNum = pageMatch ? parseInt(pageMatch[1]) : null;

  // Build caption
  let caption = `<div class="pswp-caption-content">`;
  caption += `<h3>${escapeHtml(item.album_title)}${pageNum ? ': Page ' + pageNum : ''}</h3>`;
  if (item.caption_text) {
    caption += `<p>${escapeHtml(item.caption_text).replace(/\n/g, '<br>')}</p>`;
  }
  caption += `</div>`;

  // Load dimensions
  const dimensions = await getImageDimensions(imageSrc);

  return {
    src: imageSrc,
    width: dimensions.width,
    height: dimensions.height,
    alt: `${item.album_title}${pageNum ? ' - Page ' + pageNum : ''}`,
    caption: caption
  };
}

// Get first N captions from captions array
function getExcerptCaptions(captions, maxCaptions = 3) {
  if (!captions || !Array.isArray(captions) || captions.length === 0) return '';

  // Join first N captions with double newlines
  return captions.slice(0, maxCaptions).join('\n\n');
}

// Perform search
function performSearch(query, updateUrl = true) {
  if (!query || query.trim().length < 2) {
    showInitialState();
    // Clear URL query parameter
    if (updateUrl && window.history.replaceState) {
      const url = new URL(window.location);
      url.searchParams.delete('q');
      window.history.replaceState({}, '', url);
    }
    return;
  }

  if (!fuse) {
    console.error('Search not initialized');
    return;
  }

  const results = fuse.search(query.trim());
  displayResults(results, query);

  // Update URL with search query
  if (updateUrl && window.history.replaceState) {
    const url = new URL(window.location);
    url.searchParams.set('q', query.trim());
    window.history.replaceState({}, '', url);
  }
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
    const captionTextMatched = matches.some(m => m.key === 'caption_text');

    // Categorize based on entry type and which field matched
    if (item.type === 'album') {
      // All album-level entries are album matches
      albumMatches.push(result);
      albumTitlesMatched.add(item.album_title);
    } else if (item.type === 'page' && captionTextMatched) {
      // Only show pages under "Caption Matches" if caption_text field matched
      // (not just album title or filename)
      captionMatches.push(result);
    }
  });

  return {
    albumMatches,
    captionMatches
  };
}

// Render a single result card
function renderResult(result, query, matchType, resultIndex = -1) {
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
      ${thumbnailUrl && item.type === 'page' && resultIndex >= 0 ? `
        <div class="result-thumbnail" data-href="${linkUrl}" data-result-index="${resultIndex}" role="button" tabindex="0">
          <img src="${thumbnailUrl}" alt="${escapeHtml(displayTitle)}" loading="lazy">
        </div>
      ` : thumbnailUrl ? `
        <a href="${linkUrl}" class="result-thumbnail">
          <img src="${thumbnailUrl}" alt="${escapeHtml(displayTitle)}" loading="lazy">
        </a>
      ` : ''}
      <div class="result-content">
        ${item.type === 'album' ? `<div class="result-album-title">${highlightedTitle}</div>` : ''}
        <div class="result-page-title">
          ${item.type === 'page' && resultIndex >= 0 ?
            `<span class="result-page-title-text">${escapeHtml(displayTitle)}</span>` :
            `<a href="${linkUrl}">${item.type === 'page' ? escapeHtml(displayTitle) : highlightedTitle}</a>`
          }
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
    currentPageResults = []; // Clear page results
    return;
  }

  searchEmpty.style.display = 'none';
  searchInitial.style.display = 'none';
  searchMeta.style.display = 'block';

  // Limit to first 100 results for performance
  const limitedResults = results.slice(0, 100);

  // Categorize results
  const { albumMatches, captionMatches } = categorizeResults(limitedResults);

  // Store page results for slideshow (caption matches only)
  currentPageResults = captionMatches;

  // Update count display with breakdown
  searchCount.textContent = `Found ${results.length} result${results.length === 1 ? '' : 's'} (${albumMatches.length} album, ${captionMatches.length} caption)`;

  let html = '';

  // Section 1: Album Title Matches
  if (albumMatches.length > 0) {
    html += '<div class="results-section">';
    html += '<h2 class="results-section-title">Album Title Matches</h2>';
    html += albumMatches.map(result => renderResult(result, query, 'album', -1)).join('');
    html += '</div>';
  }

  // Section 2: Caption Matches
  if (captionMatches.length > 0) {
    html += '<div class="results-section">';
    html += '<h2 class="results-section-title">Caption Matches</h2>';
    html += captionMatches.map((result, index) => renderResult(result, query, 'caption', index)).join('');
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

/**
 * Initialize PhotoSwipe for search results
 */
function initSearchLightbox() {
  const resultsContainer = document.getElementById('search-results');

  // Click handler - use capture phase to intercept before bubble phase
  resultsContainer.addEventListener('click', async (e) => {
    // Check if click is on thumbnail or its children
    const thumbnail = e.target.closest('.result-thumbnail[data-result-index]');
    if (!thumbnail) return;

    console.log('[Search] Thumbnail clicked, preventing default navigation');
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    const resultIndex = parseInt(thumbnail.dataset.resultIndex);
    if (isNaN(resultIndex)) {
      console.error('[Search] Invalid result index');
      return;
    }

    console.log('[Search] Opening PhotoSwipe for result index:', resultIndex, 'Total results:', currentPageResults.length);

    // Show loading cursor
    document.body.style.cursor = 'wait';

    try {
      // Build PhotoSwipe data source from current results
      const dataSource = await Promise.all(
        currentPageResults.map(result => resultToPhotoSwipeSlide(result))
      );

      console.log('[Search] PhotoSwipe data source built:', dataSource.length, 'slides');

      // Create PhotoSwipe instance with caption support
      const pswp = new PhotoSwipe({
        dataSource: dataSource,
        index: resultIndex,
        bgOpacity: 1,
        showHideAnimationType: 'zoom',
        imageClickAction: 'close',
        history: false, // Don't update URL hash
        // Add caption support directly in config
        captionPlugin: false, // Disable dynamic caption plugin for now
        paddingFn: (viewportSize) => {
          return viewportSize.x < 700
            ? { top: 0, bottom: 0, left: 0, right: 0 }
            : { top: 30, bottom: 30, left: 0, right: 0 };
        }
      });

      // Initialize PhotoSwipe
      pswp.init();
      console.log('[Search] PhotoSwipe opened successfully');

    } catch (error) {
      console.error('[Search] Failed to open PhotoSwipe:', error);
      console.error('[Search] Error message:', error?.message);
      console.error('[Search] Error stack:', error?.stack);
      // REMOVED FALLBACK NAVIGATION - let's see what the actual error is
      alert('PhotoSwipe failed to open. Check console for error details.');
    } finally {
      document.body.style.cursor = '';
    }
  }, true); // USE CAPTURE PHASE - critical for preventing navigation

  // Keyboard navigation handler for accessibility (Enter/Space keys)
  resultsContainer.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;

    const thumbnail = e.target.closest('.result-thumbnail[data-result-index]');
    if (!thumbnail) return;

    e.preventDefault();
    // Trigger the same handler as click
    thumbnail.click();
  }, true);
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

// Restore search from URL query parameter
function restoreSearchFromUrl() {
  const url = new URL(window.location);
  const query = url.searchParams.get('q');

  if (query) {
    searchInput.value = query;
    searchClear.style.display = 'flex';
    performSearch(query, false); // Don't update URL again
  }
}

// Initialize search on page load
document.addEventListener('DOMContentLoaded', () => {
  searchInput.disabled = true;
  initializeSearch().then(() => {
    // After search is initialized, restore query from URL
    restoreSearchFromUrl();
    // Initialize PhotoSwipe lightbox for search results
    initSearchLightbox();
  });
});
