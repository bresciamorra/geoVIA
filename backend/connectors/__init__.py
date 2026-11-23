"""
Data connectors — real APIs where available, intelligent fallback otherwise.
"""
import httpx
import asyncio
import ssl
from backend.gis_engine import query_wfs, spatial_intersect, distance_to_nearest, geojson_to_gdf
from shapely.geometry import shape, mapping

# WSL has broken CA chain — disable SSL verification for external APIs
_CLIENT_KWARGS = {"timeout": 5, "verify": False}

def _client(**kwargs):
    kw = {**_CLIENT_KWARGS, **kwargs}
    return httpx.AsyncClient(**kw)

# ─── ISPRA IdroGEO ────────────────────────────────────────────────────────────

async def get_ispra_hydrogeological(geojson: dict, lat: float, lon: float) -> dict:
    """
    ISPRA IdroGEO - PAI frane e alluvioni
    WFS: https://idrogeo.isprambiente.it/app/
    Update: annual
    """
    base = "https://idrogeo.isprambiente.it/geoserver/wfs"
    bbox = _geojson_bbox(geojson)

    results = {"frane": {}, "alluvioni": {}, "affected_pct": 0, "real": False}

    # Try frane PAI
    try:
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeName": "idrogeo:pai_frane_p",
            "outputFormat": "application/json",
            "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:4326",
            "count": "50"
        }
        async with _client(timeout=10) as client:
            r = await client.get(base, params=params)
            if r.status_code == 200:
                data = r.json()
                features = data.get("features", [])
                intersecting = spatial_intersect(geojson, features)
                if intersecting:
                    classes = [f["properties"].get("CLASSE_P", 1) for f in intersecting]
                    results["frane"] = {"max_class": max(classes), "count": len(intersecting)}
                    results["real"] = True
    except Exception as e:
        print(f"[ISPRA frane] {e}")

    # Try alluvioni PAI
    try:
        params["typeName"] = "idrogeo:pai_alluvioni_p"
        async with _client(timeout=10) as client:
            r = await client.get(base, params=params)
            if r.status_code == 200:
                data = r.json()
                features = data.get("features", [])
                intersecting = spatial_intersect(geojson, features)
                if intersecting:
                    classes = [f["properties"].get("CLASSE_P", 1) for f in intersecting]
                    results["alluvioni"] = {"max_class": max(classes), "count": len(intersecting)}
                    results["real"] = True
    except Exception as e:
        print(f"[ISPRA alluvioni] {e}")

    # Fallback: approximate from coordinates
    if not results["real"]:
        results = _ispra_fallback(lat, lon)

    return results

def _ispra_fallback(lat: float, lon: float) -> dict:
    """Approximate hydrogeological risk from known Italian zones"""
    high_hydro = [(44.8,10.3),(45.1,12.0),(38.9,16.5),(40.6,14.9),(44.4,8.9)]
    min_dist = min(((lat-z[0])**2+(lon-z[1])**2)**0.5 for z in high_hydro)
    if min_dist < 0.5:
        cls = 3
    elif min_dist < 1.5:
        cls = 2
    else:
        cls = 1
    return {
        "frane": {"max_class": cls},
        "alluvioni": {"max_class": cls},
        "affected_pct": {3: 45, 2: 25, 1: 10}.get(cls, 10),
        "real": False
    }

# ─── INGV Seismic ─────────────────────────────────────────────────────────────

async def get_ingv_seismic(lat: float, lon: float) -> dict:
    """INGV MPS04 seismic hazard map"""
    try:
        url = "https://esse1-gis.mi.ingv.it/gs_ingv/ows"
        params = {
            "service": "WFS", "version": "1.0.0", "request": "GetFeature",
            "typeName": "ingv:mps04_pga_475",
            "outputFormat": "application/json",
            "CQL_FILTER": f"CONTAINS(the_geom, POINT({lon} {lat}))",
            "maxFeatures": "1"
        }
        async with _client(timeout=8) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                features = data.get("features", [])
                if features:
                    pga = features[0]["properties"].get("pga_475", 0.05)
                    return {"pga_475": pga, "real": True}
    except Exception as e:
        print(f"[INGV] {e}")
    return {"pga_475": _ingv_fallback(lat, lon), "real": False}

