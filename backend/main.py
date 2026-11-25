from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Depends, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response, JSONResponse, RedirectResponse
from pydantic import BaseModel
import httpx, json, os, traceback, asyncio, sqlite3
import numpy as np

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, (np.bool_,)): return bool(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return super().default(obj)

def jsonify(data):
    return json.loads(json.dumps(data, cls=NumpyEncoder))
from backend.db import init_db, save_project, save_analysis, get_projects, get_project
from backend.gis_engine import compute_area_m2, compute_centroid, create_buffer
from backend.risk_engine import (assess_hydrogeological, assess_seismic, assess_biodiversity,
                                  assess_air_quality, assess_soil_consumption, assess_water,
                                  compute_global_risk)
from backend.connectors import fetch_all_data
from backend.agents_legacy import run_agents
from backend.auth import init_auth_db, register_user_pending, login_user, verify_token, approve_user, send_approval_email
from backend.modules.cumulative import analyze_cumulative
from backend.modules.mase_rag import get_mase_precedents
from backend.modules.regional import get_regional_procedures, coords_to_region
from backend.prescriptions import get_probable_prescriptions
from backend.decision_brief import generate_decision_brief
from backend.scenario import analyze_scenario, rank_scenarios
from backend.whatif import compute_whatif
from backend.agents.orchestrator import run_react, run_react_stream

app = FastAPI(title="geoVIA")
app.mount("/static", StaticFiles(directory="static"), name="static")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "hermes3:8b")
OLLAMA_MODEL_CHAT = os.getenv("OLLAMA_MODEL_CHAT", "mistral:latest")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_MODEL = os.getenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")

# If OpenRouter key is set, use OpenRouter instead of Ollama
if OPENROUTER_KEY:
    OLLAMA_URL = "https://openrouter.ai/api/v1"
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nvidia/nemotron-3-nano-omni:free")
    OLLAMA_MODEL_CHAT = OLLAMA_MODEL
    print(f"[LLM] Using OpenRouter: {OLLAMA_MODEL}")
elif HF_TOKEN:
    print(f"[LLM] Using HuggingFace: {HF_MODEL}")
else:
    print(f"[LLM] Using Ollama: {OLLAMA_URL} model={OLLAMA_MODEL}")

from datetime import datetime

SYSTEM_PROMPT_TECHNICAL = """Sei VIA Assistant, esperto di Valutazione di Impatto Ambientale per il territorio italiano.
Interpreta i risultati GIS forniti citando normative applicabili (D.Lgs 152/2006, NTC2018, PAI, Direttive UE).
Rispondi in italiano, in modo tecnico e professionale.
Non esprimere giudizi definitivi sull'autorizzabilità — spetta all'autorità competente."""

def _get_system_prompt_chat():
    today = datetime.now().strftime("%A %d %B %Y")
    return f"""Sei VIA Assistant, l'assistente della piattaforma geoVIA.
Data di oggi: {today}.
Rispondi in italiano in modo naturale e cordiale.
Se ti chiedono cose generali, rispondi normalmente.
Se ti chiedono di VIA/VAS/ambiente, dai risposte tecniche precise.
Non inventare mai dati che non conosci — dichiaralo chiaramente."""

@app.on_event("startup")
async def startup():
    init_db()
    init_auth_db()

@app.get("/")
async def index(request: Request):
    token = request.cookies.get("geovia_token")
    if not token or not verify_token(token):
        return RedirectResponse("/login", status_code=302)
    with open("static/index.html") as f:
        return HTMLResponse(f.read())

@app.get("/login")
async def login_page():
    with open("static/login.html") as f:
        return HTMLResponse(f.read())

class AuthRequest(BaseModel):
    email: str
    password: str

@app.post("/auth/login")
async def auth_login(req: AuthRequest, response: Response):
    result = login_user(req.email, req.password)
    if result["ok"]:
        response.set_cookie("geovia_token", result["token"],
                            max_age=30*24*3600, httponly=True, samesite="lax")
    return result

@app.post("/auth/register")
async def auth_register(req: AuthRequest):
    result = register_user_pending(req.email, req.password)
    if result["ok"]:
        await send_approval_email(req.email)
    return result

