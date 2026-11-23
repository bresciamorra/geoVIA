"""
Multi-agent system for geoVIA.
Each agent is specialized and minimal — only does one thing.
Agents run in parallel via asyncio.gather().
LLM is called only where interpretation is needed, never for calculations.
"""
import httpx
import json
import asyncio
import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST", "qwen2.5:3b")
MODEL_SYNTHESIS = os.getenv("OLLAMA_MODEL", "hermes3:8b")

# Override for OpenRouter
import os as _os
if _os.getenv("OPENROUTER_KEY"):
    MODEL_FAST = _os.getenv("OLLAMA_MODEL", "mistralai/mistral-7b-instruct:free")
    MODEL_SYNTHESIS = MODEL_FAST

# ── NORMATIVE KNOWLEDGE BASE ──────────────────────────────────────────────────
# Local text index — no embeddings needed for this scale
NORMS = {
    "residenziale": {
        "refs": ["NTC2018 §3.2", "D.Lgs 42/2004 art.142", "PAI art.9", "D.M. 1444/1968"],
        "key_checks": ["zona sismica", "vincolo paesaggistico", "fascia PAI", "distanza corsi d'acqua 150m"],
        "via_threshold": "Non soggetto a VIA se <10.000 m². Verifica screening per aree vincolate."
    },
    "industriale": {
        "refs": ["D.Lgs 105/2015 SEVESO III", "D.Lgs 152/2006 Parte II", "D.P.R. 59/2013 AUA", "D.Lgs 81/2008"],
        "key_checks": ["distanza centri abitati", "falda acquifera", "emissioni atmosferiche", "rifiuti speciali"],
        "via_threshold": "Allegato II D.Lgs 152/2006: VIA obbligatoria per impianti >specifiche soglie."
    },
    "viario": {
        "refs": ["D.Lgs 285/1992 CdS", "D.M. 5/11/2001", "PAI", "D.Lgs 152/2006 Allegato III"],
        "key_checks": ["attraversamento corsi d'acqua", "aree protette", "rumore D.P.C.M. 14/11/1997"],
        "via_threshold": "Strade extraurbane principali >10km: VIA obbligatoria."
    },
    "energetico": {
        "refs": ["D.Lgs 387/2003", "D.M. 10/09/2010 linee guida FER", "D.Lgs 152/2006", "L. 181/2011"],
        "key_checks": ["consumo suolo agricolo", "distanza abitazioni", "impatto paesaggistico", "rete elettrica"],
        "via_threshold": "FV >10MW: VIA obbligatoria. 1-10MW: verifica screening regionale."
    },
    "agricolo": {
        "refs": ["D.Lgs 152/2006 Parte III", "Dir. 91/676/CEE Nitrati", "D.Lgs 75/2010", "PAI"],
        "key_checks": ["zone vulnerabili nitrati", "corpi idrici", "uso fitofarmaci", "erosione suolo"],
        "via_threshold": "Generalmente non soggetto a VIA salvo bonifiche o grandi trasformazioni."
    },
    "turistico": {
        "refs": ["D.Lgs 42/2004", "NTC2018", "D.M. 19/03/2015 antincendio", "Piano Paesaggistico Regionale"],
        "key_checks": ["vincolo paesaggistico", "accessibilità", "capacità portante territorio", "rifiuti"],
        "via_threshold": "Verifica caso per caso in base a dimensioni e localizzazione."
    },
    "commerciale": {
        "refs": ["D.Lgs 114/1998", "NTC2018", "D.Lgs 152/2006", "D.P.C.M. 14/11/1997 rumore"],
        "key_checks": ["traffico indotto", "impermeabilizzazione suolo", "rumore", "rifiuti"],
        "via_threshold": "GDO >10.000 m²: possibile verifica VIA regionale."
    }
}

