"""
ocr_parser.py — OCR extraction of Google Scholar citation screenshots.

Uses Windows Runtime OCR (built into Windows 10/11, no external install needed)
to read text from images, then parses the Scholar citation block format into
structured records that can be fed to Semantic Scholar for enrichment.

Font-size detection: WinRT OCR returns per-word bounding boxes. Title text in
Google Scholar is rendered larger (and in blue) than body text, so lines whose
average word height exceeds ~1.3× the page median are tagged as large text and
treated as title candidates — avoiding confusion with abstract snippets.
"""

import re
import asyncio
import statistics
from pathlib import Path


# ── Windows Runtime OCR ────────────────────────────────────────────────────────

def _check_winrt() -> tuple[bool, str]:
    try:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return False, (
                "Windows OCR engine could not be created.\n"
                "Make sure an English language pack is installed in Windows Settings."
            )
        return True, "Windows Runtime OCR"
    except ImportError:
        return False, (
            "winsdk not installed.\n"
            "Run: pip install winsdk"
        )
    except Exception as e:
        return False, f"Windows OCR unavailable: {e}"


_OCR_OK, _OCR_MSG = _check_winrt()


def is_available() -> bool:
    return _OCR_OK

def unavailable_reason() -> str:
    return _OCR_MSG


# ── Image → structured lines via WinRT OCR ────────────────────────────────────

async def _ocr_async(image_path: str) -> list[dict]:
    """
    Returns a list of  {"text": str, "height": float}  dicts — one per OCR line,
    in top-to-bottom reading order.  height is the average bounding-box height
    of the words on that line (pixels), used as a font-size proxy.
    """
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter

    with open(image_path, "rb") as f:
        data = f.read()

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(data)
    await writer.store_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap  = await decoder.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_user_profile_languages()
    result = await engine.recognize_async(bitmap)

    lines_data = []
    for line in result.lines:
        words = list(line.words)
        if words:
            avg_h = sum(w.bounding_rect.height for w in words) / len(words)
        else:
            avg_h = 0.0
        lines_data.append({"text": line.text, "height": avg_h})

    return lines_data


def extract_lines(image_path: str) -> list[dict]:
    """
    Run Windows Runtime OCR and return structured line data:
      [{"text": str, "height": float}, ...]
    Raises RuntimeError if WinRT OCR is not available.
    """
    if not _OCR_OK:
        raise RuntimeError(_OCR_MSG)
    return asyncio.run(_ocr_async(image_path))


def extract_text(image_path: str) -> str:
    """Plain-text version of extract_lines (for debugging / compatibility)."""
    return "\n".join(l["text"] for l in extract_lines(image_path))


# ── Google Scholar text parser ─────────────────────────────────────────────────
#
# Scholar result block (after OCR):
#
#   Title of the Paper              ← larger font  (height > median × TITLE_RATIO)
#   A Author - Venue, 2021 - dom   ← normal font, contains year + dash
#   Short abstract snippet…        ← normal font, abstract text
#   Cited by 87  Related articles  ← noise
#
# Strategy:
#   1. Tag each line as "large" (title-sized) or "normal" using bounding-box heights.
#   2. Find all "author lines" (normal-font lines with year + dash pattern).
#   3. For each author line look backwards: collect consecutive large-font lines
#      immediately above it — those are the title.
#   4. If height data is unavailable / all heights are equal (e.g. plain text
#      fallback), fall back to the previous backward-lookahead heuristic.

TITLE_RATIO = 1.25   # a line is "large" if its height ≥ median × this factor

_YEAR_RE  = re.compile(r'\b(19|20)\d{2}\b')
_DASH_RE  = re.compile(r'\s[-–—]\s')
_CITED_RE = re.compile(r'[Cc]ited\s+by\s+([\d,]+)')

_NOISE_RE = re.compile(
    r'^[^\w]*'
    r'(Related articles|All \d+ versions?|Save|Cite|'
    r'More|PDF|HTML|Full\s+View|Page \d|Sign in|'
    r'My library|About|Settings|Scholar|'
    r'\[PDF\]|researchgate|academia\.edu|wiley\.com|'
    r'springer\.com|ieeexplore)',
    re.I,
)