@app.get("/auth/approve")
async def auth_approve(token: str):
    from backend.auth import verify_token
    payload = verify_token(token)
    if not payload or payload.get("action") != "approve":
        return HTMLResponse("<h2>Link non valido o scaduto.</h2>", status_code=400)
    email = payload["sub"]
    profile = payload["profile"]
    approve_user(email, profile)
    return HTMLResponse(f"""
    <html><body style="font-family:Arial;text-align:center;padding:60px;background:#f0f2f5">
      <div style="background:white;border-radius:12px;padding:40px;max-width:400px;margin:0 auto;box-shadow:0 4px 20px rgba(0,0,0,0.1)">
        <div style="font-size:48px">{'⭐' if profile == 'premium' else '✅'}</div>
        <h2 style="color:#1a252f">Accesso approvato!</h2>
        <p style="color:#7f8c8d"><strong>{email}</strong> ha ora accesso <strong>{profile.upper()}</strong> a geoVIA.</p>
        <p style="color:#95a5a6;font-size:13px">L'utente può ora accedere con le sue credenziali.</p>
      </div>
    </body></html>
    """)

@app.post("/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie("geovia_token")
    return {"ok": True}

@app.get("/admin/users")
async def admin_page(key: str = ""):
    admin_key = os.getenv("ADMIN_KEY", "geovia-admin-2026")
    if key != admin_key:
        return HTMLResponse("<h2>Accesso non autorizzato</h2>", status_code=403)
    with open("static/admin.html") as f:
        return HTMLResponse(f.read())

class ApproveRequest(BaseModel):
    email: str
    profile: str

@app.get("/admin/api/users")
async def admin_list_users(key: str = ""):
    admin_key = os.getenv("ADMIN_KEY", "geovia-admin-2026")
    if key != admin_key:
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    db_path = os.getenv("DB_PATH", "data/geovia.db")
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT email, profile, created_at FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [{"email": r[0], "profile": r[1], "created_at": r[2]} for r in rows]

@app.post("/admin/api/approve")
async def admin_approve_user(req: ApproveRequest, key: str = ""):
    admin_key = os.getenv("ADMIN_KEY", "geovia-admin-2026")
    if key != admin_key:
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    ok = approve_user(req.email, req.profile)
    return {"ok": ok}

@app.get("/api/me")
async def get_me(request: Request):
    token = request.cookies.get("geovia_token")
    if not token:
        return {"email": None, "profile": None}
    payload = verify_token(token)
    if not payload:
        return {"email": None, "profile": None}
    return {"email": payload.get("sub"), "profile": payload.get("profile", "free")}

@app.get("/api/geocode")
async def geocode(q: str):
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get("https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 5, "addressdetails": 1},
            headers={"User-Agent": "geoVIA/1.0"})
        return r.json()

@app.get("/api/wms/catasto")
async def wms_proxy(bbox: str, width: int = 512, height: int = 512):
    url = "https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php"
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
        "LAYERS": "Cartografia_Catastale",
        "FORMAT": "image/png", "TRANSPARENT": "true",
        "WIDTH": width, "HEIGHT": height,
        "CRS": "EPSG:3857", "BBOX": bbox
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200 and r.headers.get('content-type','').startswith('image'):
                return Response(content=r.content, media_type="image/png",
                              headers={"Access-Control-Allow-Origin": "*",
                                       "Cache-Control": "public, max-age=3600"})
    except Exception as e:
        print(f"[WMS proxy] {e}")
    return Response(content=b"", media_type="image/png")

@app.get("/api/projects")
async def list_projects():
    return get_projects()

@app.get("/api/projects/{pid}")
async def get_project_detail(pid: int):
    p = get_project(pid)
    if not p:
        return JSONResponse({"error": "not found"}, status_code=404)
    return p

class AnalyzeRequest(BaseModel):
    geojson: dict
    project_type: str = ""
    project_name: str = "Nuovo progetto"
    description: str = ""
    buffers: list = [100, 500, 1000]
    doc_text: str = ""


class ReactChatRequest(BaseModel):
    message: str
    geojson: dict = {}
    project_type: str = ""
    project_name: str = ""
    lat: float = 0
    lon: float = 0
    area_m2: float = 0


class HttpChatRequest(BaseModel):
    message: str
    conversation: list = []

@app.post("/api/chat")
async def http_chat(req: HttpChatRequest):
    """HTTP chat — works on Railway where WebSocket drops"""
    try:
        conversation = req.conversation + [{"role": "user", "content": req.message}]
        messages = [{"role": "system", "content": _get_system_prompt_chat()}] + conversation
        if HF_TOKEN:
            url = "https://api-inference.huggingface.co/models/" + HF_MODEL + "/v1/chat/completions"
            headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=60, verify=False) as client:
                r = await client.post(url, headers=headers,
                    json={"model": HF_MODEL, "messages": messages, "max_tokens": 1024})
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"]["content"]
                    return {"response": content,
                            "conversation": conversation + [{"role": "assistant", "content": content}]}
                return {"response": f"Errore HF: {r.status_code} {r.text[:200]}", "conversation": conversation}
        elif OPENROUTER_KEY:
            headers = {"Authorization": f"Bearer {OPENROUTER_KEY}",
                       "HTTP-Referer": "https://geovia.local",
                       "X-Title": "geoVIA", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=60, verify=False) as client:
                r = await client.post("https://openrouter.ai/api/v1/chat/completions",
                    headers=headers, json={"model": OLLAMA_MODEL_CHAT, "messages": messages})
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"]["content"]
                    return {"response": content,
                            "conversation": conversation + [{"role": "assistant", "content": content}]}
                return {"response": f"Errore: {r.status_code} {r.text[:100]}", "conversation": conversation}
        else:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(f"{OLLAMA_URL}/api/chat",
                    json={"model": OLLAMA_MODEL_CHAT, "messages": messages, "stream": False})
                if r.status_code == 200:
                    content = r.json().get("message", {}).get("content", "")
                    return {"response": content,
                            "conversation": conversation + [{"role": "assistant", "content": content}]}
                return {"response": "Errore Ollama", "conversation": conversation}
    except Exception as e:
        traceback.print_exc()
        return {"response": f"Errore: {str(e)}", "conversation": req.conversation}