async def _call_llm(prompt: str, model: str, system: str = "", timeout: int = 60) -> str:
    """Minimal LLM call — supports both Ollama and OpenRouter"""
    import os
    openrouter_key = os.getenv("OPENROUTER_KEY", "")
    if openrouter_key:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "HTTP-Referer": "https://geovia.local",
            "X-Title": "geoVIA"
        }
    else:
        url = f"{OLLAMA_URL}/api/chat"
        headers = {}

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if openrouter_key:
                    r = await client.post(url, headers=headers,
                        json={"model": model, "messages": messages})
                    if r.status_code == 200:
                        return r.json()["choices"][0]["message"]["content"]
                    print(f"[LLM OpenRouter] status={r.status_code} {r.text[:200]}")
                else:
                    r = await client.post(url,
                        json={"model": model, "messages": messages, "stream": False})
                    if r.status_code == 200:
                        content = r.json().get("message", {}).get("content", "")
                        if "<think>" in content and "</think>" in content:
                            content = content.split("</think>")[-1].strip()
                        return content
                    print(f"[LLM {model}] status={r.status_code}")
        except Exception as e:
            print(f"[LLM {model}] attempt={attempt+1} error={repr(e)}")
    return ""

# ── AGENT 1: RISK INTERPRETER ─────────────────────────────────────────────────
async def risk_agent(indicators: list, project_type: str,
                     lat: float = 0, lon: float = 0, area_m2: float = 0) -> str:
    """
    Interprets risk scores with full numeric context.
    Uses qwen2.5:3b for speed.
    """
    ind_text = "\n".join([
        f"- {i['name']}: {i['score']}/100 ({i['level']}) | P={i['p']:.2f} G={i['g']:.2f} E={i['e']:.2f} | {i['notes']}"
        for i in indicators
    ])
    critical = [i['name'] for i in indicators if i['score'] >= 60]
    medium = [i['name'] for i in indicators if 40 <= i['score'] < 60]

    prompt = f"""Progetto tipo: {project_type}
Localizzazione: lat={lat:.4f}, lon={lon:.4f}
Superficie: {area_m2:.0f} m² ({area_m2/10000:.2f} ha)

Indicatori di rischio (R = P × G × E × 100):
{ind_text}

Rischi critici (≥60): {', '.join(critical) if critical else 'nessuno'}
Rischi medi (40-59): {', '.join(medium) if medium else 'nessuno'}

In 4 frasi tecniche: descrivi i rischi dominanti con i valori specifici, spiega le interazioni tra indicatori, indica la priorità di intervento concreta per questo sito."""

    system = "Sei un esperto VIA italiano. Usa i valori numerici forniti. Rispondi in italiano, 4 frasi tecniche dirette, niente elenchi."
    return await _call_llm(prompt, MODEL_FAST, system, timeout=300)

# ── AGENT 2: NORM AGENT ───────────────────────────────────────────────────────
async def norm_agent(project_type: str, indicators: list, global_score: float) -> dict:
    """
    Returns applicable norms — mostly deterministic lookup, LLM only for edge cases.
    Fast: no LLM call for known project types.
    """
    norms = NORMS.get(project_type, {
        "refs": ["D.Lgs 152/2006", "NTC2018"],
        "key_checks": ["verifica caso per caso"],
        "via_threshold": "Verificare con autorità competente."
    })

    # Add extra refs based on high-risk indicators
    extra_refs = []
    for i in indicators:
        if i["score"] >= 60:
            if "Idrogeologico" in i["name"]:
                extra_refs.append("PAI — Piano Assetto Idrogeologico (Autorità di Bacino)")
            if "Biodiversità" in i["name"]:
                extra_refs.append("Dir. 92/43/CEE Habitat | Dir. 2009/147/CE Uccelli | D.P.R. 357/1997")
            if "Sismico" in i["name"]:
                extra_refs.append("NTC2018 §3.2 — Azione sismica | Microzonazione sismica")
            if "Idrico" in i["name"]:
                extra_refs.append("D.Lgs 152/2006 art.115 — Fasce di rispetto corpi idrici")

    return {
        "refs": list(set(norms["refs"] + extra_refs)),
        "key_checks": norms["key_checks"],
        "via_threshold": norms["via_threshold"],
        "via_required": global_score >= 60
    }

