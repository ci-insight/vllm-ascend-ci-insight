const INDEX_URL = "reports/index.json";
let allReports = [];
let allAnalyses = [];
let allJobs = []; // ALL jobs (including success) for CI stats
let charts = {};
let ciCharts = {};
let activeTab = "analysis";

// ── Category Classification ──

const CATEGORY_RULES = [
  ["lint", /(\bruff\b|pre-commit|\bmypy\b|\bflake8\b|\bE\d{3}\b|\bF\d{3}\b|\bW\d{3}\b|PR\s+title|formatting|unused\s+import|line\s+too\s+long|undefined\s+name|imported\s+but\s+unused)/i],
  ["build", /(\bcmake\b|pip\s+install|uv\s+pip|setup\.py|requirements|wheel\s|build\s+(?:fail|error|broken)|UV_INDEX|package\s.*\bnot\s+found|could\s+not\s+find.*version)/i],
  ["perf", /(\bOOM\b|out of memory|memory (?:alloc|leak|exhaust)|killed|timed?\s?out|timeout)/i],
  ["infra", /(runner\s+(?:disconnect|fail|unreachable)|disk\s+(?:full|quota)|node\s+(?:alloc|fail)|connection\s+(?:refused|timeout|reset)|rate\s?limit|HTTP\s*404|network\s+error)/i],
  ["test", /(\baccuracy\s+test\b|\baccuracy.*\b(?:regression|mismatch|degrad)\b|assert.*\b(?:fail|error)\b|\bflaky\s+test\b|\bregression\b|\btest_case\b|\btest_.*\.py\b)/i],
  ["compat", /(\bdeprecated\b|\bremoved\b.*\b(?:in|from)\b|\brenamed\b.*\bto\b|no\s+longer\s+(?:exists|available|supported)|module.*\b(?:moved|renamed)\b|import\s+path.*\b(changed|wrong)\b|incompatible)/i],
  ["code", /(\bImportError\b|\bAttributeError\b|\bModuleNotFoundError\b|\bNameError\b|\bTypeError\b|\bValueError\b|\bKeyError\b|\bIndexError\b|undefined\s+name|not\s+defined|has\s+no\s+attribute)/i],
];

function classifyJob(analysis, jobName) {
  const text = [analysis.root_cause || "", (analysis.error_snippets || []).join(" "), jobName].join(" ");
  for (const [cat, re] of CATEGORY_RULES) { if (re.test(text)) return cat; }
  return "other";
}

// ── I18n ──

function applyI18n() {
  document.title = t("title");
  document.getElementById("pageTitle").textContent = t("title");
  document.getElementById("refreshBtn").textContent = t("refresh");
  document.getElementById("langToggle").textContent = t("lang");

  // Tabs
  document.querySelectorAll(".tab").forEach(el => {
    if (el.dataset.tab === "analysis") el.textContent = t("tabAnalysis");
    if (el.dataset.tab === "ci-stats") el.textContent = t("tabCIStats");
  });

  // Analysis tab elements
  const sevSel = document.getElementById("severityFilter");
  if (sevSel) {
    sevSel.options[0].text = t("allSeverities");
    for (let i = 1; i < sevSel.options.length; i++) sevSel.options[i].text = tSeverity(sevSel.options[i].value);
  }
  const catSel = document.getElementById("categoryFilter");
  if (catSel) {
    catSel.options[0].text = t("allCategories");
    for (let i = 1; i < catSel.options.length; i++) catSel.options[i].text = tCategory(catSel.options[i].value);
  }
  document.getElementById("searchInput").placeholder = t("searchPlaceholder");

  // Chart titles
  const elSeverity = document.getElementById("chartSeverityTitle");
  const elWorkflow = document.getElementById("chartWorkflowTitle");
  const elCategory = document.getElementById("chartCategoryTitle");
  const elSection = document.getElementById("reportSectionTitle");
  if (elSeverity) elSeverity.textContent = t("severityBreakdown");
  if (elWorkflow) elWorkflow.textContent = t("topWorkflows");
  if (elCategory) elCategory.textContent = t("categoryBreakdown");
  if (elSection) elSection.textContent = t("recentReports");

  // CI tab chart titles
  const elDur = document.getElementById("chartDurationTitle");
  const elQueue = document.getElementById("chartQueueTitle");
  const elSuccess = document.getElementById("chartSuccessTitle");
  const elSlow = document.getElementById("chartSlowestTitle");
  if (elDur) elDur.textContent = t("ciDurationDist");
  if (elQueue) elQueue.textContent = t("ciQueueWait");
  if (elSuccess) elSuccess.textContent = t("ciSuccessByWF");
  if (elSlow) elSlow.textContent = t("ciSlowestJobs");
  const elCiTable = document.getElementById("ciTableTitle");
  if (elCiTable) elCiTable.textContent = t("ciTableTitle");
  // CI table headers
  ["ciThWorkflow","ciThStatus","ciThJobs","ciThWallClock","ciThAvgJob","ciThConcurrency","ciThEfficiency"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = t(id);
  });
}

