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
    from applypilot_core.database import get_connection, query_scored_jobs, store_jobs
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
    ("search_done", False), ("searching", False), ("display_offset", 0),
    ("uploaded_resume_name", ""), ("_prev_filter", None),
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
        st.session_state["display_offset"] = 0
        st.session_state["_prev_filter"] = None
        st.rerun()

    st.divider()

    # ── Post-search actions ─────────────────────────────────────────────
    if st.session_state.get("search_done"):
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

        raw_jobs = []
        error_msg = None

        try:
            from applypilot_core.scraper import search_jobsdb

            raw_jobs = search_jobsdb(
                query=_q, location=_loc, job_type=_jt,
                days_old=_days, salary_min=_sal_min, salary_max=_sal_max,
                limit=_limit, headless=True,
            )
            st.write(f"📥 Scraped **{len(raw_jobs)}** raw jobs from JobsDB")
        except Exception as e:
            error_msg = f"Scraping failed: {e}\n{_traceback.format_exc()[-300:]}"
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

            # Scrape full descriptions for first batch
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

            st.session_state["display_offset"] = 0
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

if st.session_state.get("search_done"):
    conn = get_connection(str(DB_PATH))
    db_total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    if db_total == 0:
        st.warning("⚠️ No jobs in database. Please click Search again.")
        st.session_state["search_done"] = False
        st.stop()

    # ── Filter controls ──────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        min_score = st.slider("Minimum Score", 0, 10, 0, key="score_filter_slider")
    with c2:
        sort_ui = st.selectbox(
            "Sort by",
            ["Score (high first)", "Score (low first)", "Newest"],
            index=0, key="sort_select",
        )
    sort_map = {
        "Score (high first)": "score_desc",
        "Score (low first)": "score_asc",
        "Newest": "newest",
    }

    # Reset pagination if filter/sort changed
    prev = st.session_state.get("_prev_filter")
    curr = (min_score, sort_ui)
    if prev != curr:
        st.session_state["display_offset"] = 0
        st.session_state["_prev_filter"] = curr

    # ── Query DB with filtering + sorting + pagination ───────────────────
    offset = st.session_state.get("display_offset", 0)
    display_jobs, total_matching = query_scored_jobs(
        conn, min_score=min_score, sort_by=sort_map[sort_ui],
        offset=offset, limit=PAGE_SIZE,
    )

    # ── Centralized header + stats ────────────────────────────────────────
    st.header(f"📋 Search Results ({total_matching:,} jobs match | {db_total:,} total)")
    scored_count = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL"
    ).fetchone()[0]
    if scored_count > 0:
        avg = conn.execute(
            "SELECT AVG(COALESCE(fit_score,0)) FROM jobs"
        ).fetchone()[0]
        st.info(f"📊 **{scored_count}** jobs scored | Average: **{avg:.1f}/10**")
    else:
        st.warning("⚠️ No scores computed yet.")

    # ── Empty-state: no jobs match filter ─────────────────────────────────
    if total_matching == 0:
        max_score_row = conn.execute(
            "SELECT MAX(COALESCE(fit_score,0)) FROM jobs"
        ).fetchone()
        max_s = max_score_row[0] if max_score_row else 0
        if max_s == 0:
            st.info("ℹ️ All jobs currently have a score of 0. Upload a detailed resume and search again for better matching.")
        else:
            st.info(f"ℹ️ No jobs match score ≥ {min_score}. Highest available: **{max_s}/10**. Try lowering the slider.")

    # ── Job cards ─────────────────────────────────────────────────────────
    for job in display_jobs:
        score = job.get("fit_score")
        s, _ = _score_badge(score)

        label = f"`[{s}]` {job.get('title','?')} — *{job.get('company','?')}*"
        if job.get("location"):
            label += f" | {job['location']}"
        if job.get("salary"):
            label += f" | {job['salary']}"

        with st.expander(label):
            job_url = job.get("url", "")
            st.markdown(f"🔗 [**View Original Job Posting on JobsDB**]({job_url})")

            c1, c2 = st.columns([3, 1])
            with c1:
                desc = (job.get("full_description") or job.get("description") or "")
                if desc and len(desc) > 50:
                    st.markdown("**📝 Job Description:**")
                    st.caption(desc[:800])
                elif desc:
                    st.caption(desc[:300])
                else:
                    st.info("📝 Full description not loaded. Click the link above to view the complete job posting.")
                if job.get("score_reasoning"):
                    with st.expander("🔍 Score Details"):
                        st.text(job["score_reasoning"][:400])
            with c2:
                st.markdown(f"Status: `{job.get('pipeline_status','?')}`")
                if job.get("salary"):
                    st.metric("Salary", job["salary"])
                jid = hashlib.md5(job.get("url","").encode()).hexdigest()[:12]
                if st.button("✂️ Tailor", key=f"btn_t_{jid}", use_container_width=True):
                    r = _tailor(job["url"], conn)
                    if "error" in r:
                        st.error(r["error"])
                    else:
                        st.session_state[f"data_t_{jid}"] = r
                if st.button("📧 Cover", key=f"btn_c_{jid}", use_container_width=True):
                    r = _cover(job["url"], conn)
                    if "error" in r:
                        st.error(r["error"])
                    else:
                        st.session_state[f"data_c_{jid}"] = r

            if f"data_t_{jid}" in st.session_state:
                st.divider()
                st.markdown("**✂️ Tailored Resume**")
                st.text_area("Resume", st.session_state[f"data_t_{jid}"].get("resume",""),
                             height=250, key=f"area_ta_{jid}")
            if f"data_c_{jid}" in st.session_state:
                st.divider()
                st.markdown("**📧 Cover Letter**")
                st.text_area("Cover", st.session_state[f"data_c_{jid}"].get("cover_letter",""),
                             height=200, key=f"area_ca_{jid}")

    # ── Load More (respects filtered count) ──────────────────────────────
    shown = offset + len(display_jobs)
    remaining = total_matching - shown
    if remaining > 0:
        if st.button(f"📥 Load More ({remaining} matching jobs)", use_container_width=True):
            st.session_state["display_offset"] = shown
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
