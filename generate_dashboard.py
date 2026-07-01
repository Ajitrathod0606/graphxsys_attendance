# generate_dashboard.py
import os
import json
import argparse
import datetime
import pandas as pd
from src.data_loaded import DataLoader
from src.ai_insights import generate_insights

def get_data(clid, user_id, type_val):
    """Fetch ALL data (wide date range)."""
    loader = DataLoader()
    json_str = loader.fetch_attendance_json(
        type_val=type_val,
        user_id=user_id,
        clid=clid,
        fdate='1900-01-01',
        tdate='2099-12-31',
        region='',
        district='',
        location='',
        employee=''
    )
    try:
        data = json.loads(json_str)
        print(f"✅ Retrieved {len(data)} records.")
        return data
    except json.JSONDecodeError:
        print("❌ Invalid JSON returned.")
        return []

def format_insights(text):
    """Convert bullet points (lines starting with '- ') into HTML list."""
    if not text:
        return '<p>No insights available.</p>'
    lines = text.splitlines()
    items = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('- '):
            if not in_list:
                in_list = True
                items.append('<ul class="insights-list">')
            items.append(f'<li>{stripped[2:].strip()}</li>')
        else:
            if in_list:
                items.append('</ul>')
                in_list = False
            if stripped:
                items.append(f'<p>{stripped}</p>')
    if in_list:
        items.append('</ul>')
    return '\n'.join(items)

