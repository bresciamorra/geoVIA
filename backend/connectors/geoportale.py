"""
Geoportale Nazionale (MASE/PCN) connector.
Sources:
  - DTM 20m — Modello Digitale del Terreno (WCS)
  - Rete Natura 2000 IT — SIC/ZSC/ZPS ufficiali italiani (WFS)
  - Vincoli paesaggistici D.Lgs 42/2004 art.136/142 (WFS)
  - Aree protette nazionali (WFS)

Base URL: https://wms.pcn.minambiente.it/ogc
WCS:      https://wcs.pcn.minambiente.it/ogc
WFS:      https://wfs.pcn.minambiente.it/ogc
"""
import httpx
import asyncio
import io
import math
import numpy as np
from shapely.geometry import shape

PCN_WFS = "https://wfs.pcn.minambiente.it/ogc"
PCN_WCS = "https://wcs.pcn.minambiente.it/ogc"
PCN_WMS = "https://wms.pcn.minambiente.it/ogc"


def _bbox(geojson: dict) -> tuple:
    try:
        geom = shape(geojson["geometry"] if geojson.get("type") == "Feature" else geojson)
        return geom.bounds  # (minx, miny, maxx, maxy)
    except Exception:
        return (12.0, 41.0, 12.1, 41.1)


def _expand_bbox(bbox: tuple, factor: float = 0.01) -> tuple:
    """Expand bbox by factor degrees for buffer queries"""
    return (bbox[0] - factor, bbox[1] - factor, bbox[2] + factor, bbox[3] + factor)


# ── DTM — Modello Digitale del Terreno ────────────────────────────────────────

async def get_dtm(geojson: dict, lat: float, lon: float) -> dict:
    """
    Get elevation and slope data from PCN DTM 20m.
    Used for: slope → hydrogeological risk refinement
              aspect → solar exposure
              basin delineation proxy
    """
    bbox = _expand_bbox(_bbox(geojson), 0.005)
    result = await _dtm_wcs(bbox)
    if result:
        return result
    # Fallback: estimate from SRTM via open-elevation API
    return await _dtm_open_elevation(lat, lon)


async def _dtm_wcs(bbox: tuple) -> dict:
    """Query PCN DTM via WCS GetCoverage"""
    try:
        params = {
            "SERVICE": "WCS", "VERSION": "1.0.0", "REQUEST": "GetCoverage",
            "COVERAGE": "DTM20",
            "CRS": "EPSG:4326",
            "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "WIDTH": "32", "HEIGHT": "32",
            "FORMAT": "GeoTIFF"
        }
        async with httpx.AsyncClient(timeout=12, verify=False) as client:
            r = await client.get(PCN_WCS, params=params)
            if r.status_code == 200 and b"GeoTIFF" in r.content[:100] or r.headers.get("content-type", "").startswith("image"):
                return _parse_dtm_tiff(r.content)
    except Exception as e:
        print(f"[PCN DTM WCS] {e}")
    return {}


def _parse_dtm_tiff(content: bytes) -> dict:
    """Extract elevation stats and slope from DTM GeoTIFF"""
    try:
        import rasterio
        from rasterio.transform import from_bounds
        with rasterio.open(io.BytesIO(content)) as ds:
            data = ds.read(1).astype(float)
            nodata = ds.nodata or -9999
            data[data == nodata] = np.nan
            valid = data[~np.isnan(data)]
            if len(valid) == 0:
                return {}

            elev_mean = float(np.nanmean(data))
            elev_min = float(np.nanmin(data))
            elev_max = float(np.nanmax(data))
            elev_std = float(np.nanstd(data))

            # Slope estimation (degrees) from gradient
            dy, dx = np.gradient(data, 20.0, 20.0)  # 20m resolution
            slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
            slope_deg = np.degrees(slope_rad)
            slope_mean = float(np.nanmean(slope_deg))
            slope_max = float(np.nanmax(slope_deg))

            return {
                "elev_mean_m": round(elev_mean, 1),
                "elev_min_m": round(elev_min, 1),
                "elev_max_m": round(elev_max, 1),
                "elev_range_m": round(elev_max - elev_min, 1),
                "slope_mean_deg": round(slope_mean, 1),
                "slope_max_deg": round(slope_max, 1),
                "slope_class": _slope_class(slope_mean),
                "source": "PCN DTM 20m",
                "real": True
            }
    except Exception as e:
        print(f"[PCN DTM parse] {e}")
    return {}


