"""
Risk Engine — R = P × G × E
P = Probability/Hazard (0-1)
G = Gravity/Magnitude (0-1)  
E = Exposure of receptors (0-1)

All scores are deterministic, documented, with sources.
LLM only interprets results, never calculates them.
"""
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class RiskIndicator:
    name: str
    score: float          # 0-100
    p: float              # hazard probability 0-1
    g: float              # gravity 0-1
    e: float              # exposure 0-1
    level: str            # TRASCURABILE/BASSO/MEDIO/ALTO/MOLTO ALTO
    source: str
    method: str
    uncertainty: str      # LOW/MEDIUM/HIGH
    notes: str = ""

def score_to_level(score: float) -> str:
    if score >= 80: return "MOLTO ALTO"
    if score >= 60: return "ALTO"
    if score >= 40: return "MEDIO"
    if score >= 20: return "BASSO"
    return "TRASCURABILE"

def compute_risk(p: float, g: float, e: float) -> float:
    """R = P × G × E, normalized to 0-100"""
    return round(min(100, p * g * e * 100), 1)

def assess_hydrogeological(ispra_data: dict, area_m2: float, dtm_data: dict = None) -> RiskIndicator:
    """
    Hydrogeological risk from ISPRA IdroGEO PAI + DTM slope.
    P4=very high, P3=high, P2=medium, P1=low
    """
    frane = ispra_data.get("frane", {})
    alluvioni = ispra_data.get("alluvioni", {})

    p_frana = {4: 0.9, 3: 0.7, 2: 0.4, 1: 0.2}.get(frane.get("max_class", 0), 0.1)
    p_alluvione = {4: 0.9, 3: 0.7, 2: 0.4, 1: 0.2}.get(alluvioni.get("max_class", 0), 0.1)
    p = max(p_frana, p_alluvione)

    # Refine P with slope from DTM
    if dtm_data and dtm_data.get("real"):
        slope = dtm_data.get("slope_mean_deg", 5.0)
        slope_factor = min(1.3, 1.0 + slope / 100)  # +30% max for steep terrain
        p = min(1.0, p * slope_factor)
        slope_note = f" | Pendenza: {slope:.1f}° ({dtm_data.get('slope_class','?')})"
        elev_note = f" | Quota: {dtm_data.get('elev_mean_m', 0):.0f}m"
    else:
        slope_note = ""
        elev_note = ""

    affected_pct = ispra_data.get("affected_pct", 0)
    g = min(1.0, affected_pct / 100 * 1.5 + 0.2)
    e = min(1.0, 0.3 + (area_m2 / 100000) * 0.3)

    score = compute_risk(p, g, e)
    uncertainty = "MEDIUM" if ispra_data.get("real") else "HIGH"
    if dtm_data and dtm_data.get("real"):
        uncertainty = "LOW" if ispra_data.get("real") else "MEDIUM"

    return RiskIndicator(
        name="Rischio Idrogeologico",
        score=score, p=p, g=g, e=e,
        level=score_to_level(score),
        source="ISPRA IdroGEO - PAI" + (" + PCN DTM" if dtm_data and dtm_data.get("real") else ""),
        method="R = P × G × E | Classi PAI P1-P4 + slope DTM",
        uncertainty=uncertainty,
        notes=f"Frana P{frane.get('max_class',0)}, Alluvione P{alluvioni.get('max_class',0)}, Area interessata: {affected_pct:.0f}%{slope_note}{elev_note}"
    )

def assess_seismic(ingv_data: dict, project_type: str) -> RiskIndicator:
    """
    Seismic risk from INGV MPS04.
    PGA at 475yr return period.
    """
    pga = ingv_data.get("pga_475", 0.05)

    # Hazard: PGA normalized (Italy range 0.025-0.275g)
    p = min(1.0, (pga - 0.025) / 0.25)

    # Gravity depends on project type
    gravity_weights = {
        "residenziale": 0.8, "industriale": 0.9,
        "viario": 0.6, "agricolo": 0.3,
        "turistico": 0.7, "energetico": 0.8
    }
    g = gravity_weights.get(project_type, 0.6)

    # Exposure: always significant for built structures
    e = 0.7

    score = compute_risk(p, g, e)
    return RiskIndicator(
        name="Rischio Sismico",
        score=score, p=p, g=g, e=e,
        level=score_to_level(score),
        source="INGV MPS04 - Mappa Pericolosità Sismica",
        method="R = P × G × E | PGA 475yr NTC2018",
        uncertainty="LOW" if ingv_data.get("real") else "MEDIUM",
        notes=f"PGA 475yr = {pga:.3f}g | Zona sismica NTC2018"
    )

