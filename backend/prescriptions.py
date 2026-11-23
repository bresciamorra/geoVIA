"""
Prescrizioni Probabili
Estrae prescrizioni attese da precedenti MASE simili.
Deterministico — nessun LLM.
"""
from backend.modules.mase_rag import MASE_DATASET, SETTORI_MAP
from collections import Counter


# Prescrizioni standard per tipo di rischio — knowledge base embedded
RISK_PRESCRIPTIONS = {
    "Rischio Idrogeologico": [
        ("Fascia di rispetto 10m da corsi d'acqua", "ALTA"),
        ("Piano di gestione acque meteoriche", "ALTA"),
        ("Relazione geologica e geotecnica", "ALTA"),
        ("Monitoraggio inclinometrico in fase cantiere", "MEDIA"),
        ("Verifica PAI con Autorità di Bacino", "ALTA"),
    ],
    "Rischio Sismico": [
        ("Analisi di risposta sismica locale (microzonazione)", "ALTA"),
        ("Progettazione strutturale NTC2018 zona sismica", "ALTA"),
        ("Verifica liquefazione terreno", "MEDIA"),
    ],
    "Impatto Biodiversità": [
        ("Studio di incidenza ambientale (VINCA)", "ALTA"),
        ("Monitoraggio avifauna pre e post operam", "ALTA"),
        ("Corridoi ecologici e fasce tampone", "MEDIA"),
        ("Compensazione ambientale 1:3 superficie", "MEDIA"),
        ("Monitoraggio chirotteri (impianti eolici)", "MEDIA"),
    ],
    "Qualità dell'Aria": [
        ("Piano di monitoraggio PM10/PM2.5 in fase cantiere", "ALTA"),
        ("Bagnatura periodica cantiere per abbattimento polveri", "ALTA"),
        ("Valutazione dispersione inquinanti (modello gaussiano)", "MEDIA"),
    ],
    "Consumo di Suolo": [
        ("Piano di ripristino morfologico post-esercizio", "ALTA"),
        ("Mantenimento permeabilità suolo ≥30%", "MEDIA"),
        ("Compensazione verde pubblico", "MEDIA"),
        ("Invarianza idraulica", "ALTA"),
    ],
    "Impatto Idrico": [
        ("Fascia di rispetto 150m corpi idrici (D.Lgs 152/2006 art.115)", "ALTA"),
        ("Piano gestione acque di prima pioggia", "ALTA"),
        ("Monitoraggio qualità acque superficiali", "MEDIA"),
    ],
}

# Prescrizioni specifiche per tipo progetto
PROJECT_PRESCRIPTIONS = {
    "energetico": [
        ("Piano di dismissione e ripristino a fine vita impianto", "ALTA"),
        ("Verifica interferenze con rete elettrica esistente (Terna)", "ALTA"),
        ("Studio impatto visivo e paesaggistico", "MEDIA"),
        ("Distanza minima 500m da centri abitati (eolico)", "MEDIA"),
    ],
    "residenziale": [
        ("Verde pubblico minimo 30% superficie lotto", "ALTA"),
        ("Parcheggi interrati o coperti", "MEDIA"),
        ("Piano urbanistico attuativo (PUA)", "ALTA"),
    ],
    "industriale": [
        ("Piano emergenze ambientali", "ALTA"),
        ("Distanza minima 500m da zone residenziali", "ALTA"),
        ("Autorizzazione Integrata Ambientale (AIA) se soglie IPPC", "ALTA"),
    ],
    "viario": [
        ("Barriere antirumore lungo tracciato", "ALTA"),
        ("Sottopassi fauna ogni 500m in aree naturali", "MEDIA"),
        ("Piano gestione terre e rocce da scavo", "ALTA"),
    ],
    "agricolo": [
        ("Verifica zone vulnerabili nitrati (Dir. 91/676/CEE)", "ALTA"),
        ("Piano utilizzo agronomico reflui zootecnici", "MEDIA"),
    ],
    "turistico": [
        ("Studio capacità portante territorio", "MEDIA"),
        ("Piano gestione rifiuti stagionale", "MEDIA"),
    ],
}


def get_probable_prescriptions(project_type: str, indicators: list,
                                regione: str = "", global_score: float = 0) -> dict:
    """
    Returns probable prescriptions based on:
    1. Risk indicators with score >= 30
    2. Project type
    3. Similar MASE precedents
    """
    prescriptions = []
    seen = set()

    def add(text, probability, source):
        if text not in seen:
            seen.add(text)
            prescriptions.append({"text": text, "probability": probability, "source": source})

    # From risk indicators
    for ind in indicators:
        if ind["score"] >= 30:
            for text, prob in RISK_PRESCRIPTIONS.get(ind["name"], []):
                add(text, prob, f"Rischio {ind['name']} ({ind['score']}/100)")

    # From project type
    for text, prob in PROJECT_PRESCRIPTIONS.get(project_type, []):
        add(text, prob, f"Tipo progetto: {project_type}")

    # From MASE precedents
    type_keywords = set(SETTORI_MAP.get(project_type, []))
    mase_prescriptions = []
    for p in MASE_DATASET:
        if p["settore"] == project_type or len(type_keywords & set(p.get("keywords", []))) >= 2:
            if p.get("prescrizioni") and p["prescrizioni"] != "Non disponibile":
                # Split by period and extract meaningful sentences
                parts = [s.strip() for s in p["prescrizioni"].replace(". ", ".|").split("|") if len(s.strip()) > 15]
                mase_prescriptions.extend(parts[:2])

    # Add top MASE prescriptions
    counter = Counter(mase_prescriptions)
    for text, count in counter.most_common(3):
        prob = "ALTA" if count >= 2 else "MEDIA"
        add(text, prob, f"Precedenti MASE ({count} casi simili)")

    # Sort: ALTA first
    prescriptions.sort(key=lambda x: 0 if x["probability"] == "ALTA" else 1)

    # VIA timing estimate
    via_estimate = _estimate_via_timing(global_score, project_type)

    return {
        "prescriptions": prescriptions[:12],
        "total": len(prescriptions),
        "via_estimate": via_estimate,
        "note": f"{len([p for p in prescriptions if p['probability']=='ALTA'])} prescrizioni ad alta probabilità"
    }


def _estimate_via_timing(global_score: float, project_type: str) -> dict:
    """Estimate VIA procedure timing based on risk and project type."""
    base_months = {
        "energetico": 18, "industriale": 24, "viario": 30,
        "residenziale": 12, "agricolo": 8, "turistico": 14, "commerciale": 10
    }.get(project_type, 15)

    # Higher risk = longer procedure
    if global_score >= 60:
        months = base_months + 12
        complexity = "ALTA"
    elif global_score >= 40:
        months = base_months + 6
        complexity = "MEDIA"
    else:
        months = base_months
        complexity = "BASSA"

    return {
        "months_estimate": months,
        "complexity": complexity,
        "cost_estimate_eur": months * 3000,  # rough estimate
        "note": f"Stima indicativa basata su {project_type} con complessità {complexity}"
    }
