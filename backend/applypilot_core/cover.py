"""Cover letter generation — creates a tailored cover letter for a job.

For demo purposes this fills a template with job-specific details.
In production this would call an LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from applypilot_core.database import get_connection

log = logging.getLogger(__name__)

COVER_TEMPLATE = """Dear Hiring Manager,

I am writing to express my strong interest in the {title} position at {company}. With my background in business and marketing, combined with hands-on experience in market research, digital content creation, and campaign execution, I am confident I can make a meaningful contribution to your team.

{body}

I would welcome the opportunity to discuss how my skills and enthusiasm can benefit {company}. Thank you for considering my application.

Sincerely,
Aixin Li
"""


def _generate_body(job_desc: str, keywords: list[str]) -> str:
    """Generate the body paragraph from job keywords."""
    kw_list = ", ".join(keywords[:5]).lower()
    return (
        f"Through my academic training at Shanghai International Studies University "
        f"and internships at Fosun Pharma and Golden Education, I have developed "
        f"strong competencies in {kw_list}. I am particularly drawn to this role "
        f"because it aligns with my passion for data-driven marketing and my desire "
        f"to grow in a dynamic, collaborative environment. My experience conducting "
        f"market research, managing social media campaigns, and analyzing performance "
        f"metrics has prepared me to hit the ground running and deliver results from day one."
    )


def generate_cover_letter(job_url: str, conn=None) -> dict:
    """Generate a cover letter for a specific job.

    Args:
        job_url: The URL (primary key) of the job in the database.

    Returns:
        {"cover_letter": str}
    """
    if conn is None:
        conn = get_connection()

    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (job_url,)).fetchone()
    if not row:
        return {"error": f"Job not found: {job_url}"}

    job = dict(zip(row.keys(), row))

    from applypilot_core.tailor import _extract_keywords
    desc = job.get("full_description") or job.get("description") or ""
    kws = _extract_keywords(desc, top_n=8)

    body = _generate_body(desc, kws)
    cover = COVER_TEMPLATE.format(
        title=job.get("title", "the position"),
        company=job.get("company", job.get("site", "your organization")),
        body=body,
    )

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET cover_letter_path = ?, cover_letter_at = ?, pipeline_status = 'cover_done' WHERE url = ?",
        (f"cover_{job_url[-20:]}.txt", now, job_url),
    )
    conn.commit()

    return {"cover_letter": cover, "keywords": kws, "job_title": job["title"]}