def generate_html(data, insights_text, params):
    formatted_insights = format_insights(insights_text)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Attendance Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        body { background-color: #f4f7fc; padding: 20px; }
        .card { border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
        .stat-card { text-align: center; padding: 15px 10px; border-radius: 10px; background: #fff; box-shadow: 0 2px 5px rgba(0,0,0,0.05); height: 100%; }
        .stat-card .number { font-size: 2rem; font-weight: 700; }
        .stat-card .label { color: #6c757d; font-size: 0.9rem; }
        .stat-card.on-time .number { color: #28a745; }
        .stat-card.late .number { color: #dc3545; }
        .stat-card.early .number { color: #ffc107; }
        .stat-card.auto .number { color: #17a2b8; }
        .stat-card.total .number { color: #0d6efd; }
        .badge-on-time { background-color: #28a745; color: #fff; }
        .badge-late { background-color: #dc3545; color: #fff; }
        .badge-early { background-color: #ffc107; color: #212529; }
        .badge-auto { background-color: #17a2b8; color: #fff; }
        .employee-list { max-height: 200px; overflow-y: auto; }
        .employee-list .list-group-item { border: none; padding: 0.4rem 0.75rem; font-size: 0.9rem; }
        .filter-section { background: #fff; padding: 20px; border-radius: 12px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); margin-bottom: 20px; }
        .table-responsive { background: #fff; border-radius: 12px; padding: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .table th { background-color: #f8f9fa; border-bottom: 2px solid #dee2e6; }
        .insights-box { background: #f8f9fa; padding: 20px; border-radius: 12px; border-left: 5px solid #0d6efd; }
        .insights-list { list-style-type: disc; padding-left: 20px; }
        .insights-list li { margin-bottom: 6px; line-height: 1.5; }
        .late-insight-box { background: #fff; padding: 15px; border-radius: 12px; border-left: 5px solid #dc3545; }
        footer { margin-top: 30px; text-align: center; color: #6c757d; font-size: 0.85rem; }
        .range-display { font-weight: 600; color: #0d6efd; }
        .flatpickr-input { background: #fff !important; }
        .export-btn { margin-left: 10px; }
        .ai-btn { margin-left: 10px; }
        .modal-header { background-color: #0d6efd; color: white; border-bottom: none; }
        .modal-header .btn-close { filter: invert(1); }
        .modal-body { max-height: 70vh; overflow-y: auto; }
        .modal-body .insights-list { font-size: 1rem; }
        .modal-body .insights-list li { margin-bottom: 8px; }
    </style>
</head>
<body>
<div class="container-fluid">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="fas fa-clipboard-list text-primary"></i> Attendance Dashboard</h2>
        <span class="text-muted" id="lastUpdated"></span>
    </div>

    <!-- Filters -->
    <div class="filter-section">
        <div class="row g-3 align-items-end">
            <div class="col-md-4">
                <label class="form-label"><i class="far fa-calendar-alt"></i> Date Range</label>
                <div class="input-group">
                    <input type="text" id="dateRangePicker" class="form-control" placeholder="Select date range">
                    <button class="btn btn-outline-secondary" type="button" id="clearRange"><i class="fas fa-times"></i></button>
                </div>
            </div>
            <div class="col-md-3">
                <label for="locationFilter" class="form-label"><i class="fas fa-map-marker-alt"></i> Location</label>
                <select class="form-select" id="locationFilter">
                    <option value="all">All Locations</option>
                </select>
            </div>
            <div class="col-md-2">
                <button class="btn btn-primary w-100" id="applyFilters"><i class="fas fa-sync"></i> Apply</button>
            </div>
            <div class="col-md-3 text-end">
                <span class="badge bg-light text-dark p-2" id="recordCount">0 records</span>
                <button class="btn btn-success btn-sm export-btn" id="exportExcel"><i class="fas fa-file-excel"></i> Export</button>
                <button class="btn btn-info btn-sm ai-btn" id="aiInsightsBtn" data-bs-toggle="modal" data-bs-target="#aiInsightsModal">
                    <i class="fas fa-robot"></i> AI Insights
                </button>
            </div>
        </div>
        <div class="row mt-2">
            <div class="col">
                <span class="range-display" id="selectedRange">No range selected</span>
            </div>
        </div>
    </div>

    <!-- Summary Cards -->
    <div class="row g-3 mb-4">
        <div class="col-lg-2 col-md-4 col-6"><div class="stat-card total"><div class="number" id="totalEmployees">0</div><div class="label">Total Employees</div></div></div>
        <div class="col-lg-2 col-md-4 col-6"><div class="stat-card on-time"><div class="number" id="onTimeCount">0</div><div class="label">On Time</div></div></div>
        <div class="col-lg-2 col-md-4 col-6"><div class="stat-card late"><div class="number" id="lateCount">0</div><div class="label">Late</div></div></div>
        <div class="col-lg-2 col-md-4 col-6"><div class="stat-card early"><div class="number" id="earlyCount">0</div><div class="label">Early</div></div></div>
        <div class="col-lg-2 col-md-4 col-6"><div class="stat-card auto"><div class="number" id="autoCount">0</div><div class="label">Auto Punchout</div></div></div>
        <div class="col-lg-2 col-md-4 col-6"><div class="stat-card" style="background:#f8f9fa;"><div class="number" id="avgHours">0.0</div><div class="label">Avg Hours</div></div></div>
    </div>

    <!-- Late Behaviour Insights – split In/Out -->
    <div class="row g-3 mb-4">
        <div class="col-md-6">
            <div class="card">
                <div class="card-header bg-danger text-white">
                    <i class="fas fa-sign-in-alt"></i> Late Check‑In Insights
                    <span class="badge bg-light text-dark float-end">Based on current filters</span>
                </div>
                <div class="card-body late-insight-box">
                    <h6><i class="fas fa-calendar-alt"></i> >3 Late Check‑Ins in a Month</h6>
                    <p><span class="badge bg-danger" id="lateInMonthCount">0</span> employees</p>
                    <div id="lateInMonthList" class="employee-list"><p class="text-muted">None</p></div>
                    <hr>
                    <h6><i class="fas fa-clock"></i> 3+ Consecutive Late Check‑Ins</h6>
                    <p><span class="badge bg-warning text-dark" id="lateInConsecutiveCount">0</span> employees</p>
                    <div id="lateInConsecutiveList" class="employee-list"><p class="text-muted">None</p></div>
                </div>
            </div>
        </div>
        <div class="col-md-6">
            <div class="card">
                <div class="card-header bg-danger text-white">
                    <i class="fas fa-sign-out-alt"></i> Late Check‑Out Insights
                    <span class="badge bg-light text-dark float-end">Based on current filters</span>
                </div>
                <div class="card-body late-insight-box">
                    <h6><i class="fas fa-calendar-alt"></i> >3 Late Check‑Outs in a Month</h6>
                    <p><span class="badge bg-danger" id="lateOutMonthCount">0</span> employees</p>
                    <div id="lateOutMonthList" class="employee-list"><p class="text-muted">None</p></div>
                    <hr>
                    <h6><i class="fas fa-clock"></i> 3+ Consecutive Late Check‑Outs</h6>
                    <p><span class="badge bg-warning text-dark" id="lateOutConsecutiveCount">0</span> employees</p>
                    <div id="lateOutConsecutiveList" class="employee-list"><p class="text-muted">None</p></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Late & Early Lists – separated by In/Out (for the first day of the range) -->
    <div class="row g-3 mb-4">
        <div class="col-md-3">
            <div class="card"><div class="card-header bg-danger text-white"><i class="fas fa-sign-in-alt"></i> Late Check‑In (day)</div>
            <div class="card-body employee-list" id="lateInEmployees"><p class="text-muted">None</p></div></div>
        </div>
        <div class="col-md-3">
            <div class="card"><div class="card-header bg-danger text-white"><i class="fas fa-sign-out-alt"></i> Late Check‑Out (day)</div>
            <div class="card-body employee-list" id="lateOutEmployees"><p class="text-muted">None</p></div></div>
        </div>
        <div class="col-md-3">
            <div class="card"><div class="card-header bg-success text-white"><i class="fas fa-sign-in-alt"></i> Early Check‑In (day)</div>
            <div class="card-body employee-list" id="earlyInEmployees"><p class="text-muted">None</p></div></div>
        </div>
        <div class="col-md-3">
            <div class="card"><div class="card-header bg-success text-white"><i class="fas fa-sign-out-alt"></i> Early Check‑Out (day)</div>
            <div class="card-body employee-list" id="earlyOutEmployees"><p class="text-muted">None</p></div></div>
        </div>
    </div>

    <!-- Table -->
    <div class="table-responsive">
        <table class="table table-hover table-striped" id="attendanceTable">
            <thead>
                <tr><th>#</th><th>Date</th><th>Employee</th><th>Location</th><th>Scheduled In</th><th>Time In</th><th>In Variance</th><th>Scheduled Out</th><th>Time Out</th><th>Out Variance</th><th>Total Hours</th></tr>
            </thead>
            <tbody id="tableBody"><tr><td colspan="11" class="text-center">No data</td></tr></tbody>
        </table>
    </div>

    <footer>Data generated on <span id="refreshTime"></span> &bull; CLID: {clid} &bull; Type: {type_val}</footer>
</div>

<!-- AI Insights Modal -->
<div class="modal fade" id="aiInsightsModal" tabindex="-1" aria-labelledby="aiInsightsModalLabel" aria-hidden="true">
    <div class="modal-dialog modal-lg modal-dialog-scrollable">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title" id="aiInsightsModalLabel"><i class="fas fa-robot me-2"></i>AI Insights</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
                {insights}
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
<script>
    const attendanceData = {data_json};
    let allData = attendanceData;
    let currentFilteredData = [];

    // ---------- Helper functions ----------
    function parseDate(str) {
        if (!str) return null;
        const parts = str.split('/');
        if (parts.length !== 3) return null;
        const d = parseInt(parts[0], 10);
        const m = parseInt(parts[1], 10) - 1;
        const y = parseInt(parts[2], 10) + 2000;
        return new Date(y, m, d);
    }

    function formatDate(date) {
        if (!date) return '';
        const d = String(date.getDate()).padStart(2, '0');
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const y = String(date.getFullYear()).slice(2);
        return `${d}/${m}/${y}`;
    }

    function getMonthYear(date) {
        const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        return monthNames[date.getMonth()] + ' ' + date.getFullYear();
    }

    function getDateRangeFromData() {
        const dates = allData.map(r => parseDate(r.Date)).filter(d => d);
        if (!dates.length) return { min: null, max: null };
        let min = dates[0], max = dates[0];
        dates.forEach(d => {
            if (d < min) min = d;
            if (d > max) max = d;
        });
        return { min, max };
    }

    // ---------- Compute late insights separately for In and Out ----------
    function computeLateInsights(data) {
        const empInMonth = {}, empInDates = {};
        const empOutMonth = {}, empOutDates = {};

        data.forEach(r => {
            if (r['Time In Variance'] === 'Late') {
                const d = parseDate(r.Date);
                if (!d) return;
                const monthKey = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
                const emp = r.Employee;
                if (!empInMonth[emp]) empInMonth[emp] = {};
                if (!empInMonth[emp][monthKey]) empInMonth[emp][monthKey] = 0;
                empInMonth[emp][monthKey]++;
                if (!empInDates[emp]) empInDates[emp] = [];
                empInDates[emp].push(d);
            }
            if (r['Time Out Variance'] === 'Late') {
                const d = parseDate(r.Date);
                if (!d) return;
                const monthKey = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
                const emp = r.Employee;
                if (!empOutMonth[emp]) empOutMonth[emp] = {};
                if (!empOutMonth[emp][monthKey]) empOutMonth[emp][monthKey] = 0;
                empOutMonth[emp][monthKey]++;
                if (!empOutDates[emp]) empOutDates[emp] = [];
                empOutDates[emp].push(d);
            }
        });

        // Check-In: >3 per month
        const inMonthEntries = [];
        for (const emp in empInMonth) {
            for (const monthKey in empInMonth[emp]) {
                const count = empInMonth[emp][monthKey];
                if (count > 3) {
                    const dateObj = new Date(parseInt(monthKey.split('-')[0]), parseInt(monthKey.split('-')[1])-1, 1);
                    inMonthEntries.push({ employee: emp, month: getMonthYear(dateObj), count: count });
                }
            }
        }

        // Check-In: consecutive streaks
        const inConsecutive = {};
        for (const emp in empInDates) {
            const dates = empInDates[emp].sort((a,b) => a - b);
            let maxStreak = 0, streakStart = null, streakEnd = null;
            let curStreak = 1, curStart = dates[0], curEnd = dates[0];
            for (let i = 1; i < dates.length; i++) {
                const diff = (dates[i] - dates[i-1]) / (1000*60*60*24);
                if (diff === 1) {
                    curStreak++;
                    curEnd = dates[i];
                } else {
                    if (curStreak > maxStreak) {
                        maxStreak = curStreak;
                        streakStart = curStart;
                        streakEnd = curEnd;
                    }
                    curStreak = 1;
                    curStart = dates[i];
                    curEnd = dates[i];
                }
            }
            if (curStreak > maxStreak) {
                maxStreak = curStreak;
                streakStart = curStart;
                streakEnd = curEnd;
            }
            if (maxStreak >= 3) {
                inConsecutive[emp] = { streak: maxStreak, start: streakStart, end: streakEnd };
            }
        }

        // Check-Out: >3 per month
        const outMonthEntries = [];
        for (const emp in empOutMonth) {
            for (const monthKey in empOutMonth[emp]) {
                const count = empOutMonth[emp][monthKey];
                if (count > 3) {
                    const dateObj = new Date(parseInt(monthKey.split('-')[0]), parseInt(monthKey.split('-')[1])-1, 1);
                    outMonthEntries.push({ employee: emp, month: getMonthYear(dateObj), count: count });
                }
            }
        }

        // Check-Out: consecutive streaks
        const outConsecutive = {};
        for (const emp in empOutDates) {
            const dates = empOutDates[emp].sort((a,b) => a - b);
            let maxStreak = 0, streakStart = null, streakEnd = null;
            let curStreak = 1, curStart = dates[0], curEnd = dates[0];
            for (let i = 1; i < dates.length; i++) {
                const diff = (dates[i] - dates[i-1]) / (1000*60*60*24);
                if (diff === 1) {
                    curStreak++;
                    curEnd = dates[i];
                } else {
                    if (curStreak > maxStreak) {
                        maxStreak = curStreak;
                        streakStart = curStart;
                        streakEnd = curEnd;
                    }
                    curStreak = 1;
                    curStart = dates[i];
                    curEnd = dates[i];
                }
            }
            if (curStreak > maxStreak) {
                maxStreak = curStreak;
                streakStart = curStart;
                streakEnd = curEnd;
            }
            if (maxStreak >= 3) {
                outConsecutive[emp] = { streak: maxStreak, start: streakStart, end: streakEnd };
            }
        }

        return { inMonthEntries, inConsecutive, outMonthEntries, outConsecutive };
    }

    // ---------- UI updates ----------
    let datePicker = null;

    function initDatePicker() {
        const range = getDateRangeFromData();
        const defaultStart = range.min || new Date();
        const defaultEnd = range.max || new Date();
        document.getElementById('selectedRange').innerText = `${formatDate(defaultStart)} ~ ${formatDate(defaultEnd)}`;

        datePicker = flatpickr("#dateRangePicker", {
            mode: "range",
            dateFormat: "d/m/Y",
            defaultDate: [defaultStart, defaultEnd],
            onChange: function(selectedDates, dateStr, instance) {
                // Update the displayed range label
                if (selectedDates.length === 2) {
                    const start = selectedDates[0];
                    const end = selectedDates[1];
                    document.getElementById('selectedRange').innerText = `${formatDate(start)} ~ ${formatDate(end)}`;
                } else {
                    document.getElementById('selectedRange').innerText = 'Select a range';
                }
                // Automatically re-apply filters when the range changes
                applyFilters();
            }
        });
        if (datePicker.selectedDates.length === 2) {
            const start = datePicker.selectedDates[0];
            const end = datePicker.selectedDates[1];
            document.getElementById('selectedRange').innerText = `${formatDate(start)} ~ ${formatDate(end)}`;
        }
    }

    function populateLocations() {
        const locations = [...new Set(allData.map(r => r.Location))].filter(Boolean);
        const sel = document.getElementById('locationFilter');
        sel.innerHTML = '<option value="all">All Locations</option>';
        locations.forEach(loc => {
            const opt = document.createElement('option');
            opt.value = loc;
            opt.textContent = loc;
            sel.appendChild(opt);
        });
    }

    function applyFilters() {
        let startDate = null, endDate = null;
        if (datePicker && datePicker.selectedDates.length === 2) {
            startDate = datePicker.selectedDates[0];
            endDate = datePicker.selectedDates[1];
        } else {
            // Fallback: use the full data range
            const range = getDateRangeFromData();
            startDate = range.min;
            endDate = range.max;
        }
        const locVal = document.getElementById('locationFilter').value;

        let filtered = allData.filter(r => {
            const d = parseDate(r.Date);
            if (!d) return false;
            if (startDate && d < startDate) return false;
            if (endDate && d > endDate) return false;
            return true;
        });
        if (locVal !== 'all') {
            filtered = filtered.filter(r => r.Location === locVal);
        }
        currentFilteredData = filtered;

        // Summary stats
        const total = filtered.length;
        const onTime = filtered.filter(r => r['Time In Variance'] === 'OnTime').length;
        const late = filtered.filter(r => r['Time In Variance'] === 'Late').length;
        const early = filtered.filter(r => r['Time In Variance'] === 'Early').length;
        const auto = filtered.filter(r => r['Time Out Variance'] === 'AutoPunchout').length;
        let avgHours = 0;
        if (total > 0) {
            const hours = filtered.map(r => {
                const h = r['Total Hrs'] || '00:00';
                const [hh, mm] = h.split(':').map(Number);
                return hh + mm/60;
            }).filter(h => !isNaN(h));
            if (hours.length) avgHours = hours.reduce((a,b) => a+b, 0) / hours.length;
        }
        document.getElementById('totalEmployees').innerText = total;
        document.getElementById('onTimeCount').innerText = onTime;
        document.getElementById('lateCount').innerText = late;
        document.getElementById('earlyCount').innerText = early;
        document.getElementById('autoCount').innerText = auto;
        document.getElementById('avgHours').innerText = avgHours.toFixed(1);

        // Four lists: Late In, Late Out, Early In, Early Out – for the first day of the range
        let targetDate = null;
        if (datePicker && datePicker.selectedDates.length === 2) {
            targetDate = datePicker.selectedDates[0];
        } else if (filtered.length > 0) {
            const dates = filtered.map(r => r.Date);
            const freq = {};
            dates.forEach(d => freq[d] = (freq[d]||0)+1);
            const sorted = Object.keys(freq).sort((a,b) => freq[b] - freq[a]);
            targetDate = sorted[0];
        }
        let lateInEmps = [], lateOutEmps = [], earlyInEmps = [], earlyOutEmps = [];
        if (targetDate) {
            const targetStr = formatDate(targetDate);
            const dayData = filtered.filter(r => r.Date === targetStr);
            lateInEmps  = dayData.filter(r => r['Time In Variance'] === 'Late').map(r => r.Employee);
            lateOutEmps = dayData.filter(r => r['Time Out Variance'] === 'Late').map(r => r.Employee);
            earlyInEmps = dayData.filter(r => r['Time In Variance'] === 'Early').map(r => r.Employee);
            earlyOutEmps = dayData.filter(r => r['Time Out Variance'] === 'Early').map(r => r.Employee);
        }
        lateInEmps = [...new Set(lateInEmps)];
        lateOutEmps = [...new Set(lateOutEmps)];
        earlyInEmps = [...new Set(earlyInEmps)];
        earlyOutEmps = [...new Set(earlyOutEmps)];

        document.getElementById('lateInEmployees').innerHTML = lateInEmps.length ? `<ul class="list-group">${lateInEmps.map(e => `<li class="list-group-item">${e}</li>`).join('')}</ul>` : '<p class="text-muted">None</p>';
        document.getElementById('lateOutEmployees').innerHTML = lateOutEmps.length ? `<ul class="list-group">${lateOutEmps.map(e => `<li class="list-group-item">${e}</li>`).join('')}</ul>` : '<p class="text-muted">None</p>';
        document.getElementById('earlyInEmployees').innerHTML = earlyInEmps.length ? `<ul class="list-group">${earlyInEmps.map(e => `<li class="list-group-item">${e}</li>`).join('')}</ul>` : '<p class="text-muted">None</p>';
        document.getElementById('earlyOutEmployees').innerHTML = earlyOutEmps.length ? `<ul class="list-group">${earlyOutEmps.map(e => `<li class="list-group-item">${e}</li>`).join('')}</ul>` : '<p class="text-muted">None</p>';

        // Table
        const tbody = document.getElementById('tableBody');
        if (filtered.length === 0) {
            tbody.innerHTML = `<tr><td colspan="11" class="text-center">No records for the selected range and location.</td></tr>`;
        } else {
            tbody.innerHTML = filtered.map((r, i) => {
                const inVar = r['Time In Variance'] || '';
                const outVar = r['Time Out Variance'] || '';
                const inBadge = `<span class="badge ${inVar === 'OnTime' ? 'badge-on-time' : inVar === 'Late' ? 'badge-late' : inVar === 'Early' ? 'badge-early' : inVar === 'AutoPunchout' ? 'badge-auto' : 'bg-secondary'}">${inVar || '—'}</span>`;
                const outBadge = `<span class="badge ${outVar === 'OnTime' ? 'badge-on-time' : outVar === 'Late' ? 'badge-late' : outVar === 'Early' ? 'badge-early' : outVar === 'AutoPunchout' ? 'badge-auto' : 'bg-secondary'}">${outVar || '—'}</span>`;
                return `<tr>
                    <td>${i+1}</td>
                    <td>${r.Date || ''}</td>
                    <td>${r.Employee || ''}</td>
                    <td>${r.Location || ''}</td>
                    <td>${r['Scheduled Time In'] || ''}</td>
                    <td>${r['Time In'] || ''}</td>
                    <td>${inBadge}</td>
                    <td>${r['Scheduled Time Out'] || ''}</td>
                    <td>${r['Time Out'] || ''}</td>
                    <td>${outBadge}</td>
                    <td>${r['Total Hrs'] || '00:00'}</td>
                </tr>`;
            }).join('');
        }
        document.getElementById('recordCount').innerText = `${filtered.length} records`;

        // Update Late Insights
        displayLateInsights(filtered);
    }

    // ---------- Display Late Insights (In and Out separately) ----------
    function displayLateInsights(data) {
        const { inMonthEntries, inConsecutive, outMonthEntries, outConsecutive } = computeLateInsights(data);

        // Check-In: >3 per month
        document.getElementById('lateInMonthCount').innerText = inMonthEntries.length;
        const inMonthList = document.getElementById('lateInMonthList');
        if (inMonthEntries.length) {
            inMonthList.innerHTML = `<ul class="list-group">${inMonthEntries.map(e => 
                `<li class="list-group-item">${e.employee} — ${e.month} (${e.count} days)</li>`
            ).join('')}</ul>`;
        } else {
            inMonthList.innerHTML = '<p class="text-muted">None</p>';
        }

        // Check-In: consecutive
        const inConsecList = Object.keys(inConsecutive);
        document.getElementById('lateInConsecutiveCount').innerText = inConsecList.length;
        const inConsecEl = document.getElementById('lateInConsecutiveList');
        if (inConsecList.length) {
            inConsecEl.innerHTML = `<ul class="list-group">${inConsecList.map(emp => {
                const info = inConsecutive[emp];
                return `<li class="list-group-item">${emp} — ${info.streak} consecutive days (${formatDate(info.start)} – ${formatDate(info.end)})</li>`;
            }).join('')}</ul>`;
        } else {
            inConsecEl.innerHTML = '<p class="text-muted">None</p>';
        }

        // Check-Out: >3 per month
        document.getElementById('lateOutMonthCount').innerText = outMonthEntries.length;
        const outMonthList = document.getElementById('lateOutMonthList');
        if (outMonthEntries.length) {
            outMonthList.innerHTML = `<ul class="list-group">${outMonthEntries.map(e => 
                `<li class="list-group-item">${e.employee} — ${e.month} (${e.count} days)</li>`
            ).join('')}</ul>`;
        } else {
            outMonthList.innerHTML = '<p class="text-muted">None</p>';
        }

        // Check-Out: consecutive
        const outConsecList = Object.keys(outConsecutive);
        document.getElementById('lateOutConsecutiveCount').innerText = outConsecList.length;
        const outConsecEl = document.getElementById('lateOutConsecutiveList');
        if (outConsecList.length) {
            outConsecEl.innerHTML = `<ul class="list-group">${outConsecList.map(emp => {
                const info = outConsecutive[emp];
                return `<li class="list-group-item">${emp} — ${info.streak} consecutive days (${formatDate(info.start)} – ${formatDate(info.end)})</li>`;
            }).join('')}</ul>`;
        } else {
            outConsecEl.innerHTML = '<p class="text-muted">None</p>';
        }
    }

    // ---------- Export to Excel ----------
    function exportExcel() {
        if (!currentFilteredData || currentFilteredData.length === 0) {
            alert('No data to export.');
            return;
        }
        const exportData = currentFilteredData.map(r => ({
            'Date': r.Date || '',
            'Employee': r.Employee || '',
            'Location': r.Location || '',
            'Scheduled Time In': r['Scheduled Time In'] || '',
            'Time In': r['Time In'] || '',
            'Time In Variance': r['Time In Variance'] || '',
            'Scheduled Time Out': r['Scheduled Time Out'] || '',
            'Time Out': r['Time Out'] || '',
            'Time Out Variance': r['Time Out Variance'] || '',
            'Total Hours': r['Total Hrs'] || ''
        }));
        const wb = XLSX.utils.book_new();
        const ws = XLSX.utils.json_to_sheet(exportData);
        XLSX.utils.book_append_sheet(wb, ws, 'Attendance');
        const now = new Date();
        const dateStr = now.toISOString().slice(0,10);
        XLSX.writeFile(wb, `Attendance_${dateStr}.xlsx`);
    }

    // ---------- Event listeners ----------
    document.getElementById('clearRange').addEventListener('click', function() {
        if (datePicker) {
            datePicker.clear();
            document.getElementById('selectedRange').innerText = 'No range selected';
            applyFilters();
        }
    });

    document.getElementById('applyFilters').addEventListener('click', applyFilters);
    document.getElementById('locationFilter').addEventListener('change', applyFilters);
    document.getElementById('exportExcel').addEventListener('click', exportExcel);

    // ---------- Initialization ----------
    window.onload = function() {
        populateLocations();
        initDatePicker();
        applyFilters();
        document.getElementById('lastUpdated').innerText = `Generated: ${new Date().toLocaleString()}`;
        document.getElementById('refreshTime').innerText = new Date().toLocaleString();
    };
</script>
</body>
</html>"""

    # Replace placeholders
    html = html_template.replace('{data_json}', json.dumps(data))
    html = html.replace('{insights}', formatted_insights)
    html = html.replace('{clid}', str(params['clid']))
    html = html.replace('{type_val}', str(params['type_val']))
    return html

def main():
    parser = argparse.ArgumentParser(description='Generate static dashboard with AI insights.')
    parser.add_argument('--clid', type=int, default=9, help='Client ID')
    parser.add_argument('--user-id', type=int, default=16199, help='User ID')
    parser.add_argument('--type', type=int, default=1, choices=[1,2], help='Report type')
    parser.add_argument('--output', default='attendance_dashboard.html', help='Output HTML file')
    args = parser.parse_args()

    params = {
        'clid': args.clid,
        'user_id': args.user_id,
        'type_val': args.type
    }

    print(f"Fetching ALL data for CLID={args.clid}, Type={args.type} (no date filter)")
    data = get_data(args.clid, args.user_id, args.type)
    if not data:
        print("No data retrieved. Exiting.")
        return

    print("Generating AI insights...")
    df = pd.DataFrame(data)
    insights = generate_insights(df)
    print("✅ Insights generated.")

    html_content = generate_html(data, insights, params)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"✅ Dashboard saved to {args.output}")

if __name__ == "__main__":
    main()