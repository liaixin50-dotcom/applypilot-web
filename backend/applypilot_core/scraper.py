"""JobsDB HK scraper — Playwright-based job discovery with search filters.

Supports: industry/keyword, job type (full-time/part-time/internship),
          salary range, posting recency, and paginated results.
"""

from __future__ import annotations

import logging
import re
import sys as _sys
import time
from urllib.parse import quote_plus, urlencode

log = logging.getLogger(__name__)

# ── Default cookies (fallback for demo) ─────────────────────────────────────

DEFAULT_COOKIE_STR = (
    "sol_id=143291fb-b54f-4b58-91d7-28cff624e9da; "
    "_ga=GA1.1.109626208.1780671174; "
    "JobseekerSessionId=2db0a922-9783-49aa-9275-0aac15fd9c7d; "
    "JobseekerVisitorId=2db0a922-9783-49aa-9275-0aac15fd9c7d"
)


def _parse_cookies(cookie_str: str, domain: str = ".jobsdb.com") -> list[dict]:
    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, val = part.split("=", 1)
        cookies.append({"name": name.strip(), "value": val.strip(), "domain": domain, "path": "/"})
    return cookies


# ── URL builders ────────────────────────────────────────────────────────────

def build_search_url(
    query: str = "marketing",
    location: str = "Hong Kong",
    job_type: str = "",       # full-time, part-time, internship, contract
    days_old: int = 0,        # 1, 3, 7, 14, 30; 0 = any
    salary_min: int = 0,
    salary_max: int = 0,
) -> str:
    """Build a JobsDB HK search URL with filters."""
    base = "https://hk.jobsdb.com/hk/en/Search/FindJobs"

    params: dict[str, str] = {
        "Key": query,
        "Location": location,
    }

    # Job type filter
    if job_type:
        jt_map = {
            "full-time": "242", "part-time": "243", "contract": "244",
            "temporary": "245", "internship": "246", "fresh-grad": "247",
        }
        if code := jt_map.get(job_type.lower()):
            params["JType"] = code

    # Recency filter (days)
    if days_old > 0:
        params["DateRange"] = str(days_old)

    # Salary filter (rough — JobsDB uses ranges in the UI)
    if salary_min > 0 or salary_max > 0:
        sal = f"{salary_min or 0}-{salary_max or 999999}"
        params["Salary"] = sal

    qs = urlencode(params)
    return f"{base}?{qs}"


# ── Page scraping ───────────────────────────────────────────────────────────

def _extract_job_id(url: str) -> str:
    m = re.search(r'/job/(\d+)', url)
    return m.group(1) if m else ""


