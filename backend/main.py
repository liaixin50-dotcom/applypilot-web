"""ApplyPilot Web API — FastAPI backend for the AI job application dashboard.

Endpoints (matched to Streamlit frontend):
    POST /start_pipeline   — run discover → score in background
    GET  /jobs             — list all jobs as JSON
    POST /tailor/{job_id}  — generate tailored resume for a job
    POST /cover/{job_id}   — generate cover letter for a job
    GET  /stats            — pipeline statistics

Usage:
    cd web_app/backend
    python main.py          # starts on http://localhost:8000
    uvicorn main:app --reload
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from applypilot_core.database import init_db, get_connection, get_all_jobs, get_stats
from applypilot_core.discover import discover_jobs
from applypilot_core.score import score_jobs
from applypilot_core.tailor import tailor_resume_for_job
from applypilot_core.cover import generate_cover_letter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Profile persistence paths ───────────────────────────────────────────────

import os as _os
from pathlib import Path as _Path

_APPLYPILOT_DIR = _Path(_os.environ.get("APPLYPILOT_DIR", _Path.home() / ".applypilot"))
_PROFILE_PATH = _APPLYPILOT_DIR / "profile.json"

# In-memory profile cache (survives between requests in the same process)
_current_profile: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    init_db()
    log.info("Database initialized at %s", __import__("applypilot_core.config").config.DB_PATH)
    yield


app = FastAPI(
    title="ApplyPilot API",
    description="AI-powered job application pipeline — course project demo",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global pipeline status (polled by frontend) ────────────────────────────

pipeline_status: dict = {"stage": "idle", "progress": 0}


# ── Helpers ────────────────────────────────────────────────────────────────

def _job_to_dict(row: dict) -> dict:
    """Convert a DB row to the JSON shape the frontend expects."""
    url = row.get("url", "")
    return {
        "id": hashlib.md5(url.encode()).hexdigest()[:12],
        "url": url,
        "title": row.get("title") or "Untitled",
        "company": row.get("company") or row.get("site") or "Unknown",
        "salary": row.get("salary"),
        "location": row.get("location"),
        "description": (row.get("full_description") or row.get("description") or "")[:500],
        "score": row.get("fit_score"),
        "score_reasoning": row.get("score_reasoning"),
        "pipeline_status": row.get("pipeline_status", "discovered"),
        "tailored_at": row.get("tailored_at"),
        "cover_letter_at": row.get("cover_letter_at"),
        "discovered_at": row.get("discovered_at"),
        "scored_at": row.get("scored_at"),
    }


def _run_full_pipeline() -> None:
    """Synchronous pipeline: discover → score. Runs in a background thread."""
    log.info("=== Pipeline started (background) ===")

    pipeline_status["stage"] = "discovering"
    pipeline_status["progress"] = 10
    try:
        result = discover_jobs(clear_first=True)
        log.info("Discover: %s", result)
        pipeline_status["progress"] = 50
    except Exception as e:
        log.exception("Discover failed: %s", e)
        pipeline_status["stage"] = "error"
        return

    pipeline_status["stage"] = "scoring"
    pipeline_status["progress"] = 60
    try:
        result = score_jobs()
        log.info("Score: %s", result)
        pipeline_status["progress"] = 100
    except Exception as e:
        log.exception("Score failed: %s", e)
        pipeline_status["stage"] = "error"
        return

    pipeline_status["stage"] = "done"
    pipeline_status["progress"] = 100
    log.info("=== Pipeline complete ===")


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.post("/start_pipeline")
async def start_pipeline(background_tasks: BackgroundTasks):
    """Trigger the discover → score pipeline asynchronously.

    Returns immediately; work happens in the background.
    """
    if pipeline_status["stage"] in ("discovering", "scoring"):
        return {
            "message": "Pipeline already running",
            "status": pipeline_status["stage"],
            "progress": pipeline_status["progress"],
        }
    pipeline_status["stage"] = "queued"
    pipeline_status["progress"] = 0
    background_tasks.add_task(_run_full_pipeline)
    log.info("Pipeline queued")
    return {
        "message": "Pipeline started — discover → score running in background",
        "status": "queued",
        "progress": 0,
    }


@app.get("/jobs")
async def list_jobs(status: Optional[str] = None, limit: int = 100):
    """Return all jobs as JSON.

    Query params:
        status  — filter by pipeline_status (e.g. 'scored', 'tailored')
        limit   — max jobs to return (default 100)
    """
    conn = get_connection()
    rows = get_all_jobs(conn, status=status, limit=limit)
    jobs = [_job_to_dict(r) for r in rows]
    log.info("GET /jobs → %d results (status=%s)", len(jobs), status)
    return jobs


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Return a single job by its computed ID."""
    conn = get_connection()
    for row in get_all_jobs(conn, limit=1000):
        d = _job_to_dict(row)
        if d["id"] == job_id:
            return d
    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@app.post("/tailor/{job_id}")
