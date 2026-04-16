"""
fetcher.py — multi-source citation retrieval, enrichment, and impact scoring.

Sources:
  • Semantic Scholar API  (primary — paper metadata, authors, citation contexts/intents)
  • OpenAlex API          (journal metrics — impact factor, country, type)
  • Screenshot OCR        (via ocr_parser → S2 enrichment)

Empty / unavailable fields are filled with the placeholder  <Not Found / DIY>
so users know exactly which cells they may want to fill manually.
"""

import re, time, requests
from urllib.parse import urlparse, parse_qs

S2_BASE = "https://api.semanticscholar.org/graph/v1"
OA_BASE = "https://api.openalex.org"
HEADERS = {"User-Agent": "CitationExplorer/1.0 (academic research tool)"}

NA = "<Not Found / DIY>"   # universal placeholder for missing data

_PAPER_FIELDS = (
    "paperId,title,authors,year,venue,publicationVenue,"
    "citationCount,externalIds,abstract,s2FieldsOfStudy"
)
_CITING_FIELDS = ",".join([
    "contexts", "intents", "isInfluential",
    "citingPaper.paperId",
    "citingPaper.title",
    "citingPaper.authors",
    "citingPaper.year",
    "citingPaper.venue",
    "citingPaper.publicationVenue",
    "citingPaper.citationCount",
    "citingPaper.externalIds",
    "citingPaper.abstract",
    "citingPaper.s2FieldsOfStudy",
])
_AUTHOR_FIELDS = "hIndex,citationCount,name,affiliations"

_jcache: dict[str, dict] = {}   # venue-name → OpenAlex source record


# ── Input parsing ──────────────────────────────────────────────────────────────

def parse_input(text: str) -> tuple[str, str]:
    text = text.strip()
    m = re.search(r'semanticscholar\.org/paper/([A-Za-z0-9]+)', text)
    if m: return "s2_id", m.group(1)
    if "scholar.google" in text:
        p = parse_qs(urlparse(text).query)
        if "cites"   in p: return "scholar_cites", p["cites"][0]
        if "cluster" in p: return "scholar_cites", p["cluster"][0]
        if "q"       in p: return "title",         p["q"][0]
    m = re.search(r'(10\.\d{4,9}/[^\s"<>\]]+)', text)
    if m: return "doi", m.group(1).rstrip("/.")
    m = re.search(r'ieeexplore\.ieee\.org/(?:abstract/)?document/(\d+)', text)
    if m: return "ieee_id", m.group(1)
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d+)', text)
    if m: return "arxiv", m.group(1)
    m = re.match(r'^(\d{4}\.\d+)(v\d+)?$', text)
    if m: return "arxiv", m.group(1)
    return "title", text


# ── API helpers ────────────────────────────────────────────────────────────────