def assess_biodiversity(natura2000_data: dict, corine_data: dict, hydro_data: dict = None) -> RiskIndicator:
    """Impact on biodiversity from Natura 2000, land cover and coastal proximity"""
    intersects_n2k = natura2000_data.get("intersects", False)
    distance_n2k = natura2000_data.get("distance_m", 10000)

    # Coastal areas: high biodiversity sensitivity even without explicit N2000
    is_coastal = hydro_data.get("is_coastal", False) if hydro_data else False
    dist_coast = hydro_data.get("distance_coast_m", 5000) if hydro_data else 5000
    if is_coastal and not intersects_n2k:
        # Italian coasts are almost always Natura 2000 or equivalent
        distance_n2k = min(distance_n2k, dist_coast * 2)

    cls_type = corine_data.get("dominant_type", "")
    if not cls_type:
        habitat_type = corine_data.get("dominant_class", "").lower()
        natural_habitats = ["forest", "scrub", "wetland", "water", "grassland", "wood", "heath", "coast", "beach"]
        cls_type = "forests" if any(h in habitat_type for h in natural_habitats) else "unknown"

    natural_types = {"forests", "scrub", "wetlands", "water", "grasslands"}
    is_natural = cls_type in natural_types or is_coastal

    ndvi = corine_data.get("ndvi_proxy", 0.3)
    ndvi_factor = min(1.0, 0.5 + ndvi * 0.6)

    p = 0.9 if intersects_n2k else max(0.1, 1 - distance_n2k / 5000)
    if is_coastal:
        p = max(p, 0.75)  # coasts always high sensitivity
    g = min(1.0, (0.9 if is_natural else 0.4) * ndvi_factor)
    e = 0.8 if intersects_n2k else (0.7 if is_coastal else 0.4)

    score = compute_risk(p, g, e)
    source_label = corine_data.get("source", "CORINE Land Cover")
    coastal_note = " | AREA COSTIERA — alta sensibilità ecologica" if is_coastal else ""
    return RiskIndicator(
        name="Impatto Biodiversità",
        score=score, p=p, g=g, e=e,
        level=score_to_level(score),
        source=f"Rete Natura 2000 / {source_label}",
        method="R = P × G × E | Distanza SIC/ZSC/ZPS + NDVI + costa",
        uncertainty="LOW" if corine_data.get("real") else "MEDIUM",
        notes=f"{'INTERSECA' if intersects_n2k else f'Distanza: {distance_n2k:.0f}m'} da Natura 2000 | "
              f"Uso suolo: {corine_data.get('dominant_class','Unknown')} | NDVI: {ndvi:.2f}{coastal_note}"
    )

def assess_air_quality(aq_data: dict) -> RiskIndicator:
    """Air quality impact"""
    pm25 = aq_data.get("pm25", 10)
    pm10 = aq_data.get("pm10", 20)
    no2 = aq_data.get("no2", 20)

    # EU limit values: PM2.5=25, PM10=40, NO2=40 μg/m³
    p = min(1.0, max(pm25/25, pm10/40, no2/40))
    g = 0.6
    e = 0.7

    score = compute_risk(p, g, e)
    return RiskIndicator(
        name="Qualità dell'Aria",
        score=score, p=p, g=g, e=e,
        level=score_to_level(score),
        source="ARPA / OpenAQ",
        method="R = P × G × E | Limiti Dir. 2008/50/CE",
        uncertainty="MEDIUM" if aq_data.get("real") else "HIGH",
        notes=f"PM2.5={pm25}μg/m³ (lim.25) | PM10={pm10}μg/m³ (lim.40) | NO2={no2}μg/m³ (lim.40)"
    )

