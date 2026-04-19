# Citation Explorer

A desktop tool that finds every paper citing a given work and ranks them by academic impact.

![Python](https://img.shields.io/badge/python-3.11+-blue) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey) ![License](https://img.shields.io/badge/license-AGPL--v3-blue)

---

## Features

- **Multi-source citation discovery** — queries Semantic Scholar, OpenAlex, and OpenCitations in one pass
- **Google Scholar supplement** — paste copied Scholar results or upload screenshots to capture papers not yet indexed elsewhere
- **Rich metadata** — title, year, citations, journal, impact factor, journal ranking, author h-index, affiliations, academic domain, where/how cited
- **Impact scoring** — composite rank weighted by citations, author h-index, journal IF, and recency
- **Deduplication** — merges results across all sources by title similarity
- **Export** — CSV and JSON export of the full results table
- **Input history** — last 100 queries saved with autocomplete

---

## Quick Start (pre-built .exe)

1. Download `CitationExplorer.exe` from the [dist folder](dist/CitationExplorer.exe)
2. Double-click to run — no installation needed
3. Windows 10/11 required (uses built-in Windows OCR for screenshot processing)

---

## Running from Source

### Prerequisites

- [Anaconda](https://www.anaconda.com/) or Miniconda
- Windows 10/11

### Setup

```bash
# Create and activate the environment
conda create -n citations python=3.11
conda activate citations

# Install dependencies
pip install -r requirements.txt
```

### Run

```bash
conda activate citations
python app.py
```

---

## Building the .exe

```bash
conda activate citations
build.bat
```

Output will be in `dist\CitationExplorer.exe` (~100MB, standalone, no install needed).

---

## Usage

1. **Enter a paper** — paste a title, DOI, IEEE/arXiv/Semantic Scholar URL, or any paper URL into the input field
2. *(Optional)* **Add Google Scholar results**:
   - Click **+ Paste Text** → go to Google Scholar, copy the results, paste here
   - Click **+ Screenshots** → upload screenshot images of Scholar results pages
3. Click **Find Citations** — all sources are queried in parallel and merged
4. Click any row to see full details (citation contexts, abstract, affiliations)
5. Double-click a row to open the paper in your browser
6. Export with **Export CSV** or **Export JSON**

---

## Data Sources

| Source | What it provides |
|---|---|
| [Semantic Scholar](https://www.semanticscholar.org/) | Citation graph, contexts, influence flags, author h-index |
| [OpenAlex](https://openalex.org/) | Broader coverage, journal metrics (IF, h-index, country) |
| [OpenCitations](https://opencitations.net/) | Independent citation index (DOI-based papers) |
| Google Scholar (via paste/screenshot) | Catches papers not yet indexed by the above |

All sources are free and require no API keys.

---

## Columns

| Column | Description |
|---|---|
| Rank | Impact-score rank |
| Title | Title of the citing paper |
| Year | Publication year |
| # Citations | Citation count of the citing paper |
| Academic Domain | Inferred research area |
| Journal / Venue | Publication venue |
| Publication Type | Journal, conference, preprint, etc. |
| Journal Ranking | OpenAlex journal h-index (ranking proxy) |
| Impact Factor | 2-year mean citedness (OpenAlex) |
| Journal Location | Country of the journal |
| Author(s) | Up to 6 authors listed |
| Designation | Author role (if available) |
| Affiliation(s) | Institutional affiliations |
| Author Citation Count | Total citations of the lead author |
| Author H-Index | H-index of the lead author |
| Where Cited | Section where citation appears (Intro, Methods, Results) |
| How Utilized | How the citing paper uses this work |
| Notable Mentions | Influence flags and quality indicators |
| Impact Score | Composite score (0–1) |
| Source | Which database(s) found this paper |

Cells showing `<Not Found / DIY>` can be filled in manually.

---

## Requirements

See [requirements.txt](requirements.txt). Key dependencies:

- `PyQt6` — GUI
- `requests` — API calls
- `winsdk` — Windows Runtime OCR (for screenshot processing)
