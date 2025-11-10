#!/usr/bin/env python3
"""
Builds collab-pins.json for the Leaflet map from:
- content.json (Experience, Talks, Publications)
- ROR (org registry) for experience + publications affiliations
- OpenAlex (DOI → authorships → institutions → (geo, ror))
- Crossref (union with OpenAlex; can be disabled)
- Nominatim (final fallback geocoding)

Speed-ups:
- Affiliation cache (cache/affiliations.json)
- Optional Crossref union off: PINS_USE_CROSSREF=0
- Fast mode (geocode-first for name-only): PINS_FAST=1

Optional jitter:
- PINS_JITTER=1 (25 m) or PINS_JITTER_METERS=35

Debug:
- PINS_DEBUG=1
"""

from __future__ import annotations
import json, os, re, time, sys, math
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import requests

# ---------- toggles ----------
JITTER_METERS = float(os.environ.get("PINS_JITTER_METERS", "0") or 0.0)
JITTER_SWITCH = os.environ.get("PINS_JITTER", "").lower() in ("1","true","yes","on")
USE_CROSSREF  = os.environ.get("PINS_USE_CROSSREF", "1").lower() in ("1","true","yes","on")
FAST_MODE     = os.environ.get("PINS_FAST", "").lower() in ("1","true","yes","on")

# ---------- paths & config ----------
ROOT = Path(__file__).resolve().parent
CONTENT_PATH = ROOT / "content.json"
OUT_PATH = ROOT / "collab-pins.json"
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)

CACHE_OA   = CACHE_DIR / "openalex.json"
CACHE_CR   = CACHE_DIR / "crossref.json"
CACHE_ROR  = CACHE_DIR / "ror.json"
CACHE_GEO  = CACHE_DIR / "geocode.json"
CACHE_AFF  = CACHE_DIR / "affiliations.json"
OVERRIDES_PATH = ROOT / "location_overrides.json"  # optional manual hints

CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "patternizer@proton.me").strip()
USER_AGENT = f"CollabPinsBuilder/2.1 ({CONTACT_EMAIL})"
SLEEP = 0.8  # polite default rate limit (applies only to real HTTP calls)

# ---------- caches ----------
def load_cache(p: Path) -> Dict[str, Any]:
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}

def save_cache(p: Path, data: Dict[str, Any]) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)

OPENALEX = load_cache(CACHE_OA)
CROSSREF = load_cache(CACHE_CR)
RORC     = load_cache(CACHE_ROR)
GEOCACHE = load_cache(CACHE_GEO)
AFFC     = load_cache(CACHE_AFF)

OVERRIDES: Dict[str, Dict[str,str]] = {}
if OVERRIDES_PATH.exists():
    try: OVERRIDES = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception: OVERRIDES = {}

# ---------- utils ----------
DOI_RE = re.compile(r'10\.\d{4,9}/\S+', re.I)

ORG_HINTS = {
    "Departamento de Fisica Teorica, Universidad Autonoma de Madrid": "Madrid, Spain",
    "Department of Physics, University of Bath": "Bath, UK",
    "Dept of Meteorology, University of Reading": "Reading, UK",
    "Department of Meteorology, University of Reading": "Reading, UK",
    "CEFAS": "Lowestoft, UK",
    "Centre for Environment, Fisheries & Aquaculture Science": "Lowestoft, UK",
    "Climatic Research Unit": "University of East Anglia, Norwich, UK",
    "CRU": "Climatic Research Unit, University of East Anglia, Norwich, UK",
    "CSIC": "Consejo Superior de Investigaciones Científicas, Madrid, Spain",
    "Government Fusion Division, Culham Laboratory": "Culham, Oxford, UK",
    "IAASARS": "Institute of Astronomy, Astrophysics, Space Applications and Remote Sensing, National Observatory of Athens, Penteli, Greece",
    "IERSD": "Institute of Environmental Research and Sustainable Development, National Observatory of Athens, Penteli, Greece",
    "ISARS": "Institute of Space Applications and Remote Sensing, National Observatory of Athens, Penteli, Greece",
    "IOPP": "Bristol, UK",
    "Institute of Physics Publishing": "Bristol, UK",
    "Laboratory of Atmospheric Physics, Aristotle University of Thessaloniki": "Thessaloniki, Greece",
    "National Observatory of Athens": "Penteli, Greece",
    "NOA": "National Observatory of Athens, Penteli, Greece",
    "Space & Atmospheric Physics Group, Blackett Laboratory, Imperial College": "London, UK",
    "Spanish National Research Council": "Madrid, Spain",
    "University of Reading": "Reading, UK",
    "University of Saint Andrews": "Saint Andrews, UK",
    "University of St. Andrews": "Saint Andrews, UK",
    "University of St Andrews": "Saint Andrews, UK",
    "UAM": "Universidad Autonoma de Madrid, Madrid, Spain",
    "UEA": "University of East Anglia, Norwich, UK"
}

