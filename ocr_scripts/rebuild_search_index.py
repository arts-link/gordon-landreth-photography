#!/usr/bin/env python3
"""Rebuild search index from existing ocr_captions.json files (no OCR processing).

This script provides a fast way to regenerate the search index when:
- Fixing URL slug generation bugs
- Updating album titles in frontmatter
- Testing search functionality
- Changing search index schema

Performance: ~3-5 seconds (vs 8+ hours for full OCR run)
"""

import json
from pathlib import Path
import yaml


def generate_album_slug(album_folder_name: str) -> str:
    """Convert album folder name to Hugo URL slug format.

    Hugo's default URL generation:
    - Converts to lowercase
    - Replaces " & " with double dashes (space+ampersand+space)
    - Removes brackets: () [] {}
    - Removes apostrophes (all variants)
    - Removes standalone ampersands (those not surrounded by spaces)
    - Replaces spaces with hyphens
    - Preserves: periods, plus signs, underscores, hyphens

    Examples:
      "1931-1939 courting & marriage" → "1931-1939-courting--marriage"
      "1956 Calif. Trip (Bk. 2)" → "1956-calif.-trip-bk.-2"
      "1982-1984 San Francisco[]Utah" → "1982-1984-san-franciscoutah"
      "1973-1974 John&Ben Born" → "1973-1974-johnben-born"
      "1976-1977 San Francisco_Spain" → "1976-1977-san-francisco_spain"
      "1968-1969 Louise's marriage" → "1968-1969-louises-marriage"
    """
    slug = album_folder_name.lower()

    # Replace ` & ` (space+ampersand+space) with `--` BEFORE other transformations
    slug = slug.replace(' & ', '--')

    # Remove brackets and parentheses (all types)
    slug = slug.replace('(', '')
    slug = slug.replace(')', '')
    slug = slug.replace('[', '')
    slug = slug.replace(']', '')
    slug = slug.replace('{', '')
    slug = slug.replace('}', '')

    # Remove ALL apostrophe variants (ASCII and Unicode)
    # U+0027: APOSTROPHE (straight apostrophe)
    # U+2018: LEFT SINGLE QUOTATION MARK (curly apostrophe)
    # U+2019: RIGHT SINGLE QUOTATION MARK (curly apostrophe)
    # U+201B: SINGLE HIGH-REVERSED-9 QUOTATION MARK (rare variant)
    slug = slug.replace("'", '')           # U+0027
    slug = slug.replace("\u2018", '')      # U+2018
    slug = slug.replace("\u2019", '')      # U+2019
    slug = slug.replace("\u201b", '')      # U+201B

    # Remove standalone ampersands (not surrounded by spaces - those were handled above)
    slug = slug.replace('&', '')

    # Replace spaces with single dashes (do this LAST)
    slug = slug.replace(' ', '-')

    return slug


def parse_album_metadata(album_dir: Path) -> dict:
    """Extract metadata from index.md frontmatter."""
    index_md = album_dir / "index.md"
    if not index_md.exists():
        return {}

    content = index_md.read_text(encoding="utf-8")

    # Extract YAML frontmatter between --- delimiters
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                return {}

    return {}


def rebuild_search_index(content_dir: Path, output_path: Path) -> None:
    """Rebuild search index from existing OCR JSON files."""

    # Find all albums with ocr_captions.json
    album_dirs = [
        d for d in content_dir.iterdir()
        if d.is_dir() and (d / "ocr_captions.json").exists()
    ]

    album_dirs.sort(key=lambda d: d.name)

    print(f"Found {len(album_dirs)} albums with OCR data")
    print("=" * 60)

    all_search_entries = []

    for album_dir in album_dirs:
        # Load existing OCR data
        ocr_json = album_dir / "ocr_captions.json"
        with open(ocr_json, encoding="utf-8") as f:
            album_data = json.load(f)

        # Get metadata
        metadata = parse_album_metadata(album_dir)

        # Generate FIXED slug
        album_slug = generate_album_slug(album_dir.name)

        # Add album entry
        all_search_entries.append({
            "type": "album",
            "album": album_dir.name,
            "album_title": metadata.get("title", album_dir.name),
            "album_url_slug": album_slug,
            "album_path": album_dir.name + "/",
            "searchable_text": metadata.get("title", album_dir.name)
        })

        # Sort pages by filename (matches Hugo gallery)
        pages = album_data.get("pages", [])
        pages = sorted(pages, key=lambda p: p.get("filename", ""))

        # Add page entries
        for idx, page in enumerate(pages):
            captions = page.get("captions", [])
            caption_text = " ".join(captions)

            all_search_entries.append({
                "type": "page",
                "album": album_dir.name,
                "album_title": metadata.get("title", album_dir.name),
                "album_url_slug": album_slug,
                "page_filename": page.get("filename", ""),
                "page_path": page.get("path", ""),
                "image_index": idx,
                "captions": captions,
                "caption_text": caption_text,  # ONLY caption content (for matching)
                "searchable_text": caption_text + " " + page.get("filename", "")  # All text (for fallback)
            })

        print(f"✓ {album_dir.name}: {len(pages)} pages")

    # Write search index
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(all_search_entries, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 60)
    print(f"Search index rebuilt: {output_path}")
    print(f"Albums: {len(album_dirs)}")
    print(f"Total entries: {len(all_search_entries)}")
    print("=" * 60)


def test_slug_generation():
    """Test cases to verify Hugo URL slug generation matches exactly."""
    test_cases = [
        ("1956 Calif. Trip (Bk. 2)", "1956-calif.-trip-bk.-2"),
        ("1982-1984 San Francisco[]Utah", "1982-1984-san-franciscoutah"),
        ("1973-1974 John&Ben Born", "1973-1974-johnben-born"),
        ("1976-1977 San Francisco_Spain", "1976-1977-san-francisco_spain"),
        ("1931-1939 courting & marriage", "1931-1939-courting--marriage"),
        ("1968-1969 Louise's marriage", "1968-1969-louises-marriage"),
        ("1953 A.B.C-Okla (Bk.1)", "1953-a.b.c-okla-bk.1"),
        ("1969 - 25th anniv. Trip to Europe", "1969---25th-anniv.-trip-to-europe"),
    ]

    print("\nRunning slug generation tests...")
    print("=" * 70)

    all_passed = True
    for folder_name, expected_slug in test_cases:
        actual_slug = generate_album_slug(folder_name)
        passed = actual_slug == expected_slug
        all_passed = all_passed and passed

        status = "✓" if passed else "✗"
        print(f"{status} {folder_name}")
        if not passed:
            print(f"  Expected: {expected_slug}")
            print(f"  Got:      {actual_slug}")

    print("=" * 70)
    if all_passed:
        print("All tests passed!\n")
    else:
        print("Some tests failed!\n")
        sys.exit(1)


if __name__ == "__main__":
    import sys

    content_dir = Path("content")
    output_path = Path("static/search/search-index.json")

    if not content_dir.exists():
        print(f"ERROR: Content directory not found: {content_dir}")
        sys.exit(1)

    # Run tests before rebuilding
    test_slug_generation()

    rebuild_search_index(content_dir, output_path)
