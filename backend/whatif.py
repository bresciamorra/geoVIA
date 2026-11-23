"""
What-if Analysis Engine
Confronta stato attuale (S0) con stato post-intervento (S1).
Motore deterministico: CN method, infiltrazione, UHI, consumo suolo, habitat.
"""
import math

# ── CURVE NUMBER TABLE (SCS/NRCS) ─────────────────────────────────────────────
# CN per soil group B (typical Italian soils) — fonte: TR-55 USDA
CN_TABLE = {
    "forests":     45,   # bosco denso
    "scrub":       60,   # macchia/arbusteto
    "grasslands":  69,   # prato/pascolo
    "arable":      77,   # seminativo
    "wetlands":    85,   # zone umide
    "water":       98,   # acqua
    "artificial":  90,   # urbano esistente
    "unknown":     72,   # default
    # Post-intervento
    "building":    98,   # edificato impermeabile
    "road":        98,   # strade/parcheggi
    "green":       61,   # verde mantenuto/creato
    "permeable":   80,   # pavimentazione drenante
}

# Albedo per tipo di superficie
ALBEDO = {
    "forests": 0.18, "scrub": 0.20, "grasslands": 0.22, "arable": 0.20,
    "wetlands": 0.12, "water": 0.08, "artificial": 0.12, "unknown": 0.18,
    "building": 0.15, "road": 0.05, "green": 0.22, "permeable": 0.10,
}

# NDVI proxy per tipo
NDVI_TABLE = {
    "forests": 0.75, "scrub": 0.55, "grasslands": 0.55, "arable": 0.45,
    "wetlands": 0.60, "water": 0.05, "artificial": 0.10, "unknown": 0.30,
    "building": 0.02, "road": 0.02, "green": 0.50, "permeable": 0.05,
}

# Coefficiente infiltrazione (mm/h) per tipo
INFILTRATION_K = {
    "forests": 25, "scrub": 18, "grasslands": 15, "arable": 12,
    "wetlands": 8, "water": 0, "artificial": 2, "unknown": 10,
    "building": 0, "road": 0, "green": 15, "permeable": 8,
}


def _cn_runoff(cn: float, rainfall_mm: float = 50.0) -> float:
    """
    SCS Curve Number method.
    Q = (P - 0.2S)² / (P + 0.8S)
    S = 25400/CN - 254
    rainfall_mm: design storm (50mm = ~10yr return period for Italy)
    Returns runoff depth in mm.
    """
    if cn <= 0 or cn >= 100:
        return rainfall_mm if cn >= 100 else 0.0
    S = 25400 / cn - 254
    Ia = 0.2 * S  # initial abstraction
    if rainfall_mm <= Ia:
        return 0.0
    Q = (rainfall_mm - Ia) ** 2 / (rainfall_mm + 0.8 * S)
    return round(Q, 2)


def _weighted_cn(surfaces: list) -> float:
    """Weighted CN from list of (area_m2, cn) tuples"""
    total_area = sum(a for a, _ in surfaces)
    if total_area == 0:
        return 72.0
    return sum(a * cn for a, cn in surfaces) / total_area


def _compute_s0(area_m2: float, corine_data: dict) -> dict:
    """Compute S0 (current state) from Copernicus/CORINE data"""
    cls_type = corine_data.get("dominant_type", "unknown")
    artificial_pct = corine_data.get("artificial_pct", 20.0) / 100
    ndvi = corine_data.get("ndvi_proxy", 0.30)

    # Split area into natural and artificial
    art_area = area_m2 * artificial_pct
    nat_area = area_m2 * (1 - artificial_pct)

    cn = _weighted_cn([(nat_area, CN_TABLE.get(cls_type, 72)), (art_area, 90)])
    albedo = (ALBEDO.get(cls_type, 0.18) * (1 - artificial_pct) +
              ALBEDO["artificial"] * artificial_pct)
    infil_k = (INFILTRATION_K.get(cls_type, 10) * (1 - artificial_pct) +
               INFILTRATION_K["artificial"] * artificial_pct)

    return {
        "cn": round(cn, 1),
        "ndvi": round(ndvi, 2),
        "albedo": round(albedo, 3),
        "infiltration_k": round(infil_k, 1),
        "permeable_area_m2": round(nat_area, 0),
        "impermeable_area_m2": round(art_area, 0),
        "land_type": cls_type,
        "source": corine_data.get("source", "CORINE fallback"),
    }