TYPO_FIXES = (
    (re.compile(r"\bUnivesity\b", re.I), "University"),
)

def fix_typos(s: str) -> str:
    t = s
    for rx, rep in TYPO_FIXES:
        t = rx.sub(rep, t)
    return t

def norm_place(s: str) -> str:
    s = fix_typos((s or "").strip())
    s = re.sub(r'\(online\)|online-only|virtual', '', s, flags=re.I)
    s = re.sub(r'\s+–\s+.*$', '', s)
    s = re.sub(r'\s{2,}', ' ', s).strip(" ,;-")
    return s

def norm_doi(raw: str | None) -> Optional[str]:
    if not raw:
        return None
    txt = str(raw).strip()
    txt = re.sub(r'^\s*doi:\s*', '', txt, flags=re.I)
    txt = re.sub(r'^https?://(dx\.)?doi\.org/', '', txt, flags=re.I)
    txt = txt.strip().strip('[](){}<>\'\".,;')
    txt = re.split(r'[?#]', txt, 1)[0]
    m = DOI_RE.search(txt)
    if not m:
        return None
    return m.group(0).rstrip(').,;')

def pin(name: str, desc: str, lat: float, lon: float) -> Dict[str, Any]:
    return {"name": name, "desc": desc, "coords": [round(float(lat), 5), round(float(lon), 5)]}

def unique_key(p: Dict[str, Any]) -> str:
    return f"{p['name']}|{p['desc']}|{p['coords'][0]}|{p['coords'][1]}"

def sleep(s=SLEEP): time.sleep(s)

def http_json(url: str, params: Dict[str, Any] | None = None, retry=1) -> Any:
    headers = {"User-Agent": USER_AGENT}
    if CONTACT_EMAIL and "mailto" not in (params or {}):
        params = dict(params or {}, mailto=CONTACT_EMAIL)
    for attempt in range(retry+1):
        try:
            sleep()
            r = requests.get(url, params=params, timeout=25, headers=headers)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt >= retry: raise
            time.sleep(1.5)

def dbg(msg: str):
    if os.environ.get("PINS_DEBUG"):
        print(msg)

# ---------- jitter ----------
def _meters_to_deg(lat_deg: float, meters: float) -> Tuple[float, float]:
    if meters <= 0: return (0.0, 0.0)
    dlat = meters / 111_320.0
    clat = max(0.1, math.cos(math.radians(lat_deg)))
    dlon = meters / (111_320.0 * clat)
    return (dlat, dlon)

def jitter_identical_coords(pins: List[Dict[str, Any]], meters: float = 25.0, per_ring: int = 8) -> List[Dict[str, Any]]:
    if meters <= 0: return pins
    groups: Dict[Tuple[float,float], List[int]] = {}
    for i, p in enumerate(pins):
        lat, lon = p["coords"]
        groups.setdefault((lat, lon), []).append(i)
    out = [dict(p) for p in pins]
    for (lat0, lon0), idxs in groups.items():
        if len(idxs) <= 1: continue
        idxs_sorted = sorted(idxs, key=lambda i: (out[i]["name"], out[i]["desc"]))
        for k, i in enumerate(idxs_sorted):
            ring = k // per_ring
            pos  = k % per_ring
            m_radius = meters * (1 + ring)
            dlat1, dlon1 = _meters_to_deg(lat0, m_radius)
            angle = (2 * math.pi) * (pos / per_ring)
            lat = lat0 + dlat1 * math.sin(angle)
            lon = lon0 + dlon1 * math.cos(angle)
            out[i]["coords"] = [round(lat, 5), round(lon, 5)]
    return out

