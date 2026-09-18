# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Task Management with Beads

This project uses **bd (beads)** for persistent issue tracking and task management.

### When to Use Beads vs TodoWrite

**Use Beads (`bd`) for:**
- Multi-session work (survives context clears/compaction)
- Work with dependencies (task B depends on task A)
- Strategic planning (epics, features, bugs)
- Discovered work during implementation
- Anything that needs to persist across sessions

**Use TodoWrite for:**
- Simple single-session execution tracking
- Immediate task breakdown within current session
- Quick progress visibility for current work

**Rule of thumb:** When in doubt, prefer `bd`—persistence you don't need beats lost context.

### Essential Beads Commands

**Finding Work:**
```bash
bd ready                          # Show unblocked work ready to start
bd list --status=open             # All open issues
bd list --status=in_progress      # Active work
bd show <id>                      # Detailed issue view with dependencies
```

**Creating & Updating:**
```bash
bd create --title="..." --type=task|bug|feature --priority=2
bd update <id> --status=in_progress   # Claim work
bd close <id>                         # Mark complete
bd close <id1> <id2> ...              # Close multiple (efficient for batch)
```

**Dependencies:**
```bash
bd dep add <issue> <depends-on>   # Add dependency (issue depends on depends-on)
bd blocked                        # Show all blocked issues
```

**Priority Levels:** Use 0-4 or P0-P4 (0=critical, 2=medium, 4=backlog). NOT "high"/"medium"/"low".

### 🚨 SESSION CLOSE PROTOCOL 🚨

**CRITICAL**: Before ending any session or saying "done", you MUST complete this checklist:

```bash
# 1. Review changes
git status

# 2. Stage code changes
git add <files>

# 3. Sync beads changes
bd sync

# 4. Commit code with descriptive message
git commit -m "..."

# 5. Sync any new beads changes from commit
bd sync

# 6. Push to remote (MANDATORY - work is NOT done until pushed)
git push
```

**NEVER skip this.** Work is not complete until `git push` succeeds.

**Critical Rules:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

### Beads Workflow Best Practices

1. **Start of session:** Run `bd ready` to find available work
2. **Creating tasks:** Use parallel subagents for creating multiple issues efficiently
3. **During work:** Update status with `bd update <id> --status=in_progress`
4. **Completing work:** Close all finished issues at once: `bd close <id1> <id2> ...`
5. **End of session:** Run the SESSION CLOSE PROTOCOL above
6. **Check health:** Run `bd doctor` if you encounter sync issues

For full workflow details, run `bd prime` to get the latest context.

## Project Overview

This is a Hugo static site generator project hosting a family photo gallery featuring 48+ albums from photographer Gordon Landreth, spanning 1931-1990s. The site is deployed to AWS CloudFront and includes an OCR system for digitizing photo captions.

**Technology Stack:**
- Hugo v0.121.2+ (static site generator)
- hugo-theme-gallery v4.2.5 (via Go modules)
- Python 3 + OpenCV + Tesseract (OCR utilities)
- AWS S3 + CloudFront (hosting, being migrated to Cloudflare Workers — see Deployment below)

**Base URL:** https://gordon-landreth-photography.arts-link.com

## Common Commands

### Hugo Build & Development
```bash
hugo                    # Build site to /public/
hugo --minify --gc      # Production build with minification
hugo server             # Local dev server with live reload at http://localhost:1313
hugo deploy             # Deploy to S3 with CloudFront invalidation
./deploy.sh             # Full deployment (handles AWS credential switching)
```

### CloudFront Cache Management
```bash
aws cloudfront create-invalidation --distribution-id EPSVMGZTAOYO2 --paths "/*"
```

### OCR Caption Processing
```bash
# Install dependencies
pip3 install opencv-python pytesseract numpy
brew install tesseract  # macOS system dependency

# Run OCR on album pages
python3 ocr_scripts/ocr_pages.py <input_folder> <output_json> [--captions-out <captions_json>]
```

