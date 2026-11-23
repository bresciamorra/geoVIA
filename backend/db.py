"""
Database abstraction — SpatiaLite today, PostGIS tomorrow.
Same interface, change only DB_URL env var.
"""
import os
import sqlite3
import geopandas as gpd
from shapely.geometry import shape
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "data/geovia.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    try:
        conn.load_extension("mod_spatialite")
    except Exception:
        pass  # spatialite not available, basic sqlite only
    return conn

def init_db():
    Path("data").mkdir(exist_ok=True)
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            project_type TEXT,
            description TEXT,
            geojson TEXT,
            centroid_lat REAL,
            centroid_lon REAL,
            area_m2 REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(id),
            analysis_type TEXT,
            result_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(id),
            filename TEXT,
            extracted_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

def save_project(name, project_type, description, geojson, centroid_lat, centroid_lon, area_m2):
    import json
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO projects (name, project_type, description, geojson, centroid_lat, centroid_lon, area_m2) VALUES (?,?,?,?,?,?,?)",
        (name, project_type, description, json.dumps(geojson), centroid_lat, centroid_lon, area_m2)
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid

def save_analysis(project_id, analysis_type, result):
    import json
    conn = get_conn()
    conn.execute(
        "INSERT INTO analyses (project_id, analysis_type, result_json) VALUES (?,?,?)",
        (project_id, analysis_type, json.dumps(result))
    )
    conn.commit()
    conn.close()

def get_projects():
    conn = get_conn()
    rows = conn.execute("SELECT id, name, project_type, centroid_lat, centroid_lon, area_m2, created_at FROM projects ORDER BY created_at DESC").fetchall()
    conn.close()
    return [{"id":r[0],"name":r[1],"type":r[2],"lat":r[3],"lon":r[4],"area_m2":r[5],"created_at":r[6]} for r in rows]

def get_project(pid):
    import json
    conn = get_conn()
    r = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not r:
        return None
    return {"id":r[0],"name":r[1],"type":r[2],"description":r[3],"geojson":json.loads(r[4]),"lat":r[5],"lon":r[6],"area_m2":r[7],"created_at":r[8]}
