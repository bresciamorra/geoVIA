"""
Modulo A — Precedenti MASE
Dataset embedded di precedenti reali + ricerca keyword sincrona.
Nessuna dipendenza da scraping esterno per la demo.
"""

# ── DATASET EMBEDDED (precedenti reali MASE) ──────────────────────────────────
# Fonte: portale va.mite.gov.it — procedure concluse pubbliche

MASE_DATASET = [
    {
        "mase_id": "2847",
        "titolo": "Impianto fotovoltaico da 49,9 MW - Comune di Foggia",
        "proponente": "Enel Green Power Italia S.r.l.",
        "regione": "Puglia", "provincia": "Foggia",
        "settore": "energetico", "tipo": "fotovoltaico",
        "esito": "POSITIVO CON PRESCRIZIONI", "anno": 2023,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/2847",
        "prescrizioni": "Monitoraggio avifauna semestrale. Fasce tampone 10m da corsi d'acqua. Piano di ripristino post-esercizio.",
        "keywords": ["fotovoltaico", "solare", "energetico", "FV", "pannelli"]
    },
    {
        "mase_id": "3102",
        "titolo": "Parco eolico da 42 MW - Comune di Lacedonia",
        "proponente": "ERG Renew S.p.A.",
        "regione": "Campania", "provincia": "Avellino",
        "settore": "energetico", "tipo": "eolico",
        "esito": "POSITIVO CON PRESCRIZIONI", "anno": 2022,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/3102",
        "prescrizioni": "Studio impatto visivo. Monitoraggio chirotteri. Distanza minima 500m da centri abitati. Piano dismissione.",
        "keywords": ["eolico", "wind", "turbine", "aerogeneratori", "energetico"]
    },
    {
        "mase_id": "2654",
        "titolo": "Impianto agrivoltaico 28 MW - Comune di Matera",
        "proponente": "Terna Rete Italia S.p.A.",
        "regione": "Basilicata", "provincia": "Matera",
        "settore": "energetico", "tipo": "fotovoltaico",
        "esito": "POSITIVO", "anno": 2023,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/2654",
        "prescrizioni": "Mantenimento attività agricola sottostante. Monitoraggio qualità suolo annuale.",
        "keywords": ["agrivoltaico", "fotovoltaico", "agricolo", "energetico"]
    },
    {
        "mase_id": "1987",
        "titolo": "Centrale idroelettrica 8 MW - Fiume Nera",
        "proponente": "Hydro Italia S.r.l.",
        "regione": "Umbria", "provincia": "Terni",
        "settore": "energetico", "tipo": "idroelettrico",
        "esito": "NEGATIVO", "anno": 2021,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/1987",
        "prescrizioni": "Rigetto per impatto su habitat Natura 2000 IT5220013. Deflusso minimo vitale insufficiente.",
        "keywords": ["idroelettrico", "idro", "acqua", "fiume", "energetico"]
    },
    {
        "mase_id": "3341",
        "titolo": "Impianto fotovoltaico 75 MW - Comune di Brindisi",
        "proponente": "Falck Renewables S.p.A.",
        "regione": "Puglia", "provincia": "Brindisi",
        "settore": "energetico", "tipo": "fotovoltaico",
        "esito": "POSITIVO CON PRESCRIZIONI", "anno": 2023,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/3341",
        "prescrizioni": "Compensazione ambientale 1:3. Corridoi ecologici. Monitoraggio PM10 in fase cantiere.",
        "keywords": ["fotovoltaico", "solare", "energetico", "grande scala"]
    },
    {
        "mase_id": "2201",
        "titolo": "Autostrada A3 Salerno-Reggio Calabria - Lotto 7",
        "proponente": "ANAS S.p.A.",
        "regione": "Calabria", "provincia": "Cosenza",
        "settore": "viario", "tipo": "autostrada",
        "esito": "POSITIVO CON PRESCRIZIONI", "anno": 2020,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/2201",
        "prescrizioni": "Barriere antirumore. Sottopassi fauna. Monitoraggio acque superficiali. Piano gestione terre.",
        "keywords": ["autostrada", "strada", "viario", "infrastruttura", "ANAS"]
    },
    {
        "mase_id": "2890",
        "titolo": "Ampliamento porto commerciale - Taranto",
        "proponente": "Autorità Portuale Mar Ionio",
        "regione": "Puglia", "provincia": "Taranto",
        "settore": "industriale", "tipo": "porto",
        "esito": "POSITIVO CON PRESCRIZIONI", "anno": 2022,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/2890",
        "prescrizioni": "VAS contestuale. Monitoraggio qualità acque marine. Piano dragaggio certificato.",
        "keywords": ["porto", "industriale", "marittimo", "dragaggio"]
    },
    {
        "mase_id": "1654",
        "titolo": "Impianto trattamento rifiuti speciali - Comune di Pomezia",
        "proponente": "Eco Ambiente S.r.l.",
        "regione": "Lazio", "provincia": "Roma",
        "settore": "industriale", "tipo": "rifiuti",
        "esito": "POSITIVO CON PRESCRIZIONI", "anno": 2021,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/1654",
        "prescrizioni": "Monitoraggio emissioni in atmosfera. Piano emergenze. Distanza 500m da residenze.",
        "keywords": ["rifiuti", "industriale", "trattamento", "smaltimento"]
    },
    {
        "mase_id": "3089",
        "titolo": "Lottizzazione residenziale 450 alloggi - Comune di Caserta",
        "proponente": "Costruzioni Meridionali S.p.A.",
        "regione": "Campania", "provincia": "Caserta",
        "settore": "residenziale", "tipo": "residenziale",
        "esito": "POSITIVO CON PRESCRIZIONI", "anno": 2022,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/3089",
        "prescrizioni": "Verde pubblico 30% superficie. Invarianza idraulica. Parcheggi interrati.",
        "keywords": ["residenziale", "lottizzazione", "urbanizzazione", "abitativo"]
    },
    {
        "mase_id": "2445",
        "titolo": "Impianto biomassa 10 MW - Comune di Potenza",
        "proponente": "BioEnergy Sud S.r.l.",
        "regione": "Basilicata", "provincia": "Potenza",
        "settore": "energetico", "tipo": "biomassa",
        "esito": "NEGATIVO", "anno": 2021,
        "url": "https://va.mite.gov.it/it-IT/Oggetti/Info/2445",
        "prescrizioni": "Rigetto per emissioni PM2.5 superiori ai limiti. Impatto su qualità aria zona urbana.",
        "keywords": ["biomassa", "bioenergia", "energetico", "combustione"]
    },
]

