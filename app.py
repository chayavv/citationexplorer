"""
app.py — Citation Explorer GUI
Finds all papers citing a given work and ranks them by academic impact.
"""

import sys, json, csv
from pathlib import Path
from datetime import datetime
import fetcher
import ocr_parser

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QSpinBox, QFileDialog,
    QMessageBox, QAbstractItemView, QFrame, QStatusBar, QTextEdit,
    QSplitter, QCompleter, QListWidget, QListWidgetItem, QDialog,
    QDialogButtonBox,
)
from PyQt6.QtCore  import QThread, pyqtSignal, Qt, QUrl, QStringListModel
from PyQt6.QtGui   import QDesktopServices, QFont, QColor


# ── History file (lives next to the .exe or the script) ───────────────────────

def _app_dir() -> Path:
    """Returns the folder containing the executable (or script when developing)."""
    if getattr(sys, 'frozen', False):          # running as PyInstaller .exe
        return Path(sys.executable).parent
    return Path(__file__).parent

HISTORY_FILE = _app_dir() / ".history.txt"
MAX_HISTORY  = 100

def load_history() -> list[str]:
    """Return the list of past queries (most-recent first, input column only)."""
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    queries = []
    for line in lines:
        if "\t" in line:
            queries.append(line.split("\t", 1)[1])
    return queries

def save_to_history(query: str) -> None:
    """Prepend a timestamped entry; keep only the most recent MAX_HISTORY lines."""
    query = query.strip()
    if not query:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing: list[str] = []
    if HISTORY_FILE.exists():
        existing = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    # Remove any duplicate of this query (keep history clean)
    existing = [l for l in existing if "\t" not in l or l.split("\t", 1)[1] != query]
    existing.insert(0, f"{ts}\t{query}")
    existing = existing[:MAX_HISTORY]
    HISTORY_FILE.write_text("\n".join(existing) + "\n", encoding="utf-8")

NA = fetcher.NA   # "<Not Found / DIY>"

# ── Column definitions ─────────────────────────────────────────────────────────
#  (header label, row_key, default_width, numeric_sort)
COLUMNS = [
    ("Rank",                     "rank",             46,  True),
    ("Title of Citing Paper",    "title",           270,  False),
    ("Year",                     "year",             52,  True),
    ("# Citations",              "citations",        80,  True),
    ("Academic Domain",          "domain",          130,  False),
    ("Journal / Venue",          "journal",         160,  False),
    ("Publication Type",         "journal_type",     95,  False),
    ("Journal Ranking (OA H)",   "journal_ranking",  95,  True),
    ("Impact Factor",            "impact_factor",    95,  True),
    ("Journal Location",         "journal_location", 95,  False),
    ("Author(s)",                "authors",         170,  False),
    ("Designation",              "designation",      95,  False),
    ("Affiliation(s)",           "affiliation",     180,  False),
    ("Author Citation Count",    "author_cites",     95,  True),
    ("Author H-Index",           "author_hindex",    90,  True),
    ("Where Cited",              "where_cited",     150,  False),
    ("How Utilized",             "how_utilized",    240,  False),
    ("Notable Mentions",         "notable",         150,  False),
    ("Impact Score",             "impact_score",     85,  True),
    ("Source",                   "source",           110, False),
]

