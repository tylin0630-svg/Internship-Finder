"""
Chemistry Internship Daily Digest
----------------------------------
Reads two openly-published sources and emails new matches over plain SMTP:

  1. SimplifyJobs' structured `listings.json` (same approach as
     github.com/zohaib642/internshipTracker) — mostly SWE/quant internships,
     included as a supplemental source.
  2. BioSpace's public RSS feeds (jobs.biospace.com) — a real, openly
     published RSS "Subscribe" feature on their job board, filtered to the
     Chemistry and Chemical Engineer categories. This is where most of the
     actual chemistry-relevant matches will come from.

Only one secret is required: your email app password. The email addresses
below are yours, not sensitive, so they're just constants you edit directly
instead of GitHub secrets.
"""

import os
import re
import sys
import json
import hashlib
import smtplib
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Edit these directly — they're your own info, not secret.
# ---------------------------------------------------------------------------

SENDER_EMAIL = "tylin0630@icloud.com"
RECIPIENT_EMAIL = "tylin0630@icloud.com"   # change if you want it sent elsewhere

SMTP_HOST = "smtp.mail.me.com"   # iCloud's SMTP server
SMTP_PORT = 587

# The one secret this project needs (see README for how to get it).
SENDER_APP_PASSWORD = os.environ["SENDER_APP_PASSWORD"]

# A posting must contain at least one of these words in its title or
# company name to count as a match.
MAJOR_KEYWORDS = [
    "chemistry", "chemical engineering", "biochemistry", "chemist",
    "analytical chemistry", "materials science", "materials chemistry",
]

# Which SimplifyJobs term(s) count as a match. Their data uses the exact
# string "Summer 2027", so this is far more reliable than text-searching
# for "2027" in a description.
TARGET_TERMS = {"Summer 2027"}

# Fallback year filter for sources with no explicit season field (e.g.
# BioSpace). Set to "" to disable this check entirely for those sources.
REQUIRE_YEAR = "2027"

# SimplifyJobs' structured internship data (openly published, no key needed).
LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/"
    "Summer2027-Internships/dev/.github/scripts/listings.json"
)

# BioSpace's own public RSS feeds (confirmed via the "Subscribe" link on
# their job-category browse pages — a real, sanctioned feed, not scraping).
# Discipline codes: 85 = Chemistry, 27 = Chemical Engineer. Add more by
# browsing https://jobs.biospace.com/jobs/<category>/ and copying the
# "Discipline=" number from that page's own Subscribe link.
BIOSPACE_RSS_FEEDS = [
    ("BioSpace: Chemistry", "https://jobs.biospace.com/jobsrss/?Discipline=85&countrycode=US"),
    ("BioSpace: Chemical Engineer", "https://jobs.biospace.com/jobsrss/?Discipline=27&countrycode=US"),
]

# BioSpace posts mostly full-time roles, so unlike SimplifyJobs (which has an
# exact season field) we filter on these words appearing in the title/summary.
INTERN_KEYWORDS = ["intern", "co-op", "coop", "internship"]

STATE_FILE = Path(__file__).parent / "data" / "seen_jobs.json"

# ---------------------------------------------------------------------------


def load_seen_ids() -> set:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen_ids(ids: set) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(sorted(ids), indent=2))


def matches_criteria(entry: dict) -> bool:
    if not entry.get("active", False) or not entry.get("is_visible", True):
        return False

    terms = entry.get("terms", [])
    if terms:
        # Source tags an explicit season (e.g. SimplifyJobs) — use it directly.
        if TARGET_TERMS and not (TARGET_TERMS & set(terms)):
            return False
    elif REQUIRE_YEAR:
        # Source has no season field (e.g. BioSpace) — fall back to a text
        # search for the year in the title/company text.
        combined = f"{entry.get('title', '')} {entry.get('company_name', '')}".lower()
        if REQUIRE_YEAR not in combined:
            return False

    if entry.get("prefiltered"):
        return True  # source category (e.g. BioSpace "Chemistry") already guarantees relevance

    text = f"{entry.get('title', '')} {entry.get('company_name', '')}".lower()
    return any(keyword in text for keyword in MAJOR_KEYWORDS)


def fetch_listings() -> list:
    resp = requests.get(LISTINGS_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_biospace_rss() -> list:
    """Fetch BioSpace's own public RSS feeds and normalize entries into the
    same shape as SimplifyJobs entries (id/title/company_name/locations/url/
    terms/active/is_visible) so matches_criteria() works on both."""
    normalized = []

    for feed_name, feed_url in BIOSPACE_RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=30)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except (requests.RequestException, ET.ParseError) as exc:
            print(f"Warning: failed to fetch/parse {feed_name}: {exc}", file=sys.stderr)
            continue

        for item in root.findall(".//item"):
            raw_title = (item.findtext("title") or "").strip()
            description = (item.findtext("description") or "").strip()
            link = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link).strip()

            # BioSpace RSS titles are formatted "Company: Role"
            if ": " in raw_title:
                company, role = raw_title.split(": ", 1)
            else:
                company, role = "Unknown company", raw_title

            text = f"{role} {description}".lower()
            if not any(kw in text for kw in INTERN_KEYWORDS):
                continue  # not an internship/co-op posting, skip early

            entry_id = "biospace:" + hashlib.sha1(guid.encode()).hexdigest()
            normalized.append({
                "id": entry_id,
                "source_label": feed_name,
                "title": role,
                "company_name": company,
                "locations": [description.strip().splitlines()[-1].strip()] if description else [],
                "url": link,
                "terms": [],       # BioSpace doesn't tag a season explicitly
                "active": True,
                "is_visible": True,
                "prefiltered": True,  # already restricted to a chemistry/chem-eng category
            })

    return normalized


def collect_new_matches() -> list:
    seen_ids = load_seen_ids()
    all_entries = []

    try:
        all_entries.extend(fetch_listings())
    except requests.RequestException as exc:
        print(f"Failed to fetch listings.json: {exc}", file=sys.stderr)

    all_entries.extend(fetch_biospace_rss())

    new_matches = []
    for entry in all_entries:
        entry_id = entry.get("id")
        if not entry_id or entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)
        if matches_criteria(entry):
            new_matches.append(entry)

    save_seen_ids(seen_ids)
    return new_matches


def build_email_body(entries: list) -> str:
    lines = [f"<h2>New chemistry-related internships ({len(entries)})</h2>"]
    for entry in entries:
        title = entry.get("title", "Untitled role")
        company = entry.get("company_name", "Unknown company")
        location = ", ".join(entry.get("locations", [])) or "Unknown location"
        url = entry.get("url", "#")
        source_label = entry.get("source_label", "SimplifyJobs")
        lines.append(
            f"<p><b><a href='{url}'>{title}</a></b><br>{company} — {location}<br>"
            f"<small>Source: {source_label}</small></p><hr>"
        )
    return "\n".join(lines)


def send_email(entries: list) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{len(entries)} new chemistry internship(s) — Summer 2027"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(build_email_body(entries), "html"))

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