// ── Tab Switching ──

function switchTab(name) {
  activeTab = name;
  document.querySelectorAll(".tab").forEach(el => el.classList.toggle("active", el.dataset.tab === name));
  document.querySelectorAll(".tab-content").forEach(el => el.classList.toggle("active", el.id === `tab-${name}`));

  if (name === "analysis") {
    renderMetrics();
    if (allAnalyses.length) renderCharts();
  } else if (name === "ci-stats") {
    if (allJobs.length) renderCIStats();
  }
}

// ── Data Loading ──

async function loadReports() {
  applyI18n();
  document.getElementById("reportList").innerHTML = `<div class="loading">${t("loading")}</div>`;

  try {
    const resp = await fetch(INDEX_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    allReports = data.reports || [];
    renderMetrics();
    renderReports();
    loadAnalysesData();
  } catch (err) {
    document.getElementById("reportList").innerHTML =
      `<div class="loading" style="color:var(--critical)">${t("loadFailed")}<br><small>${err.message}</small></div>`;
  }
}

async function loadAnalysesData() {
  allAnalyses = [];
  allJobs = [];
  for (const r of allReports) {
    try {
      const resp = await fetch(r.json_path);
      if (!resp.ok) continue;
      const data = await resp.json();

      // Analysis (failed job intelligence)
      for (const a of data.analyses || []) {
        if (a.confidence > 0) {
          a._pr_number = r.pr_number;
          a._pr_title = r.pr_title;
          a._analyzed_at = r.analyzed_at;
          a._category = classifyJob(a, a.job_name);
          const parts = a.job_name.split(" / ");
          a._workflow = parts[0] || "unknown";
          allAnalyses.push(a);
        }
      }

      // All jobs from runs (for CI execution stats)
      for (const run of data.runs || []) {
        for (const job of run.jobs || []) {
          if (job.started_at && job.completed_at) {
            const started = new Date(job.started_at);
            const completed = new Date(job.completed_at);
            const created = new Date(run.created_at || job.started_at);
            allJobs.push({
              job_name: job.job_name,
              job_id: job.job_id,
              conclusion: job.conclusion,
              workflow_name: run.workflow_name,
              run_id: run.run_id,
              branch: run.branch,
              started_at: job.started_at,
              completed_at: job.completed_at,
              duration: (completed - started) / 1000,
              queue_time: (started - created) / 1000,
              pr_number: r.pr_number,
            });
          }
        }
      }
    } catch (e) { /* skip */ }
  }

  if (allAnalyses.length) renderCharts();
  if (allJobs.length && activeTab === "ci-stats") renderCIStats();
}

// ── Metrics (Analysis Tab) ──

function renderMetrics() {
  const totalPRs = allReports.length;
  const totalJobs = allReports.reduce((s, r) => s + r.failed_job_count, 0);
  let crit = 0, high = 0, med = 0, low = 0;
  allReports.forEach(r => {
    if (r.top_severity === "critical") crit++;
    else if (r.top_severity === "high") high++;
    else if (r.top_severity === "medium") med++;
    else low++;
  });
  const avgConf = totalJobs > 0 ? Math.round((crit * 90 + high * 80 + med * 70 + low * 60) / Math.max(1, crit + high + med + low)) : 0;

  document.getElementById("metrics").innerHTML = `
    <div class="metric-card clickable" onclick="showDrillDown('all','all','${t("totalPRs")}')"><div class="metric-value">${totalPRs}</div><div class="metric-label">${t("totalPRs")}</div></div>
    <div class="metric-card clickable" onclick="showDrillDown('all','all','${t("totalJobs")}')"><div class="metric-value">${totalJobs}</div><div class="metric-label">${t("totalJobs")}</div></div>
    <div class="metric-card critical clickable" onclick="showDrillDown('severity','critical','${tSeverity("critical")}')"><div class="metric-value">${crit}</div><div class="metric-label">${tSeverity("critical")}</div></div>
    <div class="metric-card high clickable" onclick="showDrillDown('severity','high','${tSeverity("high")}')"><div class="metric-value">${high}</div><div class="metric-label">${tSeverity("high")}</div></div>
    <div class="metric-card medium clickable" onclick="showDrillDown('severity','medium','${tSeverity("medium")}')"><div class="metric-value">${med}</div><div class="metric-label">${tSeverity("medium")}</div></div>
    <div class="metric-card low clickable" onclick="showDrillDown('severity','low','${tSeverity("low")}')"><div class="metric-value">${low}</div><div class="metric-label">${tSeverity("low")}</div></div>
    <div class="metric-card"><div class="metric-value">${avgConf}%</div><div class="metric-label">${t("avgConf")}</div></div>
  `;
}

// ── Charts (Analysis Tab) ──

function destroyCharts() { Object.values(charts).forEach(c => c.destroy()); charts = {}; }

function renderCharts() {
  destroyCharts();
  if (!allAnalyses.length) return;
  renderSeverityChart();
  renderWorkflowChart();
  renderCategoryChart();
}

function renderSeverityChart() {
  const counts = { critical: 0, high: 0, medium: 0, low: 0 };
  allAnalyses.forEach(a => { counts[a.severity] = (counts[a.severity] || 0) + 1; });
  const labels = [tSeverity("critical"), tSeverity("high"), tSeverity("medium"), tSeverity("low")];
  const data = [counts.critical, counts.high, counts.medium, counts.low];
  const colors = ["#dc2626", "#ea580c", "#ca8a04", "#16a34a"];
  const sevKeys = ["critical", "high", "medium", "low"];

  charts.severity = new Chart(document.getElementById("chartSeverity"), {
    type: "doughnut",
    data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: "#161b22", borderWidth: 2 }] },
    options: {
      responsive: true, maintainAspectRatio: true,
      onClick: (e, els) => { if (els.length) showDrillDown("severity", sevKeys[els[0].index], tSeverity(sevKeys[els[0].index])); },
      plugins: { legend: { position: "bottom", labels: { color: "#8b949e", padding: 16, font: { size: 12 } } } },
    },
  });
}