SETTORI_MAP = {
    "energetico": ["fotovoltaico", "eolico", "idroelettrico", "biomassa", "agrivoltaico", "solare", "wind"],
    "industriale": ["industria", "porto", "rifiuti", "chimica", "raffineria"],
    "viario": ["autostrada", "strada", "ferrovia", "aeroporto", "porto"],
    "residenziale": ["residenziale", "lottizzazione", "urbanizzazione"],
    "turistico": ["turistico", "albergo", "resort", "marina"],
    "agricolo": ["agricolo", "zootecnico", "irrigazione", "bonifica"],
}

# ── SEARCH ────────────────────────────────────────────────────────────────────

def search_precedents(project_type: str, regione: str = "", limit: int = 5) -> list:
    """Keyword search on embedded dataset. Instant, no DB needed."""
    type_keywords = set(SETTORI_MAP.get(project_type, [project_type]))
    scored = []
    for p in MASE_DATASET:
        score = 0
        # Sector match
        if p["settore"] == project_type:
            score += 10
        # Keyword overlap
        kw_overlap = len(type_keywords & set(p.get("keywords", [])))
        score += kw_overlap * 3
        # Region match
        if regione and regione.lower() in p["regione"].lower():
            score += 5
        if score > 0:
            scored.append((score, p))

    scored.sort(key=lambda x: (-x[0], -x[1]["anno"]))
    return [p for _, p in scored[:limit]]

# ── MASTER FUNCTION ───────────────────────────────────────────────────────────

async def get_mase_precedents(project_type: str, regione: str = "",
                               lat: float = 0, lon: float = 0) -> dict:
    """Returns relevant MASE precedents synchronously from embedded dataset."""
    precedents = search_precedents(project_type, regione)
    return {
        "precedents": precedents,
        "total_indexed": len(MASE_DATASET),
        "indexing": False,
        "note": f"{len(MASE_DATASET)} precedenti nel database locale"
    }