def assess_soil_consumption(area_m2: float, corine_data: dict) -> RiskIndicator:
    """Soil consumption and impermeabilization"""
    cls_type = corine_data.get("dominant_type", "")
    current_use = corine_data.get("dominant_class", "unknown")
    artificial = corine_data.get("artificial_pct", 20.0)

    # Agricultural or natural land conversion is more critical
    agricultural_types = {"arable", "grasslands", "scrub"}
    natural_types = {"forests", "wetlands"}
    is_agricultural = cls_type in agricultural_types
    is_natural = cls_type in natural_types

    if is_natural:
        p = 0.95
    elif is_agricultural:
        p = 0.85
    elif cls_type == "artificial":
        p = 0.3  # already artificial, lower impact
    else:
        p = 0.5

    g = min(1.0, area_m2 / 50000)
    e = 0.6

    # Imperviousness from Copernicus reduces e if already sealed
    imp = corine_data.get("artificial_pct", 20)
    if imp > 70:
        e = 0.3  # already mostly sealed

    score = compute_risk(p, g, e)
    source_label = corine_data.get("source", "CORINE Land Cover / ISPRA")
    ndvi_text = f" | NDVI: {corine_data['ndvi_proxy']:.2f}" if corine_data.get("ndvi_proxy") else ""
    return RiskIndicator(
        name="Consumo di Suolo",
        score=score, p=p, g=g, e=e,
        level=score_to_level(score),
        source=source_label,
        method="R = P × G × E | ISPRA Consumo Suolo + Copernicus",
        uncertainty="LOW" if corine_data.get("real") else "MEDIUM",
        notes=f"Uso attuale: {current_use} | Area: {area_m2:.0f}m² | Impermeabile: {artificial:.0f}%{ndvi_text}"
    )

def assess_water(hydro_data: dict) -> RiskIndicator:
    """Water bodies impact including coastline"""
    distance_river = hydro_data.get("distance_river_m", 5000)
    distance_lake = hydro_data.get("distance_lake_m", 5000)
    distance_coast = hydro_data.get("distance_coast_m", 5000)
    in_buffer_150 = hydro_data.get("in_buffer_150m", False)
    is_coastal = hydro_data.get("is_coastal", False)
    in_fascia_300 = hydro_data.get("in_fascia_300m_costiera", False)

    min_dist = min(distance_river, distance_lake, distance_coast)

    # Coastal areas: fascia 300m = vincolo art.142 D.Lgs 42/2004
    if is_coastal or in_fascia_300:
        p = 0.95
        g = 0.85
        e = 0.80
        sea = hydro_data.get("sea_name", "")
        notes_extra = f"AREA COSTIERA {sea} — fascia 300m art.142 D.Lgs 42/2004 | Costa a {distance_coast:.0f}m"
    elif in_buffer_150:
        p = 0.9
        g = 0.7
        e = 0.6
        notes_extra = f"Fascia 150m corso d'acqua! | Distanza: {distance_river:.0f}m"
    else:
        p = min(1.0, max(0.1, 1 - min_dist / 2000))
        g = 0.7
        e = 0.6
        notes_extra = f"Distanza corso d'acqua: {distance_river:.0f}m | Fuori fascia"

    score = compute_risk(p, g, e)
    return RiskIndicator(
        name="Impatto Idrico",
        score=score, p=p, g=g, e=e,
        level=score_to_level(score),
        source="Reticolo Idrografico / OSM",
        method="R = P × G × E | D.Lgs 152/2006 art.115 + D.Lgs 42/2004 art.142",
        uncertainty="MEDIUM" if hydro_data.get("real") else "HIGH",
        notes=notes_extra
    )

def compute_global_risk(indicators: list) -> dict:
    weights = {
        "Rischio Idrogeologico": 0.25,
        "Rischio Sismico": 0.20,
        "Impatto Biodiversità": 0.20,
        "Qualità dell'Aria": 0.10,
        "Consumo di Suolo": 0.15,
        "Impatto Idrico": 0.10,
    }
    total_weight = 0
    weighted_sum = 0
    for ind in indicators:
        w = weights.get(ind.name, 0.1)
        weighted_sum += ind.score * w
        total_weight += w

    global_score = round(weighted_sum / total_weight, 1) if total_weight > 0 else 0
    return {
        "global_score": float(global_score),
        "global_level": score_to_level(global_score),
        "via_screening": _via_screening(global_score, indicators),
        "indicators": [
            {
                "name": i.name,
                "score": float(i.score),
                "level": i.level,
                "p": float(i.p),
                "g": float(i.g),
                "e": float(i.e),
                "source": i.source,
                "method": i.method,
                "uncertainty": i.uncertainty,
                "notes": i.notes
            } for i in indicators
        ]
    }

def _via_screening(score: float, indicators: list) -> str:
    """Preliminary VIA/VAS screening indication"""
    high_risks = [i for i in indicators if i.score >= 60]
    if score >= 60 or len(high_risks) >= 2:
        return "VERIFICA VIA PROBABILE — Presenza di criticità significative. Consultare autorità competente."
    elif score >= 40:
        return "VERIFICA PRELIMINARE CONSIGLIATA — Approfondire le criticità rilevate."
    else:
        return "IMPATTO POTENZIALMENTE LIMITATO — Verificare con autorità competente per tipologia progetto."