function renderWorkflowChart() {
  const wfCounts = {};
  allAnalyses.forEach(a => { wfCounts[a._workflow] = (wfCounts[a._workflow] || 0) + 1; });
  const sorted = Object.entries(wfCounts).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const wfKeys = sorted.map(([k]) => k);

  charts.workflow = new Chart(document.getElementById("chartWorkflow"), {
    type: "bar",
    data: { labels: wfKeys, datasets: [{ data: sorted.map(([, v]) => v), backgroundColor: "#1f6feb", borderRadius: 4 }] },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: true,
      onClick: (e, els) => { if (els.length) showDrillDown("workflow", wfKeys[els[0].index], wfKeys[els[0].index]); },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 } } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });
}

function renderCategoryChart() {
  const catCounts = {};
  allAnalyses.forEach(a => { catCounts[a._category] = (catCounts[a._category] || 0) + 1; });
  const order = ["code", "build", "infra", "test", "lint", "compat", "perf", "other"];
  const catKeys = order.filter(k => catCounts[k]);
  const labels = catKeys.map(k => tCategory(k));
  const data = catKeys.map(k => catCounts[k]);
  const colors = { code: "#8957e5", build: "#3fb950", infra: "#d29922", test: "#58a6ff", compat: "#f778ba", perf: "#f85149", lint: "#ca8a04", other: "#8b949e" };
  const bgColors = catKeys.map(k => colors[k] || "#8b949e");

  charts.category = new Chart(document.getElementById("chartCategory"), {
    type: "bar",
    data: { labels, datasets: [{ data, backgroundColor: bgColors, borderRadius: 4 }] },
    options: {
      responsive: true, maintainAspectRatio: true,
      onClick: (e, els) => { if (els.length) showDrillDown("category", catKeys[els[0].index], tCategory(catKeys[els[0].index])); },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
        y: { grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 }, stepSize: 1 } },
      },
    },
  });
}

// ── CI Execution Analysis ──

function destroyCICharts() { Object.values(ciCharts).forEach(c => c.destroy()); ciCharts = {}; }