# ── AGENT 3: DOC AGENT ────────────────────────────────────────────────────────
async def doc_agent(doc_text: str, project_name: str, indicators: list) -> str:
    """
    Analyzes uploaded document against risk results.
    Only called if doc_text is provided.
    """
    if not doc_text or len(doc_text) < 100:
        return ""

    critical_names = [i["name"] for i in indicators if i["score"] >= 50]
    prompt = f"""Documento tecnico per il progetto "{project_name}" (estratto):
---
{doc_text[:2000]}
---
Rischi critici rilevati dal motore GIS: {', '.join(critical_names)}

In 3 frasi: il documento affronta questi rischi? Ci sono lacune o incongruenze?"""

    system = "Sei un esperto VIA. Analizza il documento in modo critico. Rispondi in italiano, massimo 3 frasi."
    return await _call_llm(prompt, MODEL_FAST, system, timeout=90)

# ── AGENT 4: SYNTHESIS AGENT ─────────────────────────────────────────────────
async def synthesis_agent(project_name: str, project_type: str, global_score: float,
                           global_level: str, via_screening: str,
                           risk_interpretation: str, norm_result: dict,
                           doc_analysis: str, indicators: list,
                           lat: float = 0, lon: float = 0, area_m2: float = 0) -> str:
    """
    Assembles the final report from all agent outputs.
    Uses hermes3:8b for quality — called once at the end.
    """
    norm_text = "\n".join([f"• {r}" for r in norm_result["refs"]])
    checks_text = "\n".join([f"• {c}" for c in norm_result["key_checks"]])
    # Full indicator detail for synthesis
    ind_summary = "\n".join([
        f"- {i['name']}: {i['score']}/100 ({i['level']}) — {i['notes']}"
        for i in indicators
    ])
    doc_section = f"\nANALISI DOCUMENTO:\n{doc_analysis}" if doc_analysis else ""

    # Keep prompt short to avoid timeout on local LLM
    critical = [i for i in indicators if i['score'] >= 40]
    critical_text = "\n".join([f"- {i['name']}: {i['score']}/100 ({i['level']}) — {i['notes']}" for i in critical]) or "Nessun rischio critico"

    prompt = f"""Relazione tecnica VIA — {project_name} ({project_type})
Lat {lat:.4f} Lon {lon:.4f} | {area_m2:.0f} m² | Rischio globale: {global_score}/100 {global_level}
Screening: {via_screening}

Rischi rilevanti:
{critical_text}

Normative: {', '.join(norm_result['refs'][:4])}
Soglia VIA: {norm_result['via_threshold']}

Scrivi una relazione tecnica VIA con:
1. Sintesi (2 righe con valori numerici reali)
2. Analisi rischi (cita P/G/E, fonti ISPRA/INGV, valori misurati)
3. Normative applicabili con articoli specifici
4. Misure di mitigazione concrete per questo sito
5. Prossimi passi procedurali VIA/VAS

Sii specifico, cita i numeri reali, evita frasi generiche."""

    system = "Sei un esperto senior di VIA/VAS italiano. Produci relazioni tecniche precise con valori numerici reali, non generiche."
    return await _call_llm(prompt, MODEL_SYNTHESIS, system, timeout=300)

# ── ORCHESTRATOR ──────────────────────────────────────────────────────────────
async def run_agents(project_name: str, project_type: str, indicators: list,
                     global_score: float, global_level: str, via_screening: str,
                     doc_text: str = "",
                     lat: float = 0, lon: float = 0, area_m2: float = 0) -> dict:
    """
    Runs all agents. Risk, Norm and Doc agents run in parallel.
    Synthesis agent runs after, using their outputs.
    """
    # Phase 1: sequential (Ollama is single-threaded, parallel causes timeouts)
    risk_result = await risk_agent(indicators, project_type, lat, lon, area_m2)
    norm_result = await norm_agent(project_type, indicators, global_score)
    doc_result = await doc_agent(doc_text, project_name, indicators)

    # Phase 2: synthesis (sequential, needs phase 1 outputs)
    final_report = await synthesis_agent(
        project_name, project_type, global_score, global_level,
        via_screening, risk_result, norm_result, doc_result, indicators,
        lat, lon, area_m2
    )

    return {
        "risk_interpretation": risk_result,
        "norms": norm_result,
        "doc_analysis": doc_result,
        "final_report": final_report
    }
