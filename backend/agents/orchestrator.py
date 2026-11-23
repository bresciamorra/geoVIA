"""
ReAct Orchestrator — Environmental Digital Twin
Reason + Act loop con tool calling su Ollama.

Regole:
1. L'AI non calcola mai valori numerici — li legge dai tool
2. Se real=False, l'AI dichiara esplicitamente l'incertezza
3. Max 6 iterazioni per evitare loop infiniti
4. Ogni tool result include fonte e qualità del dato
"""
import httpx
import json
import os
import asyncio
from backend.agents.tools import TOOL_SCHEMAS, execute_tool, ToolResult

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "hermes3:8b")
MAX_ITERATIONS = 6

SYSTEM_PROMPT = """Sei l'AI Intelligence Engine del sistema Environmental Digital Twin geoVIA.

Il tuo ruolo è ESCLUSIVAMENTE:
1. Comprendere la richiesta dell'utente
2. Decidere quali tool chiamare per raccogliere dati reali
3. Interpretare i risultati dei tool
4. Produrre una relazione tecnica basata SOLO sui dati ricevuti

REGOLE FONDAMENTALI:
- NON inventare mai valori numerici — usa SOLO i dati restituiti dai tool
- Se un dato ha real=False, dichiaralo esplicitamente: "dato stimato, verificare con fonte ufficiale"
- NON confondere sovrapposizione cartografica con valutazione di conformità
- Cita sempre la fonte di ogni dato (ISPRA, INGV, PCN, Copernicus, ecc.)
- Se mancano dati critici, dillo chiaramente invece di stimare

QUANDO RISPONDERE SENZA TOOL:
- Solo per domande generali su normative o procedure
- Solo se hai già tutti i dati necessari dai tool precedenti

FORMATO RISPOSTA FINALE:
Struttura sempre la risposta con:
1. Sintesi (2-3 righe con i valori chiave)
2. Analisi per indicatore (con fonte e qualità dato)
3. Vincoli normativi rilevati
4. Misure di mitigazione (se richieste)
5. Prossimi passi procedurali
"""


async def run_react(
    user_message: str,
    context: dict,
    stream_callback=None
) -> dict:
    """
    ReAct loop: Reason → Act → Observe → Reason → ...
    
    context: {geojson, project_type, project_name, lat, lon, area_m2}
    stream_callback: async function(token) for streaming
    Returns: {response, tool_calls, iterations, sources}
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(user_message, context)}
    ]

    tool_calls_log = []
    sources = set()
    iterations = 0

    while iterations < MAX_ITERATIONS:
        iterations += 1

        # Call Ollama with tools
        response = await _call_ollama_tools(messages)
        if not response:
            break

        # Check if model wants to call tools
        tool_calls = response.get("message", {}).get("tool_calls", [])

        if not tool_calls:
            # Model is done — final response
            final_text = response.get("message", {}).get("content", "")
            if final_text:
                if stream_callback:
                    # Stream token by token for UX
                    for word in final_text.split(" "):
                        await stream_callback(word + " ")
                        await asyncio.sleep(0.01)
                return {
                    "response": final_text,
                    "tool_calls": tool_calls_log,
                    "iterations": iterations,
                    "sources": list(sources)
                }
            break

        # Execute tool calls
        messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", {})
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {}

            if stream_callback:
                await stream_callback(f"\n🔧 *Esecuzione tool: {tool_name}...*\n")

            result: ToolResult = await execute_tool(tool_name, tool_args, context)
            sources.add(result.source)
            tool_calls_log.append({
                "tool": tool_name,
                "args": tool_args,
                "real": result.real,
                "uncertainty": result.uncertainty,
                "source": result.source
            })

            # Add tool result to conversation
            messages.append({
                "role": "tool",
                "content": result.to_llm_str(),
                "name": tool_name
            })

    return {
        "response": "Analisi completata. Nessuna risposta generata.",
        "tool_calls": tool_calls_log,
        "iterations": iterations,
        "sources": list(sources)
    }


async def _call_ollama_tools(messages: list) -> dict:
    """Single Ollama call with tool schemas"""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": MODEL,
                    "messages": messages,
                    "tools": TOOL_SCHEMAS,
                    "stream": False
                }
            )
            if r.status_code == 200:
                data = r.json()
                # Strip think blocks
                content = data.get("message", {}).get("content", "")
                if content and "<think>" in content and "</think>" in content:
                    content = content.split("</think>")[-1].strip()
                    data["message"]["content"] = content
                return data
            print(f"[ReAct] Ollama status={r.status_code}")
    except Exception as e:
        print(f"[ReAct] {e}")
    return {}


def _build_user_message(user_message: str, context: dict) -> str:
    """Build user message with context"""
    ctx_parts = []
    if context.get("project_name"):
        ctx_parts.append(f"Progetto: {context['project_name']}")
    if context.get("project_type"):
        ctx_parts.append(f"Tipo: {context['project_type']}")
    if context.get("lat") and context.get("lon"):
        ctx_parts.append(f"Coordinate: lat={context['lat']:.4f}, lon={context['lon']:.4f}")
    if context.get("area_m2"):
        ctx_parts.append(f"Area: {context['area_m2']:.0f} m²")
    if context.get("geojson"):
        ctx_parts.append("GeoJSON disponibile nel contesto")

    ctx_str = "\n".join(ctx_parts)
    if ctx_str:
        return f"CONTESTO:\n{ctx_str}\n\nRICHIESTA:\n{user_message}"
    return user_message


async def run_react_stream(user_message: str, context: dict, ws):
    """
    ReAct with WebSocket streaming.
    Sends tokens as they arrive.
    """
    tokens = []

    async def stream_cb(token: str):
        tokens.append(token)
        try:
            await ws.send_json({"type": "react_token", "token": token})
        except Exception:
            pass

    try:
        await ws.send_json({"type": "react_start"})
        result = await run_react(user_message, context, stream_callback=stream_cb)
        await ws.send_json({
            "type": "react_done",
            "full": result["response"],
            "tool_calls": result["tool_calls"],
            "sources": result["sources"],
            "iterations": result["iterations"]
        })
        return result
    except Exception as e:
        await ws.send_json({"type": "react_error", "error": str(e)})
        return {}