function percentile(arr, p) {
  if (!arr.length) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx), hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (idx - lo) * (sorted[hi] - sorted[lo]);
}

function fmtDuration(seconds) {
  if (seconds < 60) return `${Math.round(seconds)}${t("ciSeconds")}`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}${t("ciMinutes")}`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function renderCIStats() {
  if (!allJobs.length) return;
  destroyCICharts();

  // ── Job-level metrics ──
  const durations = allJobs.map(j => j.duration).filter(d => d > 0);
  const queueTimes = allJobs.map(j => j.queue_time).filter(q => q >= 0);
  const avgDur = durations.reduce((s, d) => s + d, 0) / durations.length;
  const totalJobs = allJobs.length;
  const success = allJobs.filter(j => j.conclusion === "success").length;

  // ── Workflow-run-level metrics ──
  const wfKey = j => `${j.workflow_name}::${j.run_id}`;
  const wfGroups = {};
  allJobs.forEach(j => { (wfGroups[wfKey(j)] ||= []).push(j); });

  _wfRuns = Object.values(wfGroups).map(jobs => {
    const starts = jobs.map(j => new Date(j.started_at));
    const ends = jobs.map(j => new Date(j.completed_at));
    const firstStart = new Date(Math.min(...starts));
    const lastEnd = new Date(Math.max(...ends));
    const wallClock = (lastEnd - firstStart) / 1000;
    const sumDur = jobs.reduce((s, j) => s + j.duration, 0);
    // Compute max concurrency: count overlapping jobs
    const events = [];
    jobs.forEach(j => {
      events.push({ t: new Date(j.started_at), d: 1 });
      events.push({ t: new Date(j.completed_at), d: -1 });
    });
    events.sort((a, b) => a.t - b.t);
    let cur = 0, maxConc = 0;
    events.forEach(e => { cur += e.d; maxConc = Math.max(maxConc, cur); });
    return {
      workflow_name: jobs[0].workflow_name,
      run_id: jobs[0].run_id,
      wallClock,
      sumDur,
      jobCount: jobs.length,
      maxConcurrency: maxConc,
      parallelEfficiency: sumDur / wallClock, // >1 means parallel
      success: jobs.filter(j => j.conclusion === "success").length,
      total: jobs.length,
    };
  });

  const wcDurations = _wfRuns.map(w => w.wallClock);
  const wfTotal = _wfRuns.length;
  const wfAvgWC = wcDurations.reduce((s, d) => s + d, 0) / wfTotal;
  const wfAvgJobs = _wfRuns.reduce((s, w) => s + w.jobCount, 0) / wfTotal;
  const wfAvgEfficiency = _wfRuns.reduce((s, w) => s + w.parallelEfficiency, 0) / wfTotal;

  // ── Metric cards: Job row + Workflow row ──
  document.getElementById("ciMetrics").innerHTML = `
    <div style="grid-column:1/-1;font-size:12px;color:var(--text-dim);margin-bottom:-8px">Job 维度</div>
    <div class="metric-card"><div class="metric-value">${totalJobs}</div><div class="metric-label">${t("ciTotalJobs")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(avgDur)}</div><div class="metric-label">${t("ciAvgDuration")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(percentile(durations, 50))}</div><div class="metric-label">${t("ciJobP50")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(percentile(durations, 90))}</div><div class="metric-label">${t("ciJobP90")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(percentile(durations, 20))}</div><div class="metric-label">${t("ciJobP20")}</div></div>
    <div class="metric-card clickable" onclick="showQueueDetail()"><div class="metric-value">${fmtDuration(percentile(queueTimes, 50))}</div><div class="metric-label">${t("ciQueueTime")}</div></div>
    <div class="metric-card"><div class="metric-value">${totalJobs ? Math.round(success / totalJobs * 100) : 0}%</div><div class="metric-label">${t("ciSuccessRate")}</div></div>
    <div style="grid-column:1/-1;font-size:12px;color:var(--text-dim);margin-bottom:-8px;margin-top:8px">Workflow 维度 <span style="color:var(--text-dim);font-weight:400">(wall-clock)</span></div>
    <div class="metric-card"><div class="metric-value">${wfTotal}</div><div class="metric-label">${t("ciWfTotal")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(wfAvgWC)}</div><div class="metric-label">${t("ciWfAvgWC")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(percentile(wcDurations, 50))}</div><div class="metric-label">${t("ciWfP50")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(percentile(wcDurations, 90))}</div><div class="metric-label">${t("ciWfP90")}</div></div>
    <div class="metric-card"><div class="metric-value">${wfAvgJobs.toFixed(0)}</div><div class="metric-label">${t("ciWfAvgJobs")}</div></div>
    <div class="metric-card"><div class="metric-value">${wfAvgEfficiency.toFixed(1)}x</div><div class="metric-label">${t("ciWfEfficiency")}</div></div>
    <div class="metric-card"><div class="metric-value">${Math.round(_wfRuns.reduce((s,w)=>s+w.success/w.total,0)/wfTotal*100)}%</div><div class="metric-label">${t("ciWfSuccess")}</div></div>
  `;

  // Duration distribution - boxplot-like bar with P20/P50/P90 markers
  const p20 = percentile(durations, 20), p50 = percentile(durations, 50), p90 = percentile(durations, 90);
  const maxDur = Math.max(...durations, 1);

  // Histogram buckets
  const buckets = 20;
  const bucketSize = maxDur / buckets;
  const hist = new Array(buckets).fill(0);
  durations.forEach(d => {
    const b = Math.min(Math.floor(d / bucketSize), buckets - 1);
    hist[b]++;
  });
  const histLabels = Array.from({ length: buckets }, (_, i) => fmtDuration(i * bucketSize));

  ciCharts.duration = new Chart(document.getElementById("chartDuration"), {
    type: "bar",
    data: {
      labels: histLabels,
      datasets: [{ data: hist, backgroundColor: "#1f6feb", borderRadius: 2, barPercentage: 1, categoryPercentage: 1 }],
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        annotation: false,
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8b949e", font: { size: 9 }, maxTicksLimit: 10 } },
        y: { grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 } } },
      },
    },
  });

  // Queue time by workflow
  const wfQueue = {};
  allJobs.forEach(j => {
    if (!wfQueue[j.workflow_name]) wfQueue[j.workflow_name] = [];
    wfQueue[j.workflow_name].push(j.queue_time);
  });
  const wfSorted = Object.entries(wfQueue).map(([k, v]) => [k, v.reduce((s, d) => s + d, 0) / v.length]).sort((a, b) => b[1] - a[1]).slice(0, 8);

  ciCharts.queue = new Chart(document.getElementById("chartQueue"), {
    type: "bar",
    data: {
      labels: wfSorted.map(([k]) => k),
      datasets: [{ data: wfSorted.map(([, v]) => v), backgroundColor: "#d29922", borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 }, callback: v => fmtDuration(v) } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });

  // Success rate by workflow (with actual success/fail counts)
  const wfResults = {};
  allJobs.forEach(j => {
    if (!wfResults[j.workflow_name]) wfResults[j.workflow_name] = { success: 0, failure: 0, skipped: 0 };
    const c = j.conclusion || "skipped";
    wfResults[j.workflow_name][c] = (wfResults[j.workflow_name][c] || 0) + 1;
  });
  const wfRates = Object.entries(wfResults).map(([k, v]) => ({ name: k, rate: (v.success || 0) / ((v.success || 0) + (v.failure || 0) + (v.skipped || 0)) * 100, ...v })).sort((a, b) => a.rate - b.rate).reverse().slice(0, 10);

  ciCharts.success = new Chart(document.getElementById("chartSuccess"), {
    type: "bar",
    data: {
      labels: wfRates.map(w => w.name),
      datasets: [
        { label: t("ciSuccess"), data: wfRates.map(w => w.success), backgroundColor: "#16a34a" },
        { label: t("ciFailed"), data: wfRates.map(w => w.failure), backgroundColor: "#dc2626" },
        { label: t("ciSkipped"), data: wfRates.map(w => w.skipped), backgroundColor: "#8b949e" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 10 }, maxRotation: 45 } },
        y: { stacked: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 } } },
      },
    },
  });

  // Slowest jobs
  const slowest = allJobs.sort((a, b) => b.duration - a.duration).slice(0, 10);
  ciCharts.slowest = new Chart(document.getElementById("chartSlowest"), {
    type: "bar",
    data: {
      labels: slowest.map(j => j.job_name.length > 40 ? j.job_name.slice(0, 40) + "..." : j.job_name),
      datasets: [{ data: slowest.map(j => j.duration), backgroundColor: slowest.map(j => j.conclusion === "failure" ? "#dc2626" : j.conclusion === "success" ? "#16a34a" : "#8b949e"), borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 }, callback: v => fmtDuration(v) } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 10 } } },
      },
    },
  });

  // ── Workflow Runs Detail Table ──
  const tbody = document.getElementById("ciTableBody");
  if (!tbody) return;

  const rows = _wfRuns.sort((a, b) => b.wallClock - a.wallClock);
  tbody.innerHTML = rows.map((w, i) => {
    const statusBadge = w.success === w.total
      ? `<span class="badge badge-low">PASS</span>`
      : w.success === 0
        ? `<span class="badge badge-critical">FAIL</span>`
        : `<span class="badge badge-high">${w.success}/${w.total}</span>`;
    const concBar = w.total > 0
      ? `<span style="display:inline-block;width:60px;height:6px;border-radius:3px;background:var(--border);vertical-align:middle;overflow:hidden"><span style="display:block;height:100%;width:${w.maxConcurrency/w.total*100}%;background:var(--accent);border-radius:3px"></span></span>`
      : "";
    const effColor = w.parallelEfficiency > 2 ? "var(--low)" : w.parallelEfficiency > 1.2 ? "var(--medium)" : "var(--high)";
    const runUrl = `https://github.com/vllm-project/vllm-ascend/actions/runs/${w.run_id}`;
    return `<tr>
      <td>${i + 1}</td>
      <td title="${escapeHtml(w.workflow_name)}"><a href="${runUrl}" target="_blank" rel="noopener" style="color:var(--link);text-decoration:none" onclick="event.stopPropagation()">${escapeHtml(w.workflow_name.length > 28 ? w.workflow_name.slice(0,28)+"..." : w.workflow_name)}</a></td>
      <td>${statusBadge}</td>
      <td>${w.jobCount}</td>
      <td>${fmtDuration(w.wallClock)}</td>
      <td>${fmtDuration(w.sumDur / w.jobCount)}</td>
      <td>${w.maxConcurrency} ${concBar}</td>
      <td style="color:${effColor}">${w.parallelEfficiency.toFixed(1)}x</td>
    </tr>`;
  }).join("");
}

