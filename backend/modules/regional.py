"""
Modulo C — Portali Regionali VIA/VAS
Connettori normalizzati per i portali regionali italiani.
Ogni regione ha struttura diversa — questo modulo normalizza tutto.
"""
import httpx
import asyncio
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class RegionalProcedure:
    region: str
    proc_id: str
    title: str
    proponent: str
    status: str
    type: str           # VIA/VAS/AIA
    url: str
    last_update: str = ""
    prescriptions: str = ""

# ── REGION REGISTRY ───────────────────────────────────────────────────────────
# Maps Italian regions to their VIA portal endpoints
REGIONAL_PORTALS = {
    "campania": {
        "name": "Campania",
        "url": "https://www.regione.campania.it/regione/it/tematiche/portale-via",
        "wfs": "https://sit.regione.campania.it/geoserver/wfs",
        "search_url": "https://www.regione.campania.it/regione/it/tematiche/portale-via?page=ricerca",
        "type": "html"
    },
    "lombardia": {
        "name": "Lombardia",
        "url": "https://www.silvia.regione.lombardia.it",
        "api": "https://www.silvia.regione.lombardia.it/silvia/api/v1/procedures",
        "type": "api"
    },
    "toscana": {
        "name": "Toscana",
        "url": "https://www.regione.toscana.it/via",
        "search_url": "https://www.regione.toscana.it/via/ricerca",
        "type": "html"
    },
    "veneto": {
        "name": "Veneto",
        "url": "https://www.regione.veneto.it/web/vas-via-aia-ippc",
        "type": "html"
    },
    "lazio": {
        "name": "Lazio",
        "url": "https://www.regione.lazio.it/rl/via",
        "type": "html"
    },
    "sicilia": {
        "name": "Sicilia",
        "url": "https://www.regione.sicilia.it/la-regione-informa/valutazione-impatto-ambientale",
        "type": "html"
    },
    "puglia": {
        "name": "Puglia",
        "url": "https://www.regione.puglia.it/web/ecologia-e-ambiente/via",
        "type": "html"
    },
    "emilia-romagna": {
        "name": "Emilia-Romagna",
        "url": "https://ambiente.regione.emilia-romagna.it/it/valutazioni-ambientali",
        "type": "html"
    },
    "piemonte": {
        "name": "Piemonte",
        "url": "https://www.regione.piemonte.it/web/temi/ambiente-territorio/valutazione-impatto-ambientale-via",
        "type": "html"
    },
    "calabria": {
        "name": "Calabria",
        "url": "https://www.regione.calabria.it/website/organizzazione/dipartimento4/subsite/via/",
        "type": "html"
    }
}

# ── COORDINATE TO REGION ──────────────────────────────────────────────────────

def coords_to_region(lat: float, lon: float) -> str:
    """Approximate region from coordinates — deterministic lookup"""
    regions = [
        ("valle-d-aosta", 45.7, 46.0, 6.8, 7.9),
        ("piemonte", 44.0, 46.5, 6.6, 9.2),
        ("lombardia", 44.6, 46.7, 8.5, 11.4),
        ("trentino", 45.6, 47.1, 10.4, 12.5),
        ("veneto", 44.7, 46.7, 10.6, 13.1),
        ("friuli", 45.5, 46.7, 12.3, 13.9),
        ("liguria", 43.7, 44.7, 7.5, 10.1),
        ("emilia-romagna", 43.7, 45.1, 9.2, 12.8),
        ("toscana", 42.3, 44.5, 9.6, 12.4),
        ("umbria", 42.4, 43.6, 11.9, 13.3),
        ("marche", 42.7, 43.9, 12.3, 13.9),
        ("lazio", 41.2, 42.8, 11.4, 13.9),
        ("abruzzo", 41.7, 42.9, 13.0, 14.8),
        ("molise", 41.3, 42.1, 14.0, 15.2),
        ("campania", 39.9, 41.5, 14.0, 15.8),
        ("puglia", 39.8, 41.9, 15.0, 18.5),
        ("basilicata", 39.9, 41.1, 15.3, 16.9),
        ("calabria", 37.9, 40.1, 15.6, 16.6),
        ("sicilia", 36.6, 38.3, 12.4, 15.7),
        ("sardegna", 38.8, 41.3, 8.1, 9.8),
    ]
    for name, lat_min, lat_max, lon_min, lon_max in regions:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return "lazio"  # default

