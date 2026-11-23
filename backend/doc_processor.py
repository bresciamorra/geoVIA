import io

async def extract_text(filename: str, content: bytes) -> str:
    ext = filename.lower().split(".")[-1]
    try:
        if ext == "pdf":
            import pdfplumber
            text = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages[:15]:
                    t = page.extract_text()
                    if t: text.append(t)
            return "\n".join(text)[:10000]
        elif ext in ("doc","docx"):
            from docx import Document
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())[:10000]
        elif ext in ("xls","xlsx"):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            rows = []
            for sheet in wb.worksheets[:3]:
                rows.append(f"[{sheet.title}]")
                for row in sheet.iter_rows(max_row=100, values_only=True):
                    vals = [str(c) for c in row if c is not None]
                    if vals: rows.append(" | ".join(vals))
            return "\n".join(rows)[:10000]
        elif ext in ("png","jpg","jpeg","tiff","bmp"):
            import pytesseract
            from PIL import Image
            img = Image.open(io.BytesIO(content))
            return pytesseract.image_to_string(img, lang="ita+eng")[:10000]
        else:
            return content.decode("utf-8", errors="ignore")[:5000]
    except Exception as e:
        return f"[Errore estrazione: {e}]"