// ── Report List ──

function renderReports() {
  const search = (document.getElementById("searchInput").value || "").toLowerCase();
  const severity = document.getElementById("severityFilter").value;
  const category = document.getElementById("categoryFilter").value;
  const el = document.getElementById("reportList");

  let filtered = allReports.filter(r => {
    const text = `${r.pr_number} ${r.pr_title}`.toLowerCase();
    if (search && !text.includes(search)) return false;
    if (severity && r.top_severity !== severity) return false;
    return true;
  });

  if (category && allAnalyses.length) {
    const catPRs = new Set(allAnalyses.filter(a => a._category === category).map(a => a._pr_number));
    filtered = filtered.filter(r => catPRs.has(r.pr_number));
  }

  if (!filtered.length) { el.innerHTML = `<div class="empty">${t("noReports")}</div>`; return; }

  el.innerHTML = filtered.map(r => {
    const date = new Date(r.analyzed_at).toLocaleDateString(currentLang === "zh" ? "zh-CN" : "en-US", { month: "short", day: "numeric" });
    return `
      <div class="report-card" onclick="openDetail(${r.pr_number})">
        <div class="card-left">
          <span class="card-pr">#${r.pr_number}</span>
          <span class="card-title">${escapeHtml(r.pr_title)}</span>
        </div>
        <div class="card-right">
          <span class="badge badge-${r.top_severity}">${tSeverity(r.top_severity)}</span>
          <span>${r.failed_job_count} ${t("jobs")}</span>
          <span>${date}</span>
        </div>
      </div>`;
  }).join("");
}

