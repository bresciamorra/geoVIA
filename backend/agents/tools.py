"""
Tool definitions for the ReAct orchestrator.
Each tool has:
  - schema: JSON schema for Ollama function calling
  - execute(args, context) -> ToolResult

ToolResult always includes:
  - data: the actual result
  - source: data source name
  - real: bool — True if from real API, False if estimated
  - uncertainty: LOW / MEDIUM / HIGH
  - note: human-readable explanation of data quality
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    data: Any
    source: str
    real: bool
    uncertainty: str  # LOW / MEDIUM / HIGH
    note: str = ""

    def to_llm_str(self) -> str:
        """Format for LLM consumption — explicit about data quality"""
        quality = "DATO REALE" if self.real else "STIMA (verificare con fonte ufficiale)"
        return f"[{quality} | Fonte: {self.source} | Incertezza: {self.uncertainty}]\n{self.data}\n{self.note}"


# ── TOOL SCHEMAS (OpenAI-compatible for Ollama) ───────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_territory_state",
            "description": "Recupera lo stato attuale del territorio (S0): land cover, pendenza, quota, corpi idrici, vincoli. Da chiamare sempre come primo passo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geojson": {"type": "string", "description": "GeoJSON del poligono come stringa JSON"},
                },
                "required": ["geojson"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compute_risk_indicators",
            "description": "Calcola i 6 indicatori di rischio ambientale (idrogeologico, sismico, biodiversità, aria, suolo, idrico) con il motore R=P×G×E. Richiede lo stato del territorio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geojson": {"type": "string"},
                    "project_type": {"type": "string", "description": "Tipo progetto: residenziale, industriale, energetico, viario, agricolo, turistico, commerciale"},
                    "area_m2": {"type": "number", "description": "Superficie progetto in m²"}
                },
                "required": ["geojson", "project_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_intervention",
            "description": "Simula gli impatti di un intervento edilizio/infrastrutturale sul territorio (what-if). Calcola variazioni di deflusso, infiltrazione, UHI, NDVI, consumo suolo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geojson": {"type": "string"},
                    "building_m2": {"type": "number", "description": "Superficie edificata impermeabile"},
                    "road_m2": {"type": "number", "description": "Strade e parcheggi"},
                    "green_m2": {"type": "number", "description": "Verde mantenuto o creato"},
                    "permeable_m2": {"type": "number", "description": "Pavimentazione drenante"},
                    "rainfall_mm": {"type": "number", "description": "Pioggia di progetto in mm (default 50)"}
                },
                "required": ["geojson"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_normative_constraints",
            "description": "Verifica i vincoli normativi applicabili: Natura 2000, vincoli paesaggistici D.Lgs 42/2004, PAI, fasce fluviali, aree protette. Identifica blocchi procedurali.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geojson": {"type": "string"},
                    "project_type": {"type": "string"},
                    "global_score": {"type": "number", "description": "Score rischio globale 0-100"}
                },
                "required": ["geojson", "project_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_mase_precedents",
            "description": "Cerca precedenti VIA/VAS simili nel database MASE per tipo progetto e regione. Restituisce esiti, prescrizioni tipiche e tempi procedurali.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_type": {"type": "string"},
                    "region": {"type": "string", "description": "Regione italiana (es. Campania, Puglia)"},
                    "lat": {"type": "number"},
                    "lon": {"type": "number"}
                },
                "required": ["project_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_locations",
            "description": "Confronta 2-3 localizzazioni alternative e le rankea per rischio ambientale. Utile per scegliere il sito migliore.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenarios": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "geojson": {"type": "string"}
                            }
                        }
                    },
                    "project_type": {"type": "string"}
                },
                "required": ["scenarios", "project_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_dtm_analysis",
            "description": "Analisi morfologica del territorio: quota, pendenza, classe morfologica (pianura/collina/montagna/ripido). Fondamentale per rischio idrogeologico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "geojson": {"type": "string"},
                    "lat": {"type": "number"},
                    "lon": {"type": "number"}
                },
                "required": ["geojson"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_mitigations",
            "description": "Genera misure di mitigazione specifiche per il sito basate sui rischi calcolati e sugli impatti dell'intervento. Include effetto quantificato e riferimento normativo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "risk_indicators": {"type": "string", "description": "JSON degli indicatori di rischio"},
                    "whatif_impacts": {"type": "string", "description": "JSON degli impatti what-if (opzionale)"},
                    "project_type": {"type": "string"}
                },
                "required": ["risk_indicators", "project_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_via_procedure",
            "description": "Stima tempi, costi e complessità della procedura VIA/VAS basandosi su tipo progetto, rischio globale e vincoli presenti.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_type": {"type": "string"},
                    "global_score": {"type": "number"},
                    "has_vincoli": {"type": "boolean"},
                    "region": {"type": "string"}
                },
                "required": ["project_type", "global_score"]
            }
        }
    }
]


# ── TOOL EXECUTORS ────────────────────────────────────────────────────────────

async def execute_tool(name: str, args: dict, context: dict) -> ToolResult:
    """Route tool call to the appropriate executor"""
    executors = {
        "get_territory_state":      _exec_territory_state,
        "compute_risk_indicators":  _exec_risk_indicators,
        "simulate_intervention":    _exec_simulate,
        "check_normative_constraints": _exec_constraints,
        "get_mase_precedents":      _exec_mase,
        "compare_locations":        _exec_compare,
        "get_dtm_analysis":         _exec_dtm,
        "suggest_mitigations":      _exec_mitigations,
        "estimate_via_procedure":   _exec_via_estimate,
    }
    executor = executors.get(name)
    if not executor:
        return ToolResult(data=f"Tool '{name}' non trovato", source="system", real=False, uncertainty="HIGH")
    try:
        return await executor(args, context)
    except Exception as e:
        return ToolResult(data=f"Errore esecuzione tool: {e}", source="system", real=False, uncertainty="HIGH",
                          note="Errore interno — verificare i parametri")


async def _exec_territory_state(args: dict, context: dict) -> ToolResult:
    import json
    from backend.connectors import fetch_all_data
    from backend.connectors.geoportale import fetch_geoportale
    from backend.gis_engine import compute_centroid, compute_area_m2

    geojson = json.loads(args["geojson"]) if isinstance(args["geojson"], str) else args["geojson"]
    lat, lon = compute_centroid(geojson)
    area_m2 = compute_area_m2(geojson)

    env_data, geo_data = await asyncio.gather(
        fetch_all_data(geojson, lat, lon),
        fetch_geoportale(geojson, lat, lon),
        return_exceptions=True
    )
    if isinstance(env_data, Exception): env_data = {}
    if isinstance(geo_data, Exception): geo_data = {}

    corine = env_data.get("corine", {})
    water = env_data.get("water", {})
    dtm = geo_data.get("dtm", {})
    vincoli = geo_data.get("vincoli", {})
    n2k = env_data.get("natura2000", {})

    summary = {
        "lat": lat, "lon": lon, "area_m2": area_m2,
        "land_cover": corine.get("dominant_class", "Unknown"),
        "land_type": corine.get("dominant_type", "unknown"),
        "ndvi": corine.get("ndvi_proxy", 0.3),
        "artificial_pct": corine.get("artificial_pct", 20),
        "elevation_m": dtm.get("elev_mean_m", "N/D"),
        "slope_deg": dtm.get("slope_mean_deg", "N/D"),
        "slope_class": dtm.get("slope_class", "N/D"),
        "is_coastal": water.get("is_coastal", False),
        "distance_water_m": min(water.get("distance_river_m", 5000), water.get("distance_coast_m", 5000)),
        "natura2000_intersects": n2k.get("intersects", False),
        "natura2000_distance_m": n2k.get("distance_m", 10000),
        "vincoli_count": vincoli.get("count", 0),
        "vincoli_bloccanti": len(vincoli.get("blocchi_procedurali", [])),
    }

    real = corine.get("real", False) or dtm.get("real", False)
    return ToolResult(
        data=summary, source="Copernicus + PCN + OSM",
        real=real, uncertainty="MEDIUM" if real else "HIGH",
        note="Stato territorio S0. " + ("Dati reali da API." if real else "Dati stimati — API non raggiungibili dalla rete corrente.")
    )


async def _exec_risk_indicators(args: dict, context: dict) -> ToolResult:
    import json
    from backend.connectors import fetch_all_data
    from backend.connectors.geoportale import fetch_geoportale
    from backend.gis_engine import compute_centroid, compute_area_m2
    from backend.risk_engine import (assess_hydrogeological, assess_seismic, assess_biodiversity,
                                      assess_air_quality, assess_soil_consumption, assess_water,
                                      compute_global_risk)

    geojson = json.loads(args["geojson"]) if isinstance(args["geojson"], str) else args["geojson"]
    project_type = args.get("project_type", "industriale")
    lat, lon = compute_centroid(geojson)
    area_m2 = args.get("area_m2") or compute_area_m2(geojson)

    env_data, geo_data = await asyncio.gather(
        fetch_all_data(geojson, lat, lon),
        fetch_geoportale(geojson, lat, lon),
        return_exceptions=True
    )
    if isinstance(env_data, Exception): env_data = {}
    if isinstance(geo_data, Exception): geo_data = {}

    dtm = geo_data.get("dtm", {}) if isinstance(geo_data, dict) else {}
    indicators = [
        assess_hydrogeological(env_data.get("ispra", {}), area_m2, dtm),
        assess_seismic(env_data.get("ingv", {}), project_type),
        assess_biodiversity(env_data.get("natura2000", {}), env_data.get("corine", {}), env_data.get("water", {})),
        assess_air_quality(env_data.get("air_quality", {})),
        assess_soil_consumption(area_m2, env_data.get("corine", {})),
        assess_water(env_data.get("water", {})),
    ]
    result = compute_global_risk(indicators)

    real_count = sum(1 for k in ["ispra", "ingv", "natura2000", "corine"] if env_data.get(k, {}).get("real"))
    uncertainty = "LOW" if real_count >= 3 else "MEDIUM" if real_count >= 1 else "HIGH"

    return ToolResult(
        data=result, source="ISPRA + INGV + EEA + Copernicus",
        real=real_count > 0, uncertainty=uncertainty,
        note=f"{real_count}/4 fonti con dati reali. Score globale: {result['global_score']}/100 ({result['global_level']})"
    )


async def _exec_simulate(args: dict, context: dict) -> ToolResult:
    import json
    from backend.connectors.copernicus import fetch_copernicus
    from backend.gis_engine import compute_centroid, compute_area_m2
    from backend.whatif import compute_whatif

    geojson = json.loads(args["geojson"]) if isinstance(args["geojson"], str) else args["geojson"]
    lat, lon = compute_centroid(geojson)
    area_m2 = compute_area_m2(geojson)
    corine = await fetch_copernicus(geojson, lat, lon)
    intervention = {k: args.get(k, 0) for k in ["building_m2", "road_m2", "green_m2", "permeable_m2"]}
    rainfall = args.get("rainfall_mm", 50.0)
    result = compute_whatif(area_m2, corine, intervention, rainfall)

    return ToolResult(
        data=result, source="Motore CN/SCS + UHI + Copernicus",
        real=corine.get("real", False), uncertainty="MEDIUM",
        note=f"Impatto globale: {result['impact_level']} ({result['impact_score']}/100). Metodo CN curve number SCS/NRCS."
    )


async def _exec_constraints(args: dict, context: dict) -> ToolResult:
    import json
    from backend.connectors.geoportale import get_vincoli_paesaggistici, get_natura2000_it
    from backend.gis_engine import compute_centroid
    from backend.prescriptions import get_probable_prescriptions

    geojson = json.loads(args["geojson"]) if isinstance(args["geojson"], str) else args["geojson"]
    project_type = args.get("project_type", "industriale")
    global_score = args.get("global_score", 50)
    lat, lon = compute_centroid(geojson)

    vincoli, n2k = await asyncio.gather(
        get_vincoli_paesaggistici(geojson, lat, lon),
        get_natura2000_it(geojson, lat, lon),
        return_exceptions=True
    )
    if isinstance(vincoli, Exception): vincoli = {}
    if isinstance(n2k, Exception): n2k = {}

    # Dummy indicators for prescriptions
    presc = get_probable_prescriptions(project_type, [], "", global_score)

    result = {
        "vincoli_paesaggistici": vincoli.get("vincoli_paesaggistici", []),
        "aree_protette": vincoli.get("aree_protette", []),
        "blocchi_procedurali": vincoli.get("blocchi_procedurali", []),
        "natura2000": {"intersects": n2k.get("intersects", False), "distance_m": n2k.get("distance_m", 10000)},
        "prescrizioni_probabili": presc["prescriptions"][:5],
        "via_estimate": presc["via_estimate"],
    }
    blocchi = len(result["blocchi_procedurali"])
    return ToolResult(
        data=result, source="PCN/MASE + Natura 2000",
        real=vincoli.get("real", False), uncertainty="MEDIUM",
        note=f"{blocchi} vincoli bloccanti rilevati. Stima procedura: {presc['via_estimate']['months_estimate']} mesi."
    )


async def _exec_mase(args: dict, context: dict) -> ToolResult:
    from backend.modules.mase_rag import get_mase_precedents
    result = await get_mase_precedents(
        args.get("project_type", ""),
        args.get("region", ""),
        args.get("lat", 0), args.get("lon", 0)
    )
    return ToolResult(
        data=result, source="Database MASE (10 precedenti embedded)",
        real=True, uncertainty="MEDIUM",
        note=f"{len(result.get('precedents', []))} precedenti trovati per tipo '{args.get('project_type')}'."
    )


async def _exec_compare(args: dict, context: dict) -> ToolResult:
    import json
    from backend.scenario import analyze_scenario, rank_scenarios
    scenarios_raw = args.get("scenarios", [])
    project_type = args.get("project_type", "")
    tasks = []
    for s in scenarios_raw[:3]:
        geojson = json.loads(s["geojson"]) if isinstance(s["geojson"], str) else s["geojson"]
        tasks.append(analyze_scenario(geojson, project_type, s.get("label", "?")))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    valid = [r for r in results if not isinstance(r, Exception)]
    if not valid:
        return ToolResult(data={}, source="scenario engine", real=False, uncertainty="HIGH", note="Nessuno scenario analizzato")
    ranked = rank_scenarios(valid)
    return ToolResult(
        data=ranked, source="Risk Engine comparativo",
        real=True, uncertainty="MEDIUM",
        note=ranked.get("recommendation", "")
    )


async def _exec_dtm(args: dict, context: dict) -> ToolResult:
    import json
    from backend.connectors.geoportale import get_dtm
    from backend.gis_engine import compute_centroid
    geojson = json.loads(args["geojson"]) if isinstance(args["geojson"], str) else args["geojson"]
    lat = args.get("lat") or compute_centroid(geojson)[0]
    lon = args.get("lon") or compute_centroid(geojson)[1]
    result = await get_dtm(geojson, lat, lon)
    return ToolResult(
        data=result, source=result.get("source", "DTM"),
        real=result.get("real", False), uncertainty="LOW" if result.get("real") else "MEDIUM",
        note=f"Quota: {result.get('elev_mean_m','N/D')}m | Pendenza: {result.get('slope_mean_deg','N/D')}° ({result.get('slope_class','N/D')})"
    )


async def _exec_mitigations(args: dict, context: dict) -> ToolResult:
    import json
    from backend.prescriptions import get_probable_prescriptions
    indicators = json.loads(args["risk_indicators"]) if isinstance(args["risk_indicators"], str) else args["risk_indicators"]
    if isinstance(indicators, dict):
        indicators = indicators.get("indicators", [])
    project_type = args.get("project_type", "")
    presc = get_probable_prescriptions(project_type, indicators, "", 0)
    return ToolResult(
        data=presc["prescriptions"], source="Knowledge base prescrizioni MASE",
        real=True, uncertainty="LOW",
        note=f"{len(presc['prescriptions'])} misure di mitigazione identificate."
    )


async def _exec_via_estimate(args: dict, context: dict) -> ToolResult:
    from backend.prescriptions import _estimate_via_timing
    result = _estimate_via_timing(args.get("global_score", 50), args.get("project_type", ""))
    if args.get("has_vincoli"):
        result["months_estimate"] += 6
        result["note"] += " (+6 mesi per vincoli paesaggistici)"
    return ToolResult(
        data=result, source="Stima statistica da storico MASE",
        real=False, uncertainty="MEDIUM",
        note=f"Stima indicativa: {result['months_estimate']} mesi, ~€{result['cost_estimate_eur']:,}"
    )
