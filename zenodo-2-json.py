#!/usr/bin/env python3
# zenodo-2-json.py
# 1) Normalize Zenodo-exported citations.bib -> citations.normalized.bib
#    (EXACTLY one {…} per field; inner braces removed; common LaTeX macros flattened)
# 2) Merge normalized BibTeX into content.json -> content.updated.with_summaries.json
#    - Robust JSON loader: tolerates BOM, comments, trailing commas; falls back to skeleton if needed.

import json, re, unicodedata, pathlib, sys
from typing import Dict, Tuple, List, Any

BIB_IN        = "citations.bib"
CONTENT_IN    = "content.json"
BIB_OUT       = "citations.normalized.bib"
CONTENT_OUT   = "content.updated.with_summaries.json"

# ---------- IO ----------
def read_text(path: str) -> str:
    p = pathlib.Path(path)
    if not p.exists():
        return ""  # we'll handle missing files upstream
    return p.read_text(encoding="utf-8", errors="replace")

def write_text(path: str, text: str) -> None:
    pathlib.Path(path).write_text(text, encoding="utf-8")

def write_json(path: str, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))

# ---------- String utilities ----------
def slugify(text: str, max_words: int = 6, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", text.lower())
    s = "-".join(words[:max_words])[:max_len].strip("-")
    return s or "item"

def norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def strip_all_braces(s: str) -> str:
    return (s or "").replace("{", "").replace("}", "")

def norm_title_for_match(s: str) -> str:
    s = strip_all_braces(s or "")
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def canonical_doi(s: str) -> str:
    if not s: return ""
    s = s.strip()
    s = re.sub(r"^https?://(dx\.)?doi\.org/", "", s, flags=re.I)
    s = s.split("#", 1)[0]
    return s.lower().strip()

def doi_to_url(doi: str) -> str:
    doi = canonical_doi(doi)
    return f"https://doi.org/{doi}" if doi else ""

# ---------- BibTeX parsing ----------
def parse_bibtex_entries(src: str) -> List[Tuple[str, str, Dict[str, str]]]:
    """Return list of (entrytype, key, fields). Removes one outer layer of braces/quotes per field."""
    src = re.sub(r"(?m)^[ \t]*%.*$", "", src)  # drop full-line comments
    entries = []
    i = 0
    n = len(src)
    while True:
        m = re.search(r"@([a-zA-Z]+)\s*\{", src[i:])
        if not m:
            break
        etype = m.group(1).lower()
        start = i + m.end()
        j = i + m.end() - 1
        depth = 0
        in_quote = False
        while j < n:
            ch = src[j]
            if in_quote:
                if ch == '"' and src[j-1] != '\\':
                    in_quote = False
            else:
                if ch == '"':
                    in_quote = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        body = src[start:j]
        key_m = re.match(r"\s*([^,]+)\s*,", body, flags=re.S)
        if not key_m:
            i = j + 1
            continue
        key = key_m.group(1).strip()
        fields_blob = body[key_m.end():]

        fields: Dict[str, str] = {}
        buf = []
        depth = 0
        in_quote = False
        for ch in fields_blob:
            if in_quote:
                buf.append(ch)
                if ch == '"' and len(buf) > 1 and buf[-2] != '\\':
                    in_quote = False
                continue
            if ch == '"':
                in_quote = True
                buf.append(ch)
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            if ch == ',' and depth == 0:
                token = "".join(buf).strip()
                if token:
                    k, v = parse_field(token)
                    if k: fields[k.lower()] = v
                buf = []
            else:
                buf.append(ch)
        token = "".join(buf).strip()
        if token:
            k, v = parse_field(token)
            if k: fields[k.lower()] = v

        entries.append((etype, key, fields))
        i = j + 1
    return entries

def parse_field(token: str) -> Tuple[str, str]:
    m = re.match(r"\s*([a-zA-Z0-9_]+)\s*=\s*(.+?)\s*$", token, flags=re.S)
    if not m:
        return None, None
    k, v = m.group(1), m.group(2).strip().rstrip(",")
    # remove one outer layer of {…} or "…"
    if (v.startswith("{") and v.endswith("}")) or (v.startswith('"') and v.endswith('"')):
        v = v[1:-1]
    v = norm_spaces(v)
    return k, v

# ---------- Normalization helpers (for BIB_OUT) ----------
def unwrap_wrapping_delims(s: str) -> str:
    """Strip repeated full-string wrappers: outer {…} or quotes (preserves inner content)."""
    s = s.strip()
    # quotes
    while len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1].strip()
    # outer braces (full-string)
    while s.startswith("{") and s.endswith("}"):
        # ensure the last '}' closes the first '{'
        depth = 0
        ok = False
        for i, ch in enumerate(s):
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    ok = (i == len(s) - 1)
                    break
        if ok:
            s = s[1:-1].strip()
        else:
            break
    return s

