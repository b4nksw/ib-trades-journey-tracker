# IB Trades Journey Tracker

A macOS service that runs every weekday at 17:00, pulls your Interactive Brokers trade history via Flex Query, and generates per-stock markdown journals with adjusted average cost tracking.

## How it works

```
IB Flex Query API ──► flex_import.py ──► trades.db (SQLite)
IB Gateway (live)  ──► sync.py        ──►    │
                                             ▼
                                       calculate.py
                                             │
                                             ▼
                                       export.py ──► journal/TSLA.md
                                                     journal/portfolio_summary.md
```

- **Flex Query** supplies historical trade + dividend data (idempotent, deduped by `ib_exec_id`)
- **IB Gateway** supplies live market values and IB's own average cost (optional — the sync still runs if Gateway is unreachable)
- **Adjusted avg cost** tracks your real capital at risk: on a sell it is recalculated as `(qty × adj − sell_qty × sell_price) / (qty − sell_qty)`, which can go negative once a position has paid for itself

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | `python3 --version` |
| IB account | Paper or live |
| IB Gateway or TWS | For live market values (optional) |
| macOS | The scheduler uses launchd |

---

## One-time setup

### 1. Clone and create the virtual environment

```bash
git clone <repo-url>
cd ib-trades-journey-tracker
python3 -m venv venv
source venv/bin/activate
pip install ib_insync requests jinja2
```

### 2. Create a Flex Query in IB Portal

The Flex Query is how the script pulls your trade history without needing a live connection.

1. Log in to **IB Client Portal** → **Reports** → **Flex Queries**
2. Click **Create** → choose **Activity Flex Query**
3. Give it a name (e.g. `TradeJournal`)
4. Under **Sections**, add:
   - **Trades** — include all fields, or at minimum: `Symbol`, `Buy/Sell`, `Quantity`, `Trade Price`, `IB Commission`, `Date/Time`, `Exchange`, `Trade ID`
   - **Cash Transactions** — set Type filter to **Dividends** only; include: `Symbol`, `Amount`, `Date/Time`, `Settle Date`
5. **Date Range**: set to **Last Business Day** (the daily cron fetches incrementally; the DB deduplicates)
6. **Format**: XML
7. Save the query — IB will show you a **Query ID** (a 7-digit number)

### 3. Get your Flex Token

The Flex Token is a long-lived API key that authorises the script to download your reports.

1. In Client Portal → **Reports** → **Flex Queries** → click **Manage** (top right)
2. Click **Generate Token** (or copy the existing one)
3. Copy the token — it looks like a long numeric string

### 4. Set up your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials:

```ini
FLEX_TOKEN=your_token_here
FLEX_QUERY_ID=your_query_id_here

# IB Gateway settings — only needed for live market values
IB_HOST=127.0.0.1
IB_PORT=4001    # 4001 = live, 4002 = paper
IB_CLIENT_ID=1
```

`.env` is in `.gitignore` — your credentials will never be committed.

### 5. (Optional) Configure IB Gateway for live positions

IB Gateway provides real-time market values and IB's own average cost. The sync will run without it, but market value and unrealized P&L fields will be empty.

1. Download and install **IB Gateway** (not TWS — Gateway is headless-friendly)
2. Launch Gateway, log in, and go to **Configure → Settings → API → Settings**
3. Enable **Socket Clients** and set port to `4001` (live) or `4002` (paper)
4. Enable **Read-Only API** (the script never places orders)
5. Add `127.0.0.1` to the trusted IP list
6. Leave Gateway running when the cron fires at 17:00

### 6. Fix the plist path and install the launchd job

The plist file contains a hardcoded path. Update it to match where you cloned this repo:

```bash
# Replace the hardcoded path in the plist with your actual repo location
REPO=$(pwd)
OLD_PATH=$(grep -o '/.*run\.sh' com.ib-tracker.plist | sed 's|/run\.sh||')
sed -i '' "s|$OLD_PATH|$REPO|g" com.ib-tracker.plist
```

Then install it:

```bash
cp com.ib-tracker.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ib-tracker.plist
```

The job will now fire automatically at **17:00 Monday–Friday**.

---

## Managing the cron job

```bash
# Check whether the job is loaded
launchctl list | grep ib-tracker

# Fire it immediately (useful after setup — does not affect the 17:00 schedule)
launchctl start com.ib-tracker

# Disable the schedule (stops future runs, does not remove the plist)
launchctl unload ~/Library/LaunchAgents/com.ib-tracker.plist

# Re-enable the schedule
launchctl load ~/Library/LaunchAgents/com.ib-tracker.plist

# Remove the job entirely
launchctl unload ~/Library/LaunchAgents/com.ib-tracker.plist
rm ~/Library/LaunchAgents/com.ib-tracker.plist
```

---

## Running manually

```bash
source venv/bin/activate
python main.py
```

Watch the output in real time:

```bash
tail -f logs/sync.log
```

---

## Backfilling missed days

If the service was down and you missed several trading days, temporarily switch your Flex Query's date range to **Last N Calendar Days** (e.g. 7) in IB Portal, then re-run manually. The DB insert is idempotent (`INSERT OR IGNORE` on `ib_exec_id`), so re-importing existing trades is safe. Switch the date range back to **Last Business Day** afterwards.

---

## Output

After a successful run, the `journal/` directory contains:

```
journal/
├── TSLA.md              # per-stock journal with trade log + adj avg cost
├── AAPL.md
└── portfolio_summary.md # portfolio health snapshot
```

`journal/` is in `.gitignore`. The markdown files are regenerated on every run from the DB.

---

## Logs

```
logs/sync.log    # appended on every run; rotated manually if needed
```

A healthy run ends with a line like:

```
2026-04-27 17:00:12 INFO Done. Portfolio: 72.3% invested.
```

---

## Project structure

```
.
├── main.py          # entry point: orchestrates import → compute → export
├── config.py        # loads settings from .env via python-dotenv
├── flex_import.py   # Flex Query API client + XML parser
├── sync.py          # IB Gateway connection (live positions + account summary)
├── db.py            # SQLite schema and all DB helpers
├── calculate.py     # adjusted avg cost and P&L formulas
├── export.py        # renders Jinja2 templates to journal/*.md
├── run.sh           # shell wrapper called by launchd
├── com.ib-tracker.plist  # launchd job definition
├── templates/       # Jinja2 templates for markdown output
├── journal/         # generated output (gitignored)
├── logs/            # sync.log (gitignored)
└── trades.db        # SQLite database (gitignored)
```

---

## Adjusted average cost explained

Standard brokers reset average cost on every buy. This tracker uses a different formula that treats sells as returning capital rather than resetting the basis:

| Event | Formula |
|---|---|
| Buy | `adj = (prev_qty × prev_adj + qty × price) / new_qty` |
| Sell | `adj = (prev_qty × prev_adj − qty × price) / (prev_qty − qty)` |

Once cumulative sell proceeds exceed your total buy cost, `adj_avg_cost` goes **negative** — meaning the position is effectively free. This is the number that tells you your true remaining risk.
