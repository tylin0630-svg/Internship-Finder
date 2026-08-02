# Chemistry Internship Daily Digest

Runs every morning at 8 AM Eastern via GitHub Actions and emails you any new
chemistry-related Summer 2027 internship postings. Only **one secret** is
needed — your email app password — same approach as
[zohaib642/internshipTracker](https://github.com/zohaib642/internshipTracker),
which this is modeled on.

## Where the data comes from

**Automated (built into the script):**

1. **[BioSpace](https://jobs.biospace.com)** — their job board runs on Madgex
   software, which publishes real, sanctioned RSS feeds (there's a literal
   "Subscribe" link on every category page). The script reads their
   **Chemistry** and **Chemical Engineer** category feeds directly — this is
   the source most likely to turn up genuinely relevant postings.
2. **[SimplifyJobs' `listings.json`](https://github.com/SimplifyJobs/Summer2027-Internships)** —
   the structured data file behind their popular internship tracker.
   Openly published, updated daily. Mostly SWE/quant/hardware roles, so
   don't expect much here — included as a supplemental source since it's
   free, reliable, and zero-setup.

**Checked but not automatable** (so you'll want to check these yourself):

| Site | Why it's not automated |
|---|---|
| [ACS Chemistry Careers](https://chemistryjobs.acs.org/jobs/) | Site actively blocks automated/bot requests |
| [Chemistry World Jobs](https://jobs.chemistryworld.com) (RSC) | Same bot-detection issue, inconsistent access |
| [ChemistryJobs.com](https://www.chemistryjobs.com) | Requires JavaScript to render listings — can't run headless in GitHub Actions |
| [Prosple](https://prosple.com/chemistry-internships-usa) | Same — JS-rendered content |
| Indeed / LinkedIn / Handshake | No public feed; these platforms don't offer open APIs for this |

**Best manual option:** ACS Chemistry Careers has its own built-in "email me
new opportunities for this search" feature — it's genuinely the most
relevant chemistry-specific board out there. Set up a saved search there
yourself as a complement to this digest; this project just can't pull from
it programmatically.

Already-emailed postings are tracked in `data/seen_jobs.json`. The **first
run** will email you a full baseline of everything currently open and
matching; after that you'll only get genuinely new postings.

## One-time setup (~5 min)

### 1. Edit the email addresses in `find_internships.py`

Near the top of the file:
```python
SENDER_EMAIL = "tylin0630@icloud.com"
RECIPIENT_EMAIL = "tylin0630@icloud.com"   # change if you want it sent elsewhere
```
These aren't secret (they're just your own address), so they're plain
constants in the code rather than GitHub secrets — one less thing to set up.

### 2. Get an app-specific password for your iCloud email

1. Go to https://appleid.apple.com → Sign-In and Security → App-Specific Passwords.
2. Generate one (label it e.g. "internship-bot").
3. Copy it — you won't be able to view it again.

### 3. Create the repo and push

```bash
cd internship-alert-bot
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

### 4. Add the one secret

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | Value |
|---|---|
| `SENDER_APP_PASSWORD` | the app-specific password from step 2 |

### 5. Run it

**Actions tab → "Daily Chemistry Internship Digest" → Run workflow** to test
immediately (this sends the full baseline digest). After that it runs
automatically every day.

## Customizing what counts as a match

Edit these near the top of `find_internships.py`:
- `MAJOR_KEYWORDS` — words a SimplifyJobs posting's title/company must contain at least one of.
- `TARGET_TERMS` — which SimplifyJobs season term(s) to match (e.g. add `"Summer 2028"` later).
- `REQUIRE_YEAR` — fallback year filter for BioSpace postings (which don't tag a season explicitly).
- `BIOSPACE_RSS_FEEDS` — add more BioSpace categories by browsing
  `https://jobs.biospace.com/jobs/<category>/` and copying the `Discipline=`
  number from that page's own "Subscribe" link at the bottom.
- `INTERN_KEYWORDS` — words that mark a BioSpace posting as an internship/co-op.

## Testing locally

```bash
pip install -r requirements.txt
export SENDER_APP_PASSWORD=...
export SKIP_TIME_CHECK=true   # bypass the 8am-Eastern check for testing
python find_internships.py
```
