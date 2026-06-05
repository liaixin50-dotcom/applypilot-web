"""Job scoring — heuristic keyword match between resume and job descriptions.

For demo purposes this uses lightweight token-overlap scoring (no API key needed).
In production, swap in the LLM-backed scorer from applypilot.scoring.scorer.
"""

from __future__ import annotations

import re
import logging
from collections import Counter
from datetime import datetime, timezone

from applypilot_core.config import RESUME_PATH
from applypilot_core.database import get_connection, get_all_jobs

log = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens."""
    return re.findall(r"[a-z0-9+#]+", text.lower())


def _score_overlap(resume: str, job_text: str) -> tuple[int, str, str]:
    """Score 1-10 based on keyword overlap between resume and job description."""
    r_toks = _tokenize(resume)
    j_toks = _tokenize(job_text)
    if not j_toks:
        return 1, "", "No job text"

    r_counts = Counter(r_toks)
    common = [t for t in set(j_toks) if t in r_counts]
    frac = len(common) / max(1, len(set(j_toks)))
    score = max(1, min(10, int(1 + round(frac * 9))))
    keywords = ", ".join(sorted(common)[:20])
    reasoning = f"Matched {len(common)} keywords; overlap={frac:.2f}"
    return score, keywords, reasoning


def score_jobs(conn=None, rescore: bool = False) -> dict:
    """Score all unscored jobs (or all jobs if rescore=True).

    Returns:
        {"scored": int, "errors": int}
    """
    if conn is None:
        conn = get_connection()

    # Load resume
    if RESUME_PATH.exists():
        resume = RESUME_PATH.read_text(encoding="utf-8")
    else:
        resume = "marketing digital campaign social media content strategy analytics branding communications"
        log.warning("No resume.txt found, using default keywords")

    # Get jobs to score
    if rescore:
        jobs = get_all_jobs(conn, limit=1000)
    else:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL"
        ).fetchall()
        cols = rows[0].keys() if rows else []
        jobs = [dict(zip(cols, r)) for r in rows]

    if not jobs:
        log.info("No jobs to score")
        return {"scored": 0, "errors": 0}

    now = datetime.now(timezone.utc).isoformat()
    scored = 0
    errors = 0

    for job in jobs:
        desc = job.get("full_description") or job.get("description") or ""
        try:
            s, keywords, reasoning = _score_overlap(resume, desc[:8000])
            conn.execute(
                "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ?, pipeline_status = 'scored' WHERE url = ?",
                (s, f"{keywords}\n{reasoning}", now, job["url"]),
            )
            scored += 1
        except Exception as e:
            log.error("Scoring error for %s: %s", job.get("title", "?"), e)
            errors += 1

    conn.commit()
    log.info("Scored %d jobs (%d errors)", scored, errors)
    return {"scored": scored, "errors": errors}
