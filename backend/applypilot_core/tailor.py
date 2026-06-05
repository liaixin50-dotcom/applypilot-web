"""Resume tailoring — rewrites resume bullets to match job keywords.

For demo purposes this inserts job-specific keywords into a template.
In production this would call an LLM (Gemini / Claude / OpenAI).
"""

from __future__ import annotations

import re
import logging
from datetime import datetime, timezone

from applypilot_core.config import RESUME_PATH
from applypilot_core.database import get_connection

log = logging.getLogger(__name__)


def _extract_keywords(job_desc: str, top_n: int = 10) -> list[str]:
    """Extract salient keywords from a job description."""
    # Simple TF-based extraction (demo only)
    words = re.findall(r"[a-zA-Z]{4,}", job_desc.lower())
    stopwords = {
        "with", "that", "this", "from", "they", "have", "will", "your",
        "about", "each", "more", "some", "than", "which", "their", "other",
        "experience", "years", "candidate", "responsible", "including",
        "requirements", "position", "department", "related", "skills",
        "ability", "knowledge", "required", "minimum", "preferred",
    }
    from collections import Counter
    freq = Counter(w for w in words if w not in stopwords)
    return [w.title() for w, _ in freq.most_common(top_n)]


def tailor_resume_for_job(job_url: str, conn=None) -> dict:
    """Generate a tailored resume for a specific job.

    Args:
        job_url: The URL (primary key) of the job in the database.

    Returns:
        {"resume": str, "keywords": list[str]}
    """
    if conn is None:
        conn = get_connection()

    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (job_url,)).fetchone()
    if not row:
        return {"error": f"Job not found: {job_url}"}

    job = dict(zip(row.keys(), row))

    # Load base resume
    if RESUME_PATH.exists():
        base = RESUME_PATH.read_text(encoding="utf-8")
    else:
        base = (
            "Aixin Li\n"
            "Email: liaixin50@gmail.com | Tel: (086)15695196785\n\n"
            "Professional Summary:\n"
            "Business English graduate with hands-on experience in market research, "
            "digital marketing, and data analysis. Skilled in content creation, "
            "social media management, and campaign planning.\n\n"
            "Experience:\n"
            "- Marketing & HR Intern, Fosun Pharma (2024)\n"
            "- Campus Ambassador, Golden Education (2021-2022)\n"
            "- Publicity & Media Dept, Student Union (2021-2023)\n\n"
            "Education:\n"
            "B.A. Business English, Shanghai International Studies University (2025)\n\n"
            "Skills: MS Office, Python, SPSS, Adobe Photoshop, Adobe Premiere"
        )

    # Extract job keywords and inject into tailored summary
    desc = job.get("full_description") or job.get("description") or ""
    kws = _extract_keywords(desc, top_n=10)
    kw_str = ", ".join(kws[:8])

    tailored = (
        f"[TAILORED FOR: {job['title']} at {job.get('company', job.get('site', ''))}]\n\n"
        f"Aixin Li\n"
        f"Email: liaixin50@gmail.com | Tel: (086)15695196785\n\n"
        f"Professional Summary:\n"
        f"Business English graduate with targeted experience in {kw_str.lower()}. "
        f"Proven ability to apply analytical and creative skills to drive marketing "
        f"outcomes in fast-paced environments.\n\n"
        f"Key Skills Highlighted for This Role:\n"
        f"{chr(10).join(f'- {k}' for k in kws)}\n\n"
        f"{base.split('Experience:', 1)[1] if 'Experience:' in base else base}"
    )

    # Save to DB
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET tailored_resume_path = ?, tailored_at = ?, pipeline_status = 'tailored' WHERE url = ?",
        (f"tailored_{job_url[-20:]}.txt", now, job_url),
    )
    conn.commit()

    return {"resume": tailored, "keywords": kws, "job_title": job["title"]}