# Reliable abstract-text markers (phrases that NEVER start a paper title)
_ABSTRACT_START = re.compile(
    r'^(in this (paper|work|article|study)\b|'
    r'this paper (presents|proposes|introduces|describes|analyzes)\b|'
    r'we (propose|present|introduce|develop|show that|demonstrate)\b|'
    r'owing to \b|'
    r'abstract\b)',
    re.I,
)
_SENTENCE_RE = re.compile(r'\.\s+[A-Z]')   # mid-line sentence boundary
_ELLIPSIS_RE = re.compile(r'(\.{2,}|\u2026)\s*$')  # ends with "..." or "…"
_PDF_BADGE_RE = re.compile(               # [PDF] badge from right margin
    r'\s*\[?PDF\]?\s+\S+\.(edu|com|net|org|gov|ac\.\w{2,})\s*$', re.I)


def _is_abstract_line(line: str) -> bool:
    if _SENTENCE_RE.search(line):    return True
    if _ELLIPSIS_RE.search(line):    return True
    if len(line) > 200:              return True
    if _ABSTRACT_START.match(line):  return True
    return False


def _clean_title(t: str) -> str:
    t = _PDF_BADGE_RE.sub('', t)
    t = re.sub(r'\s*(Full\s+View|Full\s+Text)\s*$', '', t, flags=re.I)
    return t.strip()


def parse_scholar_lines(lines_data: list[dict]) -> list[dict]:
    """
    Parse structured OCR output (list of {text, height} dicts) into citation records.
    Uses per-line font height to identify title lines reliably.
    """
    # Strip noise lines, preserve height
    clean: list[dict] = [
        d for d in lines_data
        if d["text"].strip() and not _NOISE_RE.match(d["text"].strip())
    ]
    for d in clean:
        d["text"] = d["text"].strip()

    if not clean:
        return []

    # Compute median line height; tag lines as "large" (title-sized)
    heights = [d["height"] for d in clean if d["height"] > 0]
    median_h = statistics.median(heights) if heights else 0.0
    height_varies = median_h > 0 and (max(heights) / median_h > 1.15 if heights else False)

    for d in clean:
        if height_varies:
            d["large"] = d["height"] >= median_h * TITLE_RATIO
        else:
            # No reliable height variation — fall back: not large by default
            d["large"] = False

    # Pass 1: find author line indices
    author_indices = [
        i for i, d in enumerate(clean)
        if _YEAR_RE.search(d["text"]) and _DASH_RE.search(d["text"])
    ]

    results: list[dict] = []

    for ai in author_indices:
        author_line = clean[ai]["text"]

        # Pass 2: look backwards for title lines
        title_lines: list[str] = []
        for back in range(1, 4):   # up to 3 lines back
            li = ai - back
            if li < 0:
                break
            d = clean[li]
            text = d["text"]

            # Stop at another author line
            if _YEAR_RE.search(text) and _DASH_RE.search(text):
                break
            # Stop at citation-count line
            if _CITED_RE.search(text):
                break

            if height_varies:
                # With height data: only accept lines tagged as large text
                if not d["large"]:
                    break
            else:
                # Without height data: stop at abstract-like lines
                if _is_abstract_line(text):
                    break

            title_lines.insert(0, text)
            # Titles rarely span more than 2 lines
            if len(title_lines) >= 2:
                break

        title = _clean_title(" ".join(title_lines))

        if not title or len(title) <= 8 or _YEAR_RE.match(title):
            continue

        # Parse author / venue / year
        parts   = _DASH_RE.split(author_line)
        authors = parts[0].strip() if parts else ""
        year_m  = _YEAR_RE.search(author_line)
        year    = int(year_m.group()) if year_m else None

        venue = ""
        if len(parts) > 1:
            venue = re.sub(r'\b(19|20)\d{2}\b', '', parts[1]).strip(" ,–-")
            venue = _DASH_RE.split(venue)[0].strip()

        # Cited-by count from the lines below the author line
        cites = 0
        for j in range(ai + 1, min(ai + 8, len(clean))):
            cm = _CITED_RE.search(clean[j]["text"])
            if cm:
                cites = int(cm.group(1).replace(",", ""))
                break

        results.append({
            "title":     title,
            "authors":   authors,
            "venue":     venue,
            "year":      year,
            "citations": cites,
            "_source":   "screenshot",
        })

    return results


def parse_scholar_text(text: str) -> list[dict]:
    """
    Compatibility wrapper: accepts plain text (no height data).
    Uses the text-only heuristic path of parse_scholar_lines.
    """
    lines_data = [{"text": l, "height": 0.0} for l in text.splitlines()]
    return parse_scholar_lines(lines_data)
