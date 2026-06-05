"""ApplyPilot — Standalone Streamlit App (no separate backend needed).

Deploy directly to Streamlit Cloud for a single public URL.
All pipeline logic (discover → score → tailor → cover) runs in-process.

Deploy:
    1. Push this repo to GitHub
    2. Go to https://share.streamlit.io → New App
    3. Point to: frontend/streamlit_app.py
    4. Done — one public URL!
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

# ── Add backend modules to path ────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from applypilot_core.database import init_db, get_connection, get_all_jobs, store_jobs
from applypilot_core.discover import SAMPLE_JOBS, discover_jobs
from applypilot_core.tailor import _extract_keywords

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# In-process pipeline (no HTTP needed)
# ═════════════════════════════════════════════════════════════════════════════

PROFILE_PATH = _BACKEND / "profile.json"
RESUME_PATH = _BACKEND / "resume.txt"
PIPELINE_STATE: dict = {"stage": "idle", "progress": 0}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", text.lower())


def _score_overlap(resume: str, job_text: str) -> tuple[int, str, str]:
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


def _rebuild_resume(profile: dict) -> str:
    """profile.json → plain-text resume."""
    p = profile.get("personal", {})
    exp = profile.get("experience", {})
    skills = profile.get("skills_boundary", {})
    facts = profile.get("resume_facts", {})
    wa = profile.get("work_authorization", {})
    avail = profile.get("availability", {})
    comp = profile.get("compensation", {})

    lines = [
        f"{p.get('full_name', 'Candidate')}",
        f"Email: {p.get('email', '')} | Phone: {p.get('phone', '')}",
        f"City: {p.get('city', '')}, {p.get('country', '')}",
        "",
        f"PROFESSIONAL SUMMARY",
        f"{exp.get('current_job_title', 'Professional')} with "
        f"{exp.get('years_of_experience_total', 'X')} years. "
        f"Target: {exp.get('target_role', '')}. "
        f"Education: {exp.get('education_level', '')}.",
        "",
        "SKILLS",
    ]
    for cat, items in skills.items():
        if isinstance(items, list) and items:
            lines.append(f"  {cat}: {', '.join(items)}")
    lines.append("")
    lines.append("EXPERIENCE")
    for c in facts.get("preserved_companies", []):
        lines.append(f"  - {c}")
    if facts.get("preserved_school"):
        lines.append(f"\nEDUCATION\n  {facts['preserved_school']}")
    lines.append(f"\nWork Auth: {wa.get('legally_authorized_to_work', 'N/A')} | "
                 f"Available: {avail.get('earliest_start_date', 'N/A')} | "
                 f"Salary: {comp.get('salary_currency','USD')}{comp.get('salary_expectation','N/A')}")
    return "\n".join(lines)


def run_pipeline():
    """Discover → Score, updating PIPELINE_STATE in place."""
    PIPELINE_STATE["stage"] = "discovering"
    PIPELINE_STATE["progress"] = 10

    try:
        conn = init_db(str(_BACKEND / "applypilot.db"))
        conn.execute("DELETE FROM jobs")
        conn.commit()
        new, _ = store_jobs(conn, SAMPLE_JOBS, site="Mock", strategy="sample_data")
        PIPELINE_STATE["progress"] = 50
    except Exception as e:
        PIPELINE_STATE["stage"] = "error"
        return

    PIPELINE_STATE["stage"] = "scoring"
    PIPELINE_STATE["progress"] = 60

    # Load resume
    if RESUME_PATH.exists():
        resume = RESUME_PATH.read_text(encoding="utf-8")
    else:
        resume = "marketing digital campaign social media content strategy analytics"

    rows = conn.execute(
        "SELECT * FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL"
    ).fetchall()
    cols = rows[0].keys() if rows else []
    jobs = [dict(zip(cols, r)) for r in rows]

    now = datetime.now(timezone.utc).isoformat()
    for job in jobs:
        desc = job.get("full_description") or job.get("description") or ""
        s, kw, reasoning = _score_overlap(resume, desc[:8000])
        conn.execute(
            "UPDATE jobs SET fit_score=?, score_reasoning=?, scored_at=?, pipeline_status='scored' WHERE url=?",
            (s, f"{kw}\n{reasoning}", now, job["url"]),
        )
    conn.commit()
    PIPELINE_STATE["progress"] = 100
    PIPELINE_STATE["stage"] = "done"


def tailor_resume(job_url: str, conn) -> dict:
    """In-process resume tailoring."""
    row = conn.execute("SELECT * FROM jobs WHERE url=?", (job_url,)).fetchone()
    if not row:
        return {"error": "not found"}
    job = dict(zip(row.keys(), row))
    desc = job.get("full_description") or job.get("description") or ""
    kws = _extract_keywords(desc, top_n=10)

    base = RESUME_PATH.read_text(encoding="utf-8") if RESUME_PATH.exists() else "Aixin Li\nMarketing Specialist"
    tailored = (
        f"[TAILORED FOR: {job['title']} at {job.get('company', job.get('site', ''))}]\n\n"
        f"{base}\n\n"
        f"--- Highlighted Skills for This Role ---\n"
        f"{chr(10).join(f'- {k}' for k in kws)}"
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, pipeline_status='tailored' WHERE url=?",
        (f"tailored_{job_url[-20:]}.txt", now, job_url),
    )
    conn.commit()
    return {"resume": tailored, "keywords": kws}


def generate_cover(job_url: str, conn) -> dict:
    """In-process cover letter generation."""
    row = conn.execute("SELECT * FROM jobs WHERE url=?", (job_url,)).fetchone()
    if not row:
        return {"error": "not found"}
    job = dict(zip(row.keys(), row))
    desc = job.get("full_description") or job.get("description") or ""
    kws = _extract_keywords(desc, top_n=8)

    cover = (
        f"Dear Hiring Manager,\n\n"
        f"I am writing to apply for the {job['title']} position at "
        f"{job.get('company', 'your organization')}. With my background in "
        f"{', '.join(kws[:4]).lower()}, I am confident I can contribute effectively.\n\n"
        f"Through my experience in market research, content creation, and campaign "
        f"execution, I have developed strong competencies aligned with this role. "
        f"I look forward to discussing how I can add value to your team.\n\n"
        f"Sincerely,\n{_load_profile().get('personal', {}).get('full_name', 'Aixin Li')}"
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET cover_letter_path=?, cover_letter_at=?, pipeline_status='cover_done' WHERE url=?",
        (f"cover_{job_url[-20:]}.txt", now, job_url),
    )
    conn.commit()
    return {"cover_letter": cover, "keywords": kws}


def _load_profile() -> dict:
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    return {}


# ═════════════════════════════════════════════════════════════════════════════
# Streamlit UI
# ═════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="AI Job Application Assistant",
    page_icon="📋",
    layout="wide",
)

st.title("📋 AI Job Application Assistant")
st.caption("Course Project Demo — Automated Job Discovery, Scoring & Tailoring")

# ── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    # Profile Setup
    with st.expander("👤 Profile Setup", expanded=False):
        tabs = st.tabs(["Personal", "Experience", "Skills", "Work Auth"])

        with tabs[0]:
            full_name = st.text_input("Full Name", value="Aixin Li", key="p_name")
            email = st.text_input("Email", value="liaixin50@gmail.com", key="p_email")
            phone = st.text_input("Phone", value="(086)15695196785", key="p_phone")
            city = st.text_input("City", value="Shanghai", key="p_city")
            country = st.text_input("Country", value="China", key="p_country")

        with tabs[1]:
            years_exp = st.number_input("Years of Experience", 0, 30, 1, key="p_years")
            education = st.selectbox(
                "Education", ["High School", "Bachelor's Degree", "Master's Degree", "MBA", "PhD"],
                index=1, key="p_edu")
            target_role = st.text_input("Target Role", value="Marketing Specialist", key="p_role")
            companies = st.text_area(
                "Past Companies", value="Fosun Pharma\nGolden Education", height=80, key="p_co")
            school = st.text_input("School", value="Shanghai International Studies University", key="p_sch")

        with tabs[2]:
            langs = st.text_input("Languages", value="Python, English, Mandarin, Japanese", key="p_langs")
            tools = st.text_input("Tools", value="MS Office, SPSS, Photoshop, Premiere", key="p_tools")
            domains = st.text_input("Domains", value="Data Analysis, Digital Marketing, Content Creation", key="p_dom")

        with tabs[3]:
            authorized = st.selectbox("Work Authorization", ["Yes", "No"], key="p_auth")
            sponsorship = st.selectbox("Need Sponsorship", ["No", "Yes"], key="p_spon")
            salary_exp = st.number_input("Salary Expectation", 0, 500000, 85000, 5000, key="p_sal")
            currency = st.selectbox("Currency", ["USD", "HKD", "CNY", "CAD"], key="p_cur")

        if st.button("💾 Save Profile & Rebuild Resume", type="primary", use_container_width=True):
            profile = {
                "personal": {"full_name": full_name, "email": email, "phone": phone,
                             "city": city, "country": country},
                "experience": {"years_of_experience_total": str(years_exp),
                               "education_level": education, "target_role": target_role},
                "skills_boundary": {
                    "languages": [s.strip() for s in langs.split(",") if s.strip()],
                    "tools": [s.strip() for s in tools.split(",") if s.strip()],
                    "frameworks": [s.strip() for s in domains.split(",") if s.strip()],
                },
                "resume_facts": {
                    "preserved_companies": [s.strip() for s in companies.split("\n") if s.strip()],
                    "preserved_school": school,
                },
                "work_authorization": {"legally_authorized_to_work": authorized,
                                        "require_sponsorship": sponsorship},
                "availability": {"earliest_start_date": "Immediately"},
                "compensation": {"salary_expectation": str(salary_exp), "salary_currency": currency},
            }
            PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
            resume_text = _rebuild_resume(profile)
            RESUME_PATH.write_text(resume_text, encoding="utf-8")
            st.success(f"✅ Profile saved! Resume: {len(resume_text)} chars")
            st.session_state["profile_ready"] = True

    st.divider()

    # Pipeline Control
    st.header("⚙️ Pipeline Control")

    if st.button("🚀 Start Pipeline", type="primary", use_container_width=True):
        st.session_state["pipeline_running"] = True
        run_pipeline()
        st.session_state["pipeline_running"] = False
        st.success("✅ Pipeline complete!")
        st.rerun()

    if PIPELINE_STATE["stage"] not in ("idle", "done", "error"):
        stage_labels = {
            "discovering": "🔍 Discovering jobs...",
            "scoring": "📊 Scoring jobs...",
        }
        st.info(stage_labels.get(PIPELINE_STATE["stage"], PIPELINE_STATE["stage"]))
        st.progress(PIPELINE_STATE["progress"] / 100)
    elif PIPELINE_STATE["stage"] == "done":
        st.success("✅ Ready — 6 jobs scored")

    st.divider()

    # Stats
    try:
        conn = get_connection(str(_BACKEND / "applypilot.db"))
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        scored = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL").fetchone()[0]
        tailored = conn.execute("SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL").fetchone()[0]
        st.metric("Total Jobs", total)
        st.metric("Scored", scored)
        st.metric("Tailored", tailored)
    except Exception:
        pass

    st.divider()
    st.caption("github.com/liaixin50-dotcom/applypilot-web")
    st.caption("Streamlit Cloud ✈️ Standalone Mode")

# ── Main: Job Cards ─────────────────────────────────────────────────────────

st.header("📋 Discovered Jobs")

try:
    conn = get_connection(str(_BACKEND / "applypilot.db"))
    rows = get_all_jobs(conn, limit=100)
    jobs = []
    for r in rows:
        url = r.get("url", "")
        jobs.append({
            "id": hashlib.md5(url.encode()).hexdigest()[:12],
            "url": url,
            "title": r.get("title") or "Untitled",
            "company": r.get("company") or r.get("site") or "Unknown",
            "salary": r.get("salary"),
            "location": r.get("location"),
            "description": (r.get("full_description") or r.get("description") or "")[:500],
            "score": r.get("fit_score"),
            "score_reasoning": r.get("score_reasoning"),
            "pipeline_status": r.get("pipeline_status", "discovered"),
        })
except Exception:
    jobs = []

if not jobs:
    st.info("No jobs yet — fill in your profile and click **Start Pipeline** in the sidebar.")
else:
    min_score = st.slider("Minimum Score", 1, 10, 1, key="score_filter")
    filtered = [j for j in jobs if (j.get("score") or 0) >= min_score]
    st.caption(f"Showing {len(filtered)} of {len(jobs)} jobs (score ≥ {min_score})")

    for job in filtered:
        score = job.get("score")
        if score is None:
            badge = "⏳"
        elif score >= 7:
            badge = f"🟢 {score}/10"
        elif score >= 5:
            badge = f"🟡 {score}/10"
        elif score >= 3:
            badge = f"🟠 {score}/10"
        else:
            badge = f"🔴 {score}/10"

        label = f"{badge}  {job['title']} @ {job['company']}"
        if job.get("location"):
            label += f" — {job['location']}"

        with st.expander(label):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.caption((job.get("description") or "")[:500])
                if job.get("score_reasoning"):
                    with st.expander("🔍 Scoring Details"):
                        st.text(job["score_reasoning"][:400])
            with c2:
                st.markdown(f"Status: `{job.get('pipeline_status','?')}`")
                if job.get("salary"):
                    st.metric("Salary", job["salary"])

                if st.button("✂️ Tailor Resume", key=f"t_{job['id']}", use_container_width=True):
                    result = tailor_resume(job["url"], conn)
                    st.session_state[f"tailored_{job['id']}"] = result

                if st.button("📧 Cover Letter", key=f"c_{job['id']}", use_container_width=True):
                    result = generate_cover(job["url"], conn)
                    st.session_state[f"cover_{job['id']}"] = result

            if f"tailored_{job['id']}" in st.session_state:
                st.divider()
                st.markdown("### ✂️ Tailored Resume")
                st.text_area("Resume", st.session_state[f"tailored_{job['id']}"]["resume"],
                             height=300, key=f"ra_{job['id']}")

            if f"cover_{job['id']}" in st.session_state:
                st.divider()
                st.markdown("### 📧 Cover Letter")
                st.text_area("Cover Letter", st.session_state[f"cover_{job['id']}"]["cover_letter"],
                             height=250, key=f"ca_{job['id']}")