async def tailor_job(job_id: str):
    """Generate a tailored resume for the given job.

    Returns {"resume": "...", "keywords": [...]}
    """
    conn = get_connection()
    # Resolve job_id → url
    target_url = None
    for row in get_all_jobs(conn, limit=1000):
        d = _job_to_dict(row)
        if d["id"] == job_id:
            target_url = d["url"]
            break

    if not target_url:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    result = tailor_resume_for_job(target_url, conn=conn)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/cover/{job_id}")
async def cover_job(job_id: str):
    """Generate a cover letter for the given job.

    Returns {"cover_letter": "..."}
    """
    conn = get_connection()
    target_url = None
    for row in get_all_jobs(conn, limit=1000):
        d = _job_to_dict(row)
        if d["id"] == job_id:
            target_url = d["url"]
            break

    if not target_url:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    result = generate_cover_letter(target_url, conn=conn)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.get("/stats")
async def pipeline_stats():
    """Return pipeline statistics."""
    return get_stats()


@app.get("/status")
async def get_status():
    """Return current pipeline progress (polled by frontend)."""
    return pipeline_status


@app.post("/profile")
async def save_profile(profile: dict):
    """Receive a full profile.json payload from the frontend.

    Writes it to ~/.applypilot/profile.json and caches it in memory
    so that downstream stages (score, tailor, cover) can use real user data.
    """
    global _current_profile
    import json

    _APPLYPILOT_DIR.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    _current_profile = profile

    # Also rebuild resume.txt from profile so the scorer uses real content
    _rebuild_resume_from_profile(profile)

    log.info("Profile saved → %s", _PROFILE_PATH)
    return {
        "message": "Profile saved successfully",
        "path": str(_PROFILE_PATH),
        "keys": list(profile.keys()),
    }


@app.get("/profile")
async def load_profile():
    """Return the currently loaded profile (or empty dict if none set)."""
    if _current_profile:
        return _current_profile
    import json
    if _PROFILE_PATH.exists():
        return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
    return {}


# ── Profile → resume.txt builder ────────────────────────────────────────────

def _rebuild_resume_from_profile(profile: dict) -> None:
    """Convert profile.json fields into a plain-text resume for the scorer."""
    from applypilot_core.config import RESUME_PATH as _RESUME_PATH

    personal = profile.get("personal", {})
    experience = profile.get("experience", {})
    skills = profile.get("skills_boundary", {})
    facts = profile.get("resume_facts", {})
    work_auth = profile.get("work_authorization", {})
    availability = profile.get("availability", {})
    compensation = profile.get("compensation", {})

    lines = [
        f"{personal.get('full_name', 'Candidate')}",
        f"Email: {personal.get('email', '')} | Phone: {personal.get('phone', '')}",
        f"Location: {personal.get('city', '')}, {personal.get('province_state', '')}, {personal.get('country', '')}",
        f"LinkedIn: {personal.get('linkedin_url', '')}",
        "",
        "PROFESSIONAL SUMMARY",
        f"{experience.get('current_job_title', 'Professional')} with "
        f"{experience.get('years_of_experience_total', 'X')} years of experience. "
        f"Target role: {experience.get('target_role', '')}. "
        f"Education: {experience.get('education_level', '')}.",
        "",
        "TECHNICAL SKILLS",
    ]

    for category, items in skills.items():
        if isinstance(items, list) and items:
            lines.append(f"  {category}: {', '.join(items)}")

    lines.append("")
    lines.append("WORK EXPERIENCE")
    for company in facts.get("preserved_companies", []):
        lines.append(f"  - {company}")

    if facts.get("preserved_school"):
        lines.append("")
        lines.append("EDUCATION")
        lines.append(f"  {facts['preserved_school']}")

    lines.append("")
    lines.append("ADDITIONAL INFO")
    lines.append(f"  Work Authorization: {work_auth.get('legally_authorized_to_work', 'N/A')}")
    lines.append(f"  Sponsorship Required: {work_auth.get('require_sponsorship', 'N/A')}")
    lines.append(f"  Available: {availability.get('earliest_start_date', 'N/A')}")
    lines.append(f"  Salary Expectation: {compensation.get('salary_currency', 'USD')} {compensation.get('salary_expectation', 'N/A')}")

    _RESUME_PATH.write_text("\n".join(lines), encoding="utf-8")
    log.info("Resume rebuilt from profile → %s (%d chars)", _RESUME_PATH, len("\n".join(lines)))


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Run directly ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    print(f"Starting ApplyPilot API at http://0.0.0.0:{port}")
    print(f"Docs: http://0.0.0.0:{port}/docs")
    uvicorn.run(app, host="0.0.0.0", port=port)