def _ingv_fallback(lat: float, lon: float) -> float:
    zones = [(38.1,15.6,0.27),(37.5,15.1,0.25),(40.8,14.2,0.22),(46.1,13.2,0.20),(42.3,13.4,0.24),(41.9,12.5,0.10),(45.5,9.2,0.05)]
    min_dist, pga = float('inf'), 0.08
    for zlat, zlon, zpga in zones:
        d = ((lat-zlat)**2+(lon-zlon)**2)**0.5
        if d < min_dist:
            min_dist = d
            pga = max(0.025, zpga - d * 0.05)
    return round(pga, 3)

# ─── Natura 2000 ──────────────────────────────────────────────────────────────

async def get_natura2000(geojson: dict, lat: float, lon: float) -> dict:
    """European Environment Agency - Natura 2000 network"""
    try:
        url = "https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites/CDDA_Terrestrial_WM/MapServer/1/query"
        bbox = _geojson_bbox(geojson)
        params = {
            "geometry": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "SITECODE,SITENAME,SITETYPE",
            "returnGeometry": "true",
            "f": "json"
        }
        async with _client(timeout=10) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                features = data.get("features", [])
                if features:
                    return {
                        "intersects": True,
                        "distance_m": 0,
                        "sites": [f["attributes"].get("SITENAME","") for f in features[:3]],
                        "real": True
                    }
    except Exception as e:
        print(f"[Natura2000] {e}")

    # Fallback via OSM
    return await _natura2000_osm_fallback(lat, lon)

async def _natura2000_osm_fallback(lat: float, lon: float) -> dict:
    try:
        query = f"""[out:json][timeout:10];
        (relation["boundary"="protected_area"](around:5000,{lat},{lon}););
        out center 5;"""
        async with _client(timeout=12) as client:
            r = await client.post("https://overpass-api.de/api/interpreter", data={"data": query})
            if r.status_code == 200:
                elements = r.json().get("elements", [])
                if elements:
                    return {"intersects": True, "distance_m": 0, "sites": [e.get("tags",{}).get("name","") for e in elements[:3]], "real": True}
    except Exception:
        pass
    return {"intersects": False, "distance_m": 5000, "sites": [], "real": False}

# ─── CORINE Land Cover ────────────────────────────────────────────────────────

async def get_corine_landcover(lat: float, lon: float) -> dict:
    """Copernicus CORINE Land Cover 2018"""
    try:
        url = "https://image.discomap.eea.europa.eu/arcgis/rest/services/Corine/CLC2018_WM/MapServer/identify"
        params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "layers": "all",
            "tolerance": "2",
            "mapExtent": f"{lon-0.01},{lat-0.01},{lon+0.01},{lat+0.01}",
            "imageDisplay": "100,100,96",
            "returnGeometry": "false",
            "f": "json"
        }
        async with _client(timeout=10) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                results = data.get("results", [])
                if results:
                    label = results[0].get("attributes", {}).get("Label_EN", "")
                    return {"dominant_class": label, "artificial_pct": 80 if "artificial" in label.lower() else 10, "real": True}
    except Exception as e:
        print(f"[CORINE] {e}")
    return {"dominant_class": "unknown", "artificial_pct": 20, "real": False}

# ─── Air Quality ──────────────────────────────────────────────────────────────

