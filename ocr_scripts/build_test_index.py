#!/usr/bin/env python3
"""Build search index for 1-2 test albums to verify approach."""
import json
import re
from pathlib import Path

def generate_album_slug(album_folder_name: str) -> str:
    """Convert album folder name to Hugo URL slug format.

    Hugo's default URL generation:
    - Converts to lowercase
    - Replaces " & " with double dashes
    - Removes all apostrophe variants (straight and curly quotes)
    - Replaces spaces with hyphens
    - Preserves special chars like periods, plus signs, etc.

    Examples:
      "1931-1939 courting & marriage" → "1931-1939-courting--marriage"
      "1947 Nov. '47- May '48 covered bridges+" → "1947-nov.-47--may-48-covered-bridges+"
      "1968-1969 Louise's marriage" → "1968-1969-louises-marriage"
      "1964-1966 Kathy's marriage" → "1964-1966-kathys-marriage"
    """
    slug = album_folder_name.lower()

    # Replace & with -- (double dash) BEFORE replacing spaces
    slug = slug.replace(' & ', '--')

    # Remove ALL apostrophe variants (ASCII and Unicode)
    # U+0027: APOSTROPHE (straight apostrophe)
    # U+2018: LEFT SINGLE QUOTATION MARK (curly apostrophe)
    # U+2019: RIGHT SINGLE QUOTATION MARK (curly apostrophe)
    # U+201B: SINGLE HIGH-REVERSED-9 QUOTATION MARK (rare variant)
    slug = slug.replace("'", '')           # U+0027
    slug = slug.replace("\u2018", '')      # U+2018
    slug = slug.replace("\u2019", '')      # U+2019
    slug = slug.replace("\u201b", '')      # U+201B

    # Replace spaces with single dashes
    slug = slug.replace(' ', '-')

    return slug

# Test with 2 albums
test_albums = [
    "1931-1939 courting & marriage",
    "1949 Boston trip"
]

content_dir = Path("content")
search_entries = []

for album_name in test_albums:
    album_dir = content_dir / album_name
    ocr_json = album_dir / "ocr_captions.json"

    if not ocr_json.exists():
        print(f"Warning: {ocr_json} not found")
        continue

    with open(ocr_json) as f:
        album_data = json.load(f)

    album_title = album_data["album_title"]
    album_slug = generate_album_slug(album_name)

    # Sort by filename (matches Hugo gallery default)
    pages = sorted(album_data["pages"], key=lambda p: p["filename"])

    # Assign DOM indices
    for idx, page in enumerate(pages):
        search_entries.append({
            "type": "page",
            "album": album_data["album"],
            "album_title": album_title,
            "album_url_slug": album_slug,
            "page_filename": page["filename"],
            "page_path": page["path"],
            "image_index": idx,
            "captions": page.get("captions", []),
            "searchable_text": page.get("caption_text", "")
        })

    # Add album entry
    search_entries.append({
        "type": "album",
        "album": album_data["album"],
        "album_title": album_title,
        "album_url_slug": album_slug,
        "album_path": f"{album_data['album']}/",
        "searchable_text": album_title
    })

# Write test index
output = Path("static/search/search-index.json")
output.parent.mkdir(parents=True, exist_ok=True)
with open(output, 'w') as f:
    json.dump(search_entries, f, indent=2)

print(f"✓ Test search index created: {len(search_entries)} entries")
print(f"  Albums: {len([e for e in search_entries if e['type'] == 'album'])}")
print(f"  Pages: {len([e for e in search_entries if e['type'] == 'page'])}")