def _compute_s1(area_m2: float, intervention: dict) -> dict:
    """Compute S1 (post-intervention state) from user input"""
    building_m2 = float(intervention.get("building_m2", 0))
    road_m2 = float(intervention.get("road_m2", 0))
    green_m2 = float(intervention.get("green_m2", 0))
    permeable_m2 = float(intervention.get("permeable_m2", 0))

    # Remaining area
    defined = building_m2 + road_m2 + green_m2 + permeable_m2
    remaining = max(0, area_m2 - defined)
    # Remaining treated as generic impermeable if not specified
    road_m2 += remaining * 0.5
    green_m2 += remaining * 0.5

    surfaces = [
        (building_m2, CN_TABLE["building"]),
        (road_m2, CN_TABLE["road"]),
        (green_m2, CN_TABLE["green"]),
        (permeable_m2, CN_TABLE["permeable"]),
    ]
    cn = _weighted_cn(surfaces)

    ndvi = (NDVI_TABLE["building"] * building_m2 +
            NDVI_TABLE["road"] * road_m2 +
            NDVI_TABLE["green"] * green_m2 +
            NDVI_TABLE["permeable"] * permeable_m2) / area_m2

    albedo = (ALBEDO["building"] * building_m2 +
              ALBEDO["road"] * road_m2 +
              ALBEDO["green"] * green_m2 +
              ALBEDO["permeable"] * permeable_m2) / area_m2

    infil_k = (INFILTRATION_K["building"] * building_m2 +
               INFILTRATION_K["road"] * road_m2 +
               INFILTRATION_K["green"] * green_m2 +
               INFILTRATION_K["permeable"] * permeable_m2) / area_m2

    impermeable = building_m2 + road_m2
    permeable_total = green_m2 + permeable_m2

    return {
        "cn": round(cn, 1),
        "ndvi": round(ndvi, 2),
        "albedo": round(albedo, 3),
        "infiltration_k": round(infil_k, 1),
        "permeable_area_m2": round(permeable_total, 0),
        "impermeable_area_m2": round(impermeable, 0),
        "building_m2": building_m2,
        "road_m2": road_m2,
        "green_m2": green_m2,
        "permeable_m2": permeable_m2,
    }


def _judge(delta: float, thresholds: tuple) -> tuple:
    """Returns (emoji, label) based on delta vs thresholds (medium, high)"""
    abs_d = abs(delta)
    if abs_d >= thresholds[1]:
        return ("🔴", "CRITICO")
    elif abs_d >= thresholds[0]:
        return ("🟠", "ALTO")
    elif abs_d > 0:
        return ("🟡", "MEDIO")
    else:
        return ("🟢", "TRASCURABILE")


