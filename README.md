# Production RAG

Retrieval-Augmented Generation stack: upload documents, ingest them asynchronously, then chat with citations powered by a local **Ollama** LLM.

**Stack:** FastAPI · PostgreSQL · Qdrant · Redis · Celery · MinIO · React (Vite) · Ollama

```
Upload → MinIO → Celery (parse → chunk → embed → Qdrant)
Question → hybrid search (vector + BM25) → rerank → Ollama → answer + citations
```

---

## Prerequisites

| Tool | Why |
|---|---|
| [Docker](https://docs.docker.com/get-docker/) + Compose v2 | Runs API, worker, Postgres, Redis, Qdrant, MinIO |
| [Ollama](https://ollama.com) | Local LLM for answers (not auto-downloaded by Compose) |
| Node.js 18+ | Frontend playground only |
| Python 3.12+ | Only if you run the API outside Docker |

---

## 1. Clone / unzip

```bash
cd "retrieval augmented generation"   # or your extracted folder name
```

---

## 2. Configure environment

```bash
cp .env.example .env
```

Defaults work for Docker Compose. Important knobs:

| Variable | Purpose | Example |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama API from containers | `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | Model tag (must be pulled) | `llama3.1:8b` |
| `EMBEDDING_PROVIDER` | Embeddings | `bge` (default) or `openai` |

Change `OLLAMA_MODEL` in `.env` to match whatever you pull — no code changes needed.

---

## 3. Install and start Ollama

Compose does **not** pull LLM weights. Do this once on the host:

```bash
# Install from https://ollama.com/download
# Bind on all interfaces so Docker can reach the host API
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# Another terminal — pull a model (pick one you have disk/RAM for)
ollama pull llama3.1:8b
ollama list
```

Set `OLLAMA_MODEL=llama3.1:8b` (or your chosen tag) in `.env`.

**Linux systemd (persist bind address):**

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | sudo tee /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

**Optional:** run Ollama inside Compose instead:

```bash
docker compose --profile ollama up -d ollama
# In .env: OLLAMA_BASE_URL=http://ollama:11434
docker compose exec ollama ollama pull llama3.1:8b
```

---

## 4. Start the backend (Docker Compose)

```bash
docker compose up -d --build
docker compose ps
```

| Service | Host port |
|---|---|
| API | `8000` |
| PostgreSQL | `5432` |
| Redis | `6380` |
| Qdrant | `6333` / `6334` |
| MinIO API / Console | `9010` / `9011` |

Migrations run automatically on API startup (`alembic upgrade head`).

**Check health:**

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/ready
```

`/ready` should show Postgres, Redis, Qdrant, MinIO, and Ollama as `ok` once the model is pulled.

Follow logs:

```bash
docker compose logs -f api worker
```

---

## 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api`, `/health`, and `/ready` to the API on port 8000.

Sample uploads: `samples/HR.txt`, `samples/Netflix.txt`, `samples/hybrid_retrieval.txt`.

**Typical flow in the UI:** upload a file → wait for ingestion → ask a question in chat.

---

## 6. Use the API (without the UI)

```bash
# Upload
curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@samples/HR.txt;type=text/plain"

# Async ingest (parse → chunk → embed → index)
DOC_ID=<id-from-upload>
curl -s -X POST "http://localhost:8000/api/v1/ingestion/${DOC_ID}"
curl -s "http://localhost:8000/api/v1/ingestion/${DOC_ID}/status"

# Chat
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d "{\"message\":\"Summarize this document\",\"document_ids\":[\"${DOC_ID}\"]}"

# Streaming (SSE)
curl -N -X POST http://localhost:8000/api/v1/chat/stream \
  -H 'Content-Type: application/json' \
  -d "{\"message\":\"Summarize this document\",\"document_ids\":[\"${DOC_ID}\"]}"
```

Supported uploads: PDF, DOCX, XLSX, CSV, PPTX, TXT, Markdown, HTML (max size: `MAX_UPLOAD_SIZE_MB`, default 50).

Interactive docs: **http://localhost:8000/docs**

---

## Run API on the host (optional)

Infrastructure still in Docker; API via local Python:

```bash
docker compose up -d postgres redis qdrant minio minio-init
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Point `.env` hosts at localhost, e.g.:

- `POSTGRES_HOST=localhost`
- `REDIS_HOST=localhost`, `REDIS_URL=redis://localhost:6380/0` (and Celery URLs on `6380`)
- `QDRANT_URL=http://localhost:6333`
- `MINIO_ENDPOINT=localhost:9010`
- `OLLAMA_BASE_URL=http://localhost:11434`
- `DATABASE_URL` / `DATABASE_URL_SYNC` with `localhost`

```bash
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# Celery worker (separate terminal):
./scripts/celery_worker.sh
```

---

## Project layout

```text
.
├── app/                 # FastAPI backend
│   ├── api/v1/          # health, documents, ingestion, chat, metrics
│   ├── ingestion/       # parse, clean, chunk, embed, pipeline
│   ├── retrieval/       # vector, BM25, hybrid, rerank
│   ├── generation/      # Ollama client, prompts, streaming
│   ├── services/        # business logic
│   ├── workers/         # Celery tasks
│   ├── database/        # Postgres, Redis, Qdrant
│   └── storage/         # MinIO
├── alembic/             # DB migrations
├── frontend/            # React + Vite playground
├── samples/             # example documents
├── scripts/             # entrypoint, Celery, MinIO init
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

## Common settings

| Area | Variables |
|---|---|
| LLM | `OLLAMA_*` |
| Embeddings | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` |
| Chunking | `CHUNK_SIZE`, `CHUNK_OVERLAP`, `CHUNK_STRATEGY` |
| Retrieval | `RETRIEVAL_MODE`, `RETRIEVAL_TOP_K`, `RERANK_ENABLED`, `HYBRID_ALPHA` |
| Logging | `LOG_ENABLED`, `LOG_LEVEL`, `LOG_JSON=false` for human-readable logs |

Optional heavy PDF parser (Docling):

```bash
pip install -r requirements-docling.txt
# PARSER_BACKEND=docling  (or auto)
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/ready` Ollama degraded | Pull the model named in `OLLAMA_MODEL`; ensure `OLLAMA_HOST=0.0.0.0` |
| Containers cannot reach Ollama | Use `http://host.docker.internal:11434` (Compose already maps `host-gateway` on Linux) |
| First embed is slow | BGE ONNX model downloads into the `embedding_models` volume once |
| Port conflicts | Change host ports in `.env` / `docker-compose.yml` |
| Stop everything | `docker compose down` |

---

## License

Proprietary / project-local — update as needed.
