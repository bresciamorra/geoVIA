"""
Scenario Comparison Engine
Analizza 2-3 localizzazioni alternative e le rankea per rischio ambientale.
Deterministico — nessun LLM.
"""
from backend.gis_engine import compute_area_m2, compute_centroid
from backend.risk_engine import (assess_hydrogeological, assess_seismic, assess_biodiversity,
                                  assess_air_quality, assess_soil_consumption, assess_water,
                                  compute_global_risk)
from backend.connectors import fetch_all_data


async def analyze_scenario(geojson: dict, project_type: str, label: str) -> dict:
    """Analyze a single scenario polygon."""
    lat, lon = compute_centroid(geojson)
    area_m2 = compute_area_m2(geojson)
    env_data = await fetch_all_data(geojson, lat, lon)

    indicators = [
        assess_hydrogeological(env_data.get("ispra", {}), area_m2),
        assess_seismic(env_data.get("ingv", {}), project_type),
        assess_biodiversity(env_data.get("natura2000", {}), env_data.get("corine", {})),
        assess_air_quality(env_data.get("air_quality", {})),
        assess_soil_consumption(area_m2, env_data.get("corine", {})),
        assess_water(env_data.get("water", {})),
    ]
    result = compute_global_risk(indicators)
    result["label"] = label
    result["lat"] = lat
    result["lon"] = lon
    result["area_m2"] = area_m2
    result["geojson"] = geojson
    return result


def rank_scenarios(scenarios: list) -> dict:
    """
    Rank scenarios by global score (lower = better).
    Returns ranked list with delta analysis.
    """
    ranked = sorted(scenarios, key=lambda s: s["global_score"])
    best = ranked[0]

    for i, s in enumerate(ranked):
        s["rank"] = i + 1
        s["delta_vs_best"] = round(s["global_score"] - best["global_score"], 1)
        s["delta_pct"] = round((s["global_score"] - best["global_score"]) / max(best["global_score"], 1) * 100, 1)

        # Per-indicator comparison vs best
        best_ind = {ind["name"]: ind["score"] for ind in best["indicators"]}
        s["indicator_deltas"] = {
            ind["name"]: round(ind["score"] - best_ind.get(ind["name"], 0), 1)
            for ind in s["indicators"]
        }

        # Key advantages/disadvantages vs best
        if i > 0:
            worse = [k for k, v in s["indicator_deltas"].items() if v > 5]
            better = [k for k, v in s["indicator_deltas"].items() if v < -5]
            s["worse_than_best"] = worse
            s["better_than_best"] = better
        else:
            s["worse_than_best"] = []
            s["better_than_best"] = []

    # Summary recommendation
    recommendation = _build_recommendation(ranked)

    return {
        "ranked": ranked,
        "best_label": best["label"],
        "recommendation": recommendation,
        "count": len(ranked)
    }


def _build_recommendation(ranked: list) -> str:
    best = ranked[0]
    if len(ranked) == 1:
        return f"Unico scenario analizzato: {best['label']} con rischio {best['global_score']}/100 ({best['global_level']})."

    second = ranked[1]
    delta = second["delta_vs_best"]
    reasons = []

    for ind in best["indicators"]:
        second_ind = next((i for i in second["indicators"] if i["name"] == ind["name"]), None)
        if second_ind and (second_ind["score"] - ind["score"]) > 8:
            reasons.append(ind["name"].replace("Rischio ", "").replace("Impatto ", ""))

    reason_text = f" — migliore su: {', '.join(reasons)}" if reasons else ""
    return (f"Localizzazione consigliata: {best['label']} "
            f"(score {best['global_score']}/100, {best['global_level']}){reason_text}. "
            f"Risparmio rischio vs alternativa: {delta} punti ({second['delta_pct']}%).")