# ---------- DOI inference & title search ----------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

_MDPI_ISSN_TO_SLUG = {"2072-4292": "rs"}  # Remote Sensing

def doi_from_publisher_url(u: Optional[str]) -> Optional[str]:
    if not u: return None
    u = u.strip()
    m = re.search(r"nature\.com\/articles\/([a-z0-9\-\._]+)", u, re.I)
    if m: return f"10.1038/{m.group(1)}".lower()
    m = re.search(r"mdpi\.com\/(\d{4}-\d{3}[\dxX])\/(\d+)\/(\d+)\/(\d+)", u, re.I)
    if m:
        issn, vol, issue, art = m.groups()
        slug = _MDPI_ISSN_TO_SLUG.get(issn, "").lower()
        if slug: return f"10.3390/{slug}{int(vol):d}{int(issue):02d}{int(art):d}".lower()
    m = re.search(r"mdpi\.com\/journal\/([a-z0-9\-]+)\/(\d+)\/(\d+)\/(\d+)", u, re.I)
    if m:
        slug, vol, issue, art = m.groups()
        return f"10.3390/{slug}{int(vol):d}{int(issue):02d}{int(art):d}".lower()
    return None

def doi_from_any_urls(urls: List[Optional[str]]) -> Optional[str]:
    for u in urls:
        d = norm_doi(u or "")
        if d: return d.lower()
        d = doi_from_publisher_url(u)
        if d: return d.lower()
    return None

def openalex_find_doi_by_title(title: str, year: Optional[int] = None) -> Optional[str]:
    if not title: return None
    params = {"search": _clean(title), "per_page": 5}
    if year: params["from_publication_date"] = f"{year}-01-01"
    try: js = http_json("https://api.openalex.org/works", params=params, retry=1) or {}
    except Exception: js = {}
    items = js.get("results") or []
    t_norm = _clean(title).casefold()
    best = None
    for it in items:
        ititle = _clean((it.get("title") or ""))
        if ititle and ititle.casefold() == t_norm and it.get("doi"):
            return it["doi"].replace("https://doi.org/","").lower()
        if not best and it.get("doi"):
            best = it["doi"].replace("https://doi.org/","").lower()
    return best

def crossref_find_doi_by_title(title: str, year: Optional[int] = None) -> Optional[str]:
    if not title: return None
    params = {"query.title": _clean(title), "rows": 5}
    if year: params["filter"] = f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31"
    try: js = http_json("https://api.crossref.org/works", params=params, retry=1) or {}
    except Exception: js = {}
    items = (js.get("message") or {}).get("items") or []
    t_norm = _clean(title).casefold()
    best = None
    for it in items:
        ititle = _clean((it.get("title") or [""])[0])
        doi = (it.get("DOI") or "").lower()
        if ititle and ititle.casefold() == t_norm and doi:
            return doi
        if not best and doi:
            best = doi
    return best

def best_doi_for_pub(pub: Dict[str, Any]) -> Optional[str]:
    doi = doi_from_any_urls([pub.get("doi"), pub.get("pdf"), pub.get("data")])
    if doi: return doi
    title = pub.get("title") or ""
    year  = pub.get("year")
    doi = openalex_find_doi_by_title(title, year)
    if doi: return doi
    return crossref_find_doi_by_title(title, year)

# ---------- geocoding helpers ----------
def _tail_city_country(q: str) -> Optional[str]:
    parts = [p.strip() for p in q.split(",") if p.strip()]
    parts = [p for p in parts if not re.fullmatch(r'[\d\-\s]+', p)]  # drop postcodes
    if len(parts) >= 2:
        return ", ".join(parts[-2:])
    return None

def _drop_leading_department(q: str) -> str:
    return re.sub(
        r'^(Department|Dept\.?|School|Faculty|Institute|Center|Centre|Laboratory|Lab|Unit|Division|Group)\b[^,]*,\s*',
        '', q, flags=re.I
    ).strip(",; ")