### Hugo Module Management
```bash
hugo mod get -u                    # Update all modules
hugo mod get -u github.com/nicokaiser/hugo-theme-gallery/v4  # Update theme
hugo mod tidy                      # Clean up unused modules
```

### Cloudflare Workers (live)
```bash
npm install       # pulls in wrangler, playwright
npm run cf:build   # hugo --minify --gc via scripts/cf-build.sh
npm run cf:dev     # build, then serve on the real Workers runtime
npm run cf:deploy  # build, then wrangler deploy
```

### Social Cards & Structured Data
```bash
hugo --minify && npm run og   # regenerate stale/missing OG cards — requires a build first
npm run og:check              # exit 1 if any card is missing or stale (no browser needed)
```

## Architecture

### Content Organization (Hugo Page Bundles)
- Photo albums live in `/content/` as directory-based page bundles
- Each album folder contains:
  - `index.md` - Frontmatter metadata (title, weight, menu config)
  - JPG images - Scanned pages or individual photos
- URL routing is file-based: folder structure becomes site URLs
- Navigation ordering via `weight` parameter in frontmatter (descending)

### Custom Layout System
Hugo's theme override system allows customization without modifying the theme:

**Key Custom Partials:**
- `/layouts/partials/gallery.html` - Core gallery rendering with EXIF metadata extraction
  - Reads image EXIF data (dates, descriptions, orientation)
  - Generates responsive image sets (thumbnails: 600x600, full: 1600x1600)
  - Extracts dominant colors for placeholders
  - Injects per-image Schema.org `ImageObject` microdata (creator tagged as
    `site.Params.Author`, i.e. Ben Strawbridge, who scanned/published — not the photographer)
- `/layouts/partials/apply-watermark.html` - A watermark-overlay implementation
  (`images.Overlay` against `params.gallerydeluxe.watermark`) that **is never called** — no
  template references it. Live photos are unwatermarked despite this file and its config both
  existing; treat that as the actual current behavior, not this file's presence, if it matters
  for a change you're making.
- `/layouts/partials/head.html` - Full override of the theme's own head.html, to drop its
  conflicting `Params.private` robots conditional — see Copyright & Privacy below
- `/layouts/partials/opengraph.html` - Override: points `og:image` at the generated card
  instead of the theme's raw-photo default — see Social Cards & Structured Data above
- `/layouts/partials/json-ld.html` - Organization/Person/WebSite/ImageGallery structured data
- `/layouts/partials/og-card.html` + `/layouts/_default/baseof.ogcard.html` - The OG card itself
- `/layouts/partials/head-custom.html` - The one true robots meta tag, Plausible analytics
  injection, search-index preload hint

### Image Processing Pipeline
Hugo processes images at build time:
- Auto-orientation based on EXIF
- Responsive image generation (multiple sizes)
- Quality: 75% JPEG, CatmullRom resampling
- `params.gallerydeluxe.watermark` is configured but not applied — see
  `apply-watermark.html` above
- EXIF filtering: preserves dates/descriptions, strips GPS for privacy

### OCR Architecture (Client-Side Search)
The OCR system digitizes typed captions from scanned album pages for searchable content:

**Pipeline:** Scanned JPG → OpenCV preprocessing → Tesseract OCR → Caption filtering → JSON index

**Design Principles** (see `ocr_scripts/AI_HANDOFF_OCR_AND_SEARCH.md` for full details):
- **Preserve multi-line captions** - Line breaks are semantically meaningful
- **Conservative filtering** - Prefer keeping questionable text over losing real captions
- **JSON array output** (not JSONL) - Easier for client-side JavaScript consumption
- **Optimize for discovery** - Goal is searchability, not perfect transcription

**Output Schema:**
```json
[
  {
    "filename": "album_Page-05.jpg",
    "path": "album/album_Page-05.jpg",
    "captions": ["Caption line 1\nContinuation", "Caption 2"],
    "caption_text": "Caption line 1...\n\nCaption 2..."
  }
]
```