# Flatten common LaTeX macros: \emph{...}, \textit{...}, \url{...}, etc. -> just contents
MACRO_RE = re.compile(r"""
    \\[A-Za-z]+             # \command
    (?:\s*\[[^\]]*\])?      # optional [opts]
    \s*\{                   # opening brace of argument
    ([^{}]*?)               # (non-nested) content
    \}
""", re.X)

def flatten_macros_and_braces(value: str) -> str:
    s = unwrap_wrapping_delims(value)
    # Remove inline math blocks
    s = re.sub(r"\$[^$]*\$", "", s)
    # iteratively strip simple macro wrappers \cmd{...} -> ...
    for _ in range(10):
        new_s = MACRO_RE.sub(r"\1", s)
        if new_s == s:
            break
        s = new_s
    # Remove ALL remaining braces inside (final invariant)
    s = s.replace("{", "").replace("}", "")
    s = norm_spaces(s)
    return s

PREFERRED_ORDER = [
    "author","title","year","journal","booktitle","publisher","editor",
    "volume","number","pages","doi","url","institution","organization",
    "address","month","note","abstract","keywords","file"
]

def format_bib_entry(etype: str, key: str, fields: Dict[str, str]) -> str:
    """Write a clean BibTeX entry with exactly one {…} pair per field value (no inner braces)."""
    norm_fields = {}
    for k, v in fields.items():
        vv = flatten_macros_and_braces(v)
        norm_fields[k] = "{" + vv + "}"

    ordered_keys = [k for k in PREFERRED_ORDER if k in norm_fields] + \
                   sorted([k for k in norm_fields.keys() if k not in PREFERRED_ORDER])

    lines = [f"@{etype}{{{key},"]
    for k in ordered_keys:
        lines.append(f"  {k} = {norm_fields[k]},")
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines)

def normalize_bib(src: str) -> str:
    entries = parse_bibtex_entries(src)
    chunks = []
    for etype, key, fields in entries:
        chunks.append(format_bib_entry(etype, key, fields))
    return "\n\n".join(chunks) + "\n"

# ---------- Abstract → Summary ----------
def clean_latex(text: str) -> str:
    if not text:
        return ""
    t = text
    t = re.sub(r"\$[^$]*\$", "", t)  # inline math
    t = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?", r"\1", t)  # \cmd{arg} -> arg
    t = t.replace("{", "").replace("}", "")
    t = t.replace("~", " ")
    t = t.replace("\\%", "%").replace("\\_", "_").replace("\\&","&")
    t = norm_spaces(t)
    return t

def abstract_to_summary(abstract: str, max_chars: int = 300) -> str:
    if not abstract:
        return ""
    text = clean_latex(abstract)
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    sents = [s.strip() for s in sents if s.strip()]
    if not sents:
        out = text[:max_chars].rstrip()
        return out + ("…" if len(text) > max_chars else "")
    out = sents[0]
    if len(out) < max_chars * 0.55 and len(sents) > 1:
        out = f"{out} {sents[1]}"
    out = re.sub(r"\s*[,–—]\s*", "; ", out)
    out = re.sub(r"\s*;\s*;", "; ", out)
    out = norm_spaces(out)
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "…"
    return out

# ---------- Authors for JSON ----------
def format_authors_for_json(auth_raw: str) -> str:
    if not auth_raw:
        return ""
    parts = [p.strip() for p in re.split(r"\s+\band\b\s+", auth_raw, flags=re.I) if p.strip()]
    out = []
    for p in parts:
        p = strip_all_braces(p)
        if "," in p:
            last = p.split(",")[0].strip()
        else:
            toks = p.split()
            last = toks[-1].strip() if toks else p
        out.append(last)
    return ", ".join(out)

# ---------- Type mapping ----------
def map_type(bt: str) -> str:
    t = (bt or "").lower()
    if t in ("article",):
        return "journal"
    if t in ("inproceedings","conference","proceedings"):
        return "conference"
    if t in ("techreport","report"):
        return "report"
    if t in ("phdthesis","mastersthesis","thesis"):
        return "article"
    if t in ("misc","dataset","data"):
        return "dataset"
    return "article"

# ---------- Build publication JSON row ----------
PDF_RE = re.compile(r"([^\s;:]+\.pdf)\b", re.I)

def pick_pdf_from_fields(fields: Dict[str, str]) -> str:
    for k in ("file","pdf","url"):
        vv = (fields.get(k,"") or "")
        m = PDF_RE.search(vv)
        if m:
            return m.group(1)
    return ""

