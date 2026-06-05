# ApplyPilot Web App — Course Project Demo

AI-powered job application assistant with FastAPI backend + Streamlit frontend.

## Structure

```
web_app/
  backend/
    main.py                  # FastAPI server (port 8000)
    requirements.txt
    resume.txt               # Sample resume for scoring
    applypilot_core/
      __init__.py
      config.py              # Paths & defaults
      database.py            # SQLite wrapper
      discover.py            # Mock job discovery (6 sample marketing jobs)
      score.py               # Heuristic keyword-overlap scoring
      tailor.py              # Resume tailoring (keyword injection)
      cover.py               # Cover letter generation (template)
  frontend/
    app.py                   # Streamlit dashboard (port 8501)
    requirements.txt
```

## Quick Start

### 1. Install dependencies

```bash
# Backend
cd web_app/backend
pip install -r requirements.txt

# Frontend (separate terminal)
cd web_app/frontend
pip install -r requirements.txt
```

### 2. Start the backend

```bash
cd web_app/backend
python main.py
# → http://localhost:8000
# → API docs: http://localhost:8000/docs
```

### 3. Start the frontend

```bash
cd web_app/frontend
streamlit run app.py
# → http://localhost:8501
```

### 4. Use the app

1. Click **Start Pipeline** in the sidebar
2. Browse 6 sample marketing jobs with fit scores
3. Click **Tailor Resume** or **Cover Letter** on any job

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/start_pipeline` | Run discover → score in background |
| GET | `/jobs` | List all jobs (JSON) |
| GET | `/jobs/{id}` | Get single job |
| POST | `/tailor/{id}` | Generate tailored resume |
| POST | `/cover/{id}` | Generate cover letter |
| GET | `/stats` | Pipeline statistics |
| GET | `/health` | Health check |

## Mock Data

The discover module uses 6 realistic marketing jobs from HK employers
(Luk Fook, HSBC, Nike, Klook, etc.) instead of live scraping, so the
demo works without network dependencies or IP blocks.

To add your own jobs, edit `backend/applypilot_core/discover.py`
and add entries to the `SAMPLE_JOBS` list.