@app.post("/api/chat/analyze")
async def chat_analyze(req: ReactChatRequest):
    """ReAct orchestrator — AI decides which tools to call"""
    try:
        context = {
            "geojson": req.geojson,
            "project_type": req.project_type,
            "project_name": req.project_name,
            "lat": req.lat, "lon": req.lon,
            "area_m2": req.area_m2
        }
        result = await run_react(req.message, context)
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    try:
        lat, lon = compute_centroid(req.geojson)
        area_m2 = compute_area_m2(req.geojson)

        # Save project
        pid = save_project(req.project_name, req.project_type, req.description,
                           req.geojson, lat, lon, area_m2)

        # Fetch all environmental data in parallel
        env_data = await fetch_all_data(req.geojson, lat, lon)

        geo_data = env_data.get("geoportale", {})
        dtm_data = geo_data.get("dtm", {})
        vincoli_data = geo_data.get("vincoli", {})

        # Compute risk indicators (deterministic)
        indicators = [
            assess_hydrogeological(env_data.get("ispra", {}), area_m2, dtm_data),
            assess_seismic(env_data.get("ingv", {}), req.project_type),
            assess_biodiversity(env_data.get("natura2000", {}), env_data.get("corine", {}), env_data.get("water", {})),
            assess_air_quality(env_data.get("air_quality", {})),
            assess_soil_consumption(area_m2, env_data.get("corine", {})),
            assess_water(env_data.get("water", {})),
        ]

        result = compute_global_risk(indicators)
        result["project_id"] = pid
        result["lat"] = lat
        result["lon"] = lon
        result["area_m2"] = area_m2
        result["project_type"] = req.project_type
        result["project_name"] = req.project_name
        result["dtm"] = dtm_data
        result["vincoli"] = vincoli_data

        # Compute buffers
        result["buffers"] = {}
        for dist in req.buffers:
            result["buffers"][str(dist)] = create_buffer(req.geojson, dist)

        save_analysis(pid, "full_assessment", result)

        # Prescrizioni probabili (deterministico — no LLM)
        presc_data = get_probable_prescriptions(
            req.project_type, result["indicators"],
            coords_to_region(lat, lon), result["global_score"]
        )
        result["prescriptions"] = presc_data
        result["agent_output"] = {}  # filled by /api/interpret
        result["decision_brief"] = {}  # filled by /api/interpret

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


class InterpretRequest(BaseModel):
    project_name: str
    project_type: str
    indicators: list
    global_score: float
    global_level: str
    via_screening: str
    lat: float = 0
    lon: float = 0
    area_m2: float = 0
    doc_text: str = ""
    prescriptions: dict = {}

