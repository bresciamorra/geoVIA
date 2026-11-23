"""
GIS Engine — deterministic spatial analysis.
All calculations here, never in the LLM.
"""
import geopandas as gpd
import numpy as np
from shapely.geometry import shape, Point, mapping
from shapely.ops import transform
import pyproj
import httpx
import asyncio
from functools import partial

def geojson_to_gdf(geojson: dict) -> gpd.GeoDataFrame:
    """Convert GeoJSON feature/geometry to GeoDataFrame in WGS84"""
    if geojson.get("type") == "Feature":
        geom = shape(geojson["geometry"])
    elif geojson.get("type") in ("Polygon","MultiPolygon","Point","LineString"):
        geom = shape(geojson)
    else:
        geom = shape(geojson)
    gdf = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")
    return gdf

def compute_area_m2(geojson: dict) -> float:
    """Compute area in square meters using UTM projection"""
    gdf = geojson_to_gdf(geojson)
    centroid = gdf.geometry.iloc[0].centroid
    utm_zone = int((centroid.x + 180) / 6) + 1
    utm_crs = f"EPSG:{32600 + utm_zone}"
    gdf_utm = gdf.to_crs(utm_crs)
    return float(gdf_utm.geometry.area.iloc[0])

def compute_centroid(geojson: dict) -> tuple:
    gdf = geojson_to_gdf(geojson)
    c = gdf.geometry.iloc[0].centroid
    return (float(c.y), float(c.x))

def create_buffer(geojson: dict, distance_m: float) -> dict:
    """Create buffer around geometry, returns GeoJSON"""
    gdf = geojson_to_gdf(geojson)
    centroid = gdf.geometry.iloc[0].centroid
    utm_zone = int((centroid.x + 180) / 6) + 1
    utm_crs = f"EPSG:{32600 + utm_zone}"
    gdf_utm = gdf.to_crs(utm_crs)
    buffered = gdf_utm.geometry.buffer(distance_m)
    gdf_buf = gpd.GeoDataFrame(geometry=buffered, crs=utm_crs).to_crs("EPSG:4326")
    return mapping(gdf_buf.geometry.iloc[0])

async def query_wfs(url: str, params: dict, timeout: int = 15) -> dict:
    """Generic WFS query"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        print(f"[WFS] Error {url}: {e}")
    return {"features": []}

def spatial_intersect(geojson: dict, features: list) -> list:
    """Return features that intersect with the given geometry"""
    if not features:
        return []
    gdf_area = geojson_to_gdf(geojson)
    area_geom = gdf_area.geometry.iloc[0]
    results = []
    for feat in features:
        try:
            geom = shape(feat.get("geometry", {}))
            if area_geom.intersects(geom):
                results.append(feat)
        except Exception:
            continue
    return results

def distance_to_nearest(geojson: dict, features: list) -> float:
    """Return distance in meters to nearest feature"""
    if not features:
        return float('inf')
    gdf_area = geojson_to_gdf(geojson)
    centroid = gdf_area.geometry.iloc[0].centroid
    utm_zone = int((centroid.x + 180) / 6) + 1
    utm_crs = f"EPSG:{32600 + utm_zone}"
    proj = pyproj.Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True).transform
    pt_utm = transform(proj, centroid)
    min_dist = float('inf')
    for feat in features:
        try:
            geom = shape(feat["geometry"])
            geom_utm = transform(proj, geom)
            d = pt_utm.distance(geom_utm)
            if d < min_dist:
                min_dist = d
        except Exception:
            continue
    return min_dist
