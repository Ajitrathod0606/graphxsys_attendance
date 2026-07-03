# generate_dashboard.py
import os
import re
import json
import time
import argparse
import datetime
import threading
import webbrowser
import pandas as pd
from html import escape as _escape
from src.data_loaded import DataLoader
from src.ai_insights import generate_insights

def generate_insights_with_timeout(ai_df, timeout):
    """Run AI insight generation in a daemon thread bounded by `timeout` seconds.

    The Azure OpenAI call can hang if the endpoint is unreachable/misconfigured.
    Running it in a daemon thread means the dashboard is always produced within
    `timeout`, and the interpreter can still exit even if the call is stuck.
    """
    box = {}
    def _work():
        try:
            box['value'] = generate_insights(ai_df)
        except Exception as e:  # noqa: BLE001
            box['error'] = str(e)
    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return (f"- AI insights timed out after {timeout}s and were skipped so the "
                f"dashboard could load. Check the Azure OpenAI settings in your .env, "
                f"or run with --no-ai to skip this step.")
    if 'error' in box:
        return f"- AI insights unavailable: {box['error']}"
    return box.get('value', "- No AI insights returned.")

def get_data(clid, user_id, type_val):
    """Fetch ALL data up to today.

    NOTE: `tdate` is capped at today's date on purpose. The stored proc appears to
    build a per-day date spine, so an open-ended upper bound like '9999/12/31'
    makes it iterate ~8000 years of empty dates and effectively hang. Today's date
    still returns every real record (including the current day) at normal speed.
    """
    today = datetime.date.today().strftime('%Y/%m/%d')
    loader = DataLoader()
    json_str = loader.fetch_attendance_json(
        type_val=type_val,
        user_id=user_id,
        clid=clid,
        fdate='2020/01/01',
        tdate=today,
        region='',
        district='',
        location='',
        employee=''
    )
    try:
        data = json.loads(json_str)
        print(f"[OK] Retrieved {len(data)} records.")
        return data
    except json.JSONDecodeError:
        print("[ERROR] Invalid JSON returned.")
        return []

def latest_month_slice(df):
    """Return (subset_df, 'Month Year') for the max month-year present in the data.

    AI insights are generated only for the most recent month so the summary stays
    focused and relevant rather than averaging over the whole history.
    """
    if df.empty or 'Date' not in df.columns:
        return df, 'N/A'
    dt = pd.to_datetime(df['Date'], format='%d/%m/%y', errors='coerce')
    valid = dt.notna()
    if not valid.any():
        return df, 'N/A'
    mx = dt[valid].max()
    mask = valid & (dt.dt.year == mx.year) & (dt.dt.month == mx.month)
    label = mx.strftime('%B %Y')
    return df[mask], label

# Section title keyword -> (Font Awesome icon, accent colour). Matched by
# substring so slight wording differences from the model still map correctly.
_AI_SECTION_STYLES = [
    ('summary',     ('fa-chart-pie', '#2a78d6')),
    ('punctual',    ('fa-chart-pie', '#2a78d6')),
    ('location',    ('fa-location-dot', '#4a3aa7')),
    ('people',      ('fa-user-clock', '#d03b3b')),
    ('employee',    ('fa-user-clock', '#d03b3b')),
    ('concern',     ('fa-user-clock', '#d03b3b')),
    ('operational', ('fa-triangle-exclamation', '#e0850f')),
    ('risk',        ('fa-triangle-exclamation', '#e0850f')),
    ('action',      ('fa-list-check', '#0ca30c')),
    ('recommend',   ('fa-list-check', '#0ca30c')),
]

def _ai_section_style(title):
    t = title.lower()
    for kw, style in _AI_SECTION_STYLES:
        if kw in t:
            return style
    return ('fa-lightbulb', '#2a78d6')

def _md_inline(s):
    """Escape HTML, then render **bold** as <strong>."""
    s = _escape(s.strip())
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)

def format_insights(text):
    """Parse the model's sectioned output into styled category cards.

    Expected shape (per the AI task prompt):
        ## Punctuality Summary
        - bullet
        - bullet
        ## Locations to Watch
        ...
    Falls back gracefully to a single card if no headings are present (e.g. an
    error/timeout message or a plain bullet list).
    """
    if not text or not text.strip():
        return '<p class="text-muted">No insights available.</p>'

    sections = []          # list of [title, [bullets]]
    loose = []             # content before the first heading
    current = None

    heading_re = re.compile(r'^\s*(?:#{1,6}\s*(.+?)\s*#*|\*\*(.+?)\*\*)\s*:?\s*$')
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = heading_re.match(line)
        if m and not line.lstrip().startswith(('-', '*', '•')):
            title = (m.group(1) or m.group(2)).strip().rstrip(':')
            current = [title, []]
            sections.append(current)
            continue
        content = line[2:].strip() if line[:2] in ('- ', '* ', '• ') else line.lstrip('•').strip()
        (current[1] if current else loose).append(content)

    def render_section(title, bullets):
        icon, accent = _ai_section_style(title)
        lis = ''.join(f'<li>{_md_inline(b)}</li>' for b in bullets if b)
        return (
            f'<div class="ai-section" style="--ai-accent:{accent}">'
            f'<div class="ai-section-head"><span class="ai-ic"><i class="fas {icon}"></i></span>'
            f'<h3>{_escape(title)}</h3></div>'
            f'<ul class="ai-bullets">{lis or "<li>—</li>"}</ul></div>'
        )

    if not sections:
        return render_section('AI Insights', loose)

    parts = []
    if loose:
        parts.append('<p class="ai-lead">' + ' '.join(_md_inline(x) for x in loose) + '</p>')
    parts.extend(render_section(t, b) for t, b in sections)
    return '\n'.join(parts)

