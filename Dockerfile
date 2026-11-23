FROM python:3.12-slim

WORKDIR /app

# System deps for rasterio, weasyprint, geopandas
RUN apt-get update && apt-get install -y \
    libgdal-dev gdal-bin \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libglib2.0-0 libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PORT=8002

EXPOSE 8002

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8002}"]