def geocode(q: str) -> Optional[Tuple[float, float]]:
    q = norm_place(q)
    if not q: return None
    candidates = []
    def add(c):
        c = norm_place(c or "")
        if c and c not in candidates: candidates.append(c)
    add(q)
    add(_tail_city_country(q))
    add(_drop_leading_department(q))
    parts = [p.strip() for p in q.split(",") if p.strip()]
    if len(parts) >= 3:
        add(", ".join(parts[-3:]))
    for cand in candidates:
        if cand in GEOCACHE:
            v = GEOCACHE[cand]; return (v["lat"], v["lon"])
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": cand, "format": "jsonv2", "limit": 1}
        try: js = http_json(url, params=params, retry=1)
        except Exception: js = []
        if js:
            lat = float(js[0]["lat"]); lon = float(js[0]["lon"])
            GEOCACHE[cand] = {"lat": lat, "lon": lon}
            save_cache(CACHE_GEO, GEOCACHE)
            return (lat, lon)
    return None

# ---------- affiliation normalization ----------
_AFF_PRI_KEYWORDS = r"(University|Institute|Academy|Authority|Observatory|Laborator(?:y|ies)|Center|Centre|College|School)"
AFF_HINTS = (
    (re.compile(r"\bNREA\b", re.I), "New and Renewable Energy Authority, Cairo, Egypt"),
    (re.compile(r"\bAlexandria University\b", re.I), "Alexandria University, Alexandria, Egypt"),
    (re.compile(r"\bWuhan University\b", re.I), "Wuhan University, Wuhan, China"),
)

def simplify_aff_name(name: str) -> str:
    s = fix_typos(name or "")
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\b\d{3,}\b", "", s)  # postcodes
    s = re.sub(r"\b\d+\s+[A-Za-z\.\- ]+\b(Road|Rd|Street|St|Avenue|Ave|Boulevard|Blvd|Way|Lane|Ln|Drive|Dr|Highway|Hwy)\b[^,;]*", "", s, flags=re.I)
    parts = [p.strip() for p in re.split(r"[;,]", s) if p.strip()]
    if not parts: return (name or "").strip()
    for p in parts:
        if re.search(_AFF_PRI_KEYWORDS, p, re.I): return p
    for p in parts:
        if re.search(r"[A-Za-z]{3,}", p) and not re.search(r"\d", p): return p
    return parts[0]

# ---------- affiliation cache ----------
def _aff_key(name: str, ror: Optional[str]) -> str:
    if ror:
        rid = ror.strip().split("/")[-1].lower()
        return f"ror:{rid}"
    return "name:" + re.sub(r"\s+", " ", (name or "").strip().lower())

def affcache_get(name: str, ror: Optional[str]) -> Optional[Tuple[str,float,float]]:
    key = _aff_key(name, ror)
    rec = AFFC.get(key)
    if rec and all(k in rec for k in ("label","lat","lon")):
        return (rec["label"], rec["lat"], rec["lon"])
    return None

def affcache_put(name: str, ror: Optional[str], label: str, lat: float, lon: float) -> None:
    key = _aff_key(name, ror)
    AFFC[key] = {"label": label, "lat": float(lat), "lon": float(lon)}
    save_cache(CACHE_AFF, AFFC)

# ---------- ROR ----------
def ror_get_by_id(ror_id: str) -> Optional[dict]:
    rid = ror_id.strip().split('/')[-1]
    if rid in RORC and RORC[rid] is not None: return RORC[rid]
    url = f"https://api.ror.org/organizations/{rid}"
    try: data = http_json(url, params={"mailto": CONTACT_EMAIL}, retry=1)
    except Exception: data = None
    if data is not None:
        RORC[rid] = data; save_cache(CACHE_ROR, RORC)
    return data

def ror_search(name: str) -> Optional[dict]:
    key = f"search::{name}"
    if key in RORC and RORC[key] is not None: return RORC[key]
    url = "https://api.ror.org/organizations"
    try: data = http_json(url, params={"query": name, "mailto": CONTACT_EMAIL}, retry=1)
    except Exception: data = None
    if data is not None:
        RORC[key] = data; save_cache(CACHE_ROR, RORC)
    return data