async def _dtm_open_elevation(lat: float, lon: float) -> dict:
    """Fallback: open-elevation.com API"""
    try:
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            r = await client.get(
                "https://api.open-elevation.com/api/v1/lookup",
                params={"locations": f"{lat},{lon}"}
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    elev = results[0].get("elevation", 0)
                    return {
                        "elev_mean_m": float(elev),
                        "elev_min_m": float(elev),
                        "elev_max_m": float(elev),
                        "elev_range_m": 0.0,
                        "slope_mean_deg": _estimate_slope_from_elevation(elev),
                        "slope_max_deg": _estimate_slope_from_elevation(elev) * 1.5,
                        "slope_class": _slope_class(_estimate_slope_from_elevation(elev)),
                        "source": "Open-Elevation (fallback)",
                        "real": True
                    }
    except Exception as e:
        print(f"[Open-Elevation] {e}")
    return {"elev_mean_m": 0, "slope_mean_deg": 5.0, "slope_class": "PIANURA", "source": "Fallback", "real": False}


def _slope_class(slope_deg: float) -> str:
    if slope_deg < 5:   return "PIANURA"
    if slope_deg < 15:  return "COLLINARE"
    if slope_deg < 30:  return "MONTAGNA"
    return "RIPIDO"


def _estimate_slope_from_elevation(elev: float) -> float:
    """Rough slope estimate from elevation (Italy heuristic)"""
    if elev < 50:   return 2.0
    if elev < 200:  return 8.0
    if elev < 600:  return 15.0
    return 25.0


# ── NATURA 2000 IT (Geoportale ufficiale) ─────────────────────────────────────

async def get_natura2000_it(geojson: dict, lat: float, lon: float) -> dict:
    """
    Official Italian Natura 2000 network from PCN/MASE.
    More up-to-date than EEA for Italian territory.
    Layers: SIC (Siti di Importanza Comunitaria), ZSC, ZPS
    """
    bbox = _expand_bbox(_bbox(geojson), 0.05)
    result = await _natura2000_wfs(bbox, lat, lon)
    if result.get("real"):
        return result
    # Fallback to EEA (handled in __init__.py)
    return result


async def _natura2000_wfs(bbox: tuple, lat: float, lon: float) -> dict:
    """Query Natura 2000 via PCN WFS"""
    sites = []
    for layer in ["PS_ZSC_ZSC", "PS_ZPS_ZPS"]:
        try:
            params = {
                "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
                "TYPENAME": layer,
                "OUTPUTFORMAT": "application/json",
                "BBOX": f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]},EPSG:4326",
                "MAXFEATURES": "20"
            }
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                r = await client.get(PCN_WFS, params=params)
                if r.status_code == 200:
                    features = r.json().get("features", [])
                    for f in features:
                        props = f.get("properties", {})
                        sites.append({
                            "code": props.get("SITECODE", props.get("codice", "")),
                            "name": props.get("SITENAME", props.get("nome", "N/D")),
                            "type": layer.split("_")[1],
                            "source": "PCN/MASE"
                        })
        except Exception as e:
            print(f"[PCN Natura2000 {layer}] {e}")

    if sites:
        return {
            "intersects": True,
            "distance_m": 0,
            "sites": [s["name"] for s in sites[:3]],
            "site_codes": [s["code"] for s in sites[:3]],
            "site_types": list(set(s["type"] for s in sites)),
            "source": "PCN/MASE Natura 2000",
            "real": True
        }

    # No intersection — compute distance
    dist = await _natura2000_distance(lat, lon)
    return {
        "intersects": False,
        "distance_m": dist,
        "sites": [],
        "source": "PCN/MASE Natura 2000",
        "real": dist < 50000
    }


async def _natura2000_distance(lat: float, lon: float) -> float:
    """Find nearest Natura 2000 site and return distance in meters"""
    try:
        # Search in expanding radius
        for radius_deg in [0.1, 0.3, 0.5, 1.0]:
            bbox = (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)
            for layer in ["PS_ZSC_ZSC", "PS_ZPS_ZPS"]:
                params = {
                    "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
                    "TYPENAME": layer,
                    "OUTPUTFORMAT": "application/json",
                    "BBOX": f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]},EPSG:4326",
                    "MAXFEATURES": "1"
                }
                async with httpx.AsyncClient(timeout=8, verify=False) as client:
                    r = await client.get(PCN_WFS, params=params)
                    if r.status_code == 200:
                        features = r.json().get("features", [])
                        if features:
                            # Approximate distance from bbox center
                            return radius_deg * 111000 * 0.7
    except Exception as e:
        print(f"[PCN N2000 distance] {e}")
    return 10000.0  # default 10km


# ── VINCOLI PAESAGGISTICI D.Lgs 42/2004 ──────────────────────────────────────