async def get_air_quality(lat: float, lon: float) -> dict:
    """OpenAQ v3"""
    try:
        async with _client(timeout=8) as client:
            r = await client.get("https://api.openaq.org/v3/locations",
                params={"coordinates": f"{lat},{lon}", "radius": 50000, "limit": 3})
            if r.status_code == 200:
                locs = r.json().get("results", [])
                if locs:
                    mr = await client.get(f"https://api.openaq.org/v3/locations/{locs[0]['id']}/latest")
                    if mr.status_code == 200:
                        sensors = mr.json().get("results", [])
                        result = {"real": True}
                        for s in sensors:
                            pname = s.get("parameter", {}).get("name", "")
                            if pname in ("pm25","pm10","no2","o3"):
                                result[pname] = s.get("value", 0)
                        if result:
                            return result
    except Exception as e:
        print(f"[OpenAQ] {e}")
    return {"pm25": 12, "pm10": 22, "no2": 18, "real": False}

# ─── Water bodies ─────────────────────────────────────────────────────────────

# ── COASTAL DETECTION (embedded, no external API needed) ────────────────────
# Simplified coastal bounding boxes for Italian regions
# Format: (lat_min, lat_max, lon_min, lon_max, coast_side)
_ITALY_COAST_ZONES = [
    # Liguria
    (43.7, 44.5, 7.5, 10.1, "Tirreno"),
    # Toscana costa
    (42.3, 44.2, 10.0, 11.2, "Tirreno"),
    # Lazio costa
    (41.0, 42.8, 11.5, 12.5, "Tirreno"),
    # Campania costa
    (39.9, 41.3, 13.9, 15.3, "Tirreno"),
    # Calabria tirrenica
    (37.9, 40.1, 15.6, 16.2, "Tirreno"),
    # Sicilia nord
    (37.9, 38.3, 12.4, 15.7, "Tirreno"),
    # Sicilia sud
    (36.6, 37.9, 12.4, 15.3, "Mediterraneo"),
    # Calabria ionica
    (37.9, 39.8, 15.9, 16.6, "Ionio"),
    # Basilicata/Puglia ionica
    (39.8, 40.5, 16.5, 18.0, "Ionio"),
    # Puglia adriatica
    (39.8, 41.9, 15.8, 18.5, "Adriatico"),
    # Molise/Abruzzo
    (41.9, 42.7, 14.0, 14.8, "Adriatico"),
    # Marche
    (42.7, 44.0, 12.9, 14.0, "Adriatico"),
    # Emilia-Romagna
    (44.0, 44.9, 12.1, 12.7, "Adriatico"),
    # Veneto/Friuli
    (44.9, 45.8, 12.2, 13.8, "Adriatico"),
    # Sardegna
    (38.8, 41.3, 8.1, 9.8, "Mediterraneo"),
]

def _is_coastal_italy(lat: float, lon: float, buffer_deg: float = 0.08) -> tuple:
    """
    Deterministic coastal detection for Italy.
    Returns (is_coastal, distance_km_estimate, sea_name)
    buffer_deg ~8km at Italian latitudes
    """
    for lat_min, lat_max, lon_min, lon_max, sea in _ITALY_COAST_ZONES:
        # Check if point is within coastal zone (with buffer)
        if (lat_min - buffer_deg <= lat <= lat_max + buffer_deg and
                lon_min - buffer_deg <= lon <= lon_max + buffer_deg):
            # Estimate distance to coast edge
            dist_lat = min(abs(lat - lat_min), abs(lat - lat_max)) * 111000
            dist_lon = min(abs(lon - lon_min), abs(lon - lon_max)) * 111000 * 0.7
            dist_m = min(dist_lat, dist_lon)
            return True, dist_m, sea
    return False, 50000, ""