def ror_pick_coords(rec: dict) -> Optional[Tuple[str,float,float]]:
    if not rec: return None
    for addr in rec.get("addresses", []):
        lat, lng = addr.get("lat"), addr.get("lng")
        city = (addr.get("geonames_city") or {}).get("city")
        country = addr.get("country_code") or addr.get("country")
        label = ", ".join([x for x in [city, country] if x])
        if lat is not None and lng is not None:
            return (label or rec.get("name",""), float(lat), float(lng))
    for loc in rec.get("locations", []):
        lat, lng = loc.get("lat"), loc.get("lng")
        city = (loc.get("geonames_city") or {}).get("city")
        country = loc.get("country_code") or loc.get("country")
        label = ", ".join([x for x in [city, country] if x])
        if lat is not None and lng is not None:
            return (label or rec.get("name",""), float(lat), float(lng))
    name = rec.get("name", "")
    country = (rec.get("country") or {}).get("country_name") or rec.get("country_name")
    if name:
        g = geocode(", ".join([x for x in [name, country] if x]))
        if g: return (name, g[0], g[1])
    return None

def resolve_by_ror_then_geocode(name: str) -> Optional[Tuple[str, float, float]]:
    if not name: return None

    # explicit hints
    for rx, rep in AFF_HINTS:
        if rx.search(name):
            g = geocode(rep)
            if g: return (rep, g[0], g[1])

    core = simplify_aff_name(name)
    tail = _tail_city_country(name) or _tail_city_country(core)

    # FAST mode: try geocoding first, then ROR
    if FAST_MODE:
        for cand in (", ".join([x for x in [core, tail] if x]), core, tail, name):
            if not cand: continue
            g = geocode(cand)
            if g: return (cand, g[0], g[1])

    # ROR first (default path)
    for q in (name, core):
        r = ror_search(q)
        if r and r.get("items"):
            rec = sorted(r["items"], key=lambda z: z.get("score", 0), reverse=True)[0]
            coords = ror_pick_coords(rec or {})
            if coords:
                label, lat, lon = coords
                return (label or (rec or {}).get("name") or core or name, lat, lon)

    # geocode if ROR didn't yield
    for cand in (", ".join([x for x in [core, tail] if x]), core, tail, name):
        if not cand: continue
        g = geocode(cand)
        if g: return (cand, g[0], g[1])

    return None

# ---------- OpenAlex ----------
def oa_work(doi: str) -> Optional[dict]:
    if doi in OPENALEX and OPENALEX[doi] is not None:
        return OPENALEX[doi]
    urls = [f"https://api.openalex.org/works/doi:{doi}",
            "https://api.openalex.org/works/" + "https://doi.org/" + doi]
    data = None
    for u in urls:
        try:
            data = http_json(u, params={"mailto": CONTACT_EMAIL}, retry=1)
            if data: break
        except Exception:
            data = None
    if data is not None:
        OPENALEX[doi] = data; save_cache(CACHE_OA, OPENALEX)
    return data

def oa_institutions_with_geo_or_ror(work: dict) -> List[dict]:
    out = []
    if not work: return out
    for au in work.get("authorships", []):
        for inst in au.get("institutions", []):
            name = (inst.get("display_name") or "").strip()
            ror  = (inst.get("ror") or "").strip()
            geo  = inst.get("geo") or {}
            lat, lon = geo.get("latitude"), geo.get("longitude")
            city = (geo.get("city") or "")
            country = (geo.get("country") or inst.get("country_code") or "")
            rec = {"name": name, "ror": ror, "city": city, "country": country}
            if lat is not None and lon is not None:
                rec["lat"] = float(lat); rec["lon"] = float(lon)
            out.append(rec)
    return out

# ---------- Crossref ----------
def cr_work(doi: str) -> Optional[dict]:
    if doi in CROSSREF and CROSSREF[doi] is not None:
        return CROSSREF[doi]
    url = "https://api.crossref.org/works/" + doi
    try:
        data = http_json(url, params={"mailto": CONTACT_EMAIL}, retry=1)
        data = data.get("message", data)
    except Exception:
        data = None
    if data is not None:
        CROSSREF[doi] = data; save_cache(CACHE_CR, CROSSREF)
    return data