def _s2_get(path: str, params: dict, _retries: int = 4) -> dict | None:
    """
    GET from Semantic Scholar with exponential-backoff retry.
    Retries on: 429 (rate limit), 500/502/503 (server errors), and connection failures.
    Does NOT retry on 404 / 400 (bad request — retrying won't help).
    """
    url = f"{S2_BASE}{path}"
    for attempt in range(_retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None   # genuinely not found — don't retry
            if r.status_code == 429:
                wait = 5 * (attempt + 1)   # 5s, 10s, 15s, 20s
                time.sleep(wait)
                continue
            if r.status_code in (500, 502, 503):
                time.sleep(2 ** attempt)   # 1s, 2s, 4s, 8s
                continue
            return None   # other 4xx — don't retry
        except (requests.ConnectionError, requests.Timeout):
            if attempt < _retries - 1:
                time.sleep(2 ** attempt)
            continue
        except requests.RequestException:
            return None
    return None


def _oa_get(path: str, params: dict) -> dict | None:
    try:
        r = requests.get(f"{OA_BASE}{path}", params=params, headers=HEADERS, timeout=15)
        if r.status_code == 200: return r.json()
    except requests.RequestException:
        pass
    return None


def _title_sim(a: str, b: str) -> float:
    """Word-overlap (Jaccard) similarity between two title strings."""
    norm = lambda s: set(re.sub(r'[^a-z0-9]', ' ', s.lower()).split())
    wa, wb = norm(a), norm(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


# ── Paper lookup ───────────────────────────────────────────────────────────────

def lookup_paper(input_type: str, value: str) -> dict | None:
    f = {"fields": _PAPER_FIELDS}
    if input_type == "s2_id":  return _s2_get(f"/paper/{value}", f)
    if input_type == "doi":    return _s2_get(f"/paper/DOI:{value}", f)
    if input_type == "arxiv":  return _s2_get(f"/paper/arXiv:{value}", f)
    if input_type == "ieee_id":
        data = _s2_get("/paper/search", {"query": value, "fields": _PAPER_FIELDS, "limit": 5})
        if data and data.get("data"):
            for p in data["data"]:
                ext = p.get("externalIds") or {}
                if str(ext.get("IEEE","")) == value or value in str(ext.get("DOI","")):
                    return p
            return data["data"][0]
    if input_type == "title":
        # Build query variants: full title, without punctuation, first 7 words.
        # S2 search transiently returns empty results — try all variants before
        # sleeping and retrying.
        words = value.split()
        clean = re.sub(r'[^\w\s]', ' ', value).strip()
        queries = list(dict.fromkeys(filter(None, [
            value,
            clean if clean != value else None,
            " ".join(words[:7]) if len(words) > 7 else None,
            " ".join(words[:5]) if len(words) > 5 else None,
        ])))

        for attempt in range(4):
            for q in queries:
                data = _s2_get("/paper/search", {
                    "query": q, "fields": _PAPER_FIELDS, "limit": 10
                })
                if data and data.get("data"):
                    # Pick best title-similarity match; return it regardless of
                    # score — S2 already filtered to relevant results.
                    best, best_sim = data["data"][0], 0.0
                    for c in data["data"]:
                        sim = _title_sim(c.get("title", ""), value)
                        if sim > best_sim:
                            best, best_sim = c, sim
                    return best
            # All queries returned empty — brief wait then retry
            if attempt < 3:
                time.sleep(1 + attempt)   # 1s, 2s, 3s

    return None


# ── OpenAlex: convert a work record to S2-compatible paper dict ────────────────

def _oa_work_to_paper(w: dict, source_tag: str = "openalex") -> dict:
    doi = (w.get("doi") or "").replace("https://doi.org/", "")
    authors = [
        {"name": (a.get("author") or {}).get("display_name",""), "authorId": None}
        for a in (w.get("authorships") or [])[:6]
        if (a.get("author") or {}).get("display_name")
    ]
    loc    = w.get("primary_location") or {}
    source = loc.get("source") or {}
    venue  = source.get("display_name","")
    # Map OA top-level concepts (level 0-1) to s2FieldsOfStudy format
    fos = [
        {"category": c.get("display_name",""), "source": "openalex"}
        for c in (w.get("concepts") or [])
        if c.get("level", 99) <= 1 and c.get("display_name")
    ]
    return {
        "paperId":          None,
        "title":            w.get("title",""),
        "authors":          authors,
        "year":             w.get("publication_year"),
        "venue":            venue,
        "publicationVenue": {"name": venue, "type": source.get("type","")},
        "citationCount":    w.get("cited_by_count", 0),
        "externalIds":      {"DOI": doi} if doi else {},
        "abstract":         None,
        "s2FieldsOfStudy":  fos,
        "_contexts":        [],
        "_intents":         [],
        "_isInfluential":   False,
        "_source":          source_tag,
    }


# ── Citation fetching — OpenAlex ───────────────────────────────────────────────

def fetch_citations_openalex(paper: dict, on_progress=None) -> list[dict]:
    """
    Fetch papers citing *paper* from OpenAlex.
    Looks up the OpenAlex work ID via DOI (preferred) or title, then pages
    through all citing works using cursor-based pagination.
    """
    # 1. Find OpenAlex work ID
    ext = paper.get("externalIds") or {}
    doi = ext.get("DOI","")
    oa_id = None

    if doi:
        data = _oa_get(f"/works/doi:{doi}", {"select": "id"})
        if data:
            oa_id = (data.get("id") or "").split("/")[-1]

    if not oa_id:
        title = (paper.get("title") or "").strip()
        if title:
            data = _oa_get("/works", {
                "filter":   f"title.search:{title}",
                "per_page": 1,
                "select":   "id,title",
            })
            results = (data or {}).get("results", [])
            if results:
                oa_id = (results[0].get("id") or "").split("/")[-1]

    if not oa_id:
        return []

    # 2. Page through citing works
    all_papers: list[dict] = []
    cursor = "*"
    _OA_FIELDS = (
        "id,doi,title,authorships,publication_year,"
        "cited_by_count,primary_location,concepts"
    )
    while True:
        data = _oa_get("/works", {
            "filter":   f"cites:{oa_id}",
            "per_page": 200,
            "cursor":   cursor,
            "select":   _OA_FIELDS,
        })
        if not data:
            break
        for w in data.get("results", []):
            if w.get("title"):
                all_papers.append(_oa_work_to_paper(w))
        if on_progress:
            on_progress(len(all_papers))
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(0.2)

    return all_papers


# ── Citation fetching — OpenCitations (COCI) ───────────────────────────────────

_OC_BASE = "https://opencitations.net/index/coci/api/v1"

def fetch_citations_opencitations(paper: dict, on_progress=None) -> list[dict]:
    """
    Fetch citing DOIs from OpenCitations COCI (requires the source paper to have
    a DOI), then enrich each via Semantic Scholar.  Only runs if paper has a DOI.
    """
    ext = paper.get("externalIds") or {}
    doi = ext.get("DOI","")
    if not doi:
        return []

    try:
        r = requests.get(
            f"{_OC_BASE}/citations/{doi}",
            headers=HEADERS, timeout=30,
        )
        if r.status_code != 200:
            return []
        records = r.json()
    except Exception:
        return []

    # Extract unique citing DOIs (OC format: "doi:10.xxxx/xxxx")
    citing_dois = list(dict.fromkeys(
        c.get("citing","").replace("coci => ","").strip().lstrip("doi:").strip()
        for c in records
        if c.get("citing")
    ))
    if not citing_dois:
        return []

    papers: list[dict] = []
    for i, cdoi in enumerate(citing_dois):
        data = _s2_get(f"/paper/DOI:{cdoi}", {"fields": _PAPER_FIELDS})
        if data and data.get("paperId"):
            data["_contexts"]     = []
            data["_intents"]      = []
            data["_isInfluential"]= False
            data["_source"]       = "opencitations"
            papers.append(data)
        if on_progress:
            on_progress(i + 1, len(citing_dois))
        time.sleep(0.15)

    return papers


# ── Citation fetching (paginated) ──────────────────────────────────────────────

def fetch_citations_s2(paper_id: str, on_progress=None) -> list[dict]:
    """
    Returns list of citingPaper dicts with _contexts, _intents, _isInfluential added.
    """
    all_papers: list[dict] = []
    offset, page_size = 0, 100
    while True:
        data = _s2_get(f"/paper/{paper_id}/citations", {
            "fields": _CITING_FIELDS,
            "offset": offset,
            "limit":  page_size,
        })
        if not data: break
        for item in data.get("data", []):
            cp = item.get("citingPaper") or {}
            if not cp.get("paperId"): continue
            cp["_contexts"]      = item.get("contexts", [])
            cp["_intents"]       = item.get("intents", [])
            cp["_isInfluential"] = item.get("isInfluential", False)
            all_papers.append(cp)
        if on_progress: on_progress(len(all_papers))
        if not data.get("next"): break
        offset += page_size
        time.sleep(0.35)
    return all_papers


# ── Author enrichment ──────────────────────────────────────────────────────────

def enrich_author_data(papers: list[dict], on_progress=None) -> list[dict]:
    """
    Fetches h-index, total citations, and institutional affiliations for
    the top 3 listed authors of each paper.
    """
    total = len(papers)
    for i, paper in enumerate(papers):
        best_h, best_cites = 0, 0
        affiliations: list[str] = []
        for author in (paper.get("authors") or [])[:3]:
            aid = author.get("authorId")
            if not aid: continue
            info = _s2_get(f"/author/{aid}", {"fields": _AUTHOR_FIELDS})
            if info:
                best_h     = max(best_h,    info.get("hIndex")        or 0)
                best_cites = max(best_cites, info.get("citationCount") or 0)
                for aff in (info.get("affiliations") or []):
                    # S2 returns affiliations as either strings or
                    # {"institution": {"name": "..."}} dicts — handle both
                    if isinstance(aff, str):
                        if aff: affiliations.append(aff)
                    elif isinstance(aff, dict):
                        inst = aff.get("institution") or {}
                        if isinstance(inst, dict):
                            if inst.get("name"): affiliations.append(inst["name"])
                        elif isinstance(inst, str) and inst:
                            affiliations.append(inst)
            time.sleep(0.12)
        paper["_authorHIndex"]     = best_h
        paper["_authorTotalCites"] = best_cites
        paper["_affiliations"]     = list(dict.fromkeys(affiliations))
        if on_progress: on_progress(i + 1, total)
    return papers


# ── Journal enrichment via OpenAlex ───────────────────────────────────────────

def enrich_journal_data(papers: list[dict], on_progress=None) -> list[dict]:
    """
    Batch-fetches journal impact factor (2yr mean citedness), journal h-index
    (used as ranking proxy), type, and country from OpenAlex for every unique venue.
    Results are cached to avoid duplicate calls.
    """
    venues = list({
        (p.get("venue") or "").strip()
        for p in papers
        if (p.get("venue") or "").strip()
    })

    for vi, venue in enumerate(venues):
        if venue not in _jcache:
            data = _oa_get("/sources", {
                "search":   venue,
                "per_page": 1,
                "select":   "display_name,summary_stats,country_code,type",
            })
            _jcache[venue] = (data.get("results") or [{}])[0] if data else {}
            time.sleep(0.2)
        if on_progress: on_progress(vi + 1, len(venues))

    for paper in papers:
        jd    = _jcache.get((paper.get("venue") or "").strip(), {})
        stats = jd.get("summary_stats") or {}
        paper["_jIF"]      = stats.get("2yr_mean_citedness", "")
        paper["_jHIndex"]  = stats.get("h_index", "")
        paper["_jCountry"] = jd.get("country_code", "")
        paper["_jType"]    = jd.get("type", "")
    return papers


# ── Citation-context interpretation ───────────────────────────────────────────

_SECTION_MAP = {
    "background":  "Introduction / Background",
    "methodology": "Methods / Approach",
    "result":      "Results / Discussion",
}
_USAGE_MAP = {
    "background":  "Cited as foundational background or prior work",
    "methodology": "Authors adopt or extend the methodology/approach",
    "result":      "Results or findings are compared or referenced",
}

def describe_where_cited(intents: list[str]) -> str:
    if not intents: return NA
    return ", ".join(dict.fromkeys(_SECTION_MAP.get(i, i.title()) for i in intents))

def describe_how_utilized(intents: list[str], contexts: list[str], is_influential: bool) -> str:
    parts: list[str] = []
    if intents:
        usages = list(dict.fromkeys(_USAGE_MAP.get(i, i.title()) for i in intents))
        parts.append("; ".join(usages))
    if contexts:
        ctx = contexts[0].strip().replace("\n", " ")
        if len(ctx) > 300: ctx = ctx[:297] + "…"
        parts.append(f'In their own words: "{ctx}"')
    else:
        parts.append(NA)
    if is_influential:
        parts.append("★ Flagged as a highly influential citation by Semantic Scholar")
    return " — ".join(parts) if parts else NA

def notable_flags(paper: dict) -> str:
    flags: list[str] = []
    if paper.get("_isInfluential"):
        flags.append("★ Highly influential")
    h = paper.get("_authorHIndex") or 0
    if h >= 40:   flags.append(f"Top-tier author (h={h})")
    elif h >= 20: flags.append(f"Established author (h={h})")
    jif = float(paper.get("_jIF") or 0)
    if jif >= 8:  flags.append(f"High-IF journal (IF={jif:.1f})")
    elif jif >= 4: flags.append(f"Good journal (IF={jif:.1f})")
    return "; ".join(flags) if flags else NA


# ── Impact scoring ─────────────────────────────────────────────────────────────

def compute_impact_scores(papers: list[dict]) -> list[dict]:
    max_cites  = max((p.get("citationCount") or 0 for p in papers), default=1) or 1
    max_hindex = max((p.get("_authorHIndex") or 0 for p in papers), default=1) or 1
    max_jif    = max((float(p.get("_jIF") or 0) for p in papers), default=1.0) or 1.0
    for p in papers:
        cites   = (p.get("citationCount") or 0) / max_cites
        hindex  = (p.get("_authorHIndex") or 0) / max_hindex
        jif     = float(p.get("_jIF") or 0)     / max_jif
        year    = p.get("year") or 2000
        recency = max(0.0, min(1.0, (year - 2000) / 26.0))
        p["_impactScore"] = round(
            0.45 * cites + 0.20 * hindex + 0.15 * jif + 0.20 * recency, 4
        )
    papers.sort(key=lambda p: p["_impactScore"], reverse=True)
    return papers


# ── Flatten to display/export rows ────────────────────────────────────────────

def papers_to_rows(papers: list[dict]) -> list[dict]:
    rows = []
    for rank, p in enumerate(papers, 1):
        authors = p.get("authors") or []
        names   = "; ".join(a.get("name","") for a in authors[:6])
        if len(authors) > 6: names += f" + {len(authors)-6} more"
        names = names or NA

        affils    = p.get("_affiliations") or []
        affil_str = "; ".join(affils[:3]) if affils else NA

        # Academic domain: S2 gives broad top-level fields (Computer Science,
        # Engineering…). We supplement with venue/title keyword matching to
        # get a more specific subdomain, and suppress catch-all labels when
        # a specific one is available.
        fos = p.get("s2FieldsOfStudy") or []
        model_domains = [d["category"] for d in fos
                         if d.get("source") == "s2-fos-model" and d.get("category")]
        all_domains   = [d.get("category","") for d in fos if d.get("category")]
        base_domains  = list(dict.fromkeys(model_domains or all_domains))

        # Keyword → specific subdomain mapping (title + venue signal)
        title_venue_text = " ".join(filter(None, [
            p.get("title",""), p.get("venue",""),
            (p.get("publicationVenue") or {}).get("name",""),
        ])).lower()

        _SUBDOMAIN_RULES = [
            (r'secur|crypt|authenticat|privacy|intrusion|malware|cyber',  "Cybersecurity"),
            (r'vehicular|vanet|v2x|v2v|v2i|dsrc|its\b|intelligent transport', "Vehicular Networks"),
            (r'machine learning|deep learning|neural|lstm|cnn|transformer|nlp|llm', "Machine Learning / AI"),
            (r'wireless|5g|lte|wifi|bluetooth|spectrum|mimo|channel',    "Wireless Communications"),
            (r'network|routing|protocol|tcp|udp|latency|bandwidth|qos',  "Networking"),
            (r'cloud|edge|fog\b|iot|internet of things',                 "Cloud / Edge / IoT"),
            (r'robot|autonomous|drone|uav|control system',               "Robotics & Control"),
            (r'image|vision|detection|segmentation|object',              "Computer Vision"),
            (r'data mining|big data|database|sql|nosql',                 "Data Engineering"),
            (r'block ?chain|distributed ledger',                         "Blockchain"),
            (r'energy|power|smart grid|renewab',                         "Energy Systems"),
            (r'medical|health|clinical|patient|eeg|fmri',                "Biomedical / Health"),
        ]
        specific = []
        for pattern, label in _SUBDOMAIN_RULES:
            if re.search(pattern, title_venue_text):
                specific.append(label)
                break   # one specific label is enough

        # Build final domain string:
        # - If we found a specific subdomain, use it + broad field (max 2)
        # - Otherwise fall back to S2 broad fields (max 2)
        _GENERIC = {"Computer Science", "Engineering", "Mathematics",
                    "Physics", "Science", "Technology"}
        if specific:
            non_generic = [d for d in base_domains if d not in _GENERIC]
            combined = list(dict.fromkeys(specific + (non_generic or base_domains)))
            domain_str = ", ".join(combined[:2])
        else:
            domain_str = ", ".join(base_domains[:2]) or NA

        pub_venue  = p.get("publicationVenue") or {}
        venue_name = pub_venue.get("name") or p.get("venue") or NA
        venue_type = (pub_venue.get("type") or p.get("_jType") or "").replace("_"," ").title() or NA

        ext = p.get("externalIds") or {}
        doi = ext.get("DOI","")
        url = f"https://doi.org/{doi}" if doi else (
            f"https://www.semanticscholar.org/paper/{p['paperId']}" if p.get("paperId") else ""
        )

        raw_if  = p.get("_jIF","")
        if_str  = str(round(float(raw_if), 2)) if raw_if else NA
        j_rank  = str(p.get("_jHIndex","")) if p.get("_jHIndex","") else NA   # OpenAlex journal h-index

        raw_loc = p.get("_jCountry","")
        j_loc   = ("US" if raw_loc.upper() == "US" else f"International ({raw_loc.upper()})") if raw_loc else NA

        contexts       = p.get("_contexts") or []
        intents        = p.get("_intents")  or []
        is_influential = p.get("_isInfluential", False)

        rows.append({
            "rank":             rank,
            "title":            p.get("title") or NA,
            "year":             p.get("year") or NA,
            "citations":        p.get("citationCount") if p.get("citationCount") is not None else NA,
            "domain":           domain_str,
            "journal":          venue_name,
            "journal_type":     venue_type,
            "journal_ranking":  j_rank,
            "impact_factor":    if_str,
            "journal_location": j_loc,
            "authors":          names,
            "designation":      NA,
            "affiliation":      affil_str,
            "author_hindex":    str(p["_authorHIndex"]) if p.get("_authorHIndex") else NA,
            "author_cites":     str(p["_authorTotalCites"]) if p.get("_authorTotalCites") else NA,
            "where_cited":      describe_where_cited(intents),
            "how_utilized":     describe_how_utilized(intents, contexts, is_influential),
            "notable":          notable_flags(p),
            "impact_score":     p.get("_impactScore") or 0.0,
            "source":           p.get("_source", "semantic_scholar"),
            # export-only / detail panel
            "doi":              doi or NA,
            "url":              url,
            "abstract":         (p.get("abstract") or NA)[:500],
            "_contexts_full":   " | ".join(contexts) if contexts else NA,
        })
    return rows


# ── Screenshot → S2 enrichment ─────────────────────────────────────────────────

def lookup_screenshot_citations(
    raw_list: list[dict],
    on_progress=None,
) -> list[dict]:
    """
    For each raw citation dict extracted from a screenshot (keys: title, authors,
    venue, year, citations), search Semantic Scholar by title and return a list of
    enriched paper dicts in the same format as fetch_citations_s2().

    Papers that cannot be matched are returned with partial data so they still
    appear in the table (marked <Not Found / DIY> for missing fields).
    """
    enriched: list[dict] = []
    total = len(raw_list)

    for i, raw in enumerate(raw_list):
        title = (raw.get("title") or "").strip()
        if not title:
            if on_progress:
                on_progress(i + 1, total)
            continue

        data = _s2_get("/paper/search", {
            "query":  title,
            "fields": _PAPER_FIELDS,
            "limit":  5,
        })

        paper = None
        if data and data.get("data"):
            # Pick best match by title similarity
            best_sim, best_p = 0.0, None
            for candidate in data["data"]:
                sim = _title_sim(candidate.get("title", ""), title)
                if sim > best_sim:
                    best_sim, best_p = sim, candidate
            # Accept if reasonable similarity; otherwise fall back to raw data
            if best_sim >= 0.5:
                paper = best_p

        if paper:
            paper["_contexts"]      = []
            paper["_intents"]       = []
            paper["_isInfluential"] = False
            paper["_source"]        = "screenshot+s2"
            enriched.append(paper)
        else:
            # Couldn't match on S2 — keep raw data so row still appears
            stub = {
                "paperId":       None,
                "title":         title,
                "authors":       [{"name": a.strip(), "authorId": None}
                                  for a in re.split(r'[,;]', raw.get("authors",""))
                                  if a.strip()],
                "year":          raw.get("year"),
                "venue":         raw.get("venue", ""),
                "citationCount": raw.get("citations", 0),
                "externalIds":   {},
                "abstract":      None,
                "s2FieldsOfStudy": [],
                "publicationVenue": {},
                "_contexts":     [],
                "_intents":      [],
                "_isInfluential": False,
                "_source":       "screenshot",
            }
            enriched.append(stub)

        if on_progress:
            on_progress(i + 1, total)
        time.sleep(0.3)

    return enriched


# ── Deduplication ──────────────────────────────────────────────────────────────

def _row_key(row: dict) -> str:
    """Normalised title key used for deduplication."""
    return re.sub(r"[^a-z0-9]", "", (row.get("title") or "").lower())[:80]


def _merge_rows(a: dict, b: dict) -> dict:
    """
    Merge two row dicts. For each field, prefer the non-NA value.
    If both have values, prefer the one from Semantic Scholar (richer metadata).
    """
    merged = dict(a)
    for k, v in b.items():
        if k in ("rank",):
            continue
        existing = merged.get(k)
        if existing in ("", None, NA) and v not in ("", None, NA):
            merged[k] = v
        # Combine source tags so the user can see all origins
        if k == "source" and existing and v and existing != v:
            merged[k] = f"{existing} + {v}"
    return merged


def deduplicate_rows(rows: list[dict]) -> list[dict]:
    """
    Remove duplicate papers across all sources (S2, screenshot, etc.).

    Deduplication key: normalised title (lowercase, alphanumeric only, first 80 chars).
    When two records match, they are merged — non-NA fields from either record
    are preserved (S2 data wins on conflicts).

    Ranks are reassigned after deduplication.
    """
    seen: dict[str, int] = {}   # key → index in `result`
    result: list[dict]   = []

    for row in rows:
        key = _row_key(row)
        if not key:
            result.append(row)
            continue

        if key in seen:
            result[seen[key]] = _merge_rows(result[seen[key]], row)
        else:
            seen[key] = len(result)
            result.append(dict(row))

    # Re-assign sequential ranks
    for i, row in enumerate(result, 1):
        row["rank"] = i

    return result
