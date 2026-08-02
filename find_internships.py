"""
Chemistry Internship Daily Digest
----------------------------------
Pulls from openly-published sources only:

  1. USAJobs (https://data.usajobs.gov) — the U.S. government's own free,
     open jobs API. No cost, just a free email+key registration. This is
     where most federal chemistry internships live (EPA, FDA, DOE national
     labs, NIH, USDA, Pathways Internship Program, etc).

  2. Public GitHub internship-tracker repos — plain-text READMEs that
     community projects already publish openly (raw.githubusercontent.com,
     no API key, no scraping of any site that blocks bots). Mostly
     tech-focused, but occasionally has chemical/materials-science roles,
     so it's included as a supplemental source.

New matches (not already seen) get emailed via plain SMTP.
"""

import os
import re
import sys
import json
import hashlib
import smtplib
import requests
from pathlib import Path
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SENDER_EMAIL = os.environ["SENDER_EMAIL"]
SENDER_APP_PASSWORD = os.environ["SENDER_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.mail.me.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

# Free USAJobs API credentials (https://developer.usajobs.gov/apirequest/)
USAJOBS_API_KEY = os.environ.get("USAJOBS_API_KEY", "")
USAJOBS_EMAIL = os.environ.get("USAJOBS_EMAIL", "")

# A posting must contain at least one of these words to count as a match.
MAJOR_KEYWORDS = os.environ.get(
    "MAJOR_KEYWORDS",
    "chemistry|chemical engineering|biochemistry|chemist|analytical chemistry|"
    "materials science|materials chemistry",
).lower().split("|")

# If set, require this year to appear in the title/description (e.g. "2027").
# Set REQUIRE_YEAR="" to disable.
REQUIRE_YEAR = os.environ.get("REQUIRE_YEAR", "2027")

# Public, openly-published GitHub tracker READMEs (raw text, no key needed).
GITHUB_SOURCES = [
    ("SimplifyJobs/Summer2027-Internships",
     "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"),
    ("vanshb03/Summer2027-Internships",
     "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/README.md"),
]

STATE_FILE = Path(__file__).parent / "data" / "seen_jobs.json"

# ---------------------------------------------------------------------------


def load_seen_ids() -> set:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen_ids(ids: set) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(sorted(ids), indent=2))


def matches_keywords(text: str) -> bool:
    text = text.lower()
    if not any(keyword in text for keyword in MAJOR_KEYWORDS):
        return False
    if REQUIRE_YEAR and REQUIRE_YEAR not in text:
        return False
    return True


# ---------------------------------------------------------------------------
# Source 1: USAJobs (official, free, open government jobs API)
# ---------------------------------------------------------------------------

def fetch_usajobs() -> list:
    if not (USAJOBS_API_KEY and USAJOBS_EMAIL):
        print("USAJOBS_API_KEY / USAJOBS_EMAIL not set — skipping USAJobs source.", file=sys.stderr)
        return []

    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": USAJOBS_EMAIL,
        "Authorization-Key": USAJOBS_API_KEY,
    }
    results = []
    for keyword in ["chemistry intern", "chemical engineering intern", "pathways chemistry"]:
        try:
            resp = requests.get(
                "https://data.usajobs.gov/api/search",
                headers=headers,
                params={"Keyword": keyword, "ResultsPerPage": 50},
                timeout=30,
            )
            resp.raise_for_status()
            items = resp.json().get("SearchResult", {}).get("SearchResultItems", [])
            for item in items:
                results.append(item.get("MatchedObjectDescriptor", {}))
        except requests.RequestException as exc:
            print(f"Warning: USAJobs search for '{keyword}' failed: {exc}", file=sys.stderr)
    return results