# ── Dark stylesheet ────────────────────────────────────────────────────────────
STYLE = """
* { font-family: 'Segoe UI', Arial, sans-serif; }

QMainWindow, QWidget#root { background: #0f1117; color: #e2e8f0; }

QFrame#card {
    background: #1a1d27; border: 1px solid #2d3148; border-radius: 10px;
}
QLabel#h1   { font-size: 21px; font-weight: 700; color: #f1f5f9; }
QLabel#sub  { font-size: 12px; color: #64748b; }
QLabel#info { font-size: 12px; color: #94a3b8; padding: 3px 0; }
QLabel#stat { font-size: 11px; color: #64748b; }

QLineEdit {
    background: #1e2130; border: 1px solid #2d3148; border-radius: 7px;
    padding: 9px 14px; color: #e2e8f0; font-size: 13px;
}
QLineEdit:focus { border-color: #6366f1; }

QPushButton {
    background: #6366f1; color: #fff; border: none;
    border-radius: 7px; padding: 9px 22px; font-size: 13px; font-weight: 600;
}
QPushButton:hover    { background: #818cf8; }
QPushButton:pressed  { background: #4f46e5; }
QPushButton:disabled { background: #2d3148; color: #475569; }
QPushButton#cancel   { background: #dc2626; }
QPushButton#cancel:hover { background: #ef4444; }
QPushButton#sec {
    background: #1e2130; color: #94a3b8;
    border: 1px solid #2d3148;
}
QPushButton#sec:hover { background: #2d3148; color: #e2e8f0; }

QListWidget {
    background: #141720; border: 1px solid #2d3148; border-radius: 6px;
    color: #94a3b8; font-size: 11px; padding: 2px;
    max-height: 80px;
}
QListWidget::item { padding: 3px 8px; border-radius: 3px; }
QListWidget::item:selected { background: #1e2236; color: #818cf8; }
QListWidget::item:hover    { background: #1a1d2e; }

QTableWidget {
    background: #0f1117; alternate-background-color: #141720;
    border: 1px solid #2d3148; border-radius: 8px;
    gridline-color: #1e2130; color: #cbd5e1; font-size: 11px;
}
QTableWidget::item { padding: 4px 7px; border: none; }
QTableWidget::item:selected { background: #1e2236; color: #818cf8; }
QTableWidget::item:hover    { background: #1a1d2e; }

QHeaderView::section {
    background: #1a1d27; color: #818cf8; padding: 7px 8px;
    border: none; border-bottom: 1px solid #2d3148;
    border-right: 1px solid #2d3148; font-weight: 600; font-size: 11px;
}
QHeaderView::section:last { border-right: none; }

QProgressBar {
    background: #1e2130; border: none; border-radius: 4px;
    height: 6px; max-height: 6px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #6366f1, stop:1 #818cf8);
    border-radius: 4px;
}

QCheckBox { color: #94a3b8; spacing: 7px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid #2d3148;
    border-radius: 4px; background: #1e2130;
}
QCheckBox::indicator:checked { background: #6366f1; border-color: #6366f1; }

QSpinBox {
    background: #1e2130; border: 1px solid #2d3148;
    border-radius: 5px; padding: 5px 8px; color: #e2e8f0;
}

QTextEdit {
    background: #0d0f18; border: 1px solid #2d3248; border-radius: 6px;
    color: #94a3b8; font-size: 12px; padding: 8px;
}

QScrollBar:vertical   { background: #0f1117; width: 8px; border: none; }
QScrollBar::handle:vertical { background: #2d3148; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #475569; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal { background: #0f1117; height: 8px; border: none; }
QScrollBar::handle:horizontal { background: #2d3148; border-radius: 4px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: #475569; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QSplitter::handle { background: #1a1d27; }

QStatusBar { background: #0a0c12; color: #475569; font-size: 11px;
             border-top: 1px solid #1a1d27; }
QToolTip { background: #1e2130; color: #e2e8f0; border: 1px solid #2d3148;
           border-radius: 5px; padding: 6px 10px; font-size: 12px; }
"""


# ── Unified background worker ──────────────────────────────────────────────────
# Handles: S2 citation fetch (if query given) + OCR on all screenshots,
# then merges, deduplicates, enriches, scores, and emits final rows.

