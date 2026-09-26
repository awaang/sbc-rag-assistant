# SBC RAG Assistant

An authenticated demo that answers questions about health benefit plans with cited, evidence-backed answers, and abstains when the evidence is missing, ambiguous, or conflicting.

Admins upload plan PDFs, which the API automatically parses (preserving table rows), chunks, embeds locally, and uses to extract structured benefit values. Chat answers come from BM25 or FAISS semantic retrieval plus the extracted benefits, formatted deterministically with plan, section, and page citations. Gemini then writes the reply from the server's checked evidence; the server keeps the answer status and citations, and returns the deterministic answer if the Gemini API fails or its reply adds or drops a benefit value. Chat transcripts live only in browser memory.

The six PDFs in `data/source-documents/received/` are a provisional development corpus. Their SBC status and public availability are unverified, so treat all results as provisional and scoped to these files.

## Documents

- [Design Document](https://docs.google.com/document/d/11ZSbb5nSUgFteI2Futzni3PQPICCCrJea69ZhLoZgmA/edit?usp=sharing)
- [Reflection Document](https://docs.google.com/document/d/19jw4UGpzimGdHUVPghQKite5jk0CcMReJ5caYO95gZ0/edit?usp=sharing)

## Requirements

- Python 3.11+
- Node.js 20+ and npm
- A Firebase project with Email/Password sign-in enabled, a registered web app, and a service-account JSON file stored outside this repository
- A Neon Postgres database
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)

## Setup and running

### 1. Configure environment

1. Copy the `VITE_*` values from `.env.example` into `frontend/.env.local` and fill in the Firebase web app values.
2. Copy the backend values from `.env.example` into a repository-root `.env`, then set:
   - `DATABASE_URL`: Neon connection string (SSL enabled)
   - `FIREBASE_PROJECT_ID`
   - `GOOGLE_APPLICATION_CREDENTIALS`: path to the service-account JSON
   - `FRONTEND_ORIGIN=http://localhost:5173`
   - `GEMINI_ENABLED=true` and `GEMINI_API_KEY`: keep the key in this API `.env` only, never in a `VITE_*` variable
3. In Firebase Console, make sure `localhost` is an authorized domain.

### 2. Run the API

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.db.migrate        # create/update the Neon schema
uvicorn app.main:app --reload
```

- Health check: `http://localhost:8000/api/health`
- API docs: `http://localhost:8000/docs`

Rerun `python -m app.db.migrate` after pulling schema changes. The first document upload downloads the sentence-transformer model.

### 3. Run the frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` and register or sign in. Run `npm run build` to create a production bundle.

### 4. Grant admin access

From `backend/` with the service-account credentials configured:

```bash
python -m app.admin_claims grant user@example.com
python -m app.admin_claims revoke user@example.com
```

The user has to sign out and back in (or refresh their ID token) for the change to take effect. Admins can upload PDFs from **Plans**; each upload is processed automatically and becomes available to Chat once processing succeeds.

### 5. Run tests

```bash
cd backend
python -m pytest
```

### Maintenance commands

Run these from `backend/`:

```bash
python -m app.pipeline                             # process any pending documents
python -m app.pipeline --reprocess-id DOCUMENT_ID  # rebuild one document's derived data
```

### Deploy to Render

`render.yaml` defines the API web service and the static frontend.

1. Connect the repository as a Render Blueprint and fill in the prompted Firebase, Neon, Gemini API key, and frontend values.
2. Upload the service-account JSON as the Secret File `firebase-service-account.json`.
3. Once both services exist, set `VITE_API_BASE_URL` on the static site to the API URL and `FRONTEND_ORIGIN` on the API to the static site URL, then redeploy both.

Render Free provides 512 MiB of memory, which local profiling of automatic processing exceeded, so processing uploads on that plan is unverified.

## Repository overview

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app and routes
│   │   ├── ingestion.py       # PDF parsing and table-preserving chunking
│   │   ├── benefits.py        # Structured benefit extraction
│   │   ├── embed.py           # Local sentence-transformer embeddings
│   │   ├── retrieval.py       # BM25 and FAISS search
│   │   ├── answering.py       # Evidence gate, citations, deterministic answers
│   │   ├── gemini.py          # Gemini-written replies
│   │   ├── pipeline.py        # Full processing pipeline (maintenance CLI)
│   │   ├── auto_ingestion.py  # Background processing queue for uploads
│   │   ├── ingest.py          # Parse-only maintenance CLI
│   │   ├── admin_claims.py    # Grant/revoke Firebase admin role
│   │   └── db/migrate.py      # Applies SQL migrations
│   ├── migrations/            # Ordered PostgreSQL schema migrations
│   ├── tests/                 # pytest suite
│   └── requirements.txt
├── frontend/                  # React + TypeScript + Vite + Tailwind UI
│   └── src/App.tsx            # Main app (Plans, Chat, Profile, admin pages)
├── data/source-documents/received/  # Provisional PDFs and metadata.json
├── evaluation/questions.json  # Labeled evaluation questions
├── render.yaml                # Render Blueprint
├── .env.example               # Configuration variable names
├── PRD.md                     # Product requirements
├── ARCHITECTURE.md            # System design and data flow
├── PLAN.md                    # Implementation plan and status
└── AGENTS.md                  # Coding-agent guidelines
```
