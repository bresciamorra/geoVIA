"""
Decision Brief Generator
Output 1 pagina per decisore: semaforo, rischi principali, azioni immediate, stima procedura.
"""
import httpx
import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "hermes3:8b")

SEMAFORO = {
    "MOLTO ALTO": ("🔴", "STOP", "Criticità bloccanti — intervento immediato richiesto prima di procedere"),
    "ALTO":       ("🟠", "ATTENZIONE", "Rischi significativi — approfondimenti obbligatori"),
    "MEDIO":      ("🟡", "VERIFICA", "Rischi moderati — prescrizioni attese nella procedura VIA"),
    "BASSO":      ("🟢", "PROCEDI", "Rischi contenuti — procedura VIA standard"),
    "TRASCURABILE": ("🟢", "PROCEDI", "Impatto trascurabile — verifica screening sufficiente"),
}


async def generate_decision_brief(project_name: str, project_type: str,
                                   global_score: float, global_level: str,
                                   via_screening: str, indicators: list,
                                   prescriptions: list, via_estimate: dict,
                                   lat: float, lon: float, area_m2: float) -> dict:
    """
    Generate a 1-page decision brief.
    Deterministic structure + LLM for executive summary only.
    """
    emoji, verdict, verdict_desc = SEMAFORO.get(global_level, ("🟡", "VERIFICA", ""))

    # Top 3 risks
    top_risks = sorted(indicators, key=lambda i: i["score"], reverse=True)[:3]

    # Top 3 immediate actions from HIGH probability prescriptions
    high_presc = [p for p in prescriptions if p["probability"] == "ALTA"][:3]

    # LLM: only 2-sentence executive summary
    exec_summary = await _llm_summary(project_name, project_type, global_score,
                                       global_level, top_risks, lat, lon, area_m2)

    return {
        "semaforo": emoji,
        "verdict": verdict,
        "verdict_desc": verdict_desc,
        "exec_summary": exec_summary,
        "global_score": global_score,
        "global_level": global_level,
        "top_risks": [
            {"name": i["name"], "score": i["score"], "level": i["level"], "notes": i["notes"]}
            for i in top_risks
        ],
        "immediate_actions": [p["text"] for p in high_presc],
        "via_estimate": via_estimate,
        "via_screening": via_screening,
        "project_name": project_name,
        "project_type": project_type,
        "lat": lat, "lon": lon, "area_m2": area_m2,
    }


async def _llm_summary(project_name, project_type, score, level, top_risks, lat, lon, area_m2) -> str:
    risks_text = ", ".join([f"{r['name'].replace('Rischio','').replace('Impatto','').strip()} {r['score']}/100" for r in top_risks])
    prompt = (f"Progetto {project_type} '{project_name}' a lat {lat:.3f} lon {lon:.3f}, "
              f"{area_m2:.0f}m². Rischio globale {score}/100 ({level}). "
              f"Rischi principali: {risks_text}. "
              f"Scrivi 2 frasi tecniche in italiano per un decisore: cosa significa questo rischio "
              f"e qual è l'azione prioritaria. Sii diretto e specifico.")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{OLLAMA_URL}/api/chat",
                json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False})
            if r.status_code == 200:
                content = r.json().get("message", {}).get("content", "")
                if "<think>" in content and "</think>" in content:
                    content = content.split("</think>")[-1].strip()
                return content
    except Exception as e:
        print(f"[Brief LLM] {e}")
    return f"Il progetto presenta un rischio ambientale {level} ({score}/100). Procedere con le verifiche indicate."
