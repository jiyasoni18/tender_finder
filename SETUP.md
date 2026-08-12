# Setup & Run Guide

A plain, step-by-step guide — no prior experience assumed.

---

## Part 1 — Get it running on your computer

### 1. Install Python 3.10+
Check what you have:
```bash
python3 --version
```
If it prints 3.10 or higher, you're good. Otherwise install from
https://www.python.org/downloads/ (tick "Add Python to PATH" on Windows).

### 2. Get the code onto your machine
Either clone it from GitHub (once it's pushed — see Part 3):
```bash
git clone https://github.com/jiyasoni18/tender_finder
cd tender_finder
git checkout claude/doc-processing-pipeline-gl1i3f
```
…or unzip the `tender_finder.tar.gz` bundle I sent you and `cd` into it.

### 3. Create a virtual environment (keeps deps tidy)
```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 4. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium       # only needed for real IREPS/GeM scraping
```

### 5. Run the offline demo (no config needed)
```bash
python3 main.py
```
You'll see tenders flow through: some PASS → `completed/`, some REJECT →
`rejected/` (with a `.txt` saying why). Press **Ctrl-C** to stop.
This proves the whole pipeline works before you touch a single real website.

---

## Part 2 — Configure it for real

Everything you tune is in **`config.py`**. Open it in any text editor.

### A. Set your value & date ranges (Worker 2)
Find the `RangeRules` block near the top and edit the numbers:
```python
class RangeRules:
    min_value = 100_000        # keep tenders worth AT LEAST this many rupees
    max_value = 50_000_000     # ...and AT MOST this. Use None to disable a bound.

    closing_from = date.today()  # ignore tenders that already closed
    closing_to   = None          # or set date(2026, 12, 31) for an upper limit
```
- Want "only tenders between ₹5 lakh and ₹2 crore"? →
  `min_value = 500_000`, `max_value = 20_000_000`.
- Want "only tenders closing in the next 30 days"? →
  `closing_from = date.today()`, `closing_to = date.today() + timedelta(days=30)`
  (add `from datetime import timedelta` at the top if needed).

### B. Turn on the real sites
In the `SITES` list, flip `enabled`, and set the demo off:
```python
ENABLE_MOCK_SITE=false   # in your .env
ENABLE_IREPS=true
ENABLE_GEM=true
```
Then fill in the scraping logic in `sites/ireps.py` / `sites/gem.py`
(the three methods `login`, `find_new_tenders`, `fetch_pdf` — each has TODO
notes). See "Filling in a real site" below.

### C. Put your secrets in `.env`
```bash
cp .env.example .env
```
Edit `.env` and fill in your portal logins and Lark details. **Never commit
this file** — it's already git-ignored.

### D. Point it at Lark (Worker 3)
Pick a mode in `.env` → `LARK_MODE`:

- **`webhook` (easiest, 2 minutes):** In your Lark group → Settings → Bots →
  Add "Custom Bot" → copy the webhook URL into `LARK_WEBHOOK_URL`. Done. It
  posts a card per tender (no file attach).

- **`bot` (full app, uploads the PDF):** In the Lark Developer Console
  (https://open.larksuite.com) → Create App → add bot → give it scopes
  `im:message` and `im:resource` → publish → add the bot to your target group.
  Copy App ID/Secret to `LARK_APP_ID` / `LARK_APP_SECRET`, and the group's
  chat id (`oc_...`) to `LARK_RECEIVE_ID`. This is the mode you "publish as a
  tool in Lark."
  *(Using Feishu instead of global Lark? Set `LARK_API_BASE=https://open.feishu.cn`.)*

### E. Load the env and run
```bash
set -a; source .env; set +a     # Windows: use `python-dotenv` or set vars manually
python3 main.py
```
Leave it running — it polls forever. Logs go to `logs/app.log`.

---

## Part 3 — How to push the code to GitHub

### Option 1 — Let Claude push it (recommended)
The push is blocked only because the **Claude GitHub App has read-only access**
to `tender_finder`. Grant it write access once:
1. Go to https://github.com/settings/installations
2. Open the **Claude** (or "Claude Code") app → **Repository access**
3. Make sure `tender_finder` is selected with **Read and write** for Contents.
4. Tell Claude "try pushing again" — it will push the ready commit.

### Option 2 — Push it yourself from your machine
If you have the code locally (cloned or unzipped from the bundle):
```bash
cd tender_finder
git add -A
git commit -m "Add concurrent tender pipeline"     # skip if already committed
git push -u origin claude/doc-processing-pipeline-gl1i3f
```
If it asks for a password, use a **Personal Access Token** (GitHub →
Settings → Developer settings → Personal access tokens → generate one with
`repo` scope) as the password.

To open a Pull Request afterward: GitHub will show a "Compare & pull request"
button, or go to the repo → Pull requests → New.

---

## Filling in a real site (when you're ready)

Open `sites/gem.py` or `sites/ireps.py`. You only implement three methods; the
rest of the pipeline is done and won't change:

```python
def login(self):                     # log in with self.config.username / .password
def find_new_tenders(self):          # return a list[Listing] from the results page
def fetch_pdf(self, listing, dest):  # download the tender PDF to `dest`, return path
```

Tip: read `value` and `closing_date` straight off the results page into the
`Listing` — it's far more reliable than digging them out of the PDF later.
Both files have Playwright examples in comments showing exactly the shape.

If you paste me the HTML of the logged-in search-results page (or a screenshot
of the page structure), I'll write the real selectors for you.