def compute_whatif(area_m2: float, corine_data: dict, intervention: dict,
                   rainfall_mm: float = 50.0) -> dict:
    """
    Main what-if computation.
    Returns S0, S1, deltas, impacts, mitigations.
    """
    s0 = _compute_s0(area_m2, corine_data)
    s1 = _compute_s1(area_m2, intervention)

    # ── RUNOFF (CN method) ────────────────────────────────────────────────────
    q0_mm = _cn_runoff(s0["cn"], rainfall_mm)
    q1_mm = _cn_runoff(s1["cn"], rainfall_mm)
    q0_m3 = round(q0_mm * area_m2 / 1000, 1)
    q1_m3 = round(q1_mm * area_m2 / 1000, 1)
    delta_q_m3 = round(q1_m3 - q0_m3, 1)

    # ── INFILTRATION ──────────────────────────────────────────────────────────
    # Annual estimate: 200 rain events/year × 1h average
    rain_hours_year = 200
    infil0 = round(min(s0["infiltration_k"] * s0["permeable_area_m2"] / 1000 * rain_hours_year, area_m2 * 2), 0)
    infil1 = round(min(s1["infiltration_k"] * s1["permeable_area_m2"] / 1000 * rain_hours_year, area_m2 * 2), 0)
    delta_infil = round(infil1 - infil0, 0)

    # ── URBAN HEAT ISLAND ─────────────────────────────────────────────────────
    # ΔT ≈ -20 × Δalbedo + 3 × Δimp_fraction (empirical)
    delta_albedo = s1["albedo"] - s0["albedo"]
    delta_imp_frac = (s1["impermeable_area_m2"] - s0["impermeable_area_m2"]) / area_m2
    delta_T = round(-20 * delta_albedo + 3 * delta_imp_frac, 2)

    # ── NDVI / HABITAT ────────────────────────────────────────────────────────
    delta_ndvi = round(s1["ndvi"] - s0["ndvi"], 2)
    habitat_loss_m2 = max(0, s0["permeable_area_m2"] - s1["permeable_area_m2"])
    habitat_loss_pct = round(habitat_loss_m2 / area_m2 * 100, 1)

    # ── SOIL CONSUMPTION ─────────────────────────────────────────────────────
    new_impermeable = max(0, s1["impermeable_area_m2"] - s0["impermeable_area_m2"])
    soil_consumed_ha = round(new_impermeable / 10000, 3)

    # ── JUDGEMENTS ────────────────────────────────────────────────────────────
    impacts = [
        {
            "name": "Deflusso superficiale",
            "unit": "m³/evento",
            "s0": q0_m3, "s1": q1_m3,
            "delta": delta_q_m3,
            "delta_pct": round((delta_q_m3 / max(q0_m3, 1)) * 100, 1),
            **dict(zip(["emoji", "level"], _judge(delta_q_m3, (q0_m3 * 0.3, q0_m3)))),
            "note": f"Pioggia di progetto {rainfall_mm}mm | CN: {s0['cn']} → {s1['cn']}"
        },
        {
            "name": "Infiltrazione nel suolo",
            "unit": "m³/anno",
            "s0": infil0, "s1": infil1,
            "delta": delta_infil,
            "delta_pct": round((delta_infil / max(infil0, 1)) * 100, 1),
            **dict(zip(["emoji", "level"], _judge(-delta_infil, (infil0 * 0.2, infil0 * 0.5)))),
            "note": f"Superficie permeabile: {s0['permeable_area_m2']:.0f} → {s1['permeable_area_m2']:.0f} m²"
        },
        {
            "name": "Carico termico (UHI)",
            "unit": "°C stimato",
            "s0": 0.0, "s1": round(delta_T, 2),
            "delta": delta_T,
            "delta_pct": None,
            **dict(zip(["emoji", "level"], _judge(delta_T, (0.5, 1.5)))),
            "note": f"Albedo: {s0['albedo']:.2f} → {s1['albedo']:.2f} | Δimpermeabile: {delta_imp_frac*100:.0f}%"
        },
        {
            "name": "Perdita habitat/NDVI",
            "unit": "ΔNDVI",
            "s0": s0["ndvi"], "s1": s1["ndvi"],
            "delta": delta_ndvi,
            "delta_pct": round((delta_ndvi / max(s0["ndvi"], 0.01)) * 100, 1),
            **dict(zip(["emoji", "level"], _judge(-delta_ndvi, (0.1, 0.3)))),
            "note": f"Habitat perso: {habitat_loss_m2:.0f} m² ({habitat_loss_pct}%)"
        },
        {
            "name": "Consumo di suolo",
            "unit": "ha",
            "s0": 0.0, "s1": soil_consumed_ha,
            "delta": soil_consumed_ha,
            "delta_pct": None,
            **dict(zip(["emoji", "level"], _judge(soil_consumed_ha, (0.1, 0.5)))),
            "note": f"Nuovo impermeabile: {new_impermeable:.0f} m²"
        },
    ]

    # ── MITIGATIONS ───────────────────────────────────────────────────────────
    mitigations = _suggest_mitigations(s0, s1, impacts, area_m2, intervention)

    # ── GLOBAL IMPACT SCORE ───────────────────────────────────────────────────
    critical = sum(1 for i in impacts if i["level"] == "CRITICO")
    high = sum(1 for i in impacts if i["level"] == "ALTO")
    impact_score = min(100, critical * 25 + high * 12 + len([i for i in impacts if i["level"] == "MEDIO"]) * 5)
    impact_level = "CRITICO" if critical >= 2 else "ALTO" if critical >= 1 or high >= 2 else "MEDIO" if high >= 1 else "BASSO"

    return {
        "s0": s0,
        "s1": s1,
        "impacts": impacts,
        "mitigations": mitigations,
        "impact_score": impact_score,
        "impact_level": impact_level,
        "rainfall_mm": rainfall_mm,
        "area_m2": area_m2,
    }


