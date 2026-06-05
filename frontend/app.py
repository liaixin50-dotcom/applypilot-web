"""ApplyPilot Streamlit Dashboard — AI Job Application Assistant.

Usage:
    cd web_app/frontend
    streamlit run app.py
"""

import streamlit as st
import requests
import time
import os

st.set_page_config(
    page_title="AI Job Application Assistant",
    page_icon="📋",
    layout="wide",
)

# Resolve API base: env var (local dev) → st.secrets (Streamlit Cloud) → localhost
API_BASE = os.environ.get("API_BASE")
if not API_BASE:
    try:
        API_BASE = st.secrets["API_BASE"]
    except Exception:
        API_BASE = "http://localhost:8000"

st.title("📋 AI Job Application Assistant")
st.caption("Course Project Demo — Automated Job Discovery, Scoring & Tailoring")

# ═════════════════════════════════════════════════════════════════════════════
# Sidebar: Profile Setup + Pipeline Control
# ═════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    # ── Profile Setup ────────────────────────────────────────────────────
    with st.expander("👤 Profile Setup", expanded=False):
        tabs = st.tabs(["Personal", "Experience", "Skills", "Work Auth"])

        # Tab 1: Personal Info
        with tabs[0]:
            full_name = st.text_input("Full Name", value="Aixin Li", key="p_name")
            email = st.text_input("Email", value="liaixin50@gmail.com", key="p_email")
            phone = st.text_input("Phone", value="(086)15695196785", key="p_phone")
            city = st.text_input("City", value="Shanghai", key="p_city")
            country = st.text_input("Country", value="China", key="p_country")
            linkedin = st.text_input("LinkedIn URL", value="https://linkedin.com/in/aixinli", key="p_linkedin")

        # Tab 2: Experience
        with tabs[1]:
            years_exp = st.number_input("Years of Experience", min_value=0, max_value=30, value=1, key="p_years")
            education = st.selectbox(
                "Education Level",
                ["High School", "Associate's Degree", "Bachelor's Degree",
                 "Master's Degree", "PhD", "MBA"],
                index=2,
                key="p_edu",
            )
            target_role = st.text_input("Target Role", value="Marketing Specialist", key="p_role")
            preserved_companies = st.text_area(
                "Past Companies (one per line)",
                value="Fosun Pharma\nRed Star Macalline\nGolden Education",
                height=100,
                key="p_companies",
            )
            preserved_school = st.text_input(
                "School", value="Shanghai International Studies University", key="p_school"
            )

        # Tab 3: Skills
        with tabs[2]:
            languages = st.text_input(
                "Languages / Programming", value="Python, SQL, English, Mandarin, Japanese", key="p_langs"
            )
            tools = st.text_input(
                "Tools & Software", value="MS Office, SPSS, Adobe Photoshop, Adobe Premiere, Git", key="p_tools"
            )
            domains = st.text_input(
                "Domains / Frameworks", value="Data Analysis, Digital Marketing, Content Creation, Market Research", key="p_domains"
            )

        # Tab 4: Work Authorization & Compensation
        with tabs[3]:
            authorized = st.selectbox("Legally Authorized to Work", ["Yes", "No"], key="p_auth")
            sponsorship = st.selectbox("Require Sponsorship", ["No", "Yes"], key="p_sponsor")
            availability = st.text_input("Earliest Start Date", value="Immediately", key="p_avail")
            salary_exp = st.number_input(
                "Salary Expectation (annual)", min_value=0, value=85000, step=5000, key="p_salary"
            )
            salary_currency = st.selectbox("Currency", ["USD", "HKD", "CNY", "CAD"], index=0, key="p_currency")

        # Assemble & send profile
        if st.button("💾 Save Profile", type="primary", use_container_width=True, key="btn_save_profile"):
            profile_payload = {
                "personal": {
                    "full_name": full_name,
                    "preferred_name": full_name.split()[0] if full_name else "",
                    "email": email,
                    "phone": phone,
                    "address": "",
                    "city": city,
                    "province_state": "",
                    "country": country,
                    "postal_code": "",
                    "linkedin_url": linkedin,
                    "github_url": "",
                    "portfolio_url": "",
                    "website_url": "",
                },
                "work_authorization": {
                    "legally_authorized_to_work": authorized,
                    "require_sponsorship": sponsorship,
                    "work_permit_type": "",
                },
                "availability": {
                    "earliest_start_date": availability,
                    "available_for_full_time": "Yes",
                    "available_for_contract": "No",
                },
                "compensation": {
                    "salary_expectation": str(salary_exp),
                    "salary_currency": salary_currency,
                    "salary_range_min": str(int(salary_exp * 0.8)),
                    "salary_range_max": str(int(salary_exp * 1.2)),
                    "currency_conversion_note": "",
                },
                "experience": {
                    "years_of_experience_total": str(years_exp),
                    "education_level": education,
                    "current_job_title": "",
                    "current_company": "",
                    "target_role": target_role,
                },
                "skills_boundary": {
                    "languages": [s.strip() for s in languages.split(",") if s.strip()],
                    "frameworks": [s.strip() for s in domains.split(",") if s.strip()],
                    "devops": [],
                    "databases": [],
                    "tools": [s.strip() for s in tools.split(",") if s.strip()],
                },
                "resume_facts": {
                    "preserved_companies": [s.strip() for s in preserved_companies.split("\n") if s.strip()],
                    "preserved_projects": [],
                    "preserved_school": preserved_school,
                    "real_metrics": [],
                },
                "eeo_voluntary": {
                    "gender": "Decline to self-identify",
                    "race_ethnicity": "Decline to self-identify",
                    "veteran_status": "I am not a protected veteran",
                    "disability_status": "I do not wish to answer",
                },
            }
            try:
                resp = requests.post(f"{API_BASE}/profile", json=profile_payload, timeout=15)
                if resp.ok:
                    st.success(f"✅ Profile saved! ({len(profile_payload['skills_boundary']['languages'])} skills)")
                    st.session_state["profile_saved"] = True
                else:
                    st.error(f"Failed: {resp.status_code}")
            except requests.ConnectionError:
                st.error(f"Cannot reach {API_BASE}")

    st.divider()

    # ── Pipeline Control ─────────────────────────────────────────────────
    st.header("⚙️ Pipeline Control")

    if st.button("🚀 Start Pipeline (Discover → Score)", type="primary", use_container_width=True):
        try:
            resp = requests.post(f"{API_BASE}/start_pipeline", timeout=10)
            if resp.ok:
                st.session_state["pipeline_running"] = True
                st.success("Pipeline started!")
            else:
                data = resp.json()
                st.warning(data.get("message", "API error"))
        except requests.ConnectionError:
            st.error(f"Cannot connect to {API_BASE}")

    # Live progress polling
    if st.session_state.get("pipeline_running"):
        try:
            ps = requests.get(f"{API_BASE}/status", timeout=5).json()
            stage = ps.get("stage", "idle")
            progress = ps.get("progress", 0)

            stage_labels = {
                "queued": "⏳ Queued...",
                "discovering": "🔍 Discovering jobs...",
                "scoring": "📊 Scoring jobs...",
                "done": "✅ Pipeline complete!",
                "error": "❌ Pipeline failed",
                "idle": "💤 Idle",
            }
            st.info(f"{stage_labels.get(stage, stage)}")
            st.progress(progress / 100, text=f"{progress}%")

            if stage == "done":
                st.session_state["pipeline_running"] = False
                st.rerun()
            elif stage == "error":
                st.session_state["pipeline_running"] = False
        except Exception:
            pass

    st.divider()

    # ── Stats ────────────────────────────────────────────────────────────
    try:
        stats = requests.get(f"{API_BASE}/stats", timeout=5).json()
        st.metric("Total Jobs", stats.get("total", 0))
        st.metric("Scored", stats.get("scored", 0))
        st.metric("Tailored", stats.get("tailored", 0))
    except Exception:
        st.caption("(Start the pipeline to see stats)")

    st.divider()
    st.caption("Backend: " + API_BASE)
    st.caption("Built with FastAPI + Streamlit")