def scrape_search_page(page, seen_ids: set[str], max_new: int = 50) -> list[dict]:
    """Extract job cards from the currently loaded JobsDB search page.

    Uses JobsDB's `data-automation` attributes which are stable selectors.
    """
    time.sleep(1)
    try:
        page.wait_for_selector("[data-automation='jobTitle']", timeout=10000)
    except Exception:
        log.warning("No job cards found on page")

    # Find all job cards via article elements containing job links
    articles = page.query_selector_all("article")
    if not articles:
        # Fallback: find all job links and work backwards
        anchors = page.query_selector_all("a[href*='/job/']")
    else:
        anchors = []

    jobs: list[dict] = []

    # ── Strategy 1: Use data-automation selectors ────────────────────────
    title_els = page.query_selector_all("[data-automation='jobTitle']")
    company_els = page.query_selector_all("[data-automation='jobCompany']")
    location_els = page.query_selector_all("[data-automation='jobLocation']")
    salary_els = page.query_selector_all("[data-automation='jobSalary']")
    link_els = page.query_selector_all("a[href*='/job/']")

    # Build a map: job ID → data
    for i, title_el in enumerate(title_els):
        if len(jobs) >= max_new:
            break

        try:
            title = title_el.inner_text().strip()
            if not title or len(title) < 2:
                continue

            # Get company (same index should match, but may not align perfectly)
            company = None
            if i < len(company_els):
                try:
                    company = company_els[i].inner_text().strip()
                except Exception:
                    pass

            # Location
            loc_text = "Hong Kong"
            if i < len(location_els):
                try:
                    loc_text = location_els[i].inner_text().strip()
                except Exception:
                    pass

            # Salary
            salary = None
            if i < len(salary_els):
                try:
                    salary = salary_els[i].inner_text().strip()
                except Exception:
                    pass

            # Find the job URL — look for a link containing /job/ near this title
            href = None
            jid = None
            # Try parent article (MUST be 'article' — not a generic div)
            card = title_el.evaluate_handle("el => el.closest('article')")
            card_el = card.as_element() if card else None
            if card_el:
                link = card_el.query_selector("a[href*='/job/']")
                if link:
                    href = link.get_attribute("href") or ""

            if not href:
                # Fallback: use link at same index
                if i < len(link_els):
                    href = link_els[i].get_attribute("href") or ""

            if href:
                if href.startswith("/"):
                    href = "https://hk.jobsdb.com" + href
                href = href.split("#")[0]
                jid = _extract_job_id(href)

            if not jid:
                jid = f"unknown_{i}"
                href = f"https://hk.jobsdb.com/job/{jid}"

            if jid in seen_ids:
                continue
            seen_ids.add(jid)

            # Card text as snippet
            snippet = None
            if card_el:
                try:
                    snippet = card_el.inner_text()[:1500]
                except Exception:
                    pass

            jobs.append({
                "url": href,
                "jid": jid,
                "title": re.sub(r'\s+', ' ', title)[:200],
                "company": company,
                "location": loc_text,
                "salary": salary,
                "description": snippet,
            })

        except Exception as e:
            log.debug("Error extracting card %d: %s", i, e)
            continue

    # ── Strategy 2: fallback if data-automation didn't work ─────────────
    if not jobs and articles:
        for article in articles:
            if len(jobs) >= max_new:
                break
            try:
                link = article.query_selector("a[href*='/job/']")
                if not link:
                    continue
                href = link.get_attribute("href") or ""
                jid = _extract_job_id(href)
                if not jid or jid in seen_ids:
                    continue
                seen_ids.add(jid)
                if href.startswith("/"):
                    href = "https://hk.jobsdb.com" + href
                href = href.split("#")[0]

                title_el = article.query_selector("h3, h2, [class*='title']")
                title = title_el.inner_text().strip() if title_el else link.inner_text().strip()
                if not title or len(title) < 2:
                    title = f"Job {jid}"

                comp_el = article.query_selector("[class*='company'], [class*='employer']")
                company = comp_el.inner_text().strip() if comp_el else None

                jobs.append({
                    "url": href, "jid": jid,
                    "title": re.sub(r'\s+', ' ', title)[:200],
                    "company": company,
                    "location": "Hong Kong",
                    "salary": None,
                    "description": article.inner_text()[:1500] if hasattr(article, 'inner_text') else None,
                })
            except Exception:
                continue

    return jobs


def scrape_job_detail(page, url: str) -> str | None:
    """Visit a job detail page and extract the full description."""
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        time.sleep(1.5)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        # Remove nav/header/footer noise
        try:
            page.evaluate("""
                document.querySelectorAll('header, nav, footer, script, style, noscript').forEach(e => e.remove());
            """)
            time.sleep(0.3)
        except Exception:
            pass

        for sel in ["main", "article", "[data-automation='jobDescription']",
                     "[class*='description']", "[class*='job-description']", "[class*='JD']"]:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text()
                    if text and len(text) > 150:
                        return text.strip()[:20000]
            except Exception:
                continue

        body = page.inner_text("body")
        return body.strip()[:20000] if body and len(body) > 150 else None

    except Exception as e:
        log.debug("Error fetching detail %s: %s", url[:80], e)
        return None


# ── Main public API ─────────────────────────────────────────────────────────