# ── REGIONAL CONNECTORS ───────────────────────────────────────────────────────

async def get_lombardia_procedures(keyword: str = "", limit: int = 5) -> list:
    """Lombardia has a semi-structured portal"""
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            r = await client.get(
                "https://www.silvia.regione.lombardia.it/silvia/ricerca",
                params={"q": keyword, "stato": "concluso"},
                headers={"User-Agent": "geoVIA/1.0"}
            )
            if r.status_code == 200:
                return _parse_generic_html(r.text, "Lombardia", limit)
    except Exception as e:
        print(f"[Lombardia] {e}")
    return []

async def get_campania_procedures(keyword: str = "", limit: int = 5) -> list:
    """Campania VIA portal"""
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            r = await client.get(
                "https://www.regione.campania.it/regione/it/tematiche/portale-via",
                params={"q": keyword},
                headers={"User-Agent": "geoVIA/1.0"}
            )
            if r.status_code == 200:
                return _parse_generic_html(r.text, "Campania", limit)
    except Exception as e:
        print(f"[Campania] {e}")
    return []

async def get_generic_regional(region: str, keyword: str = "", limit: int = 5) -> list:
    """Generic scraper for regions without specific connector"""
    portal = REGIONAL_PORTALS.get(region)
    if not portal:
        return []
    try:
        url = portal.get("search_url", portal["url"])
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            r = await client.get(url, params={"q": keyword} if keyword else {},
                headers={"User-Agent": "geoVIA/1.0"})
            if r.status_code == 200:
                return _parse_generic_html(r.text, portal["name"], limit)
    except Exception as e:
        print(f"[{region}] {e}")
    return []

def _parse_generic_html(html: str, region: str, limit: int) -> list:
    """Generic HTML parser — extracts links and titles"""
    results = []
    # Look for procedure links
    patterns = [
        r'href="([^"]*(?:via|vas|procedura|progetto)[^"]*)"[^>]*>([^<]{10,100})</a>',
        r'<a[^>]*href="([^"]+)"[^>]*>\s*([^<]{10,80}(?:VIA|VAS|impianto|progetto)[^<]{0,50})\s*</a>',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            url, title = match.groups()
            if not url.startswith("http"):
                continue
            results.append({
                "region": region,
                "title": title.strip(),
                "url": url,
                "status": "N/D",
                "type": "VIA" if "via" in url.lower() else "VAS"
            })
            if len(results) >= limit:
                break
        if results:
            break
    return results

# ── MASTER FUNCTION ───────────────────────────────────────────────────────────

async def get_regional_procedures(lat: float, lon: float, project_type: str,
                                   keyword: str = "") -> dict:
    """
    Get regional VIA procedures for the area.
    Detects region from coordinates, queries appropriate portal.
    """
    region = coords_to_region(lat, lon)
    portal_info = REGIONAL_PORTALS.get(region, {})

    # Build search keyword from project type
    if not keyword:
        type_keywords = {
            "energetico": "fotovoltaico eolico",
            "industriale": "industria",
            "viario": "strada autostrada",
            "residenziale": "residenziale",
            "turistico": "turistico",
            "agricolo": "agricolo"
        }
        keyword = type_keywords.get(project_type, project_type)

    # Use specific connector if available, else generic
    if region == "lombardia":
        procedures = await get_lombardia_procedures(keyword)
    elif region == "campania":
        procedures = await get_campania_procedures(keyword)
    else:
        procedures = await get_generic_regional(region, keyword)

    return {
        "region": region,
        "region_name": portal_info.get("name", region.title()),
        "portal_url": portal_info.get("url", ""),
        "procedures": procedures,
        "note": f"Portale VIA {portal_info.get('name', region.title())} — {len(procedures)} procedimenti trovati"
    }

def get_all_regions_info() -> list:
    """Returns info about all supported regional portals"""
    return [
        {"region": k, "name": v["name"], "url": v["url"]}
        for k, v in REGIONAL_PORTALS.items()
    ]
