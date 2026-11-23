"""
Modulo B — Analisi Cumulativa
"""
import httpx
import asyncio
from shapely.geometry import shape
from backend.gis_engine import create_buffer, geojson_to_gdf

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

def _geojson_bbox(geojson: dict) -> tuple:
    try:
        if geojson.get("type") == "Feature":
            geom = shape(geojson["geometry"])
        else:
            geom = shape(geojson)
        b = geom.bounds
        return (b[0], b[1], b[2], b[3])
    except Exception:
        return (-180, -90, 180, 90)

# ── OSM OVERPASS ──────────────────────────────────────────────────────────────

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRROR = "https://overpass.kumi.systems/api/interpreter"

async def _overpass(query: str, label: str) -> list:
    """Generic Overpass query with mirror fallback"""
    for url in [OVERPASS_URL, OVERPASS_MIRROR]:
        try:
            async with httpx.AsyncClient(timeout=8, verify=False) as client:
                r = await client.post(url, data={"data": query})
                if r.status_code == 200:
                    elements = r.json().get("elements", [])
                    print(f"[Overpass/{label}] {url.split('/')[2]} elements={len(elements)}")
                    return elements
        except Exception as e:
            print(f"[Overpass/{label}] {url.split('/')[2]} ERROR: {e}")
    return []

async def get_osm_industrial(lat: float, lon: float, radius_m: int = 5000) -> list:
    """Industrial plants, power stations, substations from OSM"""
    query = f"""[out:json][timeout:25];
(
  node["power"~"plant|substation|generator"](around:{radius_m},{lat},{lon});
  way["power"~"plant|substation"](around:{radius_m},{lat},{lon});
  node["landuse"="industrial"](around:{radius_m},{lat},{lon});
  way["landuse"="industrial"](around:{radius_m},{lat},{lon});
);
out center 50;"""
    elements = await _overpass(query, "industrial")
    results = []
    for e in elements:
        tags = e.get("tags", {})
        center = e.get("center", e)
        results.append({
            "type": tags.get("power", tags.get("landuse", "industrial")),
            "name": tags.get("name", tags.get("operator", "N/D")),
            "lat": float(center.get("lat", lat)),
            "lon": float(center.get("lon", lon)),
            "source": "OpenStreetMap"
        })
    return results

async def get_osm_renewable(lat: float, lon: float, radius_m: int = 5000) -> list:
    """Solar, wind, hydro plants from OSM"""
    query = f"""[out:json][timeout:25];
(
  node["generator:source"~"solar|wind|hydro"](around:{radius_m},{lat},{lon});
  way["generator:source"~"solar|wind|hydro"](around:{radius_m},{lat},{lon});
  node["power"="generator"](around:{radius_m},{lat},{lon});
  way["power"="plant"](around:{radius_m},{lat},{lon});
);
out center 50;"""
    elements = await _overpass(query, "renewable")
    results = []
    for e in elements:
        tags = e.get("tags", {})
        center = e.get("center", e)
        src = tags.get("generator:source", tags.get("plant:source", "unknown"))
        results.append({
            "type": f"FER_{src.upper()}",
            "name": tags.get("name", tags.get("operator", f"Impianto {src}")),
            "lat": float(center.get("lat", lat)),
            "lon": float(center.get("lon", lon)),
            "output_mw": tags.get("generator:output:electricity", "N/D"),
            "source": "OpenStreetMap"
        })
    return results

async def get_osm_infrastructure(lat: float, lon: float, radius_m: int = 5000) -> list:
    """Roads, railways, airports from OSM"""
    query = f"""[out:json][timeout:25];
(
  way["highway"~"motorway|trunk|primary"](around:{radius_m},{lat},{lon});
  way["railway"~"rail"](around:{radius_m},{lat},{lon});
  node["aeroway"="aerodrome"](around:{radius_m},{lat},{lon});
);
out center 20;"""
    elements = await _overpass(query, "infra")
    results = []
    for e in elements:
        tags = e.get("tags", {})
        center = e.get("center", e)
        results.append({
            "type": tags.get("highway", tags.get("railway", tags.get("aeroway", "infra"))),
            "name": tags.get("name", tags.get("ref", "N/D")),
            "lat": float(center.get("lat", lat)),
            "lon": float(center.get("lon", lon)),
            "source": "OpenStreetMap"
        })
    return results

# ── ISPRA IMPIANTI ─────────────────────────────────────────────────────────────

async def get_ispra_aia_plants(lat: float, lon: float, radius_m: int = 5000) -> list:
    """AIA authorized plants from ISPRA E-PRTR"""
    try:
        url = "https://www.eprtr.it/arcgis/rest/services/EPRTR/EPRTR_WM/MapServer/0/query"
        params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "distance": radius_m,
            "units": "esriSRUnit_Meter",
            "outFields": "NOME_COMPLESSO,ATTIVITA_PRINCIPALE,COMUNE",
            "returnGeometry": "false",
            "f": "json"
        }
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                features = r.json().get("features", [])
                return [{
                    "type": "AIA",
                    "name": f["attributes"].get("NOME_COMPLESSO", "N/D"),
                    "activity": f["attributes"].get("ATTIVITA_PRINCIPALE", ""),
                    "comune": f["attributes"].get("COMUNE", ""),
                    "source": "ISPRA E-PRTR"
                } for f in features[:20]]
    except Exception as e:
        print(f"[ISPRA AIA] {e}")
    return []

