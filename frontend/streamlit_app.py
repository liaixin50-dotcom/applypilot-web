"""ApplyPilot — AI Job Application Assistant (Streamlit Cloud Edition).

Permanent deployment on Streamlit Cloud.  Uses 50 built-in marketing jobs
so no Playwright / live scraping is needed.  All pipeline stages work:
upload resume → search → score → tailor → cover letter.

Deploy: https://share.streamlit.io → New App → point to this file.
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
st.set_page_config(page_title="ApplyPilot - AI Job Assistant", page_icon="📋", layout="wide")
# ═════════════════════════════════════════════════════════════════════════════

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent / "backend" if (_HERE.parent / "backend").exists() else _HERE / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Try importing the core modules (available locally; on Streamlit Cloud
# we use a bundled copy of the essentials)
try:
    from applypilot_core.database import init_db, get_connection, get_all_jobs, store_jobs
    from applypilot_core.tailor import _extract_keywords
except ImportError:
    # Streamlit Cloud fallback — minimal bundled DB
    import sqlite3 as _sql
    import threading as _thr

    _local = _thr.local()
    _DB_PATH = _HERE / "applypilot.db"

    def _get_conn():
        if not hasattr(_local, "conn") or _local.conn is None:
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            c = _sql.connect(str(_DB_PATH), timeout=30)
            c.execute("PRAGMA journal_mode=WAL")
            c.row_factory = _sql.Row
            c.execute("""CREATE TABLE IF NOT EXISTS jobs (
                url TEXT PRIMARY KEY, title TEXT, company TEXT, salary TEXT,
                description TEXT, full_description TEXT, location TEXT,
                site TEXT, strategy TEXT, discovered_at TEXT,
                fit_score INTEGER, score_reasoning TEXT, scored_at TEXT,
                tailored_resume_path TEXT, tailored_at TEXT,
                cover_letter_path TEXT, cover_letter_at TEXT,
                pipeline_status TEXT DEFAULT 'discovered')""")
            c.commit()
            _local.conn = c
        return _local.conn

    def get_connection(path=None):
        return _get_conn()

    def init_db(path=None):
        return _get_conn()

    def get_all_jobs(conn=None, status=None, limit=100):
        c = conn or _get_conn()
        rows = c.execute("SELECT * FROM jobs ORDER BY COALESCE(fit_score,0) DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(r.keys(), r)) for r in rows] if rows else []

    def store_jobs(conn, jobs, site="Mock", strategy="mock"):
        now = datetime.now(timezone.utc).isoformat()
        n, e = 0, 0
        for j in jobs:
            try:
                conn.execute("""INSERT INTO jobs (url,title,company,salary,description,full_description,
                    location,site,strategy,discovered_at,pipeline_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,'discovered')""",
                    (j["url"], j.get("title"), j.get("company"), j.get("salary"),
                     j.get("description"), j.get("full_description"),
                     j.get("location"), site, strategy, now))
                n += 1
            except _sql.IntegrityError:
                e += 1
        conn.commit()
        return n, e

    def _extract_keywords(text, top_n=10):
        words = re.findall(r"[a-zA-Z]{4,}", text.lower())
        stop = {"with","that","this","from","they","have","will","your","about","each","more",
                "some","than","which","their","other","experience","years","candidate",
                "responsible","including","requirements","position","department","related",
                "skills","ability","knowledge","required","minimum","preferred"}
        return [w.title() for w,_ in Counter(w for w in words if w not in stop).most_common(top_n)]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# 50 built-in marketing jobs (no Playwright / live scraping needed)
# ═════════════════════════════════════════════════════════════════════════════
_JOBS_RAW = [
    # 1-10: Marketing Officers / Executives
    {"title":"Assistant Marketing Officer (CRM)","company":"Luk Fook Holdings","salary":"HK$18K-22K","location":"Sha Tin","desc":"Plan and organize marketing activities, CRM campaigns, workshops. Manage CRM system and membership database. Support daily CRM operations including data analysis and report generation. Prepare marketing materials and promotional content."},
    {"title":"Marketing Executive","company":"D & G Development Ltd","salary":"HK$20K-25K","location":"Tsing Yi","desc":"Plan and execute marketing activities for wholesale and retail sectors. Coordinate with sales team and vendors. Manage social media platforms and create engaging content. Conduct market research and competitor analysis."},
    {"title":"Marketing Assistant","company":"Zhongke Health Intl","salary":"HK$16K-19K","location":"Sheung Wan","desc":"Plan and host sales seminars and marketing events. Assist in brand management. Review product sales performance. Manage social media advertising. Create marketing content and promotional materials."},
    {"title":"Senior Marketing Executive","company":"Vita Green Health","salary":"HK$25K-35K","location":"Tsim Sha Tsui","desc":"Lead brand marketing for beauty and personal care products. Develop integrated marketing campaigns. Manage digital marketing channels. Analyze market trends and consumer insights. Supervise junior team members."},
    {"title":"Digital Marketing Specialist","company":"HSBC","salary":"HK$30K-40K","location":"Central","desc":"Drive digital marketing campaigns across multiple channels. Manage SEO/SEM and social media strategy. Analyze campaign performance and optimize conversion funnels. Experience with Google Ads and Facebook Ads Manager required."},
    {"title":"Brand Manager","company":"Nike","salary":"HK$45K-55K","location":"Kwun Tong","desc":"Lead brand strategy for HK & Macau markets. Develop integrated campaigns. Manage brand P&L and marketing budget. Drive consumer engagement. Present brand performance to senior leadership. 5-8 years experience required."},
    {"title":"Content Marketing Manager","company":"Klook","salary":"HK$35K-45K","location":"Quarry Bay","desc":"Own content strategy for APAC markets. Lead team of 4 content creators. Manage editorial calendar. Drive organic traffic through SEO content. Create compelling storytelling around travel experiences."},
    {"title":"Marketing Officer","company":"Cafe de Coral Group","salary":"HK$18K-25K","location":"Kwai Tsing","desc":"Support marketing department in planning and executing promotional campaigns. Coordinate with operations team. Manage POS materials and in-store branding. Prepare marketing reports and competitor analysis."},
    {"title":"Trade Marketing Executive","company":"Fortune Pharmacal","salary":"HK$22K-28K","location":"Quarry Bay","desc":"Develop trade marketing strategies for OTC products. Manage key account relationships. Plan and execute in-store promotions. Analyze sales data and market trends. Coordinate with sales and supply chain teams."},
    {"title":"Marketing Intern (Part Time)","company":"Vita Green Health","salary":"HK$8K-12K","location":"Wan Chai","desc":"Assist marketing team with daily operations. Support social media content creation. Help organize promotional events. Conduct market research. Suitable for fresh graduates. Flexible working hours."},
    # 11-20
    {"title":"Growth Marketing Manager","company":"Deliveroo","salary":"HK$40K-55K","location":"Causeway Bay","desc":"Drive user acquisition and retention through performance marketing. Manage multi-million HKD budget. Optimize campaigns across paid search, social, and display. Analyze cohort data and LTV metrics. Lead growth experiments."},
    {"title":"Social Media Specialist","company":"Sasa Cosmetics","salary":"HK$18K-24K","location":"Kwai Chung","desc":"Manage social media accounts across Facebook, Instagram, Xiaohongshu. Create engaging beauty content. Track social metrics and optimize posting strategy. Collaborate with KOLs and influencers for brand campaigns."},
    {"title":"CRM Marketing Manager","company":"Mannings","salary":"HK$35K-45K","location":"Quarry Bay","desc":"Develop CRM strategies to drive customer loyalty and retention. Manage loyalty program with 3M+ members. Design personalized marketing campaigns using customer data. Work with data analytics team on segmentation."},
    {"title":"E-commerce Marketing Lead","company":"Zalora","salary":"HK$30K-40K","location":"Tsim Sha Tsui","desc":"Drive online sales through digital marketing campaigns. Manage marketplace promotions and flash sales. Optimize product listings for SEO. Coordinate with brands for joint campaigns. Analyze e-commerce metrics."},
    {"title":"PR & Communications Manager","company":"New World Development","salary":"HK$40K-50K","location":"Central","desc":"Develop and execute PR strategies for corporate communications. Manage media relations and press events. Write press releases and corporate communications. Handle crisis communications. Build relationships with key media."},
    {"title":"Event Marketing Coordinator","company":"Hong Kong Tourism Board","salary":"HK$20K-28K","location":"Tsim Sha Tsui","desc":"Plan and execute tourism marketing events. Coordinate with vendors and partners. Manage event logistics and budgets. Create event promotion materials. Support major HK tourism campaigns and festivals."},
    {"title":"SEO Content Writer","company":"MoneyHero","salary":"HK$18K-25K","location":"Quarry Bay","desc":"Write SEO-optimized content for personal finance topics. Conduct keyword research and competitor analysis. Optimize existing content for search rankings. Track content performance using Google Analytics. 1M+ monthly readers."},
    {"title":"B2B Marketing Manager","company":"Microsoft HK","salary":"HK$50K-65K","location":"Cyberport","desc":"Drive B2B marketing for cloud and enterprise solutions. Develop account-based marketing strategies. Manage partner marketing programs. Create thought leadership content. Track pipeline and ROI metrics."},
    {"title":"Influencer Marketing Manager","company":"Meitu","salary":"HK$28K-38K","location":"Science Park","desc":"Develop influencer marketing strategies for beauty apps. Identify and build relationships with KOLs. Negotiate contracts and manage campaigns. Track influencer performance metrics. Manage 50+ influencer partnerships."},
    {"title":"Market Research Analyst","company":"NielsenIQ","salary":"HK$22K-30K","location":"Quarry Bay","desc":"Conduct quantitative and qualitative market research for FMCG clients. Design surveys and analyze consumer data. Prepare client presentations and reports. Use SPSS and Excel for data analysis. Track market trends."},
    # 21-30
    {"title":"Product Marketing Manager","company":"Lalamove","salary":"HK$35K-48K","location":"Kwun Tong","desc":"Drive product marketing for logistics platform. Develop go-to-market strategies. Create product messaging and positioning. Work with product and engineering teams. Analyze user feedback and market trends."},
    {"title":"Affiliate Marketing Specialist","company":"ShopBack","salary":"HK$20K-28K","location":"Causeway Bay","desc":"Manage affiliate marketing programs across APAC. Recruit and onboard new affiliate partners. Optimize commission structures. Track performance and fraud detection. Experience with affiliate networks required."},
    {"title":"Marketing Analytics Manager","company":"Standard Chartered","salary":"HK$45K-60K","location":"Central","desc":"Lead marketing analytics for retail banking. Build dashboards and attribution models. Analyze campaign ROI across channels. Present insights to C-level stakeholders. Experience with SQL, Python, Tableau required."},
    {"title":"Creative Copywriter","company":"Ogilvy HK","salary":"HK$22K-32K","location":"Quarry Bay","desc":"Write creative copy for advertising campaigns across print, digital, TV. Develop brand voice guidelines. Present creative concepts to clients. Work with art directors on integrated campaigns. Portfolio required."},
    {"title":"Customer Marketing Manager","company":"Foodpanda","salary":"HK$30K-42K","location":"Causeway Bay","desc":"Drive customer engagement through lifecycle marketing. Design email and push notification campaigns. Segment customer base for targeted promotions. Analyze churn and retention metrics. Experience with Braze or similar."},
    {"title":"Marketing Director APAC","company":"L'Oreal","salary":"HK$80K-100K","location":"Quarry Bay","desc":"Lead marketing strategy for APAC region. Manage team of 15+ marketing professionals. Oversee multi-million EUR budget. Drive brand growth across 12 markets. Report to Global CMO. 12+ years experience."},
    {"title":"Performance Marketing Lead","company":"Crypto.com","salary":"HK$40K-55K","location":"Central","desc":"Drive user acquisition through paid channels. Manage 7-figure monthly ad spend. Optimize campaigns across Google, Facebook, TikTok. A/B test creatives and landing pages. Track CAC and ROAS metrics."},
    {"title":"Community Manager","company":"Animoca Brands","salary":"HK$25K-35K","location":"Cyberport","desc":"Build and manage Web3 gaming community on Discord and Twitter. Create engagement strategies for NFT projects. Moderate community discussions. Organize online events and AMAs. Report community sentiment."},
    {"title":"Retail Marketing Manager","company":"Chow Tai Fook","salary":"HK$35K-45K","location":"Kwun Tong","desc":"Drive retail marketing for 200+ stores in HK & Macau. Plan seasonal campaigns and promotions. Manage in-store visual merchandising. Coordinate with mall marketing teams. Track foot traffic and sales data."},
    {"title":"Marketing Data Scientist","company":"ZA Bank","salary":"HK$45K-60K","location":"Cyberport","desc":"Apply machine learning to marketing optimization. Build customer segmentation and propensity models. Design A/B testing frameworks. Analyze large-scale customer data. Python, SQL, and ML experience required."},
    # 31-40
    {"title":"Junior Marketing Coordinator","company":"OpenRice","salary":"HK$15K-18K","location":"Quarry Bay","desc":"Assist in marketing campaign execution. Coordinate with restaurant partners. Update website and app content. Prepare marketing materials. Support social media posting schedule. Entry level, training provided."},
    {"title":"Employer Branding Specialist","company":"CLP Power","salary":"HK$28K-38K","location":"Hung Hom","desc":"Develop employer branding strategy for graduate recruitment. Manage career website and social media. Create employee advocacy content. Organize campus recruitment events. Track employer brand metrics."},
    {"title":"Marketing Automation Manager","company":"Prudential HK","salary":"HK$35K-48K","location":"Causeway Bay","desc":"Design and implement marketing automation workflows. Manage customer journey mapping. Set up triggered email and SMS campaigns. Integrate CRM with marketing platforms. Experience with Salesforce Marketing Cloud."},
    {"title":"Visual Merchandising Manager","company":"DFS Group","salary":"HK$30K-40K","location":"Tsim Sha Tsui","desc":"Create visual merchandising strategies for luxury retail. Design window displays and in-store layouts. Manage VM budget and production timeline. Coordinate with brand partners on guidelines. Travel required."},
    {"title":"Partnership Marketing Manager","company":"Asia Miles","salary":"HK$35K-45K","location":"Central","desc":"Develop co-branded marketing campaigns with airline and retail partners. Manage partner relationships across APAC. Create joint promotions to drive miles earning and redemption. Track partnership ROI."},
    {"title":"Field Marketing Manager","company":"Red Bull","salary":"HK$30K-38K","location":"Kwun Tong","desc":"Plan and execute field marketing activations across HK. Manage student brand ambassador program. Organize sports and culture events. Build relationships with venues and partners. 50% field work required."},
    {"title":"Internal Communications Manager","company":"MTR Corporation","salary":"HK$35K-45K","location":"Kowloon Bay","desc":"Develop internal communications strategy for 20K+ employees. Manage intranet and employee app content. Write executive communications. Organize town halls and employee events. Bilingual English/Chinese."},
    {"title":"Category Marketing Manager","company":"DFI Retail Group","salary":"HK$35K-48K","location":"Quarry Bay","desc":"Drive category growth for health & beauty products. Develop category marketing plans. Analyze market share and competitor data. Work with buying team on promotions. Manage supplier marketing funds."},
    {"title":"Marketing Technologist","company":"Hang Seng Bank","salary":"HK$40K-55K","location":"Central","desc":"Bridge marketing and technology teams. Evaluate and implement martech stack. Manage CDP and marketing automation platforms. Ensure data compliance (PDPO). Experience with Adobe Experience Cloud preferred."},
    {"title":"Sports Marketing Executive","company":"Adidas HK","salary":"HK$22K-30K","location":"Tsim Sha Tsui","desc":"Execute sports marketing campaigns for HK market. Manage athlete and team sponsorships. Organize sports events and activations. Create sports-related content for social media. Passion for sports required."},
    # 41-50
    {"title":"Content Creator (Video)","company":"9GAG","salary":"HK$18K-25K","location":"Kwun Tong","desc":"Create viral video content for social media platforms. Edit short-form videos for TikTok and Instagram Reels. Brainstorm creative concepts with team. Track video performance metrics. Adobe Premiere and After Effects skills."},
    {"title":"Marketing Procurement Manager","company":"Jardine Matheson","salary":"HK$40K-55K","location":"Central","desc":"Manage marketing procurement for group companies. Negotiate with agencies and vendors. Optimize marketing spend across categories. Develop procurement policies and frameworks. 8+ years in marketing procurement."},
    {"title":"Loyalty Program Executive","company":"The Peninsula Hotels","salary":"HK$20K-28K","location":"Tsim Sha Tsui","desc":"Manage luxury hotel loyalty program operations. Handle member inquiries and benefits fulfillment. Coordinate with properties across Asia for member experiences. Track program KPIs and member satisfaction."},
    {"title":"E-sports Marketing Manager","company":"Talon Esports","salary":"HK$30K-40K","location":"Kwun Tong","desc":"Develop marketing strategies for esports team and events. Manage sponsorship activations. Create fan engagement campaigns. Coordinate with streaming platforms. Deep understanding of gaming culture required."},
    {"title":"Medical Marketing Specialist","company":"GlaxoSmithKline","salary":"HK$35K-48K","location":"Quarry Bay","desc":"Develop marketing materials for pharmaceutical products. Organize medical education events for healthcare professionals. Ensure compliance with drug marketing regulations. Experience in pharma marketing required."},
    {"title":"Marketing Intern","company":"Google HK","salary":"HK$10K-15K","location":"Quarry Bay","desc":"Support APAC marketing team with campaign execution. Conduct market research and competitive analysis. Help organize events and workshops. Prepare marketing reports. Currently enrolled in university required."},
    {"title":"Regional Marketing Director","company":"Unilever","salary":"HK$90K-120K","location":"Kwun Tong","desc":"Lead regional marketing for personal care brands across Asia. Manage 20+ person marketing team. Drive brand strategy and innovation pipeline. Oversee 50M+ USD marketing budget. 15+ years CPG experience."},
    {"title":"Digital Designer (Marketing)","company":"Canva","salary":"HK$28K-38K","location":"Remote/HK","desc":"Design marketing assets for digital campaigns. Create social media graphics and email templates. Design landing pages for campaigns. Maintain brand consistency across all touchpoints. Figma and Adobe Creative Suite."},
    {"title":"Marketing Operations Manager","company":"Airwallex","salary":"HK$40K-55K","location":"Central","desc":"Build marketing operations infrastructure for hypergrowth fintech. Manage marketing tech stack and integrations. Create scalable processes and workflows. Track marketing KPIs and build executive dashboards. HubSpot experience."},
    {"title":"Graduate Trainee - Marketing","company":"Swire Properties","salary":"HK$20K-25K","location":"Quarry Bay","desc":"Rotational marketing traineeship across commercial and residential properties. Exposure to brand marketing, digital, events, and PR. Structured training and mentorship. Recent graduate with 2:1 or above. Leadership potential."},
]

# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", text.lower())


def _score_badge(score):
    if score is None: return "⏳", "gray"
    if score >= 7: return f"{score}/10", "green"
    if score >= 5: return f"{score}/10", "yellow"
    if score >= 3: return f"{score}/10", "orange"
    return f"{score}/10", "red"


def _load_resume() -> str:
    rp = _BACKEND / "resume.txt"
    if rp.exists():
        return rp.read_text(encoding="utf-8")
    return ""


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return text.strip() or "[No text found in PDF]"
    except ImportError:
        return "[pymupdf not installed — pip install pymupdf]"


def _extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        from zipfile import ZipFile
        from xml.etree.ElementTree import XML
        with ZipFile(io.BytesIO(file_bytes)) as z:
            xml_content = z.read("word/document.xml")
        tree = XML(xml_content)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for p in tree.iter(f"{{{ns['w']}}}p"):
            texts = [t.text for t in p.iter(f"{{{ns['w']}}}t") if t.text]
            if texts: paragraphs.append("".join(texts))
        return "\n".join(paragraphs)
    except Exception:
        return "[DOCX parsing failed]"


def _run_scoring(conn):
    """Score all unscored jobs using weighted keyword matching."""
    resume = _load_resume()
    if not resume:
        resume = "marketing digital campaign social media content strategy analytics branding communications market research data analysis"

    rows = conn.execute(
        "SELECT * FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL"
    ).fetchall()
    if not rows: return 0
    jobs = [dict(zip(r.keys(), r)) for r in rows]
    now = datetime.now(timezone.utc).isoformat()

    HIGH_VALUE = {
        "python","sql","excel","tableau","powerbi","spss","photoshop","illustrator",
        "premiere","adobe","analytics","seo","sem","crm","salesforce","hubspot",
        "marketo","google","facebook","linkedin","email","content","social","media",
        "digital","research","data","analysis","branding","campaign","copywriting",
        "strategy","budget","forecasting","budgeting","design","video","writing",
        "pr","communications","ecommerce","b2b","growth","performance",
    }
    LOW_VALUE = {
        "the","and","for","with","that","this","from","are","will","have","has",
        "can","its","not","but","all","also","each","more","some","than","which",
        "their","other","about","they","what","your","our","you","was","were",
        "experience","skills","required","work","job","position","role","company",
        "team","year","years","plan","support","manage","track","create","develop",
        "drive","required","preferred","including","candidate",
    }

    scored = 0
    for job in jobs:
        desc = (job.get("full_description") or job.get("description") or "")
        if len(desc) < 50: continue
        r_toks = set(_tokenize(resume))
        j_toks = set(_tokenize(desc.lower()))
        hi = r_toks & j_toks & HIGH_VALUE
        lo = r_toks & j_toks & LOW_VALUE
        reg = r_toks & j_toks - HIGH_VALUE - LOW_VALUE
        hits = len(hi) * 3 + len(reg)
        total = max(1, len(j_toks - LOW_VALUE))
        s = max(1, min(10, int(1 + round((hits / total) * 12))))
        if len(hi) >= 2: s = min(10, s + 1)
        reason = f"High-value matches ({len(hi)}): {', '.join(sorted(hi)[:8])}. Regular: {len(reg)}."
        conn.execute(
            "UPDATE jobs SET fit_score=?,score_reasoning=?,scored_at=?,pipeline_status='scored' WHERE url=?",
            (s, reason, now, job["url"]))
        scored += 1
    conn.commit()
    return scored


def _tailor(job_url: str, conn) -> dict:
    row = conn.execute("SELECT * FROM jobs WHERE url=?", (job_url,)).fetchone()
    if not row: return {"error": "not found"}
    job = dict(zip(row.keys(), row))
    desc = job.get("full_description") or job.get("description") or ""
    kws = _extract_keywords(desc, top_n=10)
    base = _load_resume() or "Candidate Resume"
    tailored = (
        f"[TAILORED FOR: {job['title']} at {job.get('company','?')}]\n\n{base}\n\n"
        f"--- Highlighted Skills ---\n" + "\n".join(f"- {k}" for k in kws)
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET tailored_resume_path=?,tailored_at=?,pipeline_status='tailored' WHERE url=?",
        (f"tailored_{job_url[-20:]}.txt", now, job_url))
    conn.commit()
    return {"resume": tailored, "keywords": kws}


def _cover(job_url: str, conn) -> dict:
    row = conn.execute("SELECT * FROM jobs WHERE url=?", (job_url,)).fetchone()
    if not row: return {"error": "not found"}
    job = dict(zip(row.keys(), row))
    desc = job.get("full_description") or job.get("description") or ""
    kws = _extract_keywords(desc, top_n=6)
    letter = (
        f"Dear Hiring Manager,\n\n"
        f"I am writing to apply for the {job['title']} position at "
        f"{job.get('company','your organization')}. With my background in "
        f"{', '.join(kws[:4]).lower()}, I am confident I can contribute effectively.\n\n"
        f"My experience aligns well with this role, and I look forward to "
        f"discussing how I can add value to your team.\n\n"
        f"Sincerely,\nCandidate"
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET cover_letter_path=?,cover_letter_at=?,pipeline_status='cover_done' WHERE url=?",
        (f"cover_{job_url[-20:]}.txt", now, job_url))
    conn.commit()
    return {"cover_letter": letter, "keywords": kws}


# ═════════════════════════════════════════════════════════════════════════════
# Session state
# ═════════════════════════════════════════════════════════════════════════════
for key, default in [
    ("all_jobs", []), ("display_n", 50), ("search_done", False),
    ("searching", False), ("uploaded_resume_name", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ═════════════════════════════════════════════════════════════════════════════
# Sidebar
# ═════════════════════════════════════════════════════════════════════════════

st.title("📋 ApplyPilot — AI Job Application Assistant")
st.caption("50 built-in marketing jobs · Resume scoring · Tailored applications")

with st.sidebar:
    st.header("📤 Upload Resume")
    uploaded = st.file_uploader("Resume (PDF, DOCX, or TXT)", type=["pdf","docx","txt"])
    if uploaded is not None:
        fbytes = uploaded.read()
        fname = uploaded.name
        if fname.lower().endswith(".pdf"):
            text = _extract_text_from_pdf(fbytes)
        elif fname.lower().endswith(".docx"):
            text = _extract_text_from_docx(fbytes)
        else:
            text = fbytes.decode("utf-8", errors="replace")
        if text and len(text) > 20:
            rp = _BACKEND / "resume.txt"
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(text, encoding="utf-8")
            st.session_state["uploaded_resume_name"] = fname
            st.success(f"✅ Resume loaded: {fname} ({len(text):,} chars)")
            # Reset scores for re-scoring
            conn = get_connection()
            conn.execute("UPDATE jobs SET fit_score=NULL,score_reasoning=NULL,scored_at=NULL")
            conn.commit()
        else:
            st.error(f"Could not parse {fname}")

    if st.session_state.get("uploaded_resume_name"):
        st.info(f"📄 {st.session_state['uploaded_resume_name']}")

    st.divider()

    st.header("🔍 Search Jobs")
    with st.form("search_form"):
        query = st.text_input("Keywords", value="marketing", help="Filter by title keywords")
        loc = st.selectbox("Location", ["Hong Kong","Kowloon","New Territories","Remote"], index=0)
        jt = st.selectbox("Job Type", ["Any","Full-time","Part-time","Contract","Internship"], index=0)
        submitted = st.form_submit_button("🔎 Search / Refresh Jobs", type="primary", use_container_width=True)

    if submitted:
        st.session_state["searching"] = True
        st.session_state["search_done"] = False
        st.session_state["all_jobs"] = []
        st.session_state["_search_query"] = query.lower()
        st.rerun()

    st.divider()

    # Stats
    try:
        conn = get_connection()
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        scored = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL").fetchone()[0]
        st.metric("Total Jobs", total)
        st.metric("Scored", scored)
        if scored > 0:
            avg = conn.execute("SELECT AVG(fit_score) FROM jobs WHERE fit_score IS NOT NULL").fetchone()[0]
            st.metric("Avg Score", f"{avg:.1f}/10")
    except Exception:
        pass

    st.divider()
    st.caption("Streamlit Cloud · Permanent URL")
    st.caption("50 built-in HK marketing jobs")

# ═════════════════════════════════════════════════════════════════════════════
# Search execution
# ═════════════════════════════════════════════════════════════════════════════

if st.session_state.get("searching"):
    query_filter = st.session_state.get("_search_query", "marketing").lower()
    with st.status(f"🔍 Loading jobs matching '{query_filter}'...", expanded=True) as status:
        conn = init_db()

        # Filter jobs by keyword
        filtered = [j for j in _JOBS_RAW if query_filter in j["title"].lower() or query_filter in j["desc"].lower()]
        if not filtered:
            filtered = _JOBS_RAW  # show all if no match

        # Clear DB and insert
        conn.execute("DELETE FROM jobs"); conn.commit()
        db_jobs = [{
            "url": f"job://{i}", "title": j["title"], "company": j["company"],
            "salary": j.get("salary",""), "description": j["desc"][:300],
            "full_description": j["desc"], "location": j.get("location","HK"),
        } for i, j in enumerate(filtered)]
        store_jobs(conn, db_jobs, site="Built-in", strategy="static")

        st.write(f"📋 Loaded **{len(filtered)}** jobs")

        # Auto-score
        n = _run_scoring(conn)
        st.write(f"📊 Scored **{n}** jobs")

        # Get URLs for display
        rows = conn.execute("SELECT url FROM jobs").fetchall()
        st.session_state["all_jobs"] = [{"url": r[0]} for r in rows]
        st.session_state["display_n"] = min(50, len(filtered))
        st.session_state["search_done"] = True
        status.update(label=f"✅ {len(filtered)} jobs, {n} scored", state="complete")

    st.session_state["searching"] = False

# ═════════════════════════════════════════════════════════════════════════════
# Job results
# ═════════════════════════════════════════════════════════════════════════════

if st.session_state.get("search_done") and st.session_state.get("all_jobs"):
    all_jobs = st.session_state["all_jobs"]
    display_n = st.session_state.get("display_n", 50)

    conn = get_connection()
    rows = get_all_jobs(conn, limit=9999)
    db_map = {r["url"]: r for r in rows}
    db_total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    if db_total == 0:
        st.warning("Session expired — please search again.")
        st.session_state["search_done"] = False
        st.stop()

    # Score summary
    scored_count = sum(1 for r in rows if r.get("fit_score") is not None)
    if scored_count > 0:
        avg_score = sum(r["fit_score"] for r in rows if r.get("fit_score") is not None) / scored_count
        st.info(f"📊 **{scored_count}** jobs scored | Average: **{avg_score:.1f}/10**")
    else:
        st.warning("No scores yet — please search again.")
        st.stop()

    st.header(f"📋 Search Results ({db_total:,} jobs)")

    c1, c2 = st.columns(2)
    with c1:
        min_score = st.slider("Minimum Score", 0, 10, 0)
    with c2:
        sort_by = st.selectbox("Sort by", ["Score (high first)","Score (low first)","Newest"], index=0)

    # Build display
    display_jobs = []
    for j in all_jobs[:display_n]:
        db_row = db_map.get(j.get("url", ""))
        score = db_row.get("fit_score") if db_row else None
        if min_score > 0 and (score is None or score < min_score):
            continue
        display_jobs.append({
            "id": hashlib.md5(j.get("url","").encode()).hexdigest()[:12],
            "url": j.get("url",""),
            "title": db_row.get("title","?") if db_row else "?",
            "company": db_row.get("company") if db_row else None,
            "location": db_row.get("location") if db_row else "HK",
            "salary": db_row.get("salary") if db_row else None,
            "description": (db_row.get("full_description") or db_row.get("description") or "") if db_row else "",
            "score": score,
            "score_reasoning": db_row.get("score_reasoning") if db_row else None,
            "pipeline_status": db_row.get("pipeline_status","discovered") if db_row else "discovered",
        })

    if sort_by.startswith("Score"):
        display_jobs.sort(key=lambda x: x.get("score") or 0, reverse="high" in sort_by)
    else:
        display_jobs.reverse()

    st.caption(f"Showing {len(display_jobs)} jobs (score ≥ {min_score})")

    for job in display_jobs:
        s, cls = _score_badge(job.get("score"))
        label = f"`[{s}]` {job['title']} — *{job.get('company','?')}*"
        if job.get("location"): label += f" | {job['location']}"
        if job.get("salary"): label += f" | {job['salary']}"

        with st.expander(label):
            job_url = job.get("url", "")
            if job_url.startswith("http"):
                st.markdown(f"🔗 [View Original Posting]({job_url})")

            c1, c2 = st.columns([3, 1])
            with c1:
                desc = job.get("description") or ""
                if desc and len(desc) > 20:
                    st.markdown("**📝 Description:**")
                    st.caption(desc[:800])
                else:
                    st.info("Limited description — use link above for full details.")
                if job.get("score_reasoning"):
                    with st.expander("🔍 Score Details"):
                        st.text(job["score_reasoning"][:400])
            with c2:
                st.markdown(f"Status: `{job.get('pipeline_status','?')}`")
                if job.get("salary"): st.metric("Salary", job["salary"])
                bid = job["id"]
                if st.button("✂️ Tailor", key=f"btn_t_{bid}", use_container_width=True):
                    r = _tailor(job["url"], conn)
                    st.session_state[f"data_t_{bid}"] = r
                if st.button("📧 Cover", key=f"btn_c_{bid}", use_container_width=True):
                    r = _cover(job["url"], conn)
                    st.session_state[f"data_c_{bid}"] = r

            if f"data_t_{bid}" in st.session_state:
                st.divider()
                st.markdown("**✂️ Tailored Resume**")
                st.text_area("Resume", st.session_state[f"data_t_{bid}"]["resume"], height=250, key=f"area_t_{bid}")
            if f"data_c_{bid}" in st.session_state:
                st.divider()
                st.markdown("**📧 Cover Letter**")
                st.text_area("Cover", st.session_state[f"data_c_{bid}"]["cover_letter"], height=200, key=f"area_c_{bid}")

elif not st.session_state.get("searching"):
    st.info("👆 Upload your resume in the sidebar, then click **Search / Refresh Jobs** to begin.")
    st.markdown("""
    ### Features:
    - 📤 **Upload Resume** — PDF, DOCX, or TXT
    - 🔍 **50 Built-in HK Marketing Jobs** — no scraping needed
    - 📊 **Auto-Scoring** — weighted keyword matching with your resume
    - ✂️ **Tailored Resume** — per-job customization
    - 📧 **Cover Letter** — per-job generation
    """)
