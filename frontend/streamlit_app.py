"""ApplyPilot — Standalone Job Search & Resume Assistant.

Features:
  - JobsDB live scraping with search filters
  - Resume upload (PDF/DOCX/TXT)
  - AI scoring & tailored resume generation
  - 50 results per page with "Load More"

Run:  streamlit run web_app/frontend/streamlit_app.py
"""

from __future__ import annotations

import hashlib
import io
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

# ═════════════════════════════════════════════════════════════════════════════
# Page config — MUST be the first Streamlit command
# ═════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="ApplyPilot - AI Job Assistant",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═════════════════════════════════════════════════════════════════════════════
# Safe init — catch any import / config errors early
# ═════════════════════════════════════════════════════════════════════════════
@st.cache_resource
def _init_backend():
    """One-time backend initialization (DB schema, paths)."""
    from applypilot_core.database import init_db, get_connection
    conn = init_db(str(_BACKEND / "applypilot.db"))
    return conn

try:
    _HERE = Path(__file__).resolve().parent
    _BACKEND = _HERE.parent / "backend"
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))
    from applypilot_core.database import get_connection, get_all_jobs, store_jobs
    from applypilot_core.tailor import _extract_keywords
except Exception as _e:
    st.error(f"Backend init failed: {_e}")
    st.stop()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Path setup ──────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from applypilot_core.database import init_db, get_connection, get_all_jobs, store_jobs
from applypilot_core.tailor import _extract_keywords

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
PROFILE_PATH = _BACKEND / "profile.json"
RESUME_PATH = _BACKEND / "resume.txt"
DB_PATH = _BACKEND / "applypilot.db"
PAGE_SIZE = 50  # jobs per page

