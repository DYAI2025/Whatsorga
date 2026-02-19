FROM python:3.12-slim

WORKDIR /app

# Install build deps for numpy wheels
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the sentence-transformer model so startup is fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY app/ ./app/
COPY data/ ./data/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