@app.post("/api/interpret")
async def interpret(req: InterpretRequest):
    """LLM interpretation — called separately after GIS analysis completes"""
    try:
        agent_output = await run_agents(
            project_name=req.project_name,
            project_type=req.project_type,
            indicators=req.indicators,
            global_score=req.global_score,
            global_level=req.global_level,
            via_screening=req.via_screening,
            doc_text=req.doc_text,
            lat=req.lat, lon=req.lon, area_m2=req.area_m2
        )
        brief = await generate_decision_brief(
            req.project_name, req.project_type,
            req.global_score, req.global_level, req.via_screening,
            req.indicators, req.prescriptions.get("prescriptions", []),
            req.prescriptions.get("via_estimate", {}),
            req.lat, req.lon, req.area_m2
        )
        return jsonify({"agent_output": agent_output, "decision_brief": brief})
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

class PdfRequest(BaseModel):
    project_id: int = 0
    project_name: str = ""
    lat: float = 0
    lon: float = 0
    area_m2: float = 0
    project_type: str = ""
    result: dict = {}
    ai_report: str = ""

@app.post("/api/pdf")
async def export_pdf(req: PdfRequest):
    from backend.pdf_gen import generate_pdf
    content, media_type = await generate_pdf(req.project_name, req.lat, req.lon,
                              req.area_m2, req.project_type, req.result, req.ai_report)
    safe = req.project_name.replace("/","_").replace(" ","_")[:40]
    if media_type == "application/pdf":
        disposition = f'attachment; filename="geoVIA_{safe}.pdf"'
    else:
        disposition = f'inline; filename="geoVIA_{safe}.html"'
    return Response(content=content, media_type=media_type,
                    headers={"Content-Disposition": disposition})

@app.post("/api/upload")
async def upload_doc(file: UploadFile = File(...)):
    from backend.doc_processor import extract_text
    content = await file.read()
    text = await extract_text(file.filename, content)
    return JSONResponse({"filename": file.filename, "chars": len(text),
                         "preview": text[:400], "text": text})

class EnrichRequest(BaseModel):
    lat: float
    lon: float
    project_type: str = ""
    area_m2: float = 0
    radius_m: int = 5000

class WhatIfRequest(BaseModel):
    geojson: dict
    intervention: dict  # {building_m2, road_m2, green_m2, permeable_m2}
    project_type: str = ""
    rainfall_mm: float = 50.0

@app.post("/api/whatif")
async def whatif(req: WhatIfRequest):
    try:
        from backend.gis_engine import compute_area_m2, compute_centroid
        lat, lon = compute_centroid(req.geojson)
        area_m2 = compute_area_m2(req.geojson)
        from backend.connectors.copernicus import fetch_copernicus
        corine_data = await fetch_copernicus(req.geojson, lat, lon)
        result = compute_whatif(area_m2, corine_data, req.intervention, req.rainfall_mm)
        result["lat"] = lat
        result["lon"] = lon
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

class CompareRequest(BaseModel):
    scenarios: list  # [{"label": "A", "geojson": {...}}, ...]
    project_type: str = ""

@app.post("/api/compare")
async def compare_scenarios(req: CompareRequest):
    """Analyze and rank multiple site alternatives"""
    try:
        tasks = [analyze_scenario(s["geojson"], req.project_type, s.get("label", f"Scenario {i+1}"))
                 for i, s in enumerate(req.scenarios[:3])]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid = [r for r in results if not isinstance(r, Exception)]
        if not valid:
            return JSONResponse({"error": "Nessuno scenario analizzato"}, status_code=400)
        return jsonify(rank_scenarios(valid))
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/enrich")
async def enrich(req: EnrichRequest):
    """Run all 3 enrichment modules in parallel"""
    cumulative, precedents, regional = await asyncio.gather(
        analyze_cumulative(req.lat, req.lon, req.project_type, req.area_m2, req.radius_m),
        get_mase_precedents(req.project_type, coords_to_region(req.lat, req.lon), req.lat, req.lon),
        get_regional_procedures(req.lat, req.lon, req.project_type),
        return_exceptions=True
    )
    return {
        "cumulative": cumulative if not isinstance(cumulative, Exception) else {"error": str(cumulative)},
        "precedents": precedents if not isinstance(precedents, Exception) else {"error": str(precedents)},
        "regional": regional if not isinstance(regional, Exception) else {"error": str(regional)},
    }