# ═════════════════════════════════════════════════════════════════════════════
# Session state init
# ═════════════════════════════════════════════════════════════════════════════
for key, default in [
    ("all_jobs", []), ("display_count", 0), ("search_done", False),
    ("scoring_done", False), ("searching", False), ("uploaded_resume_name", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

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
    return score, ", ".join(sorted(common)[:25]), f"Matched {len(common)} keywords; overlap={frac:.2f}"


def _load_resume() -> str:
    if RESUME_PATH.exists():
        return RESUME_PATH.read_text(encoding="utf-8")
    return ""


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using pymupdf."""
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text.strip()
    except ImportError:
        return "[PDF parsing unavailable — pip install pymupdf]"


def _extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes."""
    try:
        from zipfile import ZipFile
        from xml.etree.ElementTree import XML
        with ZipFile(io.BytesIO(file_bytes)) as z:
            xml_content = z.read("word/document.xml")
        tree = XML(xml_content)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            texts = [t.text for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t") if t.text]
            if texts:
                paragraphs.append("".join(texts))
        return "\n".join(paragraphs)
    except Exception:
        return "[DOCX parsing failed]"


def _run_scoring(conn=None):
    """Score all unscored jobs in DB using current resume.  Runs automatically after search."""
    if conn is None:
        conn = get_connection(str(DB_PATH))
    resume = _load_resume()
    if not resume:
        # Use default keywords if no resume uploaded
        resume = "marketing digital campaign social media content strategy analytics branding communications market research data analysis"

    rows = conn.execute(
        "SELECT * FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL"
    ).fetchall()
    if not rows:
        return 0
    cols = rows[0].keys()
    jobs = [dict(zip(cols, r)) for r in rows]
    now = datetime.now(timezone.utc).isoformat()

    # ── Smarter scoring: weight keyword categories differently ──────────
    # High-value keywords = hard skills, certifications, specific tools
    HIGH_VALUE = {
        "python", "sql", "excel", "tableau", "powerbi", "spss", "photoshop",
        "illustrator", "premiere", "adobe", "analytics", "seo", "sem",
        "crm", "salesforce", "hubspot", "marketo", "google analytics",
        "facebook ads", "google ads", "linkedin", "email marketing",
        "content marketing", "social media", "digital marketing",
        "market research", "data analysis", "branding", "campaign",
        "copywriting", "strategy", "budget", "forecasting", "budgeting",
    }
    LOW_VALUE = {"the", "and", "for", "with", "that", "this", "from",
                 "are", "will", "have", "has", "can", "its", "not", "but",
                 "all", "also", "each", "more", "some", "than", "which",
                 "their", "other", "about", "they", "what", "your", "our",
                 "you", "was", "were", "been", "being", "had", "did", "does",
                 "experience", "skills", "required", "requirements", "work",
                 "job", "position", "role", "company", "team", "year", "years"}

    scored = 0
    for job in jobs:
        desc = job.get("full_description") or job.get("description") or ""
        if len(desc) < 50:
            continue

        # Tokenize both
        r_toks = set(_tokenize(resume))
        j_toks = set(_tokenize(desc.lower()))

        # Weighted matching
        high_matches = r_toks & j_toks & HIGH_VALUE
        low_matches = r_toks & j_toks & LOW_VALUE
        regular_matches = r_toks & j_toks - HIGH_VALUE - LOW_VALUE

        # Score: high-value keywords count 3x, regular 1x, low-value 0x
        effective_hits = len(high_matches) * 3 + len(regular_matches)
        total_job_kws = len(j_toks - LOW_VALUE)
        frac = effective_hits / max(1, total_job_kws)
        # Map to 1-10 with better spread
        s = max(1, min(10, int(1 + round(frac * 12))))
        # Boost by 1 if there are high-value matches
        if len(high_matches) >= 2:
            s = min(10, s + 1)

        kw_str = ", ".join(sorted(high_matches)[:15])
        reason = (
            f"High-value matches ({len(high_matches)}): {', '.join(sorted(high_matches)[:8])}. "
            f"Regular matches: {len(regular_matches)}. "
            f"Score based on weighted keyword overlap."
        )
        conn.execute(
            "UPDATE jobs SET fit_score=?, score_reasoning=?, scored_at=?, pipeline_status='scored' WHERE url=?",
            (s, f"{kw_str}\n{reason}", now, job["url"]),
        )
        scored += 1

    conn.commit()
    st.session_state["scoring_done"] = True
    return scored


def _tailor(job_url: str, conn) -> dict:
    row = conn.execute("SELECT * FROM jobs WHERE url=?", (job_url,)).fetchone()
    if not row:
        return {"error": "not found"}
    job = dict(zip(row.keys(), row))
    desc = job.get("full_description") or job.get("description") or ""
    kws = _extract_keywords(desc, top_n=10)
    base = _load_resume() or "Candidate Resume"
    tailored = (
        f"[TAILORED FOR: {job['title']} at {job.get('company', '?')}]\n\n{base}\n\n"
        f"--- Key Skills for This Role ---\n"
        f"{chr(10).join(f'- {k}' for k in kws)}"
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, pipeline_status='tailored' WHERE url=?",
        (f"tailored_{job_url[-20:]}.txt", now, job_url),
    )
    conn.commit()
    return {"resume": tailored, "keywords": kws}


def _cover(job_url: str, conn) -> dict:
    row = conn.execute("SELECT * FROM jobs WHERE url=?", (job_url,)).fetchone()
    if not row:
        return {"error": "not found"}
    job = dict(zip(row.keys(), row))
    desc = job.get("full_description") or job.get("description") or ""
    kws = _extract_keywords(desc, top_n=6)
    letter = (
        f"Dear Hiring Manager,\n\n"
        f"I am writing to apply for the {job['title']} position at "
        f"{job.get('company', 'your organization')}. With a strong background in "
        f"{', '.join(kws[:4]).lower()}, I am eager to contribute to your team.\n\n"
        f"Based on my experience and skills, I believe I am well-suited for this role. "
        f"I look forward to the opportunity to discuss my application further.\n\n"
        f"Sincerely,\nCandidate"
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET cover_letter_path=?, cover_letter_at=?, pipeline_status='cover_done' WHERE url=?",
        (f"cover_{job_url[-20:]}.txt", now, job_url),
    )
    conn.commit()
    return {"cover_letter": letter, "keywords": kws}


def _score_badge(score):
    if score is None:
        return "⏳", "badge-gray"
    if score >= 7:
        return f"{score}/10", "badge-green"
    if score >= 5:
        return f"{score}/10", "badge-yellow"
    if score >= 3:
        return f"{score}/10", "badge-orange"
    return f"{score}/10", "badge-red"


# ═════════════════════════════════════════════════════════════════════════════
# UI: Sidebar
# ═════════════════════════════════════════════════════════════════════════════

st.title("📋 ApplyPilot — AI Job Search & Resume Assistant")
st.caption("JobsDB live scraping · Resume scoring · Tailored applications")

with st.sidebar:
    st.header("📤 Upload Resume")

    uploaded = st.file_uploader(
        "Upload your resume (PDF, DOCX, or TXT)",
        type=["pdf", "docx", "txt"],
        key="resume_uploader",
    )
    if uploaded is not None:
        fname = uploaded.name
        fbytes = uploaded.read()
        if fname.lower().endswith(".pdf"):
            text = _extract_text_from_pdf(fbytes)
        elif fname.lower().endswith(".docx"):
            text = _extract_text_from_docx(fbytes)
        else:
            text = fbytes.decode("utf-8", errors="replace")

        if text and not text.startswith("["):
            RESUME_PATH.write_text(text, encoding="utf-8")
            st.session_state["uploaded_resume_name"] = fname
            st.success(f"✅ Resume loaded: {fname} ({len(text):,} chars)")
            # Clear old scores so we can rescore
            try:
                conn = get_connection(str(DB_PATH))
                conn.execute("UPDATE jobs SET fit_score=NULL, score_reasoning=NULL, scored_at=NULL")
                conn.commit()
                st.session_state["scoring_done"] = False
            except Exception:
                pass
        else:
            st.error(f"Could not parse {fname}. Try a different format.")

    if st.session_state.get("uploaded_resume_name"):
        st.info(f"📄 Active: {st.session_state['uploaded_resume_name']}")

    st.divider()

    st.header("🔍 Search JobsDB")

    with st.form("search_form"):
        query = st.text_input("Industry / Keywords", value="marketing",
                              help="e.g. marketing, finance, software engineer, design")
        loc = st.selectbox("Location", ["Hong Kong", "Kowloon", "New Territories", "Remote"],
                           index=0)
        col1, col2 = st.columns(2)
        with col1:
            job_type = st.selectbox("Job Type", [
                "Any", "Full-time", "Part-time", "Contract", "Internship", "Temporary"
            ], index=0)
        with col2:
            days = st.selectbox("Posted Within", [
                "Any time", "Last 24 hours", "Last 3 days", "Last 7 days", "Last 14 days", "Last 30 days"
            ], index=2)

        col3, col4 = st.columns(2)
        with col3:
            sal_min = st.number_input("Min Salary (HKD/mo)", 0, 500000, 0, 5000)
        with col4:
            sal_max = st.number_input("Max Salary (HKD/mo)", 0, 500000, 0, 5000)

        col5, col6 = st.columns(2)
        with col5:
            company_size = st.selectbox("Company Size", [
                "Any", "Startup (1-50)", "SME (51-200)", "Large (201-1000)", "Enterprise (1000+)"
            ], index=0)
        with col6:
            result_limit = st.selectbox("Max Results", [50, 100, 150, 200], index=0)

        submitted = st.form_submit_button("🔎 Search JobsDB", type="primary", use_container_width=True)

    if submitted:
        days_map = {
            "Any time": 0, "Last 24 hours": 1, "Last 3 days": 3,
            "Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30,
        }
        jt = job_type.lower().replace(" ", "-") if job_type != "Any" else ""
        st.session_state["_search_params"] = {
            "query": query, "loc": loc, "job_type": jt,
            "days": days_map.get(days, 0),
            "sal_min": sal_min or 0, "sal_max": sal_max or 0,
            "limit": result_limit,
        }
        st.session_state["searching"] = True
        st.session_state["search_done"] = False
        st.session_state["all_jobs"] = []
        st.session_state["display_count"] = 0
        st.session_state["scoring_done"] = False
        st.rerun()

    st.divider()

    # ── Post-search actions ─────────────────────────────────────────────
    if st.session_state.get("search_done") and st.session_state.get("all_jobs"):
        st.header("📊 Post-Search")
        # Show score distribution
        try:
            conn = get_connection(str(DB_PATH))
            dist = conn.execute(
                "SELECT fit_score, COUNT(*) FROM jobs WHERE fit_score IS NOT NULL "
                "GROUP BY fit_score ORDER BY fit_score DESC"
            ).fetchall()
            if dist:
                st.caption("Score Distribution:")
                for score, cnt in dist[:8]:
                    bar = "█" * min(cnt, 20)
                    st.caption(f"  {score}/10: {bar} ({cnt})")
        except Exception:
            pass

        if st.button("✂️ Tailor Top 5 Matches", use_container_width=True):
            conn = get_connection(str(DB_PATH))
            rows = conn.execute(
                "SELECT url FROM jobs WHERE fit_score IS NOT NULL ORDER BY fit_score DESC LIMIT 5"
            ).fetchall()
            for (url,) in rows:
                _tailor(url, conn)
            st.success("Tailored top 5!")
            st.rerun()

    st.divider()
    st.caption(f"DB: {DB_PATH}")
    st.caption(f"Resume: {RESUME_PATH}")

# ═════════════════════════════════════════════════════════════════════════════
# Search execution (after form submit)
# ═════════════════════════════════════════════════════════════════════════════

if st.session_state.get("searching"):
    import traceback as _traceback

    # ── Reconstruct search params from session_state so they survive reruns ──
    search_params = st.session_state.get("_search_params", {})
    _q = search_params.get("query", "marketing")
    _loc = search_params.get("loc", "Hong Kong")
    _jt = search_params.get("job_type", "")
    _days = search_params.get("days", 0)
    _sal_min = search_params.get("sal_min", 0)
    _sal_max = search_params.get("sal_max", 0)
    _limit = search_params.get("limit", 50)

    with st.status(f"🔍 Searching JobsDB for '{_q}'...", expanded=True) as status:
        st.write(f"Query: **{_q}** in **{_loc}**")
        st.write(f"Type: {_jt or 'Any'} | Days: {_days or 'Any'} | Salary: {_sal_min}-{_sal_max} | Limit: {_limit}")

        # ── Detect Playwright availability ───────────────────────────────
        _has_playwright = False
        try:
            from playwright.sync_api import sync_playwright
            _has_playwright = True
        except (ImportError, OSError):
            pass

        raw_jobs = []
        error_msg = None

        if not _has_playwright:
            # Streamlit Cloud / no Playwright → use sample data
            st.info("📦 Running in demo mode (Playwright not available on this platform)")
            from applypilot_core.discover import SAMPLE_JOBS, discover_jobs
            discover_jobs(clear_first=True)
            raw_jobs = [
                {"url": j["url"], "title": j["title"], "company": j.get("company"),
                 "salary": j.get("salary"), "description": j.get("description"),
                 "location": j.get("location", "HK")}
                for j in SAMPLE_JOBS
            ]
            st.write(f"📥 Loaded **{len(raw_jobs)}** sample jobs (demo mode)")
        else:
            try:
                from applypilot_core.scraper import search_jobsdb

                raw_jobs = search_jobsdb(
                    query=_q, location=_loc, job_type=_jt,
                    days_old=_days, salary_min=_sal_min, salary_max=_sal_max,
                    limit=_limit, headless=True,
                )
                st.write(f"📥 Scraped **{len(raw_jobs)}** raw jobs from JobsDB")
            except Exception as e:
                error_msg = f"Scraping failed: {e}"
                st.error(error_msg)
                raw_jobs = []

        if raw_jobs:
            # Store in DB
            init_db(str(DB_PATH))
            conn = get_connection(str(DB_PATH))
            conn.execute("DELETE FROM jobs")
            conn.commit()
            db_jobs = [{
                "url": j["url"], "title": j.get("title", "Untitled"),
                "company": j.get("company"), "salary": j.get("salary"),
                "description": j.get("description"),
                "full_description": j.get("description"),
                "location": j.get("location", _loc),
            } for j in raw_jobs]
            new, _ = store_jobs(conn, db_jobs, site="JobsDB", strategy="playwright")
            st.write(f"💾 Stored **{new}** jobs in database")

            # Scrape full descriptions for first batch (only if Playwright available)
            if _has_playwright:
                st.write("📝 Fetching detail pages...")
                enriched = 0
                try:
                    from applypilot_core.scraper import scrape_job_detail
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        ctx = browser.new_context(
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            locale="en-US", viewport={"width": 1280, "height": 900})
                        pg = ctx.new_page()
                        for j in raw_jobs[:15]:
                            desc = scrape_job_detail(pg, j["url"])
                            if desc:
                                conn.execute(
                                    "UPDATE jobs SET full_description=?, detail_scraped_at=? WHERE url=?",
                                    (desc, datetime.now(timezone.utc).isoformat(), j["url"]))
                                enriched += 1
                        conn.commit()
                        browser.close()
                except Exception as e:
                    st.warning(f"Detail scraping skipped: {e}")
                st.write(f"📋 Enriched **{enriched}** descriptions")

            # Auto-score all jobs
            st.write("📊 Scoring jobs...")
            n_scored = _run_scoring(conn=conn)
            st.write(f"📊 Scored **{n_scored}** jobs")

            st.session_state["all_jobs"] = raw_jobs
            st.session_state["display_count"] = min(PAGE_SIZE, len(raw_jobs))
            st.session_state["search_done"] = True
            status.update(label=f"✅ Done — {len(raw_jobs)} jobs, {n_scored} scored", state="complete")

        else:
            st.error(f"❌ No jobs found. {error_msg or 'Try different filters.'}")
            st.session_state["search_done"] = False
            status.update(label="❌ Search failed", state="error")

    st.session_state["searching"] = False

# ═════════════════════════════════════════════════════════════════════════════
# Main: Job Results
# ═════════════════════════════════════════════════════════════════════════════

if st.session_state.get("search_done") and st.session_state.get("all_jobs"):
    all_jobs = st.session_state["all_jobs"]
    display_n = st.session_state.get("display_count", PAGE_SIZE)

    # Read scores from DB
    conn = get_connection(str(DB_PATH))
    rows = get_all_jobs(conn, limit=9999)
    db_map = {r["url"]: r for r in rows}
    db_total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    # Detect stale session state (e.g. after server restart)
    if db_total == 0:
        st.warning("⚠️ Session expired — database was reset. Please click Search again.")
        st.session_state["search_done"] = False
        st.stop()

    st.header(f"📋 Search Results ({len(all_jobs):,} jobs found)")
    # Show score summary
    scored_count = sum(1 for r in rows if r.get("fit_score") is not None)
    if scored_count > 0:
        avg_score = sum(r["fit_score"] for r in rows if r.get("fit_score") is not None) / scored_count
        st.info(f"📊 **{scored_count}** jobs scored | Average match: **{avg_score:.1f}/10**")
    else:
        st.warning("⚠️ Scores not yet computed. Please click Search again.")
        st.session_state["search_done"] = False
        st.stop()

    # Filters
    c1, c2 = st.columns(2)
    with c1:
        min_score = st.slider("Minimum Score", 0, 10, 0)
    with c2:
        sort_by = st.selectbox("Sort by", ["Score (high first)", "Score (low first)", "Newest"], index=0)

    # Prepare display list
    display_jobs = []
    for j in all_jobs[:display_n]:
        db_row = db_map.get(j.get("url", ""))
        score = db_row.get("fit_score") if db_row else None
        if min_score > 0 and (score is None or score < min_score):
            continue
        display_jobs.append({
            "id": hashlib.md5(j.get("url", "").encode()).hexdigest()[:12],
            "url": j.get("url", ""),
            "title": db_row.get("title") if db_row else j.get("title", "?"),
            "company": db_row.get("company") if db_row else j.get("company"),
            "location": j.get("location", "HK"),
            "salary": j.get("salary"),
            "description": (db_row.get("full_description") if db_row else None) or j.get("description", ""),
            "score": score,
            "score_reasoning": db_row.get("score_reasoning") if db_row else None,
            "pipeline_status": db_row.get("pipeline_status", "discovered") if db_row else "discovered",
        })

    # Sort
    if sort_by.startswith("Score"):
        display_jobs.sort(key=lambda j: j.get("score") or 0, reverse=sort_by == "Score (high first)")
    else:
        display_jobs.reverse()  # newest first approximation

    st.caption(f"Showing {len(display_jobs)} jobs (score ≥ {min_score})")

    for job in display_jobs:
        s, badge_cls = _score_badge(job.get("score"))

        expander_label = f"`[{s}]` {job['title']} — *{job.get('company', '?')}*"
        if job.get("location"):
            expander_label += f" | {job['location']}"
        if job.get("salary"):
            expander_label += f" | {job['salary']}"

        with st.expander(expander_label):
            # ── Link to original job posting (always visible) ────────────
            job_url = job.get("url", "")
            st.markdown(
                f"🔗 [**View Original Job Posting on JobsDB**]({job_url})  "
                f"*(opens in new tab)*",
                unsafe_allow_html=False,
            )

            c1, c2 = st.columns([3, 1])
            with c1:
                desc = job.get("description") or ""
                if desc and len(desc) > 50:
                    # Show job description
                    st.markdown("**📝 Job Description:**")
                    st.caption(desc[:800])
                elif desc:
                    st.caption(desc[:300])
                else:
                    st.info("📝 Full job description not loaded. Click the link above to view the complete job posting on JobsDB.")

                if job.get("score_reasoning"):
                    with st.expander("🔍 Score Details"):
                        st.text(job["score_reasoning"][:400])
            with c2:
                st.markdown(f"Status: `{job.get('pipeline_status', '?')}`")
                if job.get("salary"):
                    st.metric("Salary", job["salary"])
                btn_key = job["id"]
                if st.button("✂️ Tailor", key=f"btn_t_{btn_key}", use_container_width=True):
                    r = _tailor(job["url"], conn)
                    st.session_state[f"data_t_{btn_key}"] = r
                if st.button("📧 Cover", key=f"btn_c_{btn_key}", use_container_width=True):
                    r = _cover(job["url"], conn)
                    st.session_state[f"data_c_{btn_key}"] = r

            if f"data_t_{btn_key}" in st.session_state:
                st.divider()
                st.markdown("**✂️ Tailored Resume**")
                st.text_area("Resume", st.session_state[f"data_t_{btn_key}"]["resume"],
                             height=250, key=f"area_ta_{btn_key}")
            if f"data_c_{btn_key}" in st.session_state:
                st.divider()
                st.markdown("**📧 Cover Letter**")
                st.text_area("Cover", st.session_state[f"data_c_{btn_key}"]["cover_letter"],
                             height=200, key=f"area_ca_{btn_key}")

    # Load More button
    if display_n < len(all_jobs):
        remaining = len(all_jobs) - display_n
        if st.button(f"📥 Load More ({remaining} remaining)", use_container_width=True):
            st.session_state["display_count"] = min(display_n + PAGE_SIZE, len(all_jobs))
            st.rerun()

elif not st.session_state.get("searching"):
    st.info("👆 Use the sidebar to upload your resume and search for jobs on JobsDB.")
    st.markdown("""
    ### How to use:
    1. **Upload your resume** (PDF/DOCX/TXT) — the system will analyze it
    2. **Set search filters** — industry, job type, salary, posting date
    3. **Click Search** — scrapes live jobs from JobsDB HK
    4. **Score & Tailor** — AI analyzes fit and generates custom materials
    """)