def search_jobsdb(
    query: str = "marketing",
    location: str = "Hong Kong",
    job_type: str = "",
    days_old: int = 0,
    salary_min: int = 0,
    salary_max: int = 0,
    limit: int = 50,
    cookies_str: str = "",
    headless: bool = True,
) -> list[dict]:
    """Search JobsDB HK and return structured job listings.

    Args:
        query: Search keyword (e.g. "marketing", "finance", "software engineer").
        location: Location string (e.g. "Hong Kong", "Kowloon").
        job_type: One of "full-time", "part-time", "contract", "internship", "" = any.
        days_old: Posted within N days (0 = any time).
        salary_min: Minimum monthly salary in HKD.
        salary_max: Maximum monthly salary in HKD.
        limit: Max total jobs to return (scrapes multiple pages if needed).
        cookies_str: JobsDB cookie string (uses default demo cookies if empty).
        headless: Run browser headless (True) or visible (False).

    Returns:
        List of job dicts (url, title, company, location, salary, description).
    """
    from playwright.sync_api import sync_playwright

    cookies = _parse_cookies(cookies_str or DEFAULT_COOKIE_STR)
    search_url = build_search_url(query, location, job_type, days_old, salary_min, salary_max)

    log.info("JobsDB search: %s | type=%s | days=%d | limit=%d", query, job_type, days_old, limit)

    # ── Always use subprocess isolation on Windows ──────────────────────
    # Playwright's sync API uses asyncio subprocesses internally.  On some
    # Windows environments (Streamlit, Conda, certain Python builds) the
    # event loop fails with NotImplementedError in _make_subprocess_transport.
    # Running the scraper in a child process gives it a clean interpreter.
    import json as _json
    import subprocess as _sp
    from pathlib import Path as _Path

    _backend_dir = str(_Path(__file__).resolve().parent.parent)
    _params_json = _json.dumps({
        "query": query, "location": location, "job_type": job_type,
        "days_old": days_old, "salary_min": salary_min, "salary_max": salary_max,
        "limit": limit, "headless": headless,
        "cookies_str": cookies_str or DEFAULT_COOKIE_STR,
    })
    _proc = _sp.run(
        [_sys.executable, "-c", f'''
import json, sys
sys.path.insert(0, {_json.dumps(_backend_dir)})
params = json.loads({_json.dumps(_params_json)})
from applypilot_core.scraper import _scrape_impl
print(json.dumps(_scrape_impl(**params)))
'''],
        capture_output=True, text=True, timeout=300,
        cwd=_backend_dir,
    )
    if _proc.returncode != 0:
        raise RuntimeError(f"Scraper subprocess failed (code={_proc.returncode}): {_proc.stderr[:500]}")
    return _json.loads(_proc.stdout)


def _scrape_impl(
    query: str, location: str, job_type: str,
    days_old: int, salary_min: int, salary_max: int,
    limit: int, headless: bool, cookies_str: str,
) -> list[dict]:
    """Inner scraping implementation — also called standalone in subprocess."""
    from playwright.sync_api import sync_playwright

    cookies = _parse_cookies(cookies_str)
    search_url = build_search_url(query, location, job_type, days_old, salary_min, salary_max)

    log.info("JobsDB search: %s | type=%s | days=%d | limit=%d", query, job_type, days_old, limit)

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=80)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        context.add_cookies(cookies)
        page = context.new_page()

        # Navigate to search
        try:
            page.goto(search_url, timeout=90000, wait_until="domcontentloaded")
        except Exception as e:
            log.warning("Initial nav: %s, continuing...", e)

        time.sleep(3)
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:
            pass
        time.sleep(1)

        page_num = 1
        while len(all_jobs) < limit:
            log.info("Scraping page %d... (%d jobs so far)", page_num, len(all_jobs))

            new_jobs = scrape_search_page(page, seen_ids, max_new=limit - len(all_jobs))
            if not new_jobs:
                log.info("No more jobs found on page %d", page_num)
                break

            all_jobs.extend(new_jobs)

            # Try to go to next page
            if len(all_jobs) < limit:
                try:
                    next_btn = page.query_selector(
                        "a[aria-label='Next'], a[class*='next'], button[aria-label='Next'], "
                        "[data-automation='page-next'], a[title='Next']"
                    )
                    if next_btn:
                        next_btn.click()
                        time.sleep(2)
                        try:
                            page.wait_for_load_state("networkidle", timeout=30000)
                        except Exception:
                            pass
                        page_num += 1
                        continue
                except Exception:
                    pass
                log.info("No next page button found, stopping")
                break

        browser.close()

    log.info("JobsDB search complete: %d jobs total", len(all_jobs))
    return all_jobs


# _scrape_impl is called via subprocess by search_jobsdb above