@app.get("/api/enrich/cumulative")
async def get_cumulative(lat: float, lon: float, project_type: str = "",
                          area_m2: float = 0, radius_m: int = 5000):
    return await analyze_cumulative(lat, lon, project_type, area_m2, radius_m)

@app.get("/api/enrich/precedents")
async def get_precedents(lat: float, lon: float, project_type: str = ""):
    region = coords_to_region(lat, lon)
    return await get_mase_precedents(project_type, region, lat, lon)

@app.get("/api/enrich/regional")
async def get_regional(lat: float, lon: float, project_type: str = ""):
    return await get_regional_procedures(lat, lon, project_type)

@app.websocket("/ws/ai")
async def ai_chat(ws: WebSocket):
    await ws.accept()
    conversation = []
    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Keepalive ping
                await ws.send_json({"type": "ping"})
                continue
            data = json.loads(raw)

            if data.get("type") == "interpret":
                result = data.get("result", {})
                prompt = _build_interpretation_prompt(result)
                conversation = [{"role": "user", "content": prompt}]
                await _stream_ollama(ws, conversation, model=OLLAMA_MODEL, system=SYSTEM_PROMPT_TECHNICAL)

            elif data.get("type") == "react":
                # ReAct orchestrator with tool calling
                message = data.get("message", "")
                context = data.get("context", {})
                await run_react_stream(message, context, ws)

            elif data.get("type") == "chat":
                conversation.append({"role": "user", "content": data["message"]})
                await _stream_ollama(ws, conversation, model=OLLAMA_MODEL_CHAT, system=_get_system_prompt_chat())

    except WebSocketDisconnect:
        pass

def _build_interpretation_prompt(result: dict) -> str:
    indicators = result.get("indicators", [])
    ind_text = "\n".join([
        f"- {i['name']}: {i['score']}/100 ({i['level']}) | {i['notes']}"
        for i in indicators
    ])
    return f"""Interpreta i seguenti risultati della valutazione ambientale per il progetto "{result.get('project_name','')}" ({result.get('project_type','')}).

RISULTATI CALCOLATI DAL MOTORE GIS:
{ind_text}

RISCHIO GLOBALE: {result.get('global_score',0)}/100 — {result.get('global_level','')}
SCREENING VIA: {result.get('via_screening','')}

Fornisci:
1. Interpretazione tecnica degli indicatori più critici
2. Interazioni tra i rischi rilevati
3. Normative specifiche applicabili al tipo di progetto
4. Misure di mitigazione raccomandate
5. Indicazioni per gli approfondimenti necessari

NON ricalcolare i punteggi. Interpreta solo i dati forniti."""

async def _stream_ollama(ws: WebSocket, conversation: list, model: str = None, system: str = None):
    if model is None:
        model = OLLAMA_MODEL
    if system is None:
        system = _get_system_prompt_chat()
    full = ""
    in_think = False
    try:
        await ws.send_json({"type": "ai_start"})
    except Exception:
        return
    try:
        messages = [{"role": "system", "content": system}] + conversation
        if OPENROUTER_KEY:
            # OpenRouter — streaming SSE
            headers = {
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "HTTP-Referer": "https://geovia.local",
                "X-Title": "geoVIA",
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient(timeout=120, verify=False) as client:
                async with client.stream("POST", "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json={"model": model, "messages": messages, "stream": True}) as r:
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        chunk_str = line[6:]
                        if chunk_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(chunk_str)
                            token = chunk["choices"][0].get("delta", {}).get("content", "")
                            if token:
                                full += token
                                await ws.send_json({"type": "ai_token", "token": token})
                        except Exception:
                            continue
        else:
            # Ollama
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", f"{OLLAMA_URL}/api/chat",
                    json={"model": model, "messages": messages, "stream": True}) as r:
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except Exception:
                            continue
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            if "<think>" in token: in_think = True
                            if "</think>" in token:
                                in_think = False
                                token = token.split("</think>")[-1]
                            if not in_think:
                                full += token
                                try:
                                    await ws.send_json({"type": "ai_token", "token": token})
                                except Exception:
                                    return
                        if chunk.get("done"):
                            break
    except Exception:
        traceback.print_exc()
    conversation.append({"role": "assistant", "content": full})
    try:
        await ws.send_json({"type": "ai_done", "full": full})
    except Exception:
        pass