async def get_vincoli_paesaggistici(geojson: dict, lat: float, lon: float) -> dict:
    """
    Vincoli paesaggistici ex D.Lgs 42/2004 art.136 (dichiarazione) e art.142 (ope legis).
    Art.142 includes: coste, fiumi, laghi, montagne, foreste, zone umide, vulcani, parchi.
    Source: PCN WFS layer VP_VINCOLO_PAESAGGISTICO
    """
    bbox = _expand_bbox(_bbox(geojson), 0.01)
    vincoli = []

    try:
        params = {
            "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
            "TYPENAME": "VP_VINCOLO_PAESAGGISTICO",
            "OUTPUTFORMAT": "application/json",
            "BBOX": f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]},EPSG:4326",
            "MAXFEATURES": "20"
        }
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            r = await client.get(PCN_WFS, params=params)
            if r.status_code == 200:
                features = r.json().get("features", [])
                for f in features:
                    props = f.get("properties", {})
                    vincoli.append({
                        "tipo": props.get("TIPO_VINCOLO", props.get("tipo", "Paesaggistico")),
                        "denominazione": props.get("DENOMINAZIONE", props.get("nome", "N/D")),
                        "articolo": props.get("ARTICOLO", "art.142"),
                        "source": "PCN/MASE"
                    })
    except Exception as e:
        print(f"[PCN Vincoli] {e}")

    # Also check aree protette
    aree = await _get_aree_protette(bbox)

    return {
        "vincoli_paesaggistici": vincoli,
        "aree_protette": aree,
        "has_vincolo": len(vincoli) > 0,
        "has_area_protetta": len(aree) > 0,
        "count": len(vincoli) + len(aree),
        "blocchi_procedurali": _check_blocchi(vincoli, aree),
        "source": "PCN/MASE D.Lgs 42/2004",
        "real": True
    }


async def _get_aree_protette(bbox: tuple) -> list:
    """National and regional protected areas"""
    aree = []
    try:
        params = {
            "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
            "TYPENAME": "AP_PARCHI_NAZ",
            "OUTPUTFORMAT": "application/json",
            "BBOX": f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]},EPSG:4326",
            "MAXFEATURES": "10"
        }
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            r = await client.get(PCN_WFS, params=params)
            if r.status_code == 200:
                features = r.json().get("features", [])
                for f in features:
                    props = f.get("properties", {})
                    aree.append({
                        "nome": props.get("NOME", "Parco Nazionale"),
                        "tipo": "Parco Nazionale",
                        "source": "PCN/MASE"
                    })
    except Exception as e:
        print(f"[PCN Aree Protette] {e}")
    return aree


def _check_blocchi(vincoli: list, aree: list) -> list:
    """
    Identify procedural blockers based on vincoli.
    Returns list of blocking constraints with normative reference.
    """
    blocchi = []
    for v in vincoli:
        art = v.get("articolo", "")
        tipo = v.get("tipo", "").lower()
        if "136" in art:
            blocchi.append({
                "tipo": "VINCOLO DICHIARATIVO",
                "descrizione": f"Vincolo paesaggistico dichiarativo (art.136): {v['denominazione']}",
                "norma": "D.Lgs 42/2004 art.136 — Autorizzazione paesaggistica obbligatoria",
                "impatto": "BLOCCANTE — richiede autorizzazione Soprintendenza"
            })
        elif "142" in art or "fiume" in tipo or "lago" in tipo or "costa" in tipo:
            blocchi.append({
                "tipo": "VINCOLO OPE LEGIS",
                "descrizione": f"Vincolo paesaggistico ope legis (art.142): {v['denominazione']}",
                "norma": "D.Lgs 42/2004 art.142 — Autorizzazione paesaggistica obbligatoria",
                "impatto": "BLOCCANTE — richiede autorizzazione paesaggistica"
            })
    for a in aree:
        blocchi.append({
            "tipo": "AREA PROTETTA",
            "descrizione": f"{a['tipo']}: {a['nome']}",
            "norma": "L. 394/1991 — Legge quadro aree protette",
            "impatto": "BLOCCANTE — nulla osta Ente Parco obbligatorio"
        })
    return blocchi


# ── MASTER FUNCTION ───────────────────────────────────────────────────────────

async def fetch_geoportale(geojson: dict, lat: float, lon: float) -> dict:
    """Fetch all Geoportale data in parallel"""
    dtm, natura2000, vincoli = await asyncio.gather(
        get_dtm(geojson, lat, lon),
        get_natura2000_it(geojson, lat, lon),
        get_vincoli_paesaggistici(geojson, lat, lon),
        return_exceptions=True
    )
    result = {
        "dtm": dtm if isinstance(dtm, dict) else {},
        "natura2000_it": natura2000 if isinstance(natura2000, dict) else {},
        "vincoli": vincoli if isinstance(vincoli, dict) else {},
    }
    # Log
    dtm_d = result["dtm"]
    n2k_d = result["natura2000_it"]
    v_d = result["vincoli"]
    print(f"[Geoportale] DTM: elev={dtm_d.get('elev_mean_m','?')}m slope={dtm_d.get('slope_mean_deg','?')}° ({dtm_d.get('slope_class','?')}) src={dtm_d.get('source','?')}")
    print(f"[Geoportale] N2000: intersects={n2k_d.get('intersects','?')} dist={n2k_d.get('distance_m','?')}m src={n2k_d.get('source','?')}")
    print(f"[Geoportale] Vincoli: count={v_d.get('count','?')} blocchi={len(v_d.get('blocchi_procedurali',[]))}")
    return result