def normalize_usajobs(job: dict) -> dict:
    title = job.get("PositionTitle", "")
    org = job.get("OrganizationName", "Unknown agency")
    location = ""
    locations = job.get("PositionLocation", [])
    if locations:
        location = locations[0].get("LocationName", "")
    url = job.get("PositionURI", "#")
    summary = job.get("UserArea", {}).get("Details", {}).get("JobSummary", "")
    job_id = job.get("PositionID", hashlib.sha1(url.encode()).hexdigest())

    return {
        "id": f"usajobs:{job_id}",
        "source": "USAJobs",
        "title": title,
        "company": org,
        "location": location,
        "url": url,
        "search_text": f"{title} {summary}",
    }


# ---------------------------------------------------------------------------
# Source 2: public GitHub tracker READMEs (openly published, no key needed)
# ---------------------------------------------------------------------------

ROW_RE = re.compile(r"^\|(.+)\|\s*$")
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def parse_markdown_table_rows(markdown_text: str):
    for line in markdown_text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        # Skip header/separator rows
        if len(cells) < 4 or set("".join(cells)) <= set("-: "):
            continue
        yield cells


def first_link(cell: str) -> str:
    m = LINK_RE.search(cell)
    return m.group(2) if m else ""


def strip_markdown(cell: str) -> str:
    return re.sub(r"[\[\]!*_>#`]", "", re.sub(r"\([^)]+\)", "", cell)).strip()


def fetch_github_trackers() -> list:
    results = []
    for name, url in GITHUB_SOURCES:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"Warning: failed to fetch {name}: {exc}", file=sys.stderr)
            continue

        for cells in parse_markdown_table_rows(resp.text):
            if len(cells) < 4:
                continue
            company_cell, role_cell, location_cell, application_cell = cells[:4]
            company = strip_markdown(company_cell) or "Unknown company"
            role = strip_markdown(role_cell)
            location = strip_markdown(location_cell)
            link = first_link(application_cell) or first_link(company_cell)
            if not role or not link:
                continue

            job_id = "gh:" + hashlib.sha1(f"{company}|{role}|{link}".encode()).hexdigest()
            results.append({
                "id": job_id,
                "source": name,
                "title": role,
                "company": company,
                "location": location,
                "url": link,
                "search_text": f"{company} {role}",
            })
    return results


# ---------------------------------------------------------------------------


def collect_new_matches() -> list:
    seen_ids = load_seen_ids()

    all_jobs = []
    for job in fetch_usajobs():
        all_jobs.append(normalize_usajobs(job))
    all_jobs.extend(fetch_github_trackers())

    new_matches = []
    for job in all_jobs:
        if job["id"] in seen_ids:
            continue
        if matches_keywords(job["search_text"]):
            new_matches.append(job)
        seen_ids.add(job["id"])  # mark seen either way so we don't re-check it forever

    save_seen_ids(seen_ids)
    return new_matches


def build_email_body(jobs: list) -> str:
    lines = [f"<h2>New chemistry-related internships ({len(jobs)})</h2>"]
    for job in jobs:
        lines.append(
            f"<p><b><a href='{job['url']}'>{job['title']}</a></b><br>"
            f"{job['company']} — {job['location']}<br>"
            f"<small>Source: {job['source']}</small></p><hr>"
        )
    return "\n".join(lines)


def send_email(jobs: list) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{len(jobs)} new chemistry internship(s) — Summer 2027"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL

    html = build_email_body(jobs)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECIPIENT_EMAIL], msg.as_string())


def is_eight_am_eastern() -> bool:
    """GitHub Actions cron can't express DST directly, so the workflow fires
    twice (covering EST and EDT) and this check makes sure we only actually
    run — and only send one email — during the correct hour in New York."""
    now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    return now_et.hour == 8


def main() -> None:
    if os.environ.get("SKIP_TIME_CHECK", "false").lower() != "true":
        if not is_eight_am_eastern():
            print("Not currently 8am Eastern — skipping this run.")
            return

    new_matches = collect_new_matches()

    if not new_matches:
        print("No new matching internships found today.")
        return

    send_email(new_matches)
    print(f"Sent email with {len(new_matches)} new internship(s).")


if __name__ == "__main__":
    main()