// ── Detail Modal ──

async function openDetail(prNumber) {
  const report = allReports.find(r => r.pr_number === prNumber);
  if (!report) return;
  const modal = document.getElementById("detailModal");
  document.getElementById("detailContent").innerHTML = `<div class="loading">${t("loading")}</div>`;
  modal.classList.add("open");
  try {
    const resp = await fetch(report.json_path);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    renderDetail(await resp.json());
  } catch (err) {
    document.getElementById("detailContent").innerHTML = `<div class="loading" style="color:var(--critical)">${t("detailFailed")}: ${err.message}</div>`;
  }
}

function renderDetail(data) {
  const analyses = data.analyses || [];
  const runs = data.runs || [];
  const dateLocale = currentLang === "zh" ? "zh-CN" : "en-US";

  let html = `<h2>#${data.pr_number} ${escapeHtml(data.pr_title)}</h2>`;
  html += `<div class="meta-line">${t("author")}: ${escapeHtml(data.pr_author)}</div>`;
  html += `<div class="meta-line">URL: <a href="${escapeHtml(data.pr_url)}" target="_blank">${escapeHtml(data.pr_url)}</a></div>`;
  html += `<div class="meta-line">${t("analyzed")}: ${new Date(data.analyzed_at).toLocaleString(dateLocale)}</div>`;
  html += `<h3>${t("affectedRuns")}</h3>`;
  if (!runs.length) {
    html += `<div class="meta-line">${t("noRuns")}</div>`;
  } else {
    runs.forEach(run => {
      html += `<div class="meta-line"><strong>${escapeHtml(run.workflow_name)}</strong> (${run.run_id}) — ${run.conclusion} @ ${escapeHtml(run.branch)}</div>`;
    });
  }
  html += `<h3>${t("analysis")} (${analyses.length} ${t("failedJobs")})</h3>`;
  if (!analyses.length) {
    html += `<div class="empty">${t("noAnalysis")}</div>`;
  } else {
    analyses.forEach(a => {
      const cat = classifyJob(a, a.job_name);
      html += `<h4><span class="badge badge-${a.severity}">${tSeverity(a.severity)}</span> <span class="badge badge-${cat}">${tCategory(cat)}</span> ${escapeHtml(a.job_name)} <small style="color:var(--text-dim)">(${t("confidence")}: ${a.confidence}%)</small></h4>`;
      html += `<div class="root-cause">${escapeHtml(a.root_cause || t("noRootCause"))}</div>`;
      if (a.error_snippets && a.error_snippets.length) {
        html += `<div><strong>${t("errorSnippets")}</strong></div>`;
        a.error_snippets.forEach(s => { html += `<div class="snippet">${escapeHtml(s)}</div>`; });
      }
      if (a.related_files && a.related_files.length) {
        html += `<div><strong>${t("relatedFiles")}</strong></div><ul class="file-list">`;
        a.related_files.forEach(f => { html += `<li>${escapeHtml(f)}</li>`; });
        html += "</ul>";
      }
      if (a.fix_suggestions && a.fix_suggestions.length) {
        html += `<div><strong>${t("fixSuggestions")}</strong></div><ul class="suggestions">`;
        a.fix_suggestions.forEach(s => { html += `<li>${escapeHtml(s)}</li>`; });
        html += "</ul>";
      }
    });
  }
  document.getElementById("detailContent").innerHTML = html;
}

