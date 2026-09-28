# SBC RAG Assistant

An assistant that answers questions about six health benefit plans (four medical, one dental, one vision). Answers include plan, section, and page citations, and the assistant abstains when the evidence is insufficient.

**Live demo:** [sbc-rag-assistant.onrender.com](https://sbc-rag-assistant.onrender.com)

## Showing My Work

- [Design Document](https://docs.google.com/document/d/11ZSbb5nSUgFteI2Futzni3PQPICCCrJea69ZhLoZgmA/edit?usp=sharing): answers the questions from the project spec, including which chunking strategy I picked and why, how BM25 and semantic search performed, how accurate extraction was, and what I would do differently with a real budget
- [Reflection Document](https://docs.google.com/document/d/19jw4UGpzimGdHUVPghQKite5jk0CcMReJ5caYO95gZ0/edit?usp=sharing): how I built this project, what went wrong, and what I learned

## Requirements

- Python 3.11+
- Node.js 20+ and npm
- A Firebase project with Email/Password sign-in enabled, a registered web app, and a service-account JSON file stored outside this repository
- A Neon Postgres database
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)

## Setup

### 1. Configure environment

1. Copy the `VITE_*` values from `.env.example` into `frontend/.env.local` and fill in your Firebase web app values.
2. Copy the backend values from `.env.example` into `.env` at the repository root and set:
   - `DATABASE_URL`: Neon connection string (SSL enabled)
   - `FIREBASE_PROJECT_ID`
   - `GOOGLE_APPLICATION_CREDENTIALS`: path to the service-account JSON
   - `GEMINI_API_KEY`: keep this in `.env` only, never in a `VITE_*` variable
3. In the Firebase Console, make sure `localhost` is an authorized domain.

### 2. Run the API

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.db.migrate
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000` (docs at `/docs`). Rerun `python -m app.db.migrate` after pulling schema changes.

### 3. Run the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` and register or sign in.

### 4. Grant admin access

From `backend/`, with the virtual environment active:

```bash
python -m app.admin_claims grant user@example.com
```

The user must sign out and back in for the role to take effect. Admins upload the PDFs in `data/source-documents/received/` from the **Plans** page; each upload is processed automatically and becomes available in Chat once processing succeeds.
