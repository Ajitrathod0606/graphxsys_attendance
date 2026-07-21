# Time & Attendance Dashboard

A Python tool that pulls time-and-attendance data from SQL Server (via a stored
procedure), generates AI-written management insights with Azure OpenAI, and
produces a single, self-contained **interactive HTML dashboard** you can open in
any browser — no server required.

---

## Folder structure

```
Timesheet-9/
├── generate_dashboard.py     # ★ Main entry point — builds the HTML dashboard
├── main.py                   # CLI helper — prints a data preview + insights to the console
├── Timesheet-YYYY-MM-DD.html # Generated output (dated with the run date, e.g. Timesheet-2026-07-21.html)
├── requirements.txt          # Python dependencies
├── .env                      # Secrets: DB connection + Azure OpenAI keys (do NOT share)
├── .gitignore
├── README.md                 # This file
└── src/
    ├── data_loaded.py        # DataLoader — runs the stored proc, returns JSON / DataFrame
    └── ai_insights.py        # AIInsights — builds the prompt and calls Azure OpenAI
```

> `.venv/` and `__pycache__/` are ignored by git and are not part of the source.

---

## How it works

```
                 generate_dashboard.py  (orchestrator)
                          │
        ┌─────────────────┼──────────────────────────┐
        ▼                 ▼                           ▼
 src/data_loaded.py   src/ai_insights.py        HTML_TEMPLATE
 DataLoader           AIInsights                 (in generate_dashboard.py)
        │                 │                           │
        ▼                 ▼                           ▼
 SQL Server SP      Azure OpenAI            Timesheet-YYYY-MM-DD.html
 (all records       (insights for the       (data + insights injected,
  up to today)       latest month only)       opens in the browser)
```

1. **Fetch** — `DataLoader.fetch_attendance_json()` executes the stored procedure
   `MM_TS_TimeAttendance_AI_TEST_v1` and returns the result as JSON.
2. **Analyse** — the latest month of data is passed to `AIInsights`, which asks
   Azure OpenAI for a management briefing (five fixed sections).
3. **Render** — the full dataset and the insights are injected into `HTML_TEMPLATE`
   and written to a dated file `Timesheet-YYYY-MM-DD.html`, which then opens
   automatically.

The dashboard is **fully client-side**: all filtering, charting, sorting and
Excel/CSV export happen in the browser against data embedded in the file.

---

## Setup

### 1. Prerequisites
- Python 3.11+
- Microsoft **ODBC Driver for SQL Server** (used by `pyodbc`)
- Network access to the SQL Server and the Azure OpenAI endpoint

### 2. Install dependencies
```bash
python -m venv .venv
.venv\Scripts\activate         # Windows (PowerShell/CMD)
# source .venv/bin/activate    # macOS/Linux
pip install -r requirements.txt
```

### 3. Configure `.env`
Create a `.env` file in the project root with these keys:

```ini
# --- SQL Server ---
SQL_DRIVER={ODBC Driver 17 for SQL Server}
SQL_SERVER=your-server-host
SQL_NAME=your-database-name
SQL_USERNAME=your-username
SQL_PASSWORD=your-password

# --- Azure OpenAI ---
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/...
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
AZURE_OPENAI_KEY=your-api-key
```

> ⚠️ **Security:** `.env` contains live credentials. It should never be committed
> or shared. If it has been committed previously, rotate the exposed secrets and
> add `.env` to `.gitignore`.

---

## Usage

### Generate the dashboard
```bash
python generate_dashboard.py
```
This fetches all data up to today, generates AI insights for the latest month,
writes a dated file `Timesheet-YYYY-MM-DD.html` (the run date is appended
automatically), and opens it in your default browser.