function closeDetail() { document.getElementById("detailModal").classList.remove("open"); }

// ── Drill Down ──

let _wfRuns = []; // cached for queue detail drill-down

// ... (set in renderCIStats)

function showQueueDetail() {
  if (!_wfRuns.length) return;

  // Queue stats by workflow run
  const wfQueueStats = _wfRuns.map(w => {
    const jobs = allJobs.filter(j => j.run_id === w.run_id && j.workflow_name === w.workflow_name);
    const qTimes = jobs.map(j => j.queue_time).filter(q => q >= 0);
    return {
      workflow_name: w.workflow_name,
      run_id: w.run_id,
      totalJobs: jobs.length,
      queuedJobs: qTimes.length,
      avgQueue: qTimes.length ? qTimes.reduce((s, v) => s + v, 0) / qTimes.length : 0,
      maxQueue: qTimes.length ? Math.max(...qTimes) : 0,
      p90Queue: percentile(qTimes, 90),
    };
  }).sort((a, b) => b.avgQueue - a.avgQueue);

  const totalQueuedWFs = wfQueueStats.filter(w => w.queuedJobs > 0).length;
  const totalQueuedJobs = wfQueueStats.reduce((s, w) => s + w.queuedJobs, 0);
  const overallAvgQ = totalQueuedJobs ? wfQueueStats.reduce((s, w) => s + w.avgQueue * w.queuedJobs, 0) / totalQueuedJobs : 0;

  let html = `<h2>${t("ciQueueTime")} <span style="color:var(--text-dim);font-size:14px">(${totalQueuedWFs} Workflows, ${totalQueuedJobs} Jobs)</span></h2>`;
  html += `<div style="display:flex;gap:16px;margin:16px 0;flex-wrap:wrap">
    <div class="metric-card"><div class="metric-value">${totalQueuedWFs}</div><div class="metric-label">Queued Workflows</div></div>
    <div class="metric-card"><div class="metric-value">${totalQueuedJobs}</div><div class="metric-label">Queued Jobs</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(overallAvgQ)}</div><div class="metric-label">Avg Queue Time</div></div>
  </div>`;

  // Table of top queued runs
  html += `<div class="table-wrap"><table class="data-table">
    <thead><tr><th>#</th><th>Workflow</th><th>Jobs</th><th>Avg Queue</th><th>Max Queue</th><th>P90 Queue</th></tr></thead>
    <tbody>`;

  wfQueueStats.filter(w => w.queuedJobs > 0).slice(0, 20).forEach((w, i) => {
    const runUrl = `https://github.com/vllm-project/vllm-ascend/actions/runs/${w.run_id}`;
    html += `<tr>
      <td>${i + 1}</td>
      <td><a href="${runUrl}" target="_blank" rel="noopener" style="color:var(--link)">${escapeHtml(w.workflow_name.length > 40 ? w.workflow_name.slice(0,40)+"..." : w.workflow_name)}</a></td>
      <td>${w.queuedJobs}/${w.totalJobs}</td>
      <td>${fmtDuration(w.avgQueue)}</td>
      <td>${fmtDuration(w.maxQueue)}</td>
      <td>${fmtDuration(w.p90Queue)}</td>
    </tr>`;
  });

  html += `</tbody></table></div>`;
  document.getElementById("detailContent").innerHTML = html;
  document.getElementById("detailModal").classList.add("open");
}