def _suggest_mitigations(s0, s1, impacts, area_m2, intervention):
    mitigations = []
    building_m2 = float(intervention.get("building_m2", 0))
    road_m2 = float(intervention.get("road_m2", 0))

    runoff_impact = next((i for i in impacts if "Deflusso" in i["name"]), None)
    infil_impact = next((i for i in impacts if "Infiltrazione" in i["name"]), None)
    thermal_impact = next((i for i in impacts if "termico" in i["name"]), None)
    ndvi_impact = next((i for i in impacts if "NDVI" in i["name"]), None)

    if runoff_impact and runoff_impact["level"] in ("CRITICO", "ALTO"):
        vasca_m3 = round(runoff_impact["delta"] * 0.5, 0)
        mitigations.append({
            "measure": f"Vasca di laminazione {vasca_m3:.0f} m³",
            "effect": f"Deflusso picco -{runoff_impact['delta']*0.5:.0f} m³/evento (-50%)",
            "priority": "ALTA",
            "norm": "D.Lgs 152/2006 art.113 — invarianza idraulica"
        })

    if infil_impact and abs(infil_impact["delta"]) > 500:
        perm_area = min(road_m2 * 0.6, area_m2 * 0.15)
        infil_gain = round(perm_area * INFILTRATION_K["permeable"] / 1000 * 200, 0)
        mitigations.append({
            "measure": f"Pavimentazione drenante su {perm_area:.0f} m² parcheggi",
            "effect": f"Infiltrazione +{infil_gain:.0f} m³/anno",
            "priority": "ALTA",
            "norm": "Linee guida ISPRA consumo suolo reversibile"
        })

    if thermal_impact and thermal_impact["delta"] > 0.8:
        green_roof_area = min(building_m2 * 0.5, area_m2 * 0.1)
        dt_reduction = round(green_roof_area / area_m2 * 8, 2)
        mitigations.append({
            "measure": f"Tetto verde su {green_roof_area:.0f} m² ({green_roof_area/building_m2*100:.0f}% edificato)",
            "effect": f"ΔT -{dt_reduction:.1f}°C | NDVI +{green_roof_area/area_m2*0.4:.2f}",
            "priority": "MEDIA",
            "norm": "Piano d'Azione per l'Energia Sostenibile (PAES)"
        })

    if ndvi_impact and abs(ndvi_impact["delta"]) > 0.15:
        buffer_area = round(area_m2 ** 0.5 * 10, 0)
        mitigations.append({
            "measure": f"Fascia tampone verde perimetrale {buffer_area:.0f} m²",
            "effect": f"NDVI +{buffer_area/area_m2*0.5:.2f} | Frammentazione habitat -30%",
            "priority": "ALTA",
            "norm": "Dir. 92/43/CEE Habitat — corridoi ecologici"
        })
        mitigations.append({
            "measure": f"Compensazione ambientale {area_m2*0.0003:.2f} ha bosco",
            "effect": "Offset consumo suolo naturale — prescrizione MASE frequente",
            "priority": "MEDIA",
            "norm": "D.Lgs 34/2018 — compensazione forestale"
        })

    return mitigations