class UnifiedWorker(QThread):
    status_update      = pyqtSignal(str)
    progress_update    = pyqtSignal(int, int)
    paper_resolved     = pyqtSignal(dict)
    enrich_progress    = pyqtSignal(int, int)
    journal_progress   = pyqtSignal(int, int)
    finished_with_data = pyqtSignal(list)
    error              = pyqtSignal(str)

    def __init__(self, query: str, screenshot_paths: list, pasted_texts: list,
                 enrich: bool, max_results: int):
        super().__init__()
        self.query            = query.strip()
        self.screenshot_paths = screenshot_paths
        self.pasted_texts     = pasted_texts   # list of raw Scholar text strings
        self.enrich           = enrich
        self.max_results      = max_results
        self._cancel          = False

    def cancel(self): self._cancel = True

    def _chk(self):
        if self._cancel: raise InterruptedError

    def run(self):
        try:
            all_papers: list[dict] = []

            # ── Phase 1: Semantic Scholar citation fetch ──────────────────────
            self.status_update.emit("Parsing input…")
            itype, value = fetcher.parse_input(self.query)
            self.status_update.emit(f"Detected: {itype}  →  {value[:70]}")

            self.status_update.emit("Looking up paper on Semantic Scholar…")
            paper = fetcher.lookup_paper(itype, value)

            if not paper:
                if itype == "scholar_cites":
                    self.error.emit(
                        "Google Scholar 'Cited by' links cannot be resolved directly.\n\n"
                        "Please paste one of:\n"
                        "  • The paper's DOI  (e.g. 10.1109/...)\n"
                        "  • The paper title\n"
                        "  • An IEEE / arXiv / Semantic Scholar URL"
                    )
                else:
                    self.error.emit(
                        "Paper not found on Semantic Scholar.\n"
                        "Try pasting the DOI or exact paper title."
                    )
                return
            else:
                self.paper_resolved.emit(paper)
                total = paper.get("citationCount", 0) or 0
                self.status_update.emit(
                    f"Found: {(paper.get('title') or '')[:80]}  ({total:,} citations)"
                )

                self.status_update.emit("Fetching citing papers from Semantic Scholar…")
                self.progress_update.emit(0, total)

                def on_fetch(count, _total=total):
                    self._chk()
                    self.progress_update.emit(count, _total)
                    self.status_update.emit(f"Fetched {count:,} / {_total:,}…")

                papers_s2 = fetcher.fetch_citations_s2(
                    paper["paperId"], on_progress=on_fetch
                )
                self._chk()

                if self.max_results > 0:
                    papers_s2 = papers_s2[:self.max_results]

                self.status_update.emit(
                    f"Retrieved {len(papers_s2):,} citing papers from S2."
                )
                all_papers.extend(papers_s2)

                # ── OpenAlex citations ────────────────────────────────────────
                self.status_update.emit("Fetching citing papers from OpenAlex…")
                def on_oa(count):
                    self._chk()
                    self.status_update.emit(f"OpenAlex: {count:,} papers retrieved…")
                oa_papers = fetcher.fetch_citations_openalex(paper, on_progress=on_oa)
                self._chk()
                self.status_update.emit(f"OpenAlex: {len(oa_papers):,} papers found.")
                all_papers.extend(oa_papers)

                # ── OpenCitations (DOI-based) ─────────────────────────────────
                doi = (paper.get("externalIds") or {}).get("DOI","")
                if doi:
                    self.status_update.emit("Fetching from OpenCitations…")
                    def on_oc(done, tot):
                        self._chk()
                        self.status_update.emit(f"OpenCitations: {done}/{tot} DOIs…")
                    oc_papers = fetcher.fetch_citations_opencitations(
                        paper, on_progress=on_oc
                    )
                    self._chk()
                    self.status_update.emit(
                        f"OpenCitations: {len(oc_papers):,} papers found."
                    )
                    all_papers.extend(oc_papers)

            # ── Phase 2: OCR each queued screenshot ───────────────────────────
            n_shots = len(self.screenshot_paths)
            for idx, img_path in enumerate(self.screenshot_paths):
                self._chk()
                name = Path(img_path).name
                self.status_update.emit(
                    f"OCR [{idx+1}/{n_shots}]: {name}…"
                )
                try:
                    lines_data = ocr_parser.extract_lines(img_path)
                    raw        = ocr_parser.parse_scholar_lines(lines_data)
                    if not raw:
                        self.status_update.emit(
                            f"  No citation blocks found in {name} — skipping."
                        )
                        continue

                    self.status_update.emit(
                        f"  Found {len(raw)} blocks in {name}; querying S2…"
                    )

                    def on_ocr_prog(done, tot, _name=name):
                        self._chk()
                        self.status_update.emit(
                            f"  S2 lookup {done}/{tot} ({_name})…"
                        )

                    ocr_papers = fetcher.lookup_screenshot_citations(
                        raw, on_progress=on_ocr_prog
                    )
                    self._chk()
                    all_papers.extend(ocr_papers)
                    self.status_update.emit(
                        f"  Added {len(ocr_papers)} papers from {name}."
                    )
                except Exception as exc:
                    self.status_update.emit(
                        f"  Warning: could not process {name}: {exc}"
                    )

            if not all_papers:
                self.error.emit(
                    "No citations found from any source.\n\n"
                    "Suggestions:\n"
                    "• Check the paper title or URL\n"
                    "• Make sure screenshots show Google Scholar results pages\n"
                    "• Try a sharper / higher-resolution screenshot"
                )
                return

            # ── Phase 2b: Pasted Scholar text blocks ─────────────────────────
            n_texts = len(self.pasted_texts)
            for idx, raw_text in enumerate(self.pasted_texts):
                self._chk()
                self.status_update.emit(
                    f"Parsing pasted text [{idx+1}/{n_texts}]…"
                )
                raw = ocr_parser.parse_scholar_text(raw_text)
                if not raw:
                    self.status_update.emit(
                        f"  No citation blocks found in pasted text {idx+1} — skipping."
                    )
                    continue
                self.status_update.emit(
                    f"  Found {len(raw)} blocks; querying S2…"
                )

                def on_paste_prog(done, tot, _idx=idx):
                    self._chk()
                    self.status_update.emit(f"  S2 lookup {done}/{tot} (text block {_idx+1})…")

                text_papers = fetcher.lookup_screenshot_citations(
                    raw, on_progress=on_paste_prog
                )
                self._chk()
                all_papers.extend(text_papers)
                self.status_update.emit(
                    f"  Added {len(text_papers)} papers from pasted text {idx+1}."
                )

            # ── Phase 3: Journal enrichment (batched by venue) ────────────────
            self.status_update.emit("Fetching journal metrics from OpenAlex…")

            def on_journal(done, total_j):
                self._chk()
                self.journal_progress.emit(done, total_j)
                self.status_update.emit(f"Journal data: {done}/{total_j} venues…")

            fetcher.enrich_journal_data(all_papers, on_progress=on_journal)
            self._chk()

            # ── Phase 4: Optional author enrichment ───────────────────────────
            if self.enrich and all_papers:
                self.status_update.emit("Enriching author data (h-index, affiliations)…")

                def on_enrich(done, total_e):
                    self._chk()
                    self.enrich_progress.emit(done, total_e)
                    self.status_update.emit(f"Author enrichment: {done}/{total_e}…")

                fetcher.enrich_author_data(all_papers, on_progress=on_enrich)
                self._chk()

            # ── Phase 5: Score → rows → deduplicate ───────────────────────────
            self.status_update.emit("Computing impact scores…")
            all_papers = fetcher.compute_impact_scores(all_papers)
            rows       = fetcher.papers_to_rows(all_papers)
            rows       = fetcher.deduplicate_rows(rows)

            self.status_update.emit(f"Done — {len(rows):,} unique papers ranked.")
            self.finished_with_data.emit(rows)

        except InterruptedError:
            self.status_update.emit("Cancelled.")
        except Exception as exc:
            self.error.emit(f"Unexpected error:\n{exc}")


