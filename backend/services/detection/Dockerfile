FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/services/detection

ENV PYTHONPATH=/app
CMD ["uvicorn", "services.detection.app:app", "--host", "0.0.0.0", "--port", "8001"]
