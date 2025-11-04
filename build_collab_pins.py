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

CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "your.email@example.com").strip()
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
    "UEA": "University of East Anglia, Norwich, UK",
    "Climatic Research Unit": "University of East Anglia, Norwich, UK",
    "CEFAS": "Centre for Environment, Fisheries and Aquaculture Science, Lowestoft, UK",
    "University of Reading": "Reading, UK",
    "Dept of Meteorology, University of Reading": "Reading, UK",
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

# ---------- Nominatim geocoding ----------
def geocode(q: str) -> Optional[Tuple[float,float]]:
    q = norm_place(q)
    if not q: return None
    if q in GEOCACHE:  # exact string cache
        v = GEOCACHE[q]
        return (v["lat"], v["lon"])
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": q, "format": "jsonv2", "limit": 1}
    try:
        js = http_json(url, params=params, retry=1)
    except Exception:
        js = []
    if js:
        lat = float(js[0]["lat"]); lon = float(js[0]["lon"])
        GEOCACHE[q] = {"lat": lat, "lon": lon}
        save_cache(CACHE_GEO, GEOCACHE)
        return (lat, lon)

    # try simplified org names (drop department-level tokens)
    simple = re.sub(r'(Department|Dept\.?|School|Faculty|Institute|Center|Centre|Laboratory|Lab|Unit|Division|Group)\b.*', '', q, flags=re.I).strip(",; ")
    if simple and simple != q:
        return geocode(simple)
    return None

# ---------- ROR ----------
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
    """Return list of {name, lat, lon} or {name, ror} to resolve later."""
    out = []
    if not work: return out
    for au in work.get("authorships", []):
        for inst in au.get("institutions", []):
            name = inst.get("display_name","").strip()
            geo  = inst.get("geo") or {}
            lat, lon = geo.get("latitude"), geo.get("longitude")
            ror = (inst.get("ror") or "").strip()
            if lat is not None and lon is not None:
                city = (geo.get("city") or "")
                country = (geo.get("country") or inst.get("country_code") or "")
                label = ", ".join([x for x in [city, country] if x]) or name
                out.append({"name": label, "lat": float(lat), "lon": float(lon)})
            elif ror:
                out.append({"name": name, "ror": ror})
            elif name:
                out.append({"name": name})
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

def experience_locations(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for x in data.get("experience", []):
        org_raw = (x.get("org") or x.get("title") or "").strip()
        org = fix_typos(org_raw)
        if not org: continue

        # 1) explicit override wins
        ov = override_lookup("experience", org)
        if ov:
            g = geocode(ov)
            if g: out.append(pin(ov, f"Work – {org_raw}", *g))
            continue

        # 2) org hints (aliases)
        for alias, loc in ORG_HINTS.items():
            if alias.lower() in org.lower():
                g = geocode(loc)
                if g: out.append(pin(norm_place(loc), f"Work – {org_raw}", *g))
                break
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
        doi = norm_doi(p.get("doi","") or p.get("pdf","") or p.get("data",""))
        if not doi: continue
        title = (p.get("title") or "Publication").strip()

        # Try OpenAlex first
        work = oa_work(doi)
        insts = oa_institutions_with_geo_or_ror(work or {})

        resolved: List[Tuple[str,float,float]] = []

        # Resolve any ROR-only or name-only records
        for inst in insts:
            if "lat" in inst and "lon" in inst:
                resolved.append((inst.get("name") or "", inst["lat"], inst["lon"]))
                continue
            # ROR id present → fetch coords
            rid = inst.get("ror")
            if rid:
                rec = ror_get_by_id(rid)
                coords = ror_pick_coords(rec or {})
                if coords:
                    label, lat, lon = coords
                    resolved.append((label or (inst.get("name") or ""), lat, lon))
                    continue
            # name only → geocode
            nm = inst.get("name","")
            if nm:
                g = geocode(nm)
                if g: resolved.append((nm, g[0], g[1]))

        # If still empty, fall back to Crossref affiliations
        if not resolved:
            cr = cr_work(doi)
            affs = cr_affiliations(cr or {})
            for a in affs:
                if a.get("ror"):
                    rec = ror_get_by_id(a["ror"])
                    coords = ror_pick_coords(rec or {})
                    if coords:
                        label, lat, lon = coords
                        resolved.append((label or a["name"], lat, lon))
                        continue
                nm = a.get("name","")
                if nm:
                    g = geocode(nm)
                    if g: resolved.append((nm, g[0], g[1]))

        # de-dup city coords
        seen = set()
        for label, lat, lon in resolved:
            key = (round(lat, 4), round(lon, 4))
            if key in seen: continue
            seen.add(key)
            out.append(pin(label or "", f"Publication – {title}", lat, lon))
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
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(result)} pins → {OUT_PATH}")

if __name__ == "__main__":
    main()

