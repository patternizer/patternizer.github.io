#!/usr/bin/env python3
"""
Builds collab-pins.json for the Leaflet map from:
- content.json (Experience, Talks, Publications)
- ROR (org registry) for experience + publications affiliations
- OpenAlex (DOI → authorships → institutions → (geo, ror))
- Crossref (fallback for authors + affiliations)
- Nominatim (final fallback geocoding)

Design goals:
- Projects: DO NOT auto-locate (pins only from overrides or explicit 'place').
- Experience: robust org→city using ROR first, then geocode with heuristics.
- Publications: OpenAlex→(geo|ror) else Crossref→(ror|affiliation)->(ROR or geocode).

Caching:
  ./cache/openalex.json
  ./cache/crossref.json
  ./cache/ror.json
  ./cache/geocode.json
"""

from __future__ import annotations
import json, os, re, time, sys
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import requests

import math  # add this near other imports

# Optional jitter (off by default)

PINS_JITTER=1 # Turn on with default 25 m
PINS_JITTER_METERS=35 # Specify a radius
JITTER_METERS = float(os.environ.get("PINS_JITTER_METERS", "0") or 0.0)
JITTER_SWITCH = os.environ.get("PINS_JITTER", "").lower() in ("1","true","yes","on")

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
OVERRIDES_PATH = ROOT / "location_overrides.json"  # optional manual hints

CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "patternizer@proton.me").strip()
USER_AGENT = f"CollabPinsBuilder/2.0 ({CONTACT_EMAIL})"
SLEEP = 0.8  # polite default rate limit

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
OVERRIDES: Dict[str, Dict[str,str]] = {}
if OVERRIDES_PATH.exists():
    try: OVERRIDES = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception: OVERRIDES = {}

# ---------- utils ----------
DOI_RE = re.compile(r'10\.\d{4,9}/\S+', re.I)