def build_pub(etype: str, key: str, f: Dict[str, str]) -> Dict[str, Any]:
    raw_title = f.get("title","")
    title = strip_all_braces(raw_title).strip()
    year = (f.get("year","") or "").strip()
    authors = format_authors_for_json(f.get("author",""))
    doi_bare = canonical_doi(f.get("doi",""))
    doi_url = doi_to_url(doi_bare)
    url = (f.get("url","") or "").strip()
    abstract = (f.get("abstract","") or "").strip()
    summary = abstract_to_summary(abstract) if abstract else ""
    pdf = pick_pdf_from_fields(f)
    id_base = slugify(title) if title else slugify(key)
    pid = f"{year}-{id_base}" if year else id_base
    return {
        "id": pid,
        "title": title,
        "authors": authors,
        "year": int(year) if year.isdigit() else year,
        "type": map_type(etype),
        "summary": strip_all_braces(summary),
        "pdf": pdf,
        "doi": doi_url or url,
        "cite": "",
        "data": "",
        "code": "",
        "viz": "",
        "thumb": ""
    }

# ---------- Merge logic ----------
def merge_records(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(new)
    for k, v in old.items():
        if k == "summary":
            out[k] = v if isinstance(v, str) and v.strip() else new.get(k, "")
            continue
        if k == "year":
            out[k] = v
            continue
        if isinstance(v, str):
            if v.strip():
                out[k] = v
        elif v not in (None, "", []):
            out[k] = v
    return out

# ---------- Lenient JSON loader (BOM, comments, trailing commas) ----------
def strip_json_comments_and_trailing_commas(s: str) -> str:
    if not s:
        return s
    # BOM
    s = s.lstrip("\ufeff")
    # Remove /* */ comments
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    # Remove // comments
    s = re.sub(r"(?m)^\s*//.*?$", "", s)
    s = re.sub(r"(?m)(?<!:)//.*?$", "", s)  # also inline after values (best-effort)
    # Remove trailing commas before } or ]
    s = re.sub(r",\s*(\]|\})", r"\1", s)
    return s.strip()

def load_content_json(path: str) -> Dict[str, Any]:
    raw = read_text(path)
    if not raw.strip():
        print(f"[warn] {path} missing or empty; starting from skeleton.")
        return {"publications": []}
    # Try strict first
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Try lenient fixes
    fixed = strip_json_comments_and_trailing_commas(raw)
    try:
        return json.loads(fixed)
    except Exception as e:
        print(f"[warn] Failed to parse {path} as JSON even after fixes; using skeleton. ({e})")
        return {"publications": []}

# ---------- Main ----------
def main(bib_in=BIB_IN, json_in=CONTENT_IN, bib_out=BIB_OUT, json_out=CONTENT_OUT):
    # 1) Normalize BibTeX (strict: one brace-pair per field, inner braces removed)
    raw_bib = read_text(bib_in)
    if not raw_bib.strip():
        raise FileNotFoundError(f"{bib_in} is missing or empty.")
    normalized_bib = normalize_bib(raw_bib)
    write_text(bib_out, normalized_bib)

    # 2) Parse normalized and merge to JSON (lenient loader)
    content = load_content_json(json_in)

    entries = parse_bibtex_entries(normalized_bib)
    bib_pubs = [build_pub(et, key, f) for et, key, f in entries]

    existing = content.get("publications", []) or []

    # sanitize existing JSON text (remove stray braces)
    for p in existing:
        if isinstance(p.get("title"), str):
            p["title"] = strip_all_braces(p["title"])
        if isinstance(p.get("authors"), str):
            p["authors"] = strip_all_braces(p["authors"])
        if isinstance(p.get("summary"), str):
            p["summary"] = strip_all_braces(p["summary"])

    # Indices
    by_doi: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, Dict[str, Any]] = {}
    for p in existing:
        d = canonical_doi(p.get("doi",""))
        if d:
            by_doi[d] = p
        tkey = norm_title_for_match(p.get("title",""))
        if tkey:
            by_title[tkey] = p

    merged: List[Dict[str, Any]] = []
    seen_ids = set()

    for p in bib_pubs:
        key_doi = canonical_doi(p.get("doi",""))
        match = by_doi.get(key_doi) if key_doi else None
        if not match:
            tkey = norm_title_for_match(p.get("title",""))
            match = by_title.get(tkey) if tkey else None
        if match:
            merged.append(merge_records(match, p))
            seen_ids.add(id(match))
        else:
            merged.append(p)

    for p in existing:
        if id(p) not in seen_ids:
            merged.append(p)

    def sort_key(row: Dict[str, Any]) -> int:
        y = row.get("year")
        try: return int(y)
        except: return -1
    merged.sort(key=sort_key, reverse=True)

    content["publications"] = merged
    write_json(json_out, content)

    print(f"Wrote normalized BibTeX: {bib_out}")
    print(f"Wrote merged JSON:      {json_out}")

if __name__ == "__main__":
    # CLI: zenodo-2-json.py [bib_in] [json_in] [bib_out] [json_out]
    args = sys.argv[1:]
    bib_in   = args[0] if len(args) > 0 else BIB_IN
    json_in  = args[1] if len(args) > 1 else CONTENT_IN
    bib_out  = args[2] if len(args) > 2 else BIB_OUT
    json_out = args[3] if len(args) > 3 else CONTENT_OUT
    main(bib_in, json_in, bib_out, json_out)