# ── Numeric-aware table item ───────────────────────────────────────────────────

class NumItem(QTableWidgetItem):
    def __init__(self, val):
        self._val = val
        display   = str(val) if val not in ("", None, NA) else NA
        super().__init__(display)
        self.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def __lt__(self, other):
        try:   return float(self._val or 0) < float(other._val or 0)
        except: return str(self._val) < str(other._val)


# ── Main window ────────────────────────────────────────────────────────────────

class CitationExplorer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Citation Explorer")
        self.setMinimumSize(1400, 820)
        self._rows:    list[dict]          = []
        self._worker:  UnifiedWorker | None = None
        self._history: list[str]           = load_history()
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(20, 16, 20, 10)
        main.setSpacing(10)

        # Header
        lbl = QLabel("Citation Explorer"); lbl.setObjectName("h1")
        sub = QLabel(
            "Find every paper that cites a given work and rank them by academic impact"
        ); sub.setObjectName("sub")
        main.addWidget(lbl)
        main.addWidget(sub)

        # ── Input card ────────────────────────────────────────────────────────
        card = QFrame(); card.setObjectName("card")
        cl   = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 14); cl.setSpacing(8)

        # OCR unavailability banner
        if not ocr_parser.is_available():
            warn = QLabel(
                f"⚠  OCR unavailable — {ocr_parser.unavailable_reason().splitlines()[0]}"
            )
            warn.setObjectName("stat")
            warn.setStyleSheet("color:#f59e0b;")
            cl.addWidget(warn)

        # Row 1: query input + action buttons
        r1 = QHBoxLayout()
        self.inp = QLineEdit()
        self.inp.setPlaceholderText(
            "Paste URL (IEEE, DOI, arXiv, Semantic Scholar) or paper title…"
        )
        self.inp.returnPressed.connect(self._start)

        # History autocomplete
        self._completer_model = QStringListModel(self._history)
        self._completer = QCompleter(self._completer_model, self.inp)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setMaxVisibleItems(12)
        self.inp.setCompleter(self._completer)

        self.btn_fetch = QPushButton("Find Citations")
        self.btn_fetch.setFixedWidth(148)
        self.btn_fetch.clicked.connect(self._start)

        self.btn_cancel = QPushButton("Cancel"); self.btn_cancel.setObjectName("cancel")
        self.btn_cancel.setFixedWidth(80); self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel)

        r1.addWidget(self.inp)
        r1.addWidget(self.btn_fetch)
        r1.addWidget(self.btn_cancel)
        cl.addLayout(r1)

        # Row 2: screenshot queue controls (only shown when OCR available)
        if ocr_parser.is_available():
            r2 = QHBoxLayout()
            scr_lbl = QLabel("Screenshots:")
            scr_lbl.setObjectName("stat")
            scr_lbl.setStyleSheet("color:#64748b;")

            self.btn_add_shots = QPushButton("+ Screenshots")
            self.btn_add_shots.setObjectName("sec")
            self.btn_add_shots.setFixedWidth(130)
            self.btn_add_shots.setToolTip(
                "Queue Google Scholar screenshot images for OCR processing."
            )
            self.btn_add_shots.clicked.connect(self._add_screenshots)

            self.btn_paste_text = QPushButton("+ Paste Text")
            self.btn_paste_text.setObjectName("sec")
            self.btn_paste_text.setFixedWidth(110)
            self.btn_paste_text.setToolTip(
                "Paste text copied from Google Scholar results.\n"
                "Select all results on the page, copy, and paste here.\n"
                "More reliable than screenshots."
            )
            self.btn_paste_text.clicked.connect(self._paste_scholar_text)

            self.btn_clear_shots = QPushButton("Clear All")
            self.btn_clear_shots.setObjectName("sec")
            self.btn_clear_shots.setFixedWidth(100)
            self.btn_clear_shots.clicked.connect(self._clear_screenshots)

            r2.addWidget(scr_lbl)
            r2.addWidget(self.btn_add_shots)
            r2.addWidget(self.btn_paste_text)
            r2.addWidget(self.btn_clear_shots)
            r2.addStretch()
            cl.addLayout(r2)

            # Screenshot queue list
            self.shot_list = QListWidget()
            self.shot_list.setToolTip(
                "Queued screenshots — select one and press Delete to remove it.\n"
                "All of these will be processed when you click \"Find Citations\"."
            )
            self.shot_list.setFixedHeight(68)
            self.shot_list.setSelectionMode(
                QAbstractItemView.SelectionMode.ExtendedSelection
            )
            self.shot_list.keyPressEvent = self._shot_list_key
            cl.addWidget(self.shot_list)
        else:
            self.btn_add_shots   = None
            self.btn_paste_text  = None
            self.btn_clear_shots = None
            self.shot_list       = None

        # Row 3: enrich + max results
        r3 = QHBoxLayout()
        self.chk_enrich = QCheckBox(
            "Enrich author data  (fetches h-index, affiliation — slower)"
        )
        self.chk_enrich.setToolTip(
            "Makes one Semantic Scholar API call per author (top 3 per paper).\n"
            "Significantly improves ranking quality but adds time.\n"
            "Journal data is always fetched automatically."
        )
        ml = QLabel("Max results:"); ml.setObjectName("stat")
        self.spin = QSpinBox()
        self.spin.setRange(0, 10000); self.spin.setValue(500)
        self.spin.setSpecialValueText("All"); self.spin.setFixedWidth(90)
        self.spin.setToolTip("0 = fetch ALL citations (slow for highly-cited papers)")
        r3.addWidget(self.chk_enrich); r3.addStretch()
        r3.addWidget(ml); r3.addWidget(self.spin)
        cl.addLayout(r3)

        main.addWidget(card)

        # Source paper info bar
        self.lbl_src = QLabel("Source paper: —"); self.lbl_src.setObjectName("info")
        main.addWidget(self.lbl_src)

        # Progress row
        pr = QHBoxLayout()
        self.prog = QProgressBar(); self.prog.setRange(0,100); self.prog.setValue(0)
        self.lbl_status = QLabel("Ready"); self.lbl_status.setObjectName("stat")
        self.lbl_status.setMinimumWidth(380)
        pr.addWidget(self.prog, 1); pr.addWidget(self.lbl_status)
        main.addLayout(pr)

        # Splitter: table on top, detail panel below
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.doubleClicked.connect(self._open_url)
        self.table.currentItemChanged.connect(self._on_row_select)
        self.table.setToolTip("Double-click a row to open the paper in your browser")

        hdr = self.table.horizontalHeader()
        for i, (_, _, w, _) in enumerate(COLUMNS):
            self.table.setColumnWidth(i, w)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        hdr.setHighlightSections(False)

        # Detail panel
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(180)
        self.detail.setPlaceholderText(
            "Click a row to see full details (contexts, affiliations, abstract)…"
        )

        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        main.addWidget(splitter, 1)

        # Bottom row
        bot = QHBoxLayout()
        self.lbl_count = QLabel("No results yet"); self.lbl_count.setObjectName("stat")
        hint = QLabel(
            "Double-click → open paper   •   Click headers → sort   •   "
            "Columns marked  " + NA + "  can be filled manually"
        ); hint.setObjectName("stat")
        self.btn_dedup = QPushButton("Deduplicate")
        self.btn_dedup.setObjectName("sec")
        self.btn_dedup.setFixedWidth(112)
        self.btn_dedup.setToolTip(
            "Remove duplicate papers across all sources.\n"
            "Runs automatically after each fetch;\n"
            "click manually at any time."
        )
        self.btn_dedup.clicked.connect(self._deduplicate)

        self.btn_csv  = QPushButton("Export CSV");  self.btn_csv.setObjectName("sec")
        self.btn_json = QPushButton("Export JSON"); self.btn_json.setObjectName("sec")
        for b in (self.btn_csv, self.btn_json): b.setFixedWidth(112)
        self.btn_csv.clicked.connect(self._export_csv)
        self.btn_json.clicked.connect(self._export_json)
        bot.addWidget(self.lbl_count); bot.addStretch()
        bot.addWidget(hint); bot.addSpacing(16)
        bot.addWidget(self.btn_dedup)
        bot.addWidget(self.btn_csv); bot.addWidget(self.btn_json)
        main.addLayout(bot)

        self.sb = QStatusBar(); self.setStatusBar(self.sb)
        self.sb.showMessage(
            "Paste a paper URL or title, optionally queue screenshots, then click "
            "\"Find Citations\"."
        )

    # ── Screenshot queue helpers ───────────────────────────────────────────────

    def _paste_scholar_text(self):
        """Open a dialog for the user to paste copied Google Scholar text."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Paste Google Scholar Text")
        dlg.setMinimumSize(600, 400)
        lay = QVBoxLayout(dlg)
        lbl = QLabel(
            "Go to Google Scholar, select all citation results on the page "
            "(Ctrl+A or manually), copy (Ctrl+C), then paste below (Ctrl+V):"
        )
        lbl.setWordWrap(True)
        lbl.setObjectName("stat")
        edit = QTextEdit()
        edit.setPlaceholderText("Paste Scholar results here…")
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(lbl)
        lay.addWidget(edit, 1)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = edit.toPlainText().strip()
        if not text or self.shot_list is None:
            return

        # Preview: count how many citation blocks were detected
        preview = ocr_parser.parse_scholar_text(text)
        n = len(preview)
        label = f"[Text] {n} citation(s) detected"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, {"type": "text", "content": text})
        item.setToolTip(text[:300] + ("…" if len(text) > 300 else ""))
        self.shot_list.addItem(item)
        self.sb.showMessage(
            f"Added pasted text block ({n} citations detected, "
            f"{self.shot_list.count()} items queued total)."
        )

    def _add_screenshots(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Google Scholar Screenshots",
            "", "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)"
        )
        if not paths or self.shot_list is None:
            return
        existing_paths = {
            self.shot_list.item(i).data(Qt.ItemDataRole.UserRole).get("path","")
            for i in range(self.shot_list.count())
            if isinstance(self.shot_list.item(i).data(Qt.ItemDataRole.UserRole), dict)
        }
        added = 0
        for p in paths:
            if p not in existing_paths:
                item = QListWidgetItem(Path(p).name)
                item.setData(Qt.ItemDataRole.UserRole, {"type": "screenshot", "path": p})
                item.setToolTip(p)
                self.shot_list.addItem(item)
                added += 1
        if added:
            self.sb.showMessage(
                f"Added {added} screenshot(s) to queue "
                f"({self.shot_list.count()} total)."
            )

    def _clear_screenshots(self):
        if self.shot_list:
            self.shot_list.clear()
            self.sb.showMessage("Screenshot queue cleared.")

    def _remove_screenshot(self):
        """Remove currently selected items from the queue."""
        if self.shot_list is None:
            return
        for item in self.shot_list.selectedItems():
            self.shot_list.takeItem(self.shot_list.row(item))

    def _shot_list_key(self, event):
        """Allow Delete key to remove selected screenshots from queue."""
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._remove_screenshot()
        else:
            QListWidget.keyPressEvent(self.shot_list, event)

    def _get_queued_items(self) -> tuple[list[str], list[str]]:
        """Returns (screenshot_paths, pasted_texts) from the queue."""
        if self.shot_list is None:
            return [], []
        shots, texts = [], []
        for i in range(self.shot_list.count()):
            d = self.shot_list.item(i).data(Qt.ItemDataRole.UserRole)
            if not isinstance(d, dict):
                continue
            if d.get("type") == "screenshot":
                shots.append(d["path"])
            elif d.get("type") == "text":
                texts.append(d["content"])
        return shots, texts

    # ── Fetch lifecycle ────────────────────────────────────────────────────────

    def _start(self):
        query         = self.inp.text().strip()
        shots, texts  = self._get_queued_items()

        if not query:
            QMessageBox.warning(
                self, "No Input",
                "Please enter a paper URL or title to look up."
            )
            return

        # Persist query to history
        if query:
            save_to_history(query)
            self._history = load_history()
            self._completer_model.setStringList(self._history)

        self.table.setRowCount(0)
        self._rows = []
        self.lbl_count.setText("Fetching…")
        self.lbl_src.setText("Source paper: looking up…")
        self.prog.setValue(0); self.prog.setRange(0, 100)
        self.btn_fetch.setEnabled(False)
        if self.btn_add_shots:   self.btn_add_shots.setEnabled(False)
        if self.btn_paste_text:  self.btn_paste_text.setEnabled(False)
        if self.btn_clear_shots: self.btn_clear_shots.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.detail.clear()

        self._worker = UnifiedWorker(
            query            = query,
            screenshot_paths = shots,
            pasted_texts     = texts,
            enrich           = self.chk_enrich.isChecked(),
            max_results      = self.spin.value(),
        )
        self._worker.status_update.connect(self._on_status)
        self._worker.progress_update.connect(self._on_progress)
        self._worker.paper_resolved.connect(self._on_paper)
        self._worker.enrich_progress.connect(
            lambda d, t: self.prog.setValue(int(d/t*100) if t else 0)
        )
        self._worker.journal_progress.connect(
            lambda d, t: self.prog.setValue(int(d/t*100) if t else 0)
        )
        self._worker.finished_with_data.connect(self._on_data)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
        self._on_status("Cancelling…")

    def _on_status(self, msg):
        self.lbl_status.setText(msg); self.sb.showMessage(msg)

    def _on_progress(self, cur, total):
        if total > 0:
            self.prog.setRange(0, 100); self.prog.setValue(min(100, int(cur/total*100)))
        else:
            self.prog.setRange(0, 0)

    def _on_paper(self, paper):
        t = paper.get("title","?"); y = paper.get("year","")
        v = paper.get("venue",""); c = paper.get("citationCount", 0) or 0
        self.lbl_src.setText(
            f"Source paper:  {t}  ·  {y}  ·  {v}  ·  {c:,} total citations"
        )

    def _on_data(self, rows):
        self._rows = rows
        self._fill_table(rows)
        self.prog.setRange(0, 100); self.prog.setValue(100)

    def _on_done(self):
        self.btn_fetch.setEnabled(True)
        if self.btn_add_shots:   self.btn_add_shots.setEnabled(True)
        if self.btn_paste_text:  self.btn_paste_text.setEnabled(True)
        if self.btn_clear_shots: self.btn_clear_shots.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.prog.setRange(0, 100)
        self._worker = None

    def _on_error(self, msg):
        QMessageBox.critical(self, "Error", msg)
        self._on_status("Error."); self._on_done()

    # ── Deduplication (manual button) ─────────────────────────────────────────

    def _deduplicate(self):
        if not self._rows:
            return
        before = len(self._rows)
        self._rows = fetcher.deduplicate_rows(self._rows)
        after  = len(self._rows)
        self._fill_table(self._rows)
        self.sb.showMessage(
            f"Deduplicated: {before} → {after} unique papers "
            f"({before - after} duplicates removed)."
        )

    # ── Table population ───────────────────────────────────────────────────────

    _NA_COLOR   = QColor("#374151")   # dim grey for NA cells
    _HIGH_COLOR = QColor("#4ade80")   # green for high impact
    _MED_COLOR  = QColor("#facc15")   # yellow for medium impact

    def _fill_table(self, rows):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for ri, row in enumerate(rows):
            url = row.get("url", "")
            for ci, (_, key, _, numeric) in enumerate(COLUMNS):
                val = row.get(key, "")

                if numeric:
                    item = NumItem(val)
                else:
                    text = str(val) if val not in ("", None) else NA
                    item = QTableWidgetItem(text)
                    if ci == 1:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                        )
                    elif key in ("where_cited","how_utilized","notable","affiliation","domain"):
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                        )

                if str(val) == NA or val in ("", None):
                    item.setForeground(self._NA_COLOR)

                if key == "impact_score":
                    try:
                        s = float(val)
                        item.setForeground(
                            self._HIGH_COLOR if s >= 0.65 else
                            self._MED_COLOR  if s >= 0.35 else
                            QColor("#94a3b8")
                        )
                    except (ValueError, TypeError):
                        pass

                if key == "title":
                    ab = row.get("abstract", "")
                    if ab and ab != NA: item.setToolTip(ab[:400])

                item.setData(Qt.ItemDataRole.UserRole, url)
                self.table.setItem(ri, ci, item)

        self.table.setSortingEnabled(True)
        impact_col = next(
            i for i,(_, k, _, _) in enumerate(COLUMNS) if k == "impact_score"
        )
        self.table.sortItems(impact_col, Qt.SortOrder.DescendingOrder)
        self.lbl_count.setText(f"{len(rows):,} citing papers found")

    # ── Detail panel ──────────────────────────────────────────────────────────

    def _on_row_select(self, cur, _prev):
        if cur is None: return
        ri = cur.row()
        if ri < 0 or ri >= len(self._rows): return

        rank_item = self.table.item(ri, 0)
        if rank_item is None: return
        try:
            rank = int(rank_item.text())
        except ValueError:
            return
        matches = [r for r in self._rows if r.get("rank") == rank]
        if not matches: return
        row = matches[0]

        def f(v): return str(v) if v not in ("", None) else NA

        html = (
            f"<b>{f(row['title'])}</b><br>"
            f"<span style='color:#94a3b8'>{f(row['authors'])}</span><br><br>"
            f"<b>Affiliation(s):</b> {f(row['affiliation'])}<br>"
            f"<b>Author H-Index:</b> {f(row['author_hindex'])}  &nbsp;|&nbsp;  "
            f"<b>Author Total Cites:</b> {f(row['author_cites'])}<br>"
            f"<b>Journal:</b> {f(row['journal'])}  &nbsp;|&nbsp;  "
            f"<b>IF:</b> {f(row['impact_factor'])}  &nbsp;|&nbsp;  "
            f"<b>Location:</b> {f(row['journal_location'])}<br>"
            f"<b>Where cited:</b> {f(row['where_cited'])}<br>"
            f"<b>How utilized:</b> {f(row['how_utilized'])}<br>"
            f"<b>Notable:</b> {f(row['notable'])}<br><br>"
            f"<b>All citation contexts:</b><br>"
            f"<span style='color:#64748b'>{f(row['_contexts_full'])}</span><br><br>"
            f"<b>Abstract:</b><br>"
            f"<span style='color:#64748b'>{f(row['abstract'])}</span>"
        )
        self.detail.setHtml(
            f"<div style='font-family:Segoe UI,Arial;font-size:11px;"
            f"color:#cbd5e1;background:#0d0f18'>{html}</div>"
        )

    # ── Row open ───────────────────────────────────────────────────────────────

    def _open_url(self, index):
        item = self.table.item(index.row(), index.column())
        url  = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if url: QDesktopServices.openUrl(QUrl(url))
        else:   self.sb.showMessage("No URL available for this paper.")

    # ── Export ─────────────────────────────────────────────────────────────────

    _SKIP = {"_contexts_full"}

    def _export_csv(self):
        if not self._rows:
            QMessageBox.information(self, "No Data", "Nothing to export yet."); return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV", "citations.csv", "CSV Files (*.csv)")
        if not path: return
        export_rows = [{k:v for k,v in r.items() if k not in self._SKIP}
                       for r in self._rows]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=export_rows[0].keys())
            w.writeheader(); w.writerows(export_rows)
        self.sb.showMessage(f"Saved: {path}")

    def _export_json(self):
        if not self._rows:
            QMessageBox.information(self, "No Data", "Nothing to export yet."); return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save JSON", "citations.json", "JSON Files (*.json)")
        if not path: return
        export_rows = [{k:v for k,v in r.items() if k not in self._SKIP}
                       for r in self._rows]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(export_rows, f, indent=2, ensure_ascii=False)
        self.sb.showMessage(f"Saved: {path}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI", 10))
    w = CitationExplorer()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