async def get_water_bodies(lat: float, lon: float) -> dict:
    """OSM Overpass - rivers, lakes, water bodies and coastline"""
    # Always check coastal proximity with embedded dataset (no API needed)
    is_coastal_embed, dist_coast_embed, sea_name = _is_coastal_italy(lat, lon)

    try:
        query = f"""[out:json][timeout:10];
        (
          way["waterway"~"river|stream|canal"](around:2000,{lat},{lon});
          relation["natural"="water"](around:2000,{lat},{lon});
          way["natural"="coastline"](around:1000,{lat},{lon});
          node["natural"="bay"](around:2000,{lat},{lon});
        );
        out center 10;"""
        async with _client(timeout=12) as client:
            r = await client.post("https://overpass-api.de/api/interpreter", data={"data": query})
            if r.status_code == 200:
                elements = r.json().get("elements", [])
                if elements:
                    rivers = [e for e in elements if e.get("tags",{}).get("waterway")]
                    lakes = [e for e in elements if e.get("tags",{}).get("natural") == "water"]
                    coast = [e for e in elements if e.get("tags",{}).get("natural") in ("coastline", "bay")]
                    dist_r = _approx_distance(lat, lon, rivers[0]) if rivers else 5000
                    dist_l = _approx_distance(lat, lon, lakes[0]) if lakes else 5000
                    dist_c = _approx_distance(lat, lon, coast[0]) if coast else dist_coast_embed
                    is_coastal = bool(coast) or is_coastal_embed
                    min_dist = min(dist_r, dist_l, dist_c)
                    return {
                        "distance_river_m": dist_r,
                        "distance_lake_m": dist_l,
                        "distance_coast_m": dist_c,
                        "is_coastal": is_coastal,
                        "sea_name": sea_name,
                        "in_buffer_150m": min_dist < 150,
                        "in_fascia_300m_costiera": dist_c < 300,
                        "real": True
                    }
    except Exception:
        pass

    # OSM unavailable — use embedded coastal detection
    in_fascia = is_coastal_embed and dist_coast_embed < 300
    print(f"[Water] OSM unavailable. Coastal embed: is_coastal={is_coastal_embed} dist={dist_coast_embed:.0f}m sea={sea_name}")
    return {
        "distance_river_m": 1000,
        "distance_lake_m": 5000,
        "distance_coast_m": dist_coast_embed,
        "is_coastal": is_coastal_embed,
        "sea_name": sea_name,
        "in_buffer_150m": False,
        "in_fascia_300m_costiera": in_fascia,
        "real": is_coastal_embed  # real if we detected coast from embedded data
    }

def _approx_distance(lat, lon, element) -> float:
    c = element.get("center", element)
    elat = c.get("lat", lat)
    elon = c.get("lon", lon)
    return ((lat-elat)**2 + (lon-elon)**2)**0.5 * 111000

def _geojson_bbox(geojson: dict) -> tuple:
    from shapely.geometry import shape, mapping
    try:
        if geojson.get("type") == "Feature":
            geom = shape(geojson["geometry"])
        else:
            geom = shape(geojson)
        b = geom.bounds
        return (b[0], b[1], b[2], b[3])
    except Exception:
        return (-180, -90, 180, 90)

from backend.connectors.copernicus import fetch_copernicus
from backend.connectors.geoportale import fetch_geoportale

# ─── Master connector ─────────────────────────────────────────────────────────

async def fetch_all_data(geojson: dict, lat: float, lon: float) -> dict:
    """Fetch all environmental data in parallel"""
    results = await asyncio.gather(
        get_ispra_hydrogeological(geojson, lat, lon),
        get_ingv_seismic(lat, lon),
        get_natura2000(geojson, lat, lon),
        fetch_copernicus(geojson, lat, lon),
        get_air_quality(lat, lon),
        get_water_bodies(lat, lon),
        fetch_geoportale(geojson, lat, lon),
        return_exceptions=True
    )
    keys = ["ispra", "ingv", "natura2000", "corine", "air_quality", "water", "geoportale"]
    data = {}
    for k, r in zip(keys, results):
        data[k] = r if not isinstance(r, Exception) else {}

    # Merge Geoportale Natura2000 if better than EEA
    geo = data.get("geoportale", {})
    n2k_it = geo.get("natura2000_it", {})
    if n2k_it.get("real"):
        data["natura2000"] = n2k_it  # prefer official Italian source

    corine = data.get("corine", {})
    print(f"[LandCover] source={corine.get('source','fallback')} class={corine.get('dominant_class','?')} ndvi={corine.get('ndvi_proxy','?')} art={corine.get('artificial_pct','?')}%")
    return data