ORG_HINTS = {
    # Helpful aliases (edit/extend as you wish)

	"Departamento de Fisica Teorica, Universidad Autonoma de Madrid": "Madrid, Spain",
	"Department of Physics, University of Bath": "Bath, UK",
    "Dept of Meteorology, University of Reading": "Reading, UK",
    "Department of Meteorology, University of Reading": "Reading, UK",
    "CEFAS": "Centre for Environment, Fisheries and Aquaculture Science, Lowestoft, UK",
    "CEFAS": "Lowestoft, UK",
	"Centre for Environment, Fisheries & Aquaculture Science": "CEFAS, Lowestoft, UK",    
    "Centre for Environment, Fisheries & Aquaculture Science": "Lowestoft, UK",
    "Climatic Research Unit": "University of East Anglia, Norwich, UK",
    "CRU": "Climatic Research Unit, University of East Anglia, Norwich, UK",
    "CSIC": "Consejo Superior de Investigaciones Científicas, Madrid, Spain",
	"Government Fusion Division, Culham Laboratory": "Culham, Oxford, UK",	
	"IAASARS": "Institute of Astronomy, Astrophysics, Space Applications and Remote Sensing, National Observatory of Athens, Penteli, Greece", 
	"IERSD": "Institute of Environmental Research and Sustainable Development, National Observatory of Athens, Penteli, Greece",
	"ISARS": "Institute of Space Applications and Remote Sensing, National Observatory of Athens, Penteli, Greece",
	"IOPP": "Institute of Physics Publishing, Bristol, UK",
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
    s = re.sub(r'\s+–\s+.*$', '', s)  # drop ' – blah' if present
    s = re.sub(r'\s{2,}', ' ', s).strip(" ,;-")
    return s

def norm_doi(raw: str | None) -> Optional[str]:
    if not raw:
        return None
    txt = str(raw).strip()

    # Strip common wrappers (doi:..., https://doi.org/..., etc.)
    txt = re.sub(r'^\s*doi:\s*', '', txt, flags=re.I)
    txt = re.sub(r'^https?://(dx\.)?doi\.org/', '', txt, flags=re.I)

    # Drop surrounding punctuation/brackets and any URL query/fragment
    txt = txt.strip().strip('[](){}<>\'\".,;')
    txt = re.split(r'[?#]', txt, 1)[0]

    # Find a DOI anywhere in the remaining text
    m = DOI_RE.search(txt)
    if not m:
        return None

    doi = m.group(0).rstrip(').,;')
    return doi

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
        except Exception as e:
            if attempt >= retry: raise
            time.sleep(1.5)

def _meters_to_deg(lat_deg: float, meters: float) -> Tuple[float, float]:
    """Approx convert meters to (dlat, dlon) degrees at latitude."""
    if meters <= 0:
        return (0.0, 0.0)
    dlat = meters / 111_320.0
    # protect near poles
    clat = max(0.1, math.cos(math.radians(lat_deg)))
    dlon = meters / (111_320.0 * clat)
    return (dlat, dlon)

def jitter_identical_coords(pins: List[Dict[str, Any]], meters: float = 25.0, per_ring: int = 8) -> List[Dict[str, Any]]:
    """
    For pins that share identical coordinates, spread them in small rings around
    the original point. Deterministic order (sorted by name+desc).
    """
    if meters <= 0:
        return pins

    # group indexes by exact coord tuple
    groups: Dict[Tuple[float,float], List[int]] = {}
    for i, p in enumerate(pins):
        lat, lon = p["coords"]
        groups.setdefault((lat, lon), []).append(i)

    out = [dict(p) for p in pins]  # shallow copy

    for (lat0, lon0), idxs in groups.items():
        n = len(idxs)
        if n <= 1:
            continue

        # deterministic ordering within the group
        idxs_sorted = sorted(idxs, key=lambda i: (out[i]["name"], out[i]["desc"]))

        # base step in degrees at this latitude for the requested jitter radius
        # we’ll place points on concentric rings of radius = meters * (1 + ring)
        for k, i in enumerate(idxs_sorted):
            ring = k // per_ring
            pos  = k % per_ring
            m_radius = meters * (1 + ring)  # 25m, then 50m, 75m, ...
            dlat1, dlon1 = _meters_to_deg(lat0, m_radius)

            # angle around the ring
            angle = (2 * math.pi) * (pos / per_ring)
            lat = lat0 + dlat1 * math.sin(angle)
            lon = lon0 + dlon1 * math.cos(angle)

            # keep your 5-dp convention (≈1.1 m at equator)
            out[i]["coords"] = [round(lat, 5), round(lon, 5)]

    return out

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

# Known publisher URL → DOI mappers
_MDPI_ISSN_TO_SLUG = {
    # enough for your dataset; extend anytime
    "2072-4292": "rs",  # Remote Sensing
}
def doi_from_publisher_url(u: Optional[str]) -> Optional[str]:
    if not u: return None
    u = u.strip()

    # Nature / Scientific Reports
    m = re.search(r"nature\.com\/articles\/([a-z0-9\-\._]+)", u, re.I)
    if m:
        return f"10.1038/{m.group(1)}".lower()

    # MDPI – two common path styles
    #  a) mdpi.com/<ISSN>/<vol>/<issue>/<article>
    m = re.search(r"mdpi\.com\/(\d{4}-\d{3}[\dxX])\/(\d+)\/(\d+)\/(\d+)", u, re.I)
    if m:
        issn, vol, issue, art = m.groups()
        slug = _MDPI_ISSN_TO_SLUG.get(issn, "").lower()
        if slug:
            return f"10.3390/{slug}{int(vol):d}{int(issue):02d}{int(art):d}".lower()
    #  b) mdpi.com/journal/<slug>/<vol>/<issue>/<article>
    m = re.search(r"mdpi\.com\/journal\/([a-z0-9\-]+)\/(\d+)\/(\d+)\/(\d+)", u, re.I)
    if m:
        slug, vol, issue, art = m.groups()
        return f"10.3390/{slug}{int(vol):d}{int(issue):02d}{int(art):d}".lower()

    return None

def doi_from_any_urls(urls: List[Optional[str]]) -> Optional[str]:
    for u in urls:
        # first: native DOI anywhere in string
        d = norm_doi(u or "")
        if d: return d.lower()
        # second: known publisher patterns
        d = doi_from_publisher_url(u)
        if d: return d.lower()
    return None

def openalex_find_doi_by_title(title: str, year: Optional[int] = None) -> Optional[str]:
    if not title: return None
    params = {"search": _clean(title), "per-page": 5}
    if year: params["from_publication_date"] = f"{year}-01-01"
    try:
        js = http_json("https://api.openalex.org/works", params=params, retry=1) or {}
    except Exception:
        js = {}
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
    if year:
        params["filter"] = f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31"
    try:
        js = http_json("https://api.crossref.org/works", params=params, retry=1) or {}
    except Exception:
        js = {}
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
    # 1) anything that already looks like a DOI, or derive from known publisher URLs
    doi = doi_from_any_urls([pub.get("doi"), pub.get("pdf"), pub.get("data")])
    if doi: return doi
    # 2) search by title (OpenAlex first, then Crossref)
    title = pub.get("title") or ""
    year  = pub.get("year")
    doi = openalex_find_doi_by_title(title, year)
    if doi: return doi
    return crossref_find_doi_by_title(title, year)

# ---------- Nominatim geocoding ----------
def _aff_key(name: str, ror: Optional[str]) -> str:
    if ror:
        rid = ror.strip().split("/")[-1].lower()
        return f"ror:{rid}"
    return re.sub(r"\s+", " ", (name or "").strip().lower())

def _tail_city_country(q: str) -> Optional[str]:
    parts = [p.strip() for p in q.split(",") if p.strip()]
    if len(parts) >= 2:
        tail = ", ".join(parts[-2:])  # e.g., "Norwich, UK"
        return tail
    return None

def _drop_leading_department(q: str) -> str:
    # Remove a single leading department/institute segment up to the first comma, keep the rest
    return re.sub(
        r'^(Department|Dept\.?|School|Faculty|Institute|Center|Centre|Laboratory|Lab|Unit|Division|Group)\b[^,]*,\s*',
        '',
        q,
        flags=re.I
    ).strip(",; ")

def geocode(q: str) -> Optional[Tuple[float, float]]:
    q = norm_place(q)
    if not q:
        return None

    # build candidate strings to try
    candidates = []
    def add(c):
        c = norm_place(c or "")
        if c and c not in candidates:
            candidates.append(c)

    add(q)
    add(_tail_city_country(q))
    add(_drop_leading_department(q))
    # one more: last 3 comma parts (helps things like "Culham, Oxford, UK")
    parts = [p.strip() for p in q.split(",") if p.strip()]
    if len(parts) >= 3:
        add(", ".join(parts[-3:]))

    # try each candidate until something geocodes
    for cand in candidates:
        if cand in GEOCACHE:
            v = GEOCACHE[cand]
            return (v["lat"], v["lon"])
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": cand, "format": "jsonv2", "limit": 1}
        try:
            js = http_json(url, params=params, retry=1)
        except Exception:
            js = []
        if js:
            lat = float(js[0]["lat"]); lon = float(js[0]["lon"])
            GEOCACHE[cand] = {"lat": lat, "lon": lon}
            save_cache(CACHE_GEO, GEOCACHE)
            return (lat, lon)

    return None

# ---------- ROR ----------
def resolve_by_ror_then_geocode(name: str) -> Optional[Tuple[str, float, float]]:
    if not name:
        return None
    r = ror_search(name)
    rec = None
    if r and r.get("items"):
        rec = sorted(r["items"], key=lambda z: z.get("score", 0), reverse=True)[0]
        coords = ror_pick_coords(rec or {})
        if coords:
            label, lat, lon = coords
            return (label or name, lat, lon)
    g = geocode(name)
    if g:
        return (name, g[0], g[1])
    # also try just the tail
    tail = _tail_city_country(name)
    if tail:
        g2 = geocode(tail)
        if g2:
            return (tail, g2[0], g2[1])
    return None

def ror_get_by_id(ror_id: str) -> Optional[dict]:
    rid = ror_id.strip().split('/')[-1]
    if rid in RORC: return RORC[rid]
    url = f"https://api.ror.org/organizations/{rid}"
    try:
        data = http_json(url, params={"mailto": CONTACT_EMAIL}, retry=1)
    except Exception:
        data = None
    RORC[rid] = data
    save_cache(CACHE_ROR, RORC)
    return data

def ror_search(name: str) -> Optional[dict]:
    key = f"search::{name}"
    if key in RORC: return RORC[key]
    url = "https://api.ror.org/organizations"
    try:
        data = http_json(url, params={"query": name, "mailto": CONTACT_EMAIL}, retry=1)
    except Exception:
        data = None
    RORC[key] = data
    save_cache(CACHE_ROR, RORC)
    return data

def ror_pick_coords(rec: dict) -> Optional[Tuple[str,float,float]]:
    """Return (label, lat, lon) from a ROR org record, else None."""
    if not rec: return None
    # Newer ROR payloads: try 'addresses' first
    for addr in rec.get("addresses", []):
        lat, lng = addr.get("lat"), addr.get("lng")
        city = (addr.get("geonames_city") or {}).get("city")
        country = addr.get("country_code") or addr.get("country")
        label = ", ".join([x for x in [city, country] if x])
        if lat is not None and lng is not None:
            return (label or rec.get("name",""), float(lat), float(lng))
    # Older 'locations'
    for loc in rec.get("locations", []):
        lat, lng = loc.get("lat"), loc.get("lng")
        city = (loc.get("geonames_city") or {}).get("city")
        country = loc.get("country_code") or loc.get("country")
        label = ", ".join([x for x in [city, country] if x])
        if lat is not None and lng is not None:
            return (label or rec.get("name",""), float(lat), float(lng))
    # Fallback: geocode display name with country hint
    name = rec.get("name", "")
    country = (rec.get("country") or {}).get("country_name") or rec.get("country_name")
    if name:
        g = geocode(", ".join([x for x in [name, country] if x]))
        if g: return (name, g[0], g[1])
    return None

# ---------- OpenAlex ----------
def oa_work(doi: str) -> Optional[dict]:
    if doi in OPENALEX: return OPENALEX[doi]
    urls = [
        f"https://api.openalex.org/works/doi:{doi}",
        "https://api.openalex.org/works/" + "https://doi.org/" + doi
    ]
    data = None
    for u in urls:
        try:
            data = http_json(u, params={"mailto": CONTACT_EMAIL}, retry=1)
            break
        except Exception:
            data = None
    OPENALEX[doi] = data
    save_cache(CACHE_OA, OPENALEX)
    return data

def oa_institutions_with_geo_or_ror(work: dict) -> List[dict]:
    """Return list of institution dicts: may include lat/lon and/or ror."""
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
    if doi in CROSSREF: return CROSSREF[doi]
    url = "https://api.crossref.org/works/" + doi
    try:
        data = http_json(url, params={"mailto": CONTACT_EMAIL}, retry=1)
        data = data.get("message", data)
    except Exception:
        data = None
    CROSSREF[doi] = data
    save_cache(CACHE_CR, CROSSREF)
    return data

def cr_affiliations(message: dict) -> List[dict]:
    """Return list of affiliation dicts: {name, ror?}."""
    out = []
    if not message: return out
    for au in message.get("author", []) or []:
        for aff in au.get("affiliation", []) or []:
            name = (aff.get("name") or "").strip()
            if not name: continue
            # Crossref may embed ROR id in affiliation
            rid = None
            for idobj in aff.get("id", []):
                if isinstance(idobj, dict) and "ROR" in (idobj.get("type","").upper()):
                    rid = idobj.get("value") or idobj.get("id")
                    break
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

def dbg(msg: str):
    if os.environ.get("PINS_DEBUG"):
        print(msg)

def experience_locations(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for x in data.get("experience", []):
        org_raw = (x.get("org") or x.get("title") or "").strip()
        org = fix_typos(org_raw)

        # 0) quick tail "City, Country" hint
        tail = _tail_city_country(org)
        if tail:
            g = geocode(tail)
            if g:
                out.append(pin(tail, f"Work – {org_raw}", *g))
                continue
        
        if not org: continue

        # 1) explicit override wins
        ov = override_lookup("experience", org)
        if ov:
            g = geocode(ov)
            if g: out.append(pin(ov, f"Work – {org_raw}", *g))
            continue

        # 2) org hints (aliases)
        hit = False
        for alias, loc in ORG_HINTS.items():
            if alias.lower() in org.lower():
                hit = True
                g = geocode(loc)
                if g:
                    out.append(pin(norm_place(loc), f"Work – {org_raw}", *g))
                    break  # only break if we actually appended
        if hit and (not out or out[-1]["desc"] != f"Work – {org_raw}"):
            # alias matched but failed to geocode → fall through to ROR/other
            pass
        elif hit:
            # alias succeeded → continue to next experience item
            continue
        else:
            # 3) ROR search by name (best match)
            r = ror_search(org)
            rec = None
            if r and r.get("items"):
                # pick item with highest score; prefer country if org string ends with country code
                items = sorted(r["items"], key=lambda z: z.get("score", 0), reverse=True)
                rec = items[0]
            coords = ror_pick_coords(rec or {})
            if coords:
                label, lat, lon = coords
                out.append(pin(label or org, f"Work – {org_raw}", lat, lon))
            else:
                # 4) geocode raw org with UK/USA hints if present
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
    # By request: DO NOT auto-locate projects.
    # Only use explicit overrides (or a 'place' field if you later add one).
    for p in data.get("projects", []):
        text = " ".join([p.get("title",""), p.get("desc","")])
        ov = override_lookup("projects", text)
        if ov:
            g = geocode(ov)
            if g: out.append(pin(ov, f"Project – {p.get('title','Project')}", *g))
        elif p.get("place"):  # optional support
            place = norm_place(p["place"])
            g = geocode(place)
            if g: out.append(pin(place, f"Project – {p.get('title','Project')}", *g))
    return out

def publications_locations(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for p in data.get("publications", []):

        doi = best_doi_for_pub(p)
        if not doi:
            dbg(f"[pub] no DOI for '{p.get('title','(untitled)')}' — skipping")
            continue
            
        title = (p.get("title") or "Publication").strip()
        pin_desc = f"Publication – {title}"

        # ---- collect candidates from OpenAlex
        insts = oa_institutions_with_geo_or_ror(oa_work(doi) or {})

        # ---- also collect candidates from Crossref (always union, not fallback)
        cr = cr_work(doi)
        if cr:
            for a in cr_affiliations(cr):
                nm = a.get("name","").strip()
                rid = a.get("ror")
                if nm or rid:
                    insts.append({"name": nm, "ror": rid})

        # ---- resolve to coords + dedupe by affiliation identity (ROR or name)
        seen_aff = set()
        pins_for_paper: List[Dict[str, Any]] = []

        for inst in insts:
            nm  = inst.get("name","").strip()
            rid = (inst.get("ror") or "").strip() or None
            lat = inst.get("lat"); lon = inst.get("lon")
            city = inst.get("city","") or None
            country = inst.get("country","") or None

            # a) if we already have coordinates from OA
            if lat is not None and lon is not None:
                key = _aff_key(nm or (city or "") , rid)
                if key in seen_aff:
                    continue
                seen_aff.add(key)
                label_city = ", ".join([c for c in [city, country] if c]) or ""
                pin_name = nm if nm else (label_city or "Affiliation")
                if label_city and nm:
                    pin_name = f"{nm} — {label_city}"
                pins_for_paper.append(pin(pin_name, pin_desc, lat, lon))
                continue

            # b) resolve via ROR id if present
            if rid:
                rec = ror_get_by_id(rid)
                coords = ror_pick_coords(rec or {})
                if coords:
                    label_city, la, lo = coords
                    key = _aff_key(nm or (rec or {}).get("name",""), rid)
                    if key in seen_aff:
                        continue
                    seen_aff.add(key)
                    base_nm = nm or (rec or {}).get("name","") or label_city or "Affiliation"
                    pin_name = base_nm
                    if label_city and base_nm not in label_city:
                        pin_name = f"{base_nm} — {label_city}"
                    pins_for_paper.append(pin(pin_name, pin_desc, la, lo))
                    continue
                # fall through to name resolution if coords not found

            # c) resolve by ROR search then geocode (name-only)
            if nm:
                rr = resolve_by_ror_then_geocode(nm)
                if rr:
                    label_city, la, lo = rr[0], rr[1], rr[2]
                    # try to discover a ROR id now (improves dedupe)
                    rs = ror_search(nm) or {}
                    rid2 = None
                    if rs.get("items"):
                        rid2 = (rs["items"][0].get("id") or "").strip() or None
                    key = _aff_key(nm, rid2)
                    if key in seen_aff:
                        continue
                    seen_aff.add(key)
                    pin_name = nm
                    if label_city and nm not in label_city:
                        pin_name = f"{nm} — {label_city}"
                    pins_for_paper.append(pin(pin_name, pin_desc, la, lo))

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
    exp = experience_locations(data); print(f"  +{len(exp)}")
    all_pins += exp

    print("Talks → place / geocode …")
    tks = talks_locations(data); print(f"  +{len(tks)}")
    all_pins += tks

    print("Projects → overrides only …")
    prj = projects_locations(data); print(f"  +{len(prj)}")
    all_pins += prj

    print("Publications → OpenAlex → (ROR|geo) → Crossref fallback …")
    pubs = publications_locations(data); print(f"  +{len(pubs)}")
    all_pins += pubs

    result = dedupe_pins(all_pins)

    # Optional jitter: on if PINS_JITTER_METERS>0, or if PINS_JITTER=true (uses 25 m)
    if JITTER_METERS > 0 or JITTER_SWITCH:
        jitter_radius = JITTER_METERS if JITTER_METERS > 0 else 25.0
        result = jitter_identical_coords(result, meters=jitter_radius, per_ring=8)

    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(result)} pins → {OUT_PATH}")

if __name__ == "__main__":
    main()