# ═════════════════════════════════════════════════════════════════════════════
# Main area: Job Cards
# ═════════════════════════════════════════════════════════════════════════════

st.header("📋 Discovered Jobs")

try:
    resp = requests.get(f"{API_BASE}/jobs", timeout=10)
    if resp.ok:
        jobs = resp.json()
    else:
        jobs = []
        st.warning(f"API returned {resp.status_code}")
except requests.ConnectionError:
    jobs = []
    st.info(
        "👋 **Welcome!** The backend isn't running yet.\n\n"
        "To get started, open a terminal and run:\n\n"
        "```bash\n"
        "cd web_app/backend\n"
        "pip install -r requirements.txt\n"
        "python main.py\n"
        "```\n\n"
        "Then come back and click **Start Pipeline** in the sidebar."
    )

if not jobs:
    st.info("No jobs yet — click **Start Pipeline** in the sidebar to begin.")
else:
    min_score = st.slider("Minimum Score", 1, 10, 1, key="score_filter")
    filtered = [j for j in jobs if (j.get("score") or 0) >= min_score]
    st.caption(f"Showing {len(filtered)} of {len(jobs)} jobs (score ≥ {min_score})")

    for job in filtered:
        score = job.get("score")
        if score is None:
            score_badge = "⏳"
        elif score >= 7:
            score_badge = f"🟢 {score}/10"
        elif score >= 5:
            score_badge = f"🟡 {score}/10"
        elif score >= 3:
            score_badge = f"🟠 {score}/10"
        else:
            score_badge = f"🔴 {score}/10"

        expander_label = f"{score_badge}  {job['title']} @ {job['company']}"
        if job.get("location"):
            expander_label += f" — {job['location']}"

        with st.expander(expander_label):
            col1, col2 = st.columns([3, 1])

            with col1:
                desc = job.get("description") or "No description available."
                st.markdown("**📝 Description Preview:**")
                st.caption(desc[:500])

                if job.get("score_reasoning"):
                    with st.expander("🔍 Scoring Details"):
                        st.text(job["score_reasoning"][:400])

            with col2:
                st.markdown(f"**Status:** `{job.get('pipeline_status', '?')}`")
                if job.get("salary"):
                    st.metric("Salary", job["salary"])

                if st.button("✂️ Tailor Resume", key=f"tailor_{job['id']}", use_container_width=True):
                    with st.spinner("Generating tailored resume..."):
                        try:
                            tr = requests.post(f"{API_BASE}/tailor/{job['id']}", timeout=30)
                            if tr.ok:
                                st.session_state[f"tailored_{job['id']}"] = tr.json()
                            else:
                                st.error(f"Failed: {tr.status_code}")
                        except Exception as e:
                            st.error(str(e))

                if st.button("📧 Cover Letter", key=f"cover_{job['id']}", use_container_width=True):
                    with st.spinner("Generating cover letter..."):
                        try:
                            cr = requests.post(f"{API_BASE}/cover/{job['id']}", timeout=30)
                            if cr.ok:
                                st.session_state[f"cover_{job['id']}"] = cr.json()
                            else:
                                st.error(f"Failed: {cr.status_code}")
                        except Exception as e:
                            st.error(str(e))

            # Show tailored resume
            if f"tailored_{job['id']}" in st.session_state:
                st.divider()
                st.markdown("### ✂️ Tailored Resume")
                data = st.session_state[f"tailored_{job['id']}"]
                st.text_area(
                    "Resume Content",
                    data.get("resume", ""),
                    height=350,
                    key=f"resume_area_{job['id']}",
                )
                st.caption(f"Keywords: {', '.join(data.get('keywords', []))}")

            # Show cover letter
            if f"cover_{job['id']}" in st.session_state:
                st.divider()
                st.markdown("### 📧 Cover Letter")
                data = st.session_state[f"cover_{job['id']}"]
                st.text_area(
                    "Cover Letter",
                    data.get("cover_letter", ""),
                    height=300,
                    key=f"cover_area_{job['id']}",
                )