**Hugo Integration (Planned):**
1. Place `ocr_captions.json` in `/static/search/`
2. Create search page at `/content/search.md`
3. Implement JavaScript client-side search (no backend needed for 81 pages)

### Configuration Files
- `/config/_default/hugo.toml` - Main site config (base URL, theme, image processing)
- `/config/production/hugo.toml` - Production overrides (Plausible analytics domain)
- `/config/_default/deployment.toml` - S3 bucket + CloudFront distribution settings
- `go.mod` / `go.sum` - Hugo module dependencies
- `/i18n/en.toml` - UI string translations

### Deployment Infrastructure

**Cloudflare is live.** `gordon-landreth-photography.arts-link.com` serves from the Worker via
a Custom Domain. AWS is kept as the rollback for now — do not tear down the S3/CloudFront side
until the Cloudflare side has been serving reliably for a good while longer.

- **Cloudflare Worker (live):** `wrangler.jsonc` → `scripts/cf-build.sh`. An assets-only
  Worker — no `main`, nothing executes per request, `public/` is served straight from the
  edge. Same shape as arts-link.com's Worker.
- **`workers_dev` is deliberately `false` here**, unlike arts-link.com. That site is public
  marketing content, so a crawlable `*.workers.dev` preview costs nothing. This site is a
  family photo archive that's noindex,nofollow but *not* access-controlled — a public preview
  subdomain would just be a second, easily-guessable copy of the same private images. Use
  `wrangler dev` locally, or the dashboard's per-version preview links, instead.
