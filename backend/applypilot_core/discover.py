"""Mock job discovery — uses built-in sample jobs instead of live scraping.

In production this would call JobSpy / Workday / Playwright scrapers.
For demo purposes we use a curated list of realistic marketing jobs so
the dashboard always works without network dependencies or IP blocks.
"""

from __future__ import annotations

import logging

from applypilot_core.database import get_connection, store_jobs

log = logging.getLogger(__name__)

# ── Sample marketing jobs (HK / remote) ─────────────────────────────────

SAMPLE_JOBS: list[dict] = [
    {
        "url": "https://hk.jobsdb.com/job/89404838",
        "title": "Assistant Marketing Officer (CRM)",
        "company": "Luk Fook Holdings Company Limited",
        "salary": "HK$18,000 - HK$22,000",
        "location": "Sha Tin District, Hong Kong",
        "description": (
            "Plan and organize all marketing activities, CRM campaigns, "
            "workshops or events to enhance members' engagement and loyalty. "
            "Manage CRM system and membership database. Support daily operations "
            "of CRM programs including data analysis and report generation."
        ),
        "full_description": (
            "How You Will Do It:\n"
            "- Plan and organize all marketing activities, CRM campaigns, workshops or events to enhance members' engagement and loyalty\n"
            "- Manage CRM system and membership database\n"
            "- Support daily operations of CRM programs including data analysis and report generation\n"
            "- Prepare marketing materials and promotional content\n"
            "- Coordinate with internal and external parties for marketing projects\n\n"
            "Requirements:\n"
            "- Degree holder in Marketing, Business Administration or related discipline\n"
            "- Minimum 3 years of marketing experience, preferably in retail or jewellery industry\n"
            "- Proficient in MS Office (Excel, PowerPoint, Word)\n"
            "- Good command of both written and spoken English, Chinese and Mandarin\n"
            "- Strong analytical skills and attention to detail\n"
            "- Knowledge of CRM systems is an advantage\n"
            "- Good communication and interpersonal skills"
        ),
    },
    {
        "url": "https://hk.jobsdb.com/job/92550602",
        "title": "Marketing Executive",
        "company": "D & G Development Limited",
        "salary": "HK$20,000 - HK$25,000",
        "location": "Tsing Yi, Kwai Tsing District, Hong Kong",
        "description": (
            "Responsible for planning and executing marketing activities for "
            "wholesale and retail sectors. Provide support to the marketing "
            "department in planning, organizing, promoting campaigns and events."
        ),
        "full_description": (
            "The incumbent is responsible for planning and executing marketing activities "
            "for our wholesale and retail sector of our Marketing Department.\n\n"
            "Responsibilities:\n"
            "- Provide support to marketing department in planning, organizing, promoting campaigns and events\n"
            "- Coordinate with sales team and external vendors for marketing projects\n"
            "- Manage social media platforms and create engaging content\n"
            "- Conduct market research and competitor analysis\n"
            "- Prepare marketing reports and presentations\n"
            "- Assist in ad-hoc marketing projects as assigned\n\n"
            "Requirements:\n"
            "- Degree holder in Marketing, Communications or Business related discipline\n"
            "- 2+ years of marketing experience, preferably in FMCG or retail\n"
            "- Proficient in MS Office and Chinese word processing\n"
            "- Knowledge of Adobe Photoshop, Illustrator is an advantage\n"
            "- Good command of both written and spoken English and Chinese\n"
            "- Creative, proactive and a good team player"
        ),
    },
    {
        "url": "https://hk.jobsdb.com/job/92422676",
        "title": "Marketing Assistant",
        "company": "Zhongke Health International (H.K.) Co., Limited",
        "salary": "HK$16,000 - HK$19,000",
        "location": "Sheung Wan, Central and Western District, Hong Kong",
        "description": (
            "Responsible for planning and hosting sales seminars and events. "
            "Assist in brand management and marketing strategy development. "
            "Manage social media advertising and content creation."
        ),
        "full_description": (
            "Responsibilities:\n"
            "- Plan and host different sales seminars and marketing events\n"
            "- Assist in brand management and marketing strategy development\n"
            "- Review product sales performance based on market forecasts and follow up\n"
            "- Manage social media advertising, familiar with social media advertising and operations\n"
            "- Create marketing content and promotional materials\n\n"
            "Requirements:\n"
            "- Experience in event organization preferred, immediate availability is an advantage\n"
            "- Fluent in Cantonese, high level of Chinese writing ability (can independently write event MC scripts)\n"
            "- Basic Mandarin\n"
            "- Good business acumen and communication skills\n"
            "- Proficient in MS Office and Chinese word processing\n"
            "- Diploma or above in Marketing, Communications or related discipline"
        ),
    },
    {
        "url": "https://www.linkedin.com/jobs/view/4012345678",
        "title": "Digital Marketing Specialist",
        "company": "HSBC",
        "salary": "HK$30,000 - HK$40,000",
        "location": "Central, Hong Kong",
        "description": (
            "Drive digital marketing campaigns across multiple channels. "
            "Manage SEO/SEM, social media strategy, and content marketing. "
            "Analyze campaign performance and optimize conversion funnels."
        ),
        "full_description": (
            "We are seeking a Digital Marketing Specialist to join our growing team.\n\n"
            "Key Responsibilities:\n"
            "- Plan, execute and optimize digital marketing campaigns across paid search, display, and social channels\n"
            "- Manage SEO/SEM strategies to improve organic visibility and traffic\n"
            "- Create and curate engaging content for social media platforms\n"
            "- Track and analyze campaign performance using Google Analytics and other tools\n"
            "- Develop email marketing campaigns and marketing automation workflows\n"
            "- Collaborate with design team on creative assets\n"
            "- Monitor industry trends and competitor activities\n\n"
            "Requirements:\n"
            "- Bachelor degree in Marketing, Digital Media, or related field\n"
            "- 3-5 years of experience in digital marketing\n"
            "- Hands-on experience with Google Ads, Facebook Ads Manager, LinkedIn Campaign Manager\n"
            "- Proficient in Google Analytics, Google Tag Manager, and data visualization tools\n"
            "- Strong analytical skills and data-driven mindset\n"
            "- Experience with marketing automation tools (HubSpot, Marketo) is a plus\n"
            "- Excellent written and verbal communication skills in English and Chinese"
        ),
    },
    {
        "url": "https://www.linkedin.com/jobs/view/4023456789",
        "title": "Brand Manager",
        "company": "Nike",
        "salary": "HK$45,000 - HK$55,000",
        "location": "Kwun Tong, Hong Kong",
        "description": (
            "Lead brand strategy for Hong Kong & Macau markets. "
            "Develop integrated marketing campaigns, manage brand P&L, "
            "and drive consumer engagement through innovative initiatives."
        ),
        "full_description": (
            "Nike is looking for a passionate Brand Manager to drive our brand presence "
            "in Hong Kong and Macau.\n\n"
            "Responsibilities:\n"
            "- Develop and execute integrated brand marketing strategies for HK & Macau\n"
            "- Lead 360-degree marketing campaigns from concept to execution\n"
            "- Manage brand P&L and marketing budget\n"
            "- Analyze consumer insights and market trends to inform brand decisions\n"
            "- Drive digital-first consumer engagement strategies\n"
            "- Collaborate with cross-functional teams (Sales, Product, Creative)\n"
            "- Manage agency relationships and external partners\n"
            "- Present brand performance updates to senior leadership\n\n"
            "Requirements:\n"
            "- 5-8 years of brand marketing experience, preferably in sportswear or lifestyle\n"
            "- Proven track record of building brands and driving growth\n"
            "- Strong strategic thinking and analytical skills\n"
            "- Excellent project management and leadership abilities\n"
            "- Experience managing multi-million dollar marketing budgets\n"
            "- Fluent in English and Chinese (Cantonese and Mandarin)\n"
            "- MBA or advanced degree is a plus"
        ),
    },
    {
        "url": "https://www.linkedin.com/jobs/view/4034567890",
        "title": "Content Marketing Manager",
        "company": "Klook",
        "salary": "HK$35,000 - HK$45,000",
        "location": "Quarry Bay, Hong Kong",
        "description": (
            "Own the content strategy for APAC markets. Lead a team of "
            "content creators, manage editorial calendar, and drive organic "
            "traffic growth through SEO-optimized content."
        ),
        "full_description": (
            "Join Klook as our Content Marketing Manager and shape the voice "
            "of Asia's leading travel experiences platform.\n\n"
            "Responsibilities:\n"
            "- Develop and execute content marketing strategy across all digital channels\n"
            "- Lead and mentor a team of 4 content creators and copywriters\n"
            "- Manage editorial calendar and content production pipeline\n"
            "- Drive organic traffic growth through SEO-optimized content\n"
            "- Create compelling storytelling around travel experiences and destinations\n"
            "- Collaborate with Product, Design, and Growth teams\n"
            "- Measure content performance and optimize based on data\n"
            "- Build and maintain brand tone of voice guidelines\n\n"
            "Requirements:\n"
            "- 4-6 years of content marketing experience, ideally in e-commerce or travel\n"
            "- Strong portfolio of published content across multiple formats\n"
            "- Deep understanding of SEO best practices and content optimization\n"
            "- Experience with content management systems and analytics tools\n"
            "- Excellent writing and editing skills in English and Chinese\n"
            "- Data-driven mindset with ability to translate metrics into insights\n"
            "- Experience managing creative teams is required"
        ),
    },
]


def discover_jobs(clear_first: bool = False) -> dict:
    """Run mock job discovery — inserts sample jobs into the database.

    Args:
        clear_first: If True, delete all existing jobs first (fresh start).

    Returns:
        Dict with counts: new, existing, total.
    """
    from applypilot_core.database import init_db

    conn = init_db()

    if clear_first:
        conn.execute("DELETE FROM jobs")
        conn.commit()
        log.info("Cleared existing jobs")

    new, existing = store_jobs(conn, SAMPLE_JOBS, site="Mock", strategy="sample_data")
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    log.info("Mock discovery: %d new, %d existing, %d total", new, existing, total)
    return {"new": new, "existing": existing, "total": total}