# ── SEVESO SITES ──────────────────────────────────────────────────────────────

async def get_seveso_sites(lat: float, lon: float, radius_m: int = 5000) -> list:
    """SEVESO III sites from ISPRA"""
    try:
        url = "https://www.eprtr.it/arcgis/rest/services/SEVESO/SEVESO_WM/MapServer/0/query"
        params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "distance": radius_m,
            "units": "esriSRUnit_Meter",
            "outFields": "NOME,COMUNE,LIVELLO",
            "returnGeometry": "false",
            "f": "json"
        }
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                features = r.json().get("features", [])
                return [{
                    "type": f"SEVESO_{f['attributes'].get('LIVELLO','III')}",
                    "name": f["attributes"].get("NOME", "N/D"),
                    "comune": f["attributes"].get("COMUNE", ""),
                    "source": "ISPRA SEVESO"
                } for f in features[:10]]
    except Exception as e:
        print(f"[SEVESO] {e}")
    return []

# ── CUMULATIVE IMPACT CALCULATOR ──────────────────────────────────────────────

def compute_cumulative_impact(plants: list, project_type: str, area_m2: float) -> dict:
    """
    Calculates cumulative impact score based on existing plants in buffer.
    Deterministic algorithm — no LLM.
    """
    fer_count = sum(1 for p in plants if "FER" in p.get("type", ""))
    industrial_count = sum(1 for p in plants if p.get("type") in ("industrial", "AIA"))
    seveso_count = sum(1 for p in plants if "SEVESO" in p.get("type", ""))
    infra_count = sum(1 for p in plants if p.get("type") in ("motorway", "trunk", "rail"))

    # Cumulative pressure score 0-100
    pressure = min(100, (
        fer_count * 8 +
        industrial_count * 12 +
        seveso_count * 20 +
        infra_count * 5
    ))

    # Project-specific sensitivity
    sensitivity = {
        "residenziale": 1.3,
        "turistico": 1.2,
        "agricolo": 1.1,
        "energetico": 0.9,
        "industriale": 0.8,
        "viario": 0.7,
    }.get(project_type, 1.0)

    cumulative_score = min(100, round(pressure * sensitivity, 1))

    return {
        "score": cumulative_score,
        "level": "ALTO" if cumulative_score >= 60 else "MEDIO" if cumulative_score >= 30 else "BASSO",
        "breakdown": {
            "fer_impianti": fer_count,
            "impianti_industriali": industrial_count,
            "siti_seveso": seveso_count,
            "infrastrutture": infra_count,
            "totale": len(plants)
        },
        "note": f"Pressione cumulativa nell'area di influenza: {len(plants)} impianti/infrastrutture rilevati"
    }

# ── MASTER FUNCTION ───────────────────────────────────────────────────────────

def _corine_fallback(lat: float, lon: float, radius_m: int) -> list:
    """
    Fallback when Overpass returns nothing: estimate from geographic context.
    Uses lat/lon to infer likely infrastructure presence in Italy.
    Returns synthetic elements for scoring purposes only.
    """
    results = []
    # Italy has dense road network — primary roads almost always present in 5km
    results.append({"type": "primary", "name": "Rete viaria primaria (stima)",
                    "lat": lat, "lon": lon, "source": "Stima geografica"})
    # If radius >= 5km, likely at least one substation in Italy
    if radius_m >= 5000:
        results.append({"type": "substation", "name": "Cabina elettrica (stima)",
                        "lat": lat + 0.01, "lon": lon + 0.01, "source": "Stima geografica"})
    print(f"[Cumulative] Overpass returned 0 — using geographic fallback ({len(results)} items)")
    return results

async def analyze_cumulative(lat: float, lon: float, project_type: str,
                              area_m2: float, radius_m: int = 5000) -> dict:
    """Run all cumulative checks in parallel"""
    print(f"[Cumulative] Starting analysis lat={lat:.4f} lon={lon:.4f} radius={radius_m}m")
    industrial, renewable, infra, aia, seveso = await asyncio.gather(
        get_osm_industrial(lat, lon, radius_m),
        get_osm_renewable(lat, lon, radius_m),
        get_osm_infrastructure(lat, lon, radius_m),
        get_ispra_aia_plants(lat, lon, radius_m),
        get_seveso_sites(lat, lon, radius_m),
        return_exceptions=True
    )

    all_plants = []
    for result in [industrial, renewable, infra, aia, seveso]:
        if isinstance(result, list):
            all_plants.extend(result)

    print(f"[Cumulative] Total elements found: {len(all_plants)}")

    # Fallback if Overpass returned nothing (timeout, rate limit, rural area)
    if len(all_plants) == 0:
        all_plants = _corine_fallback(lat, lon, radius_m)

    impact = compute_cumulative_impact(all_plants, project_type, area_m2)
    impact["plants"] = all_plants[:30]
    impact["radius_m"] = radius_m
    impact["data_source"] = "OpenStreetMap" if len(all_plants) > 2 else "Stima geografica (fallback)"
    return impact