- **`cf-build.sh` self-installs `hugo_extended`.** Cloudflare Workers Builds' own tool-detection
  installs the *standard* Hugo binary, not extended — confirmed against a real build log, which
  ran the full ~10-12 minute image-processing pass and only failed at the very end, compiling
  `main.scss` (the theme's CSS pipeline needs the libsass transpiler, extended-only). The build
  script now checks for `+extended` on whatever `hugo` it's handed and fetches the real binary
  itself if it's missing, rather than trusting the detector or guessing at an env var to fix it.
- **No preview/production baseURL branching in `cf-build.sh`**, unlike arts-link.com's build
  script — see Copyright & Privacy below for why `.Params.private` can't just be cascaded true
  site-wide, and how privacy is actually enforced regardless of which branch built the page.
- **AWS S3 Bucket (rollback):** gordon-landreth-photography.arts-link.com (us-east-2)
- **CloudFront Distribution ID:** EPSVMGZTAOYO2
- **Cache Control:** 630-day max-age for static assets
- **Deploy Script:** `./deploy.sh` handles AWS credential profile switching and invalidation
- **`arts-link.com`'s CLAUDE.md has the full Workers Builds gotchas** (the "three checks on a
  PR, not two" GitHub App connection issue, `Settings → Builds` disconnected-banner trap, etc.)
  — the failure modes are the same here.

### Social Cards & Structured Data

- **Every home/album page gets its own 1200×630 OG card.** The `ogcard` output format
  (`config/_default/hugo.toml`) renders a second HTML output at `<page>/og.html`
  (`layouts/_default/baseof.ogcard.html` + `layouts/partials/og-card.html`), screenshotted by
  `scripts/og-images.mjs` (`npm run og`) into `static/og/`, same technique as arts-link.com's
  own card pipeline. Images are **committed** — nothing renders at deploy time. CI should run
  `npm run og:check` and fail if a card is missing or stale (not yet wired into a workflow here).
- **Three variants**, not one full-bleed crop: the source scans are portrait rectangles, so a
  wide fill would lose most of each print. A single photo bleeds to the card's own right edge
  with the title set in a facing "verso" column (a plate tipped into a monograph, not a pasted
  thumbnail) for home and any album page with photos; pages with none (About, Search, a future
  404) get a plain black, formal card instead — no image forced where the layout has none.
- **`layouts/partials/opengraph.html` overrides the theme's own** for one reason: point
  `og:image` at the generated card (falling back to `static/og-default.jpg` for a page added
  since the last `npm run og`) instead of the raw, multi-megabyte scan the stock partial links.
- **`layouts/partials/json-ld.html`** adds an Organization (Arts-Link, who built the site) +
  Person (Gordon Landreth, the photographer) + WebSite graph to every page, plus an
  ImageGallery node on album pages — on the theory that `noindex` asks bots not to index a
  page, not that they'll honor it, so whatever does read the page should read something
  accurate. This is separate from the per-image `itemscope`/`itemtype` microdata already inline
  in the stock `gallery.html` partial, which tags each photo's creator as `site.Params.Author`
  (Ben Strawbridge, who scanned and published it) — a different, also-correct answer to a
  different question than "who took the photograph."

## Important Constraints

### Copyright & Privacy
- **All images are family property** - Not public domain, do not suggest making them public
- **The site is noindex,nofollow but not access-controlled** - no login, nothing blocking a
  direct URL. "Private" here means "please don't index or crawl this," not "gated" — the two
  read the same in casual conversation but call for different fixes.
- **`hugo.toml`'s top-level `private = true` does nothing** - Hugo only reads `[params.*]` into
  `.Params`, not bare top-level keys. Don't "fix" this with a `[[cascade]]` that pushes
  `params.private = true` onto every page — `home.html` reads that exact same
  `Params.private` key to decide which albums appear in the grid, so cascading it true
  site-wide would silently empty the homepage while fixing robots. The actual, only
  noindex,nofollow tag lives in `head-custom.html`; `layouts/partials/head.html` (a full
  override of the theme's own) exists solely to drop the stock partial's own conflicting
  `Params.private` robots conditional, which used to ship a second, contradictory tag on
  every page.
- **`robots.txt` stays a permissive `User-agent: *` with no `Disallow`, on purpose.** Blocking
  crawlers at the robots.txt level would also block social-unfurl bots (iMessage, Slack,
  Twitter/X), which generally ignore `noindex` when fetching Open Graph data — this site wants
  to stay linkable/shareable even though it doesn't want to be indexed. See Social Cards &
  Structured Data above for the corollary: since `noindex` only asks politely and plenty of
  bots don't honor it, every page also carries real, accurate JSON-LD rather than nothing.
- Plausible analytics only (privacy-focused, no Google Analytics)
- GPS EXIF data intentionally stripped from images

### OCR System Philosophy
When working with the OCR system, always respect these principles:

❌ **Do NOT:**
- Flatten caption line breaks into single lines
- Drop small text blocks blindly (single words can be valid captions)
- Aggressively tune filters based on word count or length heuristics
- Discard raw OCR data

✅ **Do:**
- Preserve original multi-line caption structure
- Use conservative filtering to avoid losing real captions
- Optimize for search discovery, not perfect transcription
- Reference `ocr_scripts/AI_HANDOFF_OCR_AND_SEARCH.md` for detailed guidance

### Development Workflow
- **Task management:** Use `bd` (beads) for persistent issue tracking - see "Task Management with Beads" section above
- **Content-as-code:** Albums are just folders + markdown files
- **No database/CMS** - Fully static architecture
- **Git-based content workflow** - Commits track album additions, beads auto-syncs with git
- **Build-time optimization** - All image processing happens during `hugo` build
- **AWS CLI required** - Must have `aws configure` set up for deployment
- **Session completion:** Always run SESSION CLOSE PROTOCOL before ending work (see Beads section)

## Testing

No formal test suite exists. Verify changes by:
1. Running `hugo server` and visually inspecting at http://localhost:1313
2. Checking build output for errors: `hugo --minify --gc`
3. Testing deployment to staging (if needed) before production

## Module System

This project uses Hugo modules (not traditional theme directories):
- Theme dependency managed via `go.mod`
- Custom partials override theme defaults without forking
- Update theme: `hugo mod get -u`