# ---------------------------------------------------------------------------
# HTML template.  Data/insights are injected via distinctive __TOKENS__ using
# str.replace(), so the JavaScript below uses normal single braces and stays
# valid.
# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Attendance Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --page:        #f4f6fa;
            --surface:     #ffffff;
            --ink:         #10151f;
            --ink-soft:    #52596b;
            --ink-muted:   #8b91a1;
            --border:      #e6e9f0;
            --grid:        #eef0f5;
            --brand:       #2a78d6;
            --brand-dark:  #1c5cab;
            --c-ontime:    #0ca30c;
            --c-late:      #d03b3b;
            --c-early:     #2a78d6;
            --c-auto:      #fab219;
            --c-aqua:      #1baf7a;
            --radius:      14px;
            --shadow:      0 1px 3px rgba(16,21,31,.06), 0 8px 24px rgba(16,21,31,.05);
            --shadow-sm:   0 1px 2px rgba(16,21,31,.06);
        }
        * { box-sizing: border-box; }
        body {
            background: var(--page);
            color: var(--ink);
            font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
            margin: 0; padding: 0 0 48px; font-size: 14px;
        }
        .app-header {
            background: linear-gradient(120deg, #1c5cab 0%, #2a78d6 60%, #2f8fe0 100%);
            color: #fff; padding: 20px 28px; box-shadow: var(--shadow-sm);
        }
        .app-header h1 { font-size: 1.35rem; font-weight: 700; margin: 0; letter-spacing: -.2px; }
        .header-range-chip { font-size: .82rem; font-weight: 600; background: rgba(255,255,255,.18); padding: 4px 13px; border-radius: 999px; white-space: nowrap; }
        .app-header .sub { opacity: .85; font-size: .85rem; margin-top: 2px; }
        .app-header .meta { text-align: right; font-size: .78rem; opacity: .9; line-height: 1.5; }
        .wrap { max-width: 1600px; margin: 0 auto; padding: 22px 28px 0; }

        .panel {
            background: var(--surface); border: 1px solid var(--border);
            border-radius: var(--radius); box-shadow: var(--shadow);
        }
        .panel-pad { padding: 18px 20px; }
        .panel-title { font-size: .95rem; font-weight: 700; margin: 0 0 2px; display: flex; align-items: center; gap: 8px; }
        .panel-sub { color: var(--ink-muted); font-size: .78rem; margin: 0 0 14px; }

        /* ---------- Filters ---------- */
        .filters { margin-bottom: 18px; }
        .filters .form-label {
            font-size: .72rem; font-weight: 600; text-transform: uppercase;
            letter-spacing: .04em; color: var(--ink-soft); margin-bottom: 4px;
        }
        .filters .form-control, .filters .form-select { font-size: .85rem; border-color: var(--border); border-radius: 9px; }
        .filters .form-control:focus, .filters .form-select:focus { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(42,120,214,.15); }
        .preset-group { display: flex; flex-wrap: wrap; gap: 6px; }
        .preset-btn {
            font-size: .78rem; padding: 5px 12px; border-radius: 999px;
            border: 1px solid var(--border); background: #fff; color: var(--ink-soft); cursor: pointer; transition: all .12s;
        }
        .preset-btn:hover { border-color: var(--brand); color: var(--brand); }
        .preset-btn.active { background: var(--brand); border-color: var(--brand); color: #fff; }

        /* ---------- Tabs ---------- */
        .tabbar { display: flex; gap: 4px; border-bottom: 2px solid var(--border); margin-bottom: 20px; flex-wrap: wrap; }
        .tab-link {
            border: none; background: none; padding: 11px 20px; font-size: .9rem; font-weight: 600;
            color: var(--ink-soft); cursor: pointer; border-bottom: 3px solid transparent; margin-bottom: -2px;
            display: flex; align-items: center; gap: 8px; transition: color .12s;
        }
        .tab-link:hover { color: var(--brand); }
        .tab-link.active { color: var(--brand); border-bottom-color: var(--brand); }
        .tab-link .chip { font-size: .68rem; background: var(--grid); color: var(--ink-soft); padding: 1px 8px; border-radius: 999px; font-weight: 700; }
        .tab-pane { display: none; }
        .tab-pane.active { display: block; }

        /* ---------- KPI tiles ---------- */
        .kpi-row { display: grid; grid-template-columns: repeat(7, 1fr); gap: 14px; margin-bottom: 20px; }
        @media (max-width: 1200px) { .kpi-row { grid-template-columns: repeat(4, 1fr); } }
        @media (max-width: 640px)  { .kpi-row { grid-template-columns: repeat(2, 1fr); } }
        .kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; box-shadow: var(--shadow-sm); position: relative; overflow: hidden; }
        .kpi .label { font-size: .72rem; color: var(--ink-muted); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
        .kpi .value { font-size: 1.85rem; font-weight: 700; line-height: 1.15; margin-top: 4px; letter-spacing: -.5px; }
        .kpi .foot { font-size: .74rem; color: var(--ink-soft); margin-top: 2px; }
        .kpi .accent { position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
        .kpi.k-total  .accent { background: var(--brand); }
        .kpi.k-emp    .accent { background: var(--c-aqua); }
        .kpi.k-loc    .accent { background: #4a3aa7; }
        .kpi.k-ontime .accent { background: var(--c-ontime); }
        .kpi.k-late   .accent { background: var(--c-late); }
        .kpi.k-auto   .accent { background: var(--c-auto); }
        .kpi.k-hours  .accent { background: var(--ink-soft); }
        .kpi.k-ontime .value { color: var(--c-ontime); }
        .kpi.k-late   .value { color: var(--c-late); }

        /* ---------- Charts ---------- */
        .chart-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 20px; }
        .chart-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        @media (max-width: 992px) { .chart-grid, .chart-grid-2 { grid-template-columns: 1fr; } }
        .chart-box { position: relative; height: 300px; }
        .chart-box.tall { height: 340px; }

        /* ---------- Insight cards ---------- */
        .insight-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media (max-width: 992px) { .insight-grid { grid-template-columns: 1fr; } }
        .insight-head { display: flex; align-items: center; gap: 8px; font-weight: 700; padding: 12px 18px; border-bottom: 1px solid var(--border); font-size: .9rem; }
        .insight-head.warn { color: var(--c-late); }
        .sub-block { padding: 14px 18px; }
        .sub-block h6 { font-size: .82rem; font-weight: 700; color: var(--ink-soft); margin: 0 0 8px; display: flex; align-items: center; gap: 6px; }
        .emp-list { max-height: 260px; overflow-y: auto; margin: 0; padding: 0; list-style: none; }
        .emp-list li { font-size: .82rem; padding: 6px 10px; border-radius: 8px; display: flex; justify-content: space-between; gap: 8px; align-items: center; }
        .emp-list li:nth-child(odd) { background: #fafbfd; }
        .emp-list .tag { font-size: .72rem; color: var(--ink-muted); white-space: nowrap; }
        .pill { font-size: .72rem; font-weight: 700; padding: 2px 9px; border-radius: 999px; }
        .pill.red { background: rgba(208,59,59,.12); color: var(--c-late); }
        .pill.amber { background: rgba(250,178,25,.16); color: #a9720a; }
        .none-note { color: var(--ink-muted); font-size: .82rem; margin: 4px 0 0; }

        /* ---------- Table ---------- */
        .table-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
        .table-wrap { overflow: auto; max-height: 70vh; border: 1px solid var(--border); border-radius: 10px; }
        table.att { width: 100%; border-collapse: separate; border-spacing: 0; font-size: .82rem; }
        table.att thead th {
            position: sticky; top: 0; z-index: 2; background: #f7f9fc; color: var(--ink-soft);
            font-weight: 600; text-transform: uppercase; font-size: .7rem; letter-spacing: .03em;
            padding: 10px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; cursor: pointer; user-select: none;
        }
        table.att thead th:hover { color: var(--brand); }
        table.att thead th i { opacity: .5; margin-left: 4px; }
        table.att tbody td { padding: 9px 12px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
        table.att tbody tr:hover { background: #f7faff; }
        table.att .num { font-variant-numeric: tabular-nums; }
        .badge-v { font-size: .7rem; font-weight: 700; padding: 3px 9px; border-radius: 6px; display: inline-block; }
        .v-ontime { background: rgba(12,163,12,.12); color: #0a7d0a; }
        .v-late   { background: rgba(208,59,59,.12); color: var(--c-late); }
        .v-early  { background: rgba(42,120,214,.12); color: var(--brand); }
        .v-auto   { background: rgba(250,178,25,.18); color: #a9720a; }
        .v-none   { background: #eef0f5; color: var(--ink-muted); }

        /* ---------- AI ---------- */
        .ai-note { background: rgba(42,120,214,.08); border: 1px solid rgba(42,120,214,.2); color: var(--brand-dark); border-radius: 10px; padding: 10px 14px; font-size: .82rem; margin-bottom: 18px; display: flex; align-items: center; gap: 8px; }
        .ai-sections { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; align-items: start; }
        @media (max-width: 900px) { .ai-sections { grid-template-columns: 1fr; } }
        .ai-lead { grid-column: 1 / -1; font-size: .9rem; color: var(--ink-soft); margin: 0; }
        .ai-section { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; background: var(--surface); box-shadow: var(--shadow-sm); }
        .ai-section-head { display: flex; align-items: center; gap: 11px; padding: 13px 16px; border-bottom: 1px solid var(--border); background: linear-gradient(0deg, #fbfcfe, #fff); }
        .ai-section-head .ai-ic { width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center; color: #fff; font-size: .92rem; background: var(--ai-accent, var(--brand)); flex: none; box-shadow: 0 2px 6px rgba(16,21,31,.12); }
        .ai-section-head h3 { font-size: .92rem; font-weight: 700; margin: 0; color: var(--ink); }
        .ai-bullets { list-style: none; margin: 0; padding: 14px 16px 14px 18px; }
        .ai-bullets li { position: relative; padding-left: 18px; margin-bottom: 11px; line-height: 1.55; font-size: .86rem; color: var(--ink-soft); }
        .ai-bullets li:last-child { margin-bottom: 0; }
        .ai-bullets li::before { content: ''; position: absolute; left: 0; top: 7px; width: 7px; height: 7px; border-radius: 50%; background: var(--ai-accent, var(--brand)); }
        .ai-bullets li strong { color: var(--ink); font-weight: 700; }

        footer { text-align: center; color: var(--ink-muted); font-size: .8rem; margin-top: 26px; }
        ::-webkit-scrollbar { width: 9px; height: 9px; }
        ::-webkit-scrollbar-thumb { background: #cfd4de; border-radius: 999px; }
    </style>
</head>
<body>
<div class="app-header">
    <div class="wrap" style="padding-top:0;padding-bottom:0;display:flex;justify-content:space-between;align-items:center;">
        <div>
            <h1 style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;">
                <span><i class="fas fa-clock me-2"></i>Time &amp; Attendance Dashboard</span>
                <span class="header-range-chip"><i class="far fa-calendar-alt me-1"></i><span id="headerRange">All dates</span></span>
            </h1>
        </div>
        <div class="meta">
            <div><i class="far fa-clock me-1"></i>Generated __GENERATED__</div>
        </div>
    </div>
</div>

<div class="wrap">
    <!-- ============ Filters (global) ============ -->
    <div class="panel panel-pad filters">
        <div class="row g-3 align-items-end">
            <div class="col-lg-4 col-md-6">
                <label class="form-label"><i class="far fa-calendar-alt me-1"></i>Date range</label>
                <div class="input-group">
                    <input type="text" id="dateRange" class="form-control" placeholder="All dates" autocomplete="off">
                    <button class="btn btn-outline-secondary" type="button" id="clearRange" title="Clear"><i class="fas fa-times"></i></button>
                </div>
            </div>
            <div class="col-lg-3 col-md-6">
                <label class="form-label"><i class="fas fa-map-marker-alt me-1"></i>Location</label>
                <select class="form-select" id="fLocation"><option value="all">All locations</option></select>
            </div>
            <div class="col-lg-3 col-md-6">
                <label class="form-label"><i class="fas fa-user me-1"></i>Employee name</label>
                <select class="form-select" id="fEmployee"><option value="all">All employees</option></select>
            </div>
            <div class="col-lg-2 col-md-6 d-flex align-items-end">
                <button class="btn btn-outline-secondary w-100" id="resetFilters"><i class="fas fa-rotate-left me-1"></i>Reset</button>
            </div>
        </div>
        <div class="d-flex align-items-center mt-3 pt-3 flex-wrap gap-2" style="border-top:1px solid var(--border);">
            <div class="preset-group" id="presetGroup">
                <button class="preset-btn active" data-preset="latest">Latest day</button>
                <button class="preset-btn" data-preset="month">This month</button>
                <button class="preset-btn" data-preset="lastmonth">Last month</button>
                <button class="preset-btn" data-preset="30">Last 30 days</button>
                <button class="preset-btn" data-preset="7">Last 7 days</button>
                <button class="preset-btn" data-preset="all">All time</button>
            </div>
        </div>
    </div>

    <!-- ============ Tab bar ============ -->
    <div class="tabbar" id="tabbar">
        <button class="tab-link active" data-tab="overview"><i class="fas fa-gauge-high"></i>Overview</button>
        <button class="tab-link" data-tab="log"><i class="fas fa-table-list"></i>Attendance Log <span class="chip" id="logChip">0</span></button>
        <button class="tab-link" data-tab="insights"><i class="fas fa-triangle-exclamation"></i>Late Insights</button>
        <button class="tab-link" data-tab="ai"><i class="fas fa-robot"></i>AI Insights</button>
    </div>

    <!-- ============ TAB: Overview ============ -->
    <div class="tab-pane active" id="tab-overview">
        <div class="kpi-row">
            <div class="kpi k-total"><span class="accent"></span><div class="label">Records</div><div class="value" id="kTotal">0</div><div class="foot">attendance rows</div></div>
            <div class="kpi k-emp"><span class="accent"></span><div class="label">Employees</div><div class="value" id="kEmp">0</div><div class="foot">in selection</div></div>
            <div class="kpi k-loc"><span class="accent"></span><div class="label">Locations</div><div class="value" id="kLoc">0</div><div class="foot">in selection</div></div>
            <div class="kpi k-ontime"><span class="accent"></span><div class="label">On-time in</div><div class="value" id="kOntime">0%</div><div class="foot" id="kOntimeFoot">0 check-ins</div></div>
            <div class="kpi k-late"><span class="accent"></span><div class="label">Late in</div><div class="value" id="kLate">0%</div><div class="foot" id="kLateFoot">0 check-ins</div></div>
            <div class="kpi k-auto"><span class="accent"></span><div class="label">Auto punch-out</div><div class="value" id="kAuto">0</div><div class="foot">unclosed shifts</div></div>
            <div class="kpi k-hours"><span class="accent"></span><div class="label">Avg hours</div><div class="value" id="kHours">0.0</div><div class="foot">per shift</div></div>
        </div>
        <div class="chart-grid">
            <div class="panel panel-pad">
                <div class="panel-title"><i class="fas fa-chart-line" style="color:var(--brand)"></i>Daily attendance trend</div>
                <p class="panel-sub">Records logged vs. late check-ins per day</p>
                <div class="chart-box tall"><canvas id="trendChart"></canvas></div>
            </div>
            <div class="panel panel-pad">
                <div class="panel-title"><i class="fas fa-chart-column" style="color:var(--c-aqua)"></i>Punctuality mix</div>
                <p class="panel-sub">Check-in vs. check-out status</p>
                <div class="chart-box tall"><canvas id="statusChart"></canvas></div>
            </div>
        </div>
        <div class="chart-grid-2">
            <div class="panel panel-pad">
                <div class="panel-title"><i class="fas fa-location-dot" style="color:var(--c-late)"></i>Locations with most late check-ins</div>
                <p class="panel-sub">Top 10 by late check-in count</p>
                <div class="chart-box"><canvas id="locChart"></canvas></div>
            </div>
            <div class="panel panel-pad">
                <div class="panel-title"><i class="fas fa-user-clock" style="color:var(--c-late)"></i>Employees with most late check-ins</div>
                <p class="panel-sub">Top 10 by late check-in count</p>
                <div class="chart-box"><canvas id="empChart"></canvas></div>
            </div>
        </div>
    </div>

    <!-- ============ TAB: Attendance Log ============ -->
    <div class="tab-pane" id="tab-log">
        <div class="panel panel-pad">
            <div class="table-toolbar">
                <div class="panel-title mb-0"><i class="fas fa-table-list" style="color:var(--brand)"></i>Attendance detail</div>
                <div>
                    <button class="btn btn-success btn-sm" id="exportExcel"><i class="fas fa-file-excel me-1"></i>Export Excel</button>
                </div>
            </div>
            <div class="table-wrap">
                <table class="att">
                    <thead>
                        <tr>
                            <th style="cursor:default">#</th>
                            <th data-key="Date">Date <i class="fas fa-sort"></i></th>
                            <th data-key="Employee">Employee <i class="fas fa-sort"></i></th>
                            <th data-key="Location">Location <i class="fas fa-sort"></i></th>
                            <th data-key="Scheduled Time In">Sched In</th>
                            <th data-key="Time In">Time In</th>
                            <th data-key="Time In Variance">In <i class="fas fa-sort"></i></th>
                            <th data-key="Scheduled Time Out">Sched Out</th>
                            <th data-key="Time Out">Time Out</th>
                            <th data-key="Time Out Variance">Out <i class="fas fa-sort"></i></th>
                            <th data-key="Total Hrs">Hours <i class="fas fa-sort"></i></th>
                        </tr>
                    </thead>
                    <tbody id="tableBody"><tr><td colspan="11" class="text-center text-muted py-4">No data</td></tr></tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ============ TAB: Late Insights ============ -->
    <div class="tab-pane" id="tab-insights">
        <div class="insight-grid">
            <div class="panel">
                <div class="insight-head warn"><i class="fas fa-sign-in-alt"></i>Late Check-In patterns</div>
                <div class="sub-block">
                    <h6><i class="far fa-calendar-alt"></i>More than 3 late check-ins in a month</h6>
                    <ul class="emp-list" id="lateInMonth"><li><span class="none-note">None</span></li></ul>
                </div>
                <div class="sub-block" style="border-top:1px solid var(--border)">
                    <h6><i class="fas fa-arrow-right-long"></i>3+ consecutive late check-in days</h6>
                    <ul class="emp-list" id="lateInStreak"><li><span class="none-note">None</span></li></ul>
                </div>
            </div>
            <div class="panel">
                <div class="insight-head warn"><i class="fas fa-sign-out-alt"></i>Late Check-Out patterns</div>
                <div class="sub-block">
                    <h6><i class="far fa-calendar-alt"></i>More than 3 late check-outs in a month</h6>
                    <ul class="emp-list" id="lateOutMonth"><li><span class="none-note">None</span></li></ul>
                </div>
                <div class="sub-block" style="border-top:1px solid var(--border)">
                    <h6><i class="fas fa-arrow-right-long"></i>3+ consecutive late check-out days</h6>
                    <ul class="emp-list" id="lateOutStreak"><li><span class="none-note">None</span></li></ul>
                </div>
            </div>
        </div>
    </div>

    <!-- ============ TAB: AI Insights ============ -->
    <div class="tab-pane" id="tab-ai">
        <div class="panel panel-pad">
            <div class="panel-title"><i class="fas fa-robot" style="color:var(--brand)"></i>AI-generated insights</div>
            <p class="panel-sub">Automated analysis of the most recent month of attendance data</p>
            <div class="ai-note"><i class="fas fa-circle-info"></i>These insights cover <b>&nbsp;__AI_PERIOD__&nbsp;</b> — the latest month available in the database.</div>
            <div class="ai-sections">__INSIGHTS__</div>
        </div>
    </div>

    <footer>Time &amp; Attendance Dashboard &bull; Generated __GENERATED__</footer>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
"use strict";
const RAW = __DATA_JSON__;

const C = { ontime:'#0ca30c', late:'#d03b3b', early:'#2a78d6', auto:'#fab219', brand:'#2a78d6', aqua:'#1baf7a', ink:'#52596b', grid:'#eef0f5', muted:'#8b91a1' };
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

// ---------- helpers ----------
function parseDate(str) {
    if (!str) return null;
    const p = String(str).split('/');
    if (p.length !== 3) return null;
    const d = parseInt(p[0], 10), m = parseInt(p[1], 10) - 1, y = parseInt(p[2], 10) + 2000;
    if (isNaN(d) || isNaN(m) || isNaN(y)) return null;
    return new Date(y, m, d);
}
function fmtDate(dt) {
    if (!dt) return '';
    return String(dt.getDate()).padStart(2, '0') + '/' + String(dt.getMonth() + 1).padStart(2, '0') + '/' + String(dt.getFullYear()).slice(2);
}
function monthLabel(dt) { return MONTHS[dt.getMonth()] + ' ' + dt.getFullYear(); }
function fmtLong(dt) { return dt.getDate() + ' ' + MONTHS[dt.getMonth()] + ' ' + dt.getFullYear(); }
function hoursToNum(h) {
    if (!h) return NaN;
    const p = String(h).split(':');
    if (p.length < 2) return NaN;
    const hh = parseInt(p[0], 10), mm = parseInt(p[1], 10);
    if (isNaN(hh) || isNaN(mm)) return NaN;
    return hh + mm / 60;
}
function dataDateRange() {
    let min = null, max = null;
    RAW.forEach(r => { const d = parseDate(r.Date); if (!d) return; if (!min || d < min) min = d; if (!max || d > max) max = d; });
    return { min, max };
}
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function badge(v) {
    const map = { OnTime:'v-ontime', Late:'v-late', Early:'v-early', AutoPunchout:'v-auto' };
    const txt = { OnTime:'On time', Late:'Late', Early:'Early', AutoPunchout:'Auto' };
    if (!v) return '<span class="badge-v v-none">&mdash;</span>';
    return '<span class="badge-v ' + (map[v] || 'v-none') + '">' + (txt[v] || v) + '</span>';
}

// ---------- state ----------
let picker = null, filtered = [], sortKey = 'Date', sortDir = 1;
const charts = {};

function populateSelect(id, values, allLabel) {
    const sel = document.getElementById(id);
    sel.innerHTML = '<option value="all">' + allLabel + '</option>';
    values.filter(Boolean).sort((a, b) => a.localeCompare(b)).forEach(v => {
        const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o);
    });
}

// ---------- filtering ----------
function getFilters() {
    let start = null, end = null;
    if (picker && picker.selectedDates.length === 2) { start = picker.selectedDates[0]; end = picker.selectedDates[1]; }
    return { start, end, loc: document.getElementById('fLocation').value, emp: document.getElementById('fEmployee').value };
}
function computeFiltered() {
    const f = getFilters();
    const end = f.end ? new Date(f.end.getFullYear(), f.end.getMonth(), f.end.getDate(), 23, 59, 59) : null;
    filtered = RAW.filter(r => {
        const d = parseDate(r.Date);
        if (f.start && (!d || d < f.start)) return false;
        if (end && (!d || d > end)) return false;
        if (f.loc !== 'all' && r.Location !== f.loc) return false;
        if (f.emp !== 'all' && r.Employee !== f.emp) return false;
        return true;
    });
    const hr = document.getElementById('headerRange');
    if (hr) hr.textContent = (f.start && f.end) ? (fmtLong(f.start) + ' – ' + fmtLong(f.end)) : 'All dates';
}

// ---------- KPIs ----------
function updateKpis() {
    const n = filtered.length;
    const emps = new Set(filtered.map(r => r.Employee).filter(Boolean));
    const locs = new Set(filtered.map(r => r.Location).filter(Boolean));
    const onTime = filtered.filter(r => r['Time In Variance'] === 'OnTime').length;
    const late = filtered.filter(r => r['Time In Variance'] === 'Late').length;
    const auto = filtered.filter(r => r['Time Out Variance'] === 'AutoPunchout').length;
    const hrs = filtered.map(r => hoursToNum(r['Total Hrs'])).filter(h => !isNaN(h));
    const avg = hrs.length ? hrs.reduce((a, b) => a + b, 0) / hrs.length : 0;
    const pct = x => n ? Math.round(x / n * 100) : 0;
    document.getElementById('kTotal').textContent = n.toLocaleString();
    document.getElementById('kEmp').textContent = emps.size;
    document.getElementById('kLoc').textContent = locs.size;
    document.getElementById('kOntime').textContent = pct(onTime) + '%';
    document.getElementById('kOntimeFoot').textContent = onTime.toLocaleString() + ' check-ins';
    document.getElementById('kLate').textContent = pct(late) + '%';
    document.getElementById('kLateFoot').textContent = late.toLocaleString() + ' check-ins';
    document.getElementById('kAuto').textContent = auto.toLocaleString();
    document.getElementById('kHours').textContent = avg.toFixed(1);
    document.getElementById('logChip').textContent = n.toLocaleString();
}

// ---------- charts ----------
const baseOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: C.ink, boxWidth: 12, boxHeight: 12, usePointStyle: true, font: { size: 12 } } } } };
function gridScale() {
    return {
        x: { grid: { color: C.grid, drawTicks: false }, border: { display: false }, ticks: { color: C.muted, font: { size: 11 }, maxRotation: 0, autoSkipPadding: 16 } },
        y: { grid: { color: C.grid, drawTicks: false }, border: { display: false }, ticks: { color: C.muted, font: { size: 11 }, precision: 0 }, beginAtZero: true }
    };
}
function renderTrend() {
    const byDay = {};
    filtered.forEach(r => { const d = parseDate(r.Date); if (!d) return; const k = d.getTime(); if (!byDay[k]) byDay[k] = { d, total: 0, late: 0 }; byDay[k].total++; if (r['Time In Variance'] === 'Late') byDay[k].late++; });
    const rows = Object.values(byDay).sort((a, b) => a.d - b.d);
    if (charts.trend) charts.trend.destroy();
    charts.trend = new Chart(document.getElementById('trendChart'), {
        type: 'line',
        data: { labels: rows.map(r => fmtDate(r.d)), datasets: [
            { label: 'Records', data: rows.map(r => r.total), borderColor: C.brand, backgroundColor: 'rgba(42,120,214,.10)', borderWidth: 2, fill: true, tension: .3, pointRadius: 0, pointHoverRadius: 5 },
            { label: 'Late check-ins', data: rows.map(r => r.late), borderColor: C.late, backgroundColor: 'transparent', borderWidth: 2, fill: false, tension: .3, pointRadius: 0, pointHoverRadius: 5 }
        ]},
        options: Object.assign({}, baseOpts, { interaction: { mode: 'index', intersect: false }, scales: gridScale() })
    });
}
function renderStatus() {
    const cats = ['OnTime', 'Late', 'Early', 'AutoPunchout'], labels = ['On time', 'Late', 'Early', 'Auto'];
    const inData = cats.map(c => filtered.filter(r => r['Time In Variance'] === c).length);
    const outData = cats.map(c => filtered.filter(r => r['Time Out Variance'] === c).length);
    if (charts.status) charts.status.destroy();
    charts.status = new Chart(document.getElementById('statusChart'), {
        type: 'bar',
        data: { labels, datasets: [
            { label: 'Check-in', data: inData, backgroundColor: C.brand, borderRadius: 4, maxBarThickness: 26 },
            { label: 'Check-out', data: outData, backgroundColor: C.aqua, borderRadius: 4, maxBarThickness: 26 }
        ]},
        options: Object.assign({}, baseOpts, { scales: gridScale() })
    });
}
function topBar(canvasId, chartKey, counts) {
    const rows = Object.keys(counts).map(k => ({ k, v: counts[k] })).filter(r => r.v > 0).sort((a, b) => b.v - a.v).slice(0, 10);
    if (charts[chartKey]) charts[chartKey].destroy();
    charts[chartKey] = new Chart(document.getElementById(canvasId), {
        type: 'bar',
        data: { labels: rows.map(r => r.k), datasets: [ { label: 'Late check-ins', data: rows.map(r => r.v), backgroundColor: C.late, borderRadius: 4, maxBarThickness: 20 } ] },
        options: Object.assign({}, baseOpts, {
            indexAxis: 'y', plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: C.grid, drawTicks: false }, border: { display: false }, ticks: { color: C.muted, precision: 0 }, beginAtZero: true },
                y: { grid: { display: false }, border: { display: false }, ticks: { color: C.ink, font: { size: 11 } } }
            }
        })
    });
}
function renderTopCharts() {
    const locCounts = {}, empCounts = {};
    filtered.forEach(r => { if (r['Time In Variance'] === 'Late') { if (r.Location) locCounts[r.Location] = (locCounts[r.Location] || 0) + 1; if (r.Employee) empCounts[r.Employee] = (empCounts[r.Employee] || 0) + 1; } });
    topBar('locChart', 'loc', locCounts);
    topBar('empChart', 'emp', empCounts);
}

// ---------- late-behaviour insights ----------
function analyseLate(varKey) {
    const perMonth = {}, dates = {};
    filtered.forEach(r => {
        if (r[varKey] !== 'Late') return;
        const d = parseDate(r.Date); if (!d) return;
        const emp = r.Employee || 'Unknown';
        const mk = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
        perMonth[emp] = perMonth[emp] || {}; perMonth[emp][mk] = (perMonth[emp][mk] || 0) + 1;
        (dates[emp] = dates[emp] || []).push(d);
    });
    const monthly = [];
    for (const emp in perMonth) for (const mk in perMonth[emp]) {
        if (perMonth[emp][mk] > 3) { const dt = new Date(parseInt(mk.split('-')[0]), parseInt(mk.split('-')[1]) - 1, 1); monthly.push({ emp, month: monthLabel(dt), count: perMonth[emp][mk] }); }
    }
    monthly.sort((a, b) => b.count - a.count);
    const streaks = [];
    for (const emp in dates) {
        const ds = dates[emp].slice().sort((a, b) => a - b);
        let best = 1, bs = ds[0], be = ds[0], cur = 1, cs = ds[0];
        for (let i = 1; i < ds.length; i++) {
            const diff = Math.round((ds[i] - ds[i - 1]) / 86400000);
            if (diff === 1) { cur++; } else if (diff === 0) { continue; } else { if (cur > best) { best = cur; bs = cs; be = ds[i - 1]; } cur = 1; cs = ds[i]; }
        }
        if (cur > best) { best = cur; bs = cs; be = ds[ds.length - 1]; }
        if (best >= 3) streaks.push({ emp, streak: best, start: bs, end: be });
    }
    streaks.sort((a, b) => b.streak - a.streak);
    return { monthly, streaks };
}
function fillList(id, items, render) {
    const el = document.getElementById(id);
    el.innerHTML = items.length ? items.map(render).join('') : '<li><span class="none-note">None in current selection</span></li>';
}
function renderInsights() {
    const inA = analyseLate('Time In Variance'), outA = analyseLate('Time Out Variance');
    const monthRow = e => '<li><span>' + esc(e.emp) + '</span><span class="tag">' + e.month + ' <span class="pill red">' + e.count + ' days</span></span></li>';
    const streakRow = e => '<li><span>' + esc(e.emp) + '</span><span class="tag">' + fmtDate(e.start) + '–' + fmtDate(e.end) + ' <span class="pill amber">' + e.streak + ' days</span></span></li>';
    fillList('lateInMonth', inA.monthly, monthRow);
    fillList('lateInStreak', inA.streaks, streakRow);
    fillList('lateOutMonth', outA.monthly, monthRow);
    fillList('lateOutStreak', outA.streaks, streakRow);
}

// ---------- table (all rows, no pagination) ----------
function sortedRows() {
    const rows = filtered.slice();
    rows.sort((a, b) => {
        let av, bv;
        if (sortKey === 'Date') { av = parseDate(a.Date) || 0; bv = parseDate(b.Date) || 0; }
        else if (sortKey === 'Total Hrs') { av = hoursToNum(a[sortKey]) || 0; bv = hoursToNum(b[sortKey]) || 0; }
        else { av = (a[sortKey] || '').toString().toLowerCase(); bv = (b[sortKey] || '').toString().toLowerCase(); }
        if (av < bv) return -1 * sortDir; if (av > bv) return 1 * sortDir; return 0;
    });
    return rows;
}
function renderTable() {
    const rows = sortedRows();
    const tbody = document.getElementById('tableBody');
    if (!rows.length) { tbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted py-4">No records match the current filters.</td></tr>'; }
    else {
        tbody.innerHTML = rows.map((r, i) =>
            '<tr>' +
            '<td class="num">' + (i + 1) + '</td>' +
            '<td class="num">' + esc(r.Date) + '</td>' +
            '<td>' + esc(r.Employee) + '</td>' +
            '<td>' + esc(r.Location) + '</td>' +
            '<td class="num">' + esc(r['Scheduled Time In']) + '</td>' +
            '<td class="num">' + esc(r['Time In']) + '</td>' +
            '<td>' + badge(r['Time In Variance']) + '</td>' +
            '<td class="num">' + esc(r['Scheduled Time Out']) + '</td>' +
            '<td class="num">' + esc(r['Time Out']) + '</td>' +
            '<td>' + badge(r['Time Out Variance']) + '</td>' +
            '<td class="num">' + esc(r['Total Hrs'] || '00:00') + '</td>' +
            '</tr>'
        ).join('');
    }
    document.querySelectorAll('table.att thead th').forEach(th => {
        const icon = th.querySelector('i'); if (!icon) return;
        icon.className = th.dataset.key === sortKey ? (sortDir === 1 ? 'fas fa-sort-up' : 'fas fa-sort-down') : 'fas fa-sort';
    });
}

// ---------- master refresh ----------
function refresh() {
    computeFiltered();
    updateKpis();
    renderTrend();
    renderStatus();
    renderTopCharts();
    renderInsights();
    renderTable();
}

// ---------- export ----------
function exportRows() {
    return sortedRows().map(r => ({
        Date: r.Date || '', Employee: r.Employee || '', Location: r.Location || '',
        'Scheduled Time In': r['Scheduled Time In'] || '', 'Time In': r['Time In'] || '', 'Time In Variance': r['Time In Variance'] || '',
        'Scheduled Time Out': r['Scheduled Time Out'] || '', 'Time Out': r['Time Out'] || '', 'Time Out Variance': r['Time Out Variance'] || '',
        'Total Hours': r['Total Hrs'] || ''
    }));
}
function stamp() { const d = new Date(); return d.getFullYear() + ('0' + (d.getMonth() + 1)).slice(-2) + ('0' + d.getDate()).slice(-2); }
function exportExcel() {
    const rows = exportRows(); if (!rows.length) { alert('No data to export.'); return; }
    const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), 'Attendance'); XLSX.writeFile(wb, 'Attendance_' + stamp() + '.xlsx');
}

// ---------- presets ----------
function applyPreset(preset) {
    const { min, max } = dataDateRange(); if (!max) return;
    if (preset === 'all') { picker.clear(); markPreset('all'); refresh(); return; }
    let start = null, end = max;
    if (preset === 'latest') { start = new Date(max); end = new Date(max); }
    else if (preset === '7') { start = new Date(max); start.setDate(start.getDate() - 6); }
    else if (preset === '30') { start = new Date(max); start.setDate(start.getDate() - 29); }
    else if (preset === 'month') { start = new Date(max.getFullYear(), max.getMonth(), 1); }
    else if (preset === 'lastmonth') { start = new Date(max.getFullYear(), max.getMonth() - 1, 1); end = new Date(max.getFullYear(), max.getMonth(), 0); }
    if (min && start < min) start = min;
    picker.setDate([start, end], false);
    markPreset(preset); refresh();
}
function markPreset(preset) { document.querySelectorAll('.preset-btn').forEach(b => b.classList.toggle('active', b.dataset.preset === preset)); }

// ---------- tabs ----------
function activateTab(name) {
    document.querySelectorAll('.tab-link').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
    if (name === 'overview') Object.values(charts).forEach(c => { try { c.resize(); } catch (e) {} });
}

// ---------- init ----------
window.addEventListener('DOMContentLoaded', function () {
    populateSelect('fLocation', [...new Set(RAW.map(r => r.Location))], 'All locations');
    populateSelect('fEmployee', [...new Set(RAW.map(r => r.Employee))], 'All employees');

    picker = flatpickr('#dateRange', {
        mode: 'range', dateFormat: 'd/m/y', allowInput: false,
        onChange: function (sel) { if (sel.length === 2) markPreset(''); refresh(); }
    });

    document.getElementById('clearRange').addEventListener('click', () => { picker.clear(); markPreset('all'); refresh(); });
    document.getElementById('resetFilters').addEventListener('click', () => {
        picker.clear();
        document.getElementById('fLocation').value = 'all';
        document.getElementById('fEmployee').value = 'all';
        markPreset('all'); refresh();
    });
    ['fLocation', 'fEmployee'].forEach(id => document.getElementById(id).addEventListener('change', refresh));
    document.querySelectorAll('.preset-btn').forEach(b => b.addEventListener('click', () => applyPreset(b.dataset.preset)));

    document.getElementById('exportExcel').addEventListener('click', exportExcel);
    document.querySelectorAll('table.att thead th').forEach(th => {
        if (!th.dataset.key) return;
        th.addEventListener('click', () => { if (sortKey === th.dataset.key) sortDir *= -1; else { sortKey = th.dataset.key; sortDir = 1; } renderTable(); });
    });
    document.querySelectorAll('.tab-link').forEach(b => b.addEventListener('click', () => activateTab(b.dataset.tab)));

    // Default view: only the latest date present in the data.
    if (dataDateRange().max) applyPreset('latest'); else refresh();
});
</script>
</body>
</html>"""

def generate_html(data, insights_text, params):
    generated = datetime.datetime.now().strftime('%d %b %Y, %H:%M')
    html = HTML_TEMPLATE
    html = html.replace('__DATA_JSON__', json.dumps(data))
    html = html.replace('__INSIGHTS__', format_insights(insights_text))
    html = html.replace('__AI_PERIOD__', str(params.get('ai_period', 'N/A')))
    html = html.replace('__CLID__', str(params['clid']))
    html = html.replace('__TYPE__', str(params['type_val']))
    html = html.replace('__TOTAL__', str(len(data)))
    html = html.replace('__GENERATED__', generated)
    return html

def main():
    parser = argparse.ArgumentParser(description='Generate static attendance dashboard with AI insights.')
    parser.add_argument('--clid', type=int, default=9, help='Client ID')
    parser.add_argument('--user-id', type=int, default=16199, help='User ID')
    parser.add_argument('--type', type=int, default=1, choices=[1, 2], help='Report type')
    parser.add_argument('--output', default='attendance_dashboard.html', help='Output HTML file')
    parser.add_argument('--no-ai', action='store_true', help='Skip AI insight generation (fastest)')
    parser.add_argument('--ai-timeout', type=int, default=90, help='Max seconds to wait for AI insights before skipping')
    parser.add_argument('--no-open', action='store_true', help='Do not open the dashboard in a browser afterwards')
    args = parser.parse_args()

    params = {'clid': args.clid, 'user_id': args.user_id, 'type_val': args.type}

    print(f"Fetching ALL data for CLID={args.clid}, Type={args.type} (no date filter)...")
    t0 = time.time()
    data = get_data(args.clid, args.user_id, args.type)
    print(f"[OK] Data fetch took {time.time() - t0:.1f}s")
    if not data:
        print("No data retrieved. Exiting.")
        return

    # AI insights are scoped to the latest month present in the data.
    df = pd.DataFrame(data)
    ai_df, ai_period = latest_month_slice(df)
    params['ai_period'] = ai_period

    if args.no_ai:
        insights = f"- AI insight generation was skipped (--no-ai). Latest month in data: {ai_period}."
    else:
        print(f"Generating AI insights for latest month: {ai_period} ({len(ai_df)} records, timeout {args.ai_timeout}s)...")
        t1 = time.time()
        insights = generate_insights_with_timeout(ai_df, args.ai_timeout)
        print(f"[OK] AI step took {time.time() - t1:.1f}s")

    html_content = generate_html(data, insights, params)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html_content)
    out_path = os.path.abspath(args.output)
    print(f"[OK] Dashboard saved to {out_path}")

    if not args.no_open:
        try:
            webbrowser.open('file:///' + out_path.replace('\\', '/'))
            print("[OK] Opening dashboard in your default browser...")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] Could not auto-open browser: {e}")

if __name__ == "__main__":
    main()