function showDrillDown(filterType, filterValue, displayName) {
  let matches;
  if (filterType === "severity") matches = allAnalyses.filter(a => a.severity === filterValue);
  else if (filterType === "workflow") matches = allAnalyses.filter(a => a._workflow === filterValue);
  else if (filterType === "all") matches = allAnalyses;
  else matches = allAnalyses.filter(a => a._category === filterValue);

  const grouped = {};
  matches.forEach(a => {
    if (!grouped[a._pr_number]) grouped[a._pr_number] = [];
    grouped[a._pr_number].push(a);
  });

  const dateLocale = currentLang === "zh" ? "zh-CN" : "en-US";
  let html = `<h2>${displayName} <span style="color:var(--text-dim);font-size:14px">(${matches.length} ${t("jobs")})</span></h2>`;

  for (const [prNum, items] of Object.entries(grouped)) {
    const pr = allReports.find(r => r.pr_number === parseInt(prNum));
    html += `<div style="margin:16px 0 8px">
      <a href="javascript:void(0)" onclick="closeDetail();openDetail(${prNum})" style="color:var(--link);font-weight:600;font-size:15px">#${prNum}</a>
      <span style="color:var(--text-dim);font-size:13px;margin-left:8px">${escapeHtml(pr ? pr.pr_title : "")}</span>
    </div>`;
    items.forEach(a => {
      const date = new Date(a._analyzed_at).toLocaleDateString(dateLocale, { month: "short", day: "numeric" });
      html += `<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin:6px 0">
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">
          <span class="badge badge-${a.severity}">${tSeverity(a.severity)}</span>
          <span class="badge badge-${a._category}">${tCategory(a._category)}</span>
          <span style="font-size:13px;color:var(--text-dim)">${escapeHtml(a.job_name)}</span>
          <span style="font-size:12px;color:var(--text-dim);margin-left:auto">${date} · ${a.confidence}%</span>
        </div>
        <div class="root-cause" style="font-size:13px;margin:0">${escapeHtml(a.root_cause || t("noRootCause"))}</div>
        ${a.fix_suggestions && a.fix_suggestions.length ? `<div style="margin-top:6px;font-size:12px;color:var(--text-dim)">${t("fixSuggestions")} ${escapeHtml(a.fix_suggestions[0])}</div>` : ""}
      </div>`;
    });
  }
  document.getElementById("detailContent").innerHTML = html;
  document.getElementById("detailModal").classList.add("open");
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// ── Event Handlers ──

document.getElementById("searchInput").addEventListener("input", renderReports);
document.getElementById("severityFilter").addEventListener("change", renderReports);
document.getElementById("categoryFilter").addEventListener("change", renderReports);

// ── Boot ──

applyI18n();
loadReports();
