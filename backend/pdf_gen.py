from datetime import datetime

async def generate_pdf(name, lat, lon, area_m2, project_type, result, ai_report) -> tuple:
    """Returns (bytes, media_type)"""
    html = _build_html(name, lat, lon, area_m2, project_type, result, ai_report)
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html).write_pdf()
        print(f"[PDF] generated {len(pdf_bytes)} bytes")
        return pdf_bytes, "application/pdf"
    except Exception as e:
        print(f"[PDF] weasyprint failed: {e}")
        return html.encode("utf-8"), "text/html"

def _build_html(name, lat, lon, area_m2, project_type, result, ai_report) -> str:
    level_colors = {"MOLTO ALTO":"#c0392b","ALTO":"#e67e22","MEDIO":"#f39c12","BASSO":"#27ae60","TRASCURABILE":"#2ecc71"}
    gc = level_colors.get(result.get("global_level","MEDIO"),"#f39c12")

    rows = ""
    for i in result.get("indicators", []):
        c = level_colors.get(i["level"], "#f39c12")
        bar = f'<div style="background:#e9ecef;border-radius:3px;height:10px"><div style="background:{c};width:{i["score"]}%;height:10px;border-radius:3px"></div></div>'
        rows += f"""<tr>
            <td style="padding:8px;font-weight:500">{i['name']}</td>
            <td style="padding:8px;width:160px">{bar}</td>
            <td style="padding:8px;font-weight:bold;color:{c}">{i['score']}/100</td>
            <td style="padding:8px"><span style="background:{c};color:white;padding:2px 8px;border-radius:10px;font-size:11px">{i['level']}</span></td>
            <td style="padding:8px;font-size:11px">{i['source']}</td>
        </tr>
        <tr><td colspan="5" style="padding:2px 8px 10px;font-size:11px;color:#666;border-bottom:1px solid #eee">
            {i['notes']}
        </td></tr>"""

    screening_color = "#c0392b" if "PROBABILE" in result.get("via_screening","") else "#e67e22" if "CONSIGLIATA" in result.get("via_screening","") else "#27ae60"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
body{{font-family:'Helvetica Neue',Arial,sans-serif;color:#2c3e50;margin:40px;font-size:13px}}
.header{{border-bottom:3px solid #2c3e50;padding-bottom:20px;margin-bottom:30px}}
.logo{{font-size:22px;font-weight:bold;color:#1a252f}}
.subtitle{{color:#7f8c8d;font-size:12px;margin-top:4px}}
.global{{background:{gc};color:white;padding:16px 20px;border-radius:8px;margin:20px 0;display:flex;align-items:center;gap:20px}}
.global h2{{margin:0;font-size:32px}}
.screening{{background:{screening_color}15;border-left:4px solid {screening_color};padding:12px 16px;margin:16px 0;font-size:12px}}
table{{width:100%;border-collapse:collapse;margin:16px 0}}
th{{background:#2c3e50;color:white;padding:10px;text-align:left;font-size:12px}}
.ai-report{{background:#f8f9fa;border-left:4px solid #2c3e50;padding:16px;margin:16px 0;white-space:pre-wrap;font-size:12px;line-height:1.7}}
.footer{{border-top:1px solid #bdc3c7;margin-top:40px;padding-top:12px;font-size:10px;color:#95a5a6}}
.meta{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:16px 0;font-size:12px}}
.meta-item{{background:#f8f9fa;padding:8px 12px;border-radius:4px}}
.meta-label{{color:#7f8c8d;font-size:10px;text-transform:uppercase}}
</style></head><body>
<div class="header">
  <div class="logo">🌍 geoVIA — Valutazione Impatto Ambientale</div>
  <div class="subtitle">Report generato il {datetime.now().strftime('%d/%m/%Y alle %H:%M')} | Motore GIS deterministico + AI Ollama</div>
</div>

<h2>📋 {name}</h2>
<div class="meta">
  <div class="meta-item"><div class="meta-label">Tipo Progetto</div>{project_type.upper() or 'N/D'}</div>
  <div class="meta-item"><div class="meta-label">Coordinate</div>{lat:.5f}°N, {lon:.5f}°E</div>
  <div class="meta-item"><div class="meta-label">Area</div>{area_m2:,.0f} m² ({area_m2/10000:.2f} ha)</div>
  <div class="meta-item"><div class="meta-label">ID Progetto</div>{result.get('project_id','N/D')}</div>
</div>

<div class="global">
  <div><h2>{result.get('global_score',0)}/100</h2><div style="font-size:14px">{result.get('global_level','')}</div></div>
  <div style="font-size:13px">Rischio Ambientale Complessivo<br><small>Media ponderata 6 indicatori</small></div>
</div>

<div class="screening"><strong>⚖️ Screening VIA/VAS:</strong> {result.get('via_screening','')}</div>

<h3>Indicatori di Rischio</h3>
<table>
  <tr><th>Indicatore</th><th>Livello</th><th>Score</th><th>Classe</th><th>Fonte</th></tr>
  {rows}
</table>

<h3>Interpretazione AI — {datetime.now().strftime('%d/%m/%Y')}</h3>
<div class="ai-report">{ai_report or 'Report AI non disponibile.'}</div>

<div class="footer">
  geoVIA | Fonti: ISPRA IdroGEO, INGV MPS04, Rete Natura 2000, CORINE Land Cover, OpenAQ, OSM |
  Questo documento è uno strumento di supporto tecnico. Non sostituisce la procedura formale VIA/VAS
  né il parere dell'autorità competente ai sensi del D.Lgs 152/2006.
</div>
</body></html>"""