def cr_affiliations(message: dict) -> List[dict]:
    out = []
    if not message: return out
    for au in message.get("author", []) or []:
        for aff in au.get("affiliation", []) or []:
            name = (aff.get("name") or "").strip()
            if not name: continue
            rid = None
            for idobj in aff.get("id", []) or []:
                if isinstance(idobj, dict) and "ROR" in (idobj.get("type","").upper()):
                    rid = idobj.get("value") or idobj.get("id"); break
            out.append({"name": name, "ror": rid} if rid else {"name": name})
    return out

# ---------- extractors from content.json ----------
def load_content() -> Dict[str, Any]:
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))

def override_lookup(section: str, needle: str) -> Optional[str]:
    for kw, loc in OVERRIDES.get(section, {}).items():
        if kw.lower() in (needle or "").lower():
            return norm_place(loc)
    return None

# ---------- sections ----------
def experience_locations(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for x in data.get("experience", []):
        org_raw = (x.get("org") or x.get("title") or "").strip()
        org = fix_typos(org_raw)
        tail = _tail_city_country(org)
        if tail:
            g = geocode(tail)
            if g: out.append(pin(tail, f"Work – {org_raw}", *g)); continue
        if not org: continue
        ov = override_lookup("experience", org)
        if ov:
            g = geocode(ov)
            if g: out.append(pin(ov, f"Work – {org_raw}", *g)); continue
        hit = False
        for alias, loc in ORG_HINTS.items():
            if alias.lower() in org.lower():
                hit = True; g = geocode(loc)
                if g: out.append(pin(norm_place(loc), f"Work – {org_raw}", *g)); break
        if hit and (not out or out[-1]["desc"] != f"Work – {org_raw}"):
            pass
        elif hit:
            continue
        else:
            r = ror_search(org); rec = None
            if r and r.get("items"):
                items = sorted(r["items"], key=lambda z: z.get("score", 0), reverse=True)
                rec = items[0]
            coords = ror_pick_coords(rec or {})
            if coords:
                label, lat, lon = coords
                out.append(pin(label or org, f"Work – {org_raw}", lat, lon))
            else:
                org_q = org
                if re.search(r'\bUK\b', org, re.I): org_q = org + ", United Kingdom"
                if re.search(r'\bUSA|US\b', org, re.I): org_q = org + ", United States"
                g = geocode(org_q)
                if g: out.append(pin(org_q, f"Work – {org_raw}", *g))
    return out

def talks_locations(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for t in data.get("talks", []):
        place = norm_place(t.get("place",""))
        if not place or "online" in place.lower(): continue
        ov = override_lookup("talks", (t.get("title","") + " " + place))
        if ov: place = ov
        g = geocode(place)
        if g: out.append(pin(place, f"Talk – {t.get('title','Talk')}", *g))
    return out

def projects_locations(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for p in data.get("projects", []):
        text = " ".join([p.get("title",""), p.get("desc","")])
        ov = override_lookup("projects", text)
        if ov:
            g = geocode(ov)
            if g: out.append(pin(ov, f"Project – {p.get('title','Project')}", *g))
        elif p.get("place"):
            place = norm_place(p["place"])
            g = geocode(place)
            if g: out.append(pin(place, f"Project – {p.get('title','Project')}", *g))
    return out

# ---------- publications ----------
def publications_locations(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for p in data.get("publications", []):
        doi = best_doi_for_pub(p)
        title = (p.get("title") or "Publication").strip()
        if not doi:
            dbg(f"[pub] no DOI for '{title}'"); continue
        pin_desc = f"Publication – {title}"
        dbg(f"[pub] {title} → DOI {doi}")

        # OpenAlex affiliations
        insts = oa_institutions_with_geo_or_ror(oa_work(doi) or {})

        # Crossref union (optional or fallback)
        if USE_CROSSREF:
            cr = cr_work(doi)
            if cr:
                insts += [{"name": a.get("name","").strip(), "ror": a.get("ror")} for a in cr_affiliations(cr)]
        else:
            if not insts:  # if OA empty, still try Crossref as fallback
                cr = cr_work(doi)
                if cr:
                    insts += [{"name": a.get("name","").strip(), "ror": a.get("ror")} for a in cr_affiliations(cr)]

        dbg(f"[pub] {title}: {len(insts)} raw affiliations")

        seen_aff = set()
        pins_for_paper: List[Dict[str, Any]] = []

        for inst in insts:
            nm  = (inst.get("name") or "").strip()
            rid = (inst.get("ror") or "").strip() or None
            lat = inst.get("lat"); lon = inst.get("lon")
            city = inst.get("city","") or None
            country = inst.get("country","") or None

            # ---- A) Already got coords from OA
            if lat is not None and lon is not None:
                key = _aff_key(nm or (city or ""), rid)
                if key in seen_aff: continue
                seen_aff.add(key)
                label_city = ", ".join([c for c in [city, country] if c]) or ""
                pin_name = nm if nm else (label_city or "Affiliation")
                if label_city and nm:
                    pin_name = f"{nm} — {label_city}"
                pins_for_paper.append(pin(pin_name, pin_desc, lat, lon))
                # store in affiliation cache
                affcache_put(nm or label_city or "Affiliation", rid, pin_name, lat, lon)
                continue

            # ---- B) Check affiliation cache
            cached = affcache_get(nm, rid)
            if cached:
                label_city, la, lo = cached
                key = _aff_key(nm, rid)
                if key not in seen_aff:
                    seen_aff.add(key)
                    pin_name = nm or label_city or "Affiliation"
                    if label_city and nm and nm not in label_city:
                        pin_name = f"{nm} — {label_city}"
                    pins_for_paper.append(pin(pin_name, pin_desc, la, lo))
                continue

            # ---- C) Resolve via ROR id
            if rid:
                rec = ror_get_by_id(rid)
                coords = ror_pick_coords(rec or {})
                if coords:
                    label_city, la, lo = coords
                    key = _aff_key(nm or (rec or {}).get("name",""), rid)
                    if key not in seen_aff:
                        seen_aff.add(key)
                        base_nm = nm or (rec or {}).get("name","") or label_city or "Affiliation"
                        pin_name = base_nm
                        if label_city and base_nm not in label_city:
                            pin_name = f"{base_nm} — {label_city}"
                        pins_for_paper.append(pin(pin_name, pin_desc, la, lo))
                        affcache_put(nm or base_nm, rid, label_city or base_nm, la, lo)
                    continue
                # fall through if ROR had no coords

            # ---- D) Name-only: resolve (fast geocode-first if FAST_MODE)
            if nm:
                rr = resolve_by_ror_then_geocode(nm)
                if rr:
                    label_city, la, lo = rr
                    key = _aff_key(nm, None)
                    if key not in seen_aff:
                        seen_aff.add(key)
                        pin_name = nm
                        if label_city and nm not in label_city:
                            pin_name = f"{nm} — {label_city}"
                        pins_for_paper.append(pin(pin_name, pin_desc, la, lo))
                        affcache_put(nm, None, label_city or nm, la, lo)

        out.extend(pins_for_paper)

    return out

# ---------- assemble + dedupe ----------
def dedupe_pins(pins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {}
    for p in pins: seen[unique_key(p)] = p
    return list(seen.values())

# ---------- main ----------
def main():
    if not CONTENT_PATH.exists():
        print(f"ERROR: {CONTENT_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    print("Reading content.json …")
    data = load_content()
    all_pins: List[Dict[str, Any]] = []

    print("Experience → ROR / geocode …")
    exp = experience_locations(data); print(f"  +{len(exp)}"); all_pins += exp

    print("Talks → place / geocode …")
    tks = talks_locations(data); print(f"  +{len(tks)}"); all_pins += tks

    print("Projects → overrides only …")
    prj = projects_locations(data); print(f"  +{len(prj)}"); all_pins += prj

    print("Publications → OpenAlex (+ Crossref) → (ROR|geo) …")
    pubs = publications_locations(data); print(f"  +{len(pubs)}"); all_pins += pubs

    result = dedupe_pins(all_pins)

    if JITTER_METERS > 0 or JITTER_SWITCH:
        jitter_radius = JITTER_METERS if JITTER_METERS > 0 else 25.0
        result = jitter_identical_coords(result, meters=jitter_radius, per_ring=8)

    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(result)} pins → {OUT_PATH}")

if __name__ == "__main__":
    main()