### Command-line options
| Flag | Default | Description |
|------|---------|-------------|
| `--clid` | `9` | Client ID |
| `--user-id` | `16199` | User ID |
| `--type` | `1` | Report type (`1` or `2`) |
| `--output` | `Timesheet.html` | Output HTML base name; the run date is appended → `Timesheet-YYYY-MM-DD.html` |
| `--no-ai` | off | Skip AI insight generation (fastest run) |
| `--ai-timeout` | `90` | Max seconds to wait for AI before skipping |
| `--no-open` | off | Do not auto-open the browser afterwards |

Examples:
```bash
python generate_dashboard.py --no-ai                 # fastest, data only
python generate_dashboard.py --clid 9 --type 2       # different report type
python generate_dashboard.py --output Report.html    # custom base -> Report-YYYY-MM-DD.html
```

### Console preview (optional)
```bash
python main.py
```
Prints a table preview and AI insights to the terminal (no HTML output).

---

## The dashboard

**Filters** (apply across every tab): **Date range**, **Location**, **Employee**.
Quick presets: *Latest day* (default), This month, Last month, Last 30 / 7 days,
All time. The active range is shown as a chip next to the title.

- The date picker is bounded to the **actual data range** — days with no data
  (including any date after the latest record) are greyed out and can't be picked.
- The **Location** and **Employee** dropdowns are **date-aware**: they list only
  the values present within the currently selected date range. Changing the date
  refreshes the options; a selection that's no longer in range falls back to "All".

**Tabs:**
- **Overview** — KPI tiles (records, employees, locations, on-time %, late %,
  auto punch-outs, average hours) plus charts: daily trend, punctuality mix, and
  top locations / employees by late check-ins.
- **Attendance Log** — the full detail table (all rows, sortable), with
  Excel / CSV export.
- **Late Insights** — employees with >3 late check-ins/outs in a month, and 3+
  consecutive late days.
- **AI Insights** — the Azure OpenAI briefing for the latest month, shown as
  categorized cards (Punctuality, Locations, People, Operational Risk, Actions).

---

## Data shape

Each record returned by the stored procedure has these fields:

| Field | Example | Notes |
|-------|---------|-------|
| `Date` | `01/07/26` | `dd/mm/yy` |
| `Location` | `70 Westchester Square` | Store/location name — drives the filter dropdown, KPI count, and charts |
| `Address` | `1110 Pennsylvania Ave` | Street address — shown in the Attendance Log table |
| `Employee` | `Tayyab Tahir` | |
| `Scheduled Time In` | `10 AM EST` | |
| `Time In` | `10:45AM` | |
| `Time In Variance` | `Late` | `OnTime` / `Late` / `Early` |
| `Scheduled Time Out` | `8:00 PM EST` | |
| `Time Out` | `7:01PM` | |
| `Time Out Variance` | `Early` | `OnTime` / `Late` / `Early` / `AutoPunchout` |
| `Total Hrs` | `8:16` | `h:mm` |

---

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| Stuck on "Fetching ALL data…" for a long time | The stored proc builds a per-day date spine; an open-ended `tdate` (e.g. `9999/12/31`) makes it iterate thousands of years. `get_data()` caps `tdate` at **today**. A 180s query timeout in `data_loaded.py` prevents infinite hangs. |
| AI step slow or hangs | The Azure client has a 45s timeout + 1 retry, and generation runs under a bounded daemon thread (`--ai-timeout`, default 90s). Use `--no-ai` to skip it entirely. |
| AI tab shows a timeout/error note | Check the `AZURE_OPENAI_*` values in `.env`. The dashboard still generates fully with all data. |
| Browser didn't open | Run with the file path shown in the console, or omit `--no-open`. Open `attendance_dashboard.html` manually. |
| `pyodbc` connection error | Verify the ODBC driver name in `SQL_DRIVER` matches an installed driver. |

---

## Notes
- The generated `Timesheet-YYYY-MM-DD.html` is a **generated artifact**. A new
  file is produced per run date (re-running on the same day overwrites it); treat
  the `.py` files as the source of truth.
- The dashboard loads Bootstrap, Flatpickr, Chart.js and SheetJS from CDNs, so an
  internet connection is needed to view it with full styling and charts.
