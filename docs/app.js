const INDEX_URL = "reports/index.json";
const CI_RUNS_URL = "reports/ci-runs.json";
const COVERAGE_URL = "reports/coverage.json";
let allReports = [];
let allAnalyses = [];
let allJobs = []; // Current CI jobs when ci-runs.json exists, otherwise historical report jobs.
let historicalJobs = [];
let ciMetadata = null;
let ciCoverage = null;
let ciMetadataLoaded = false;
let ciWorkflowRuns = [];
let charts = {};

// ---- Loaded from config/rules.json (single source of truth) ----
let PIPELINE_PATTERNS = null;
let CATEGORY_RULES = null;

async function loadRules() {
  if (CATEGORY_RULES) return;
  try {
    const resp = await fetchReportJson("rules.json");
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const cfg = await resp.json();
    PIPELINE_PATTERNS = {};
    for (const [pt, def] of Object.entries(cfg.pipeline_types || {})) {
      if (def.patterns && def.patterns.length)
        PIPELINE_PATTERNS[pt] = def.patterns.map(p => new RegExp(p));
    }
    CATEGORY_RULES = (cfg.categories || []).map(c =>
      [c.key, new RegExp(c.patterns.join("|"), "i")]
    );
  } catch (e) {
    console.warn("config/rules.json unavailable, using fallback rules");
    _loadFallbackRules();
  }
}

function _loadFallbackRules() {
  PIPELINE_PATTERNS = {
    pr_e2e: [/E2E-Light/, /E2E-Full/, /PR Create/, /Merge Conflict/, /Image Build/, /Docs link check/, /Cache csrc/],
    nightly: [/Nightly-A2/, /Nightly-A3/, /vLLM Main Schedule/],
  };
  CATEGORY_RULES = [
    ["lint", /(\bruff\b|pre-commit|E\d{3}|F\d{3}|unused\s+import|line\s+too\s+long|undefined\s+name)/i],
    ["build", /(\bcmake\b|pip\s+install|uv\s+pip|setup\.py|build\s+(?:fail|error)|UV_INDEX|package\s.*not\s+found)/i],
    ["perf", /(\bOOM\b|out of memory|killed|timed?\s?out|timeout)/i],
    ["infra", /(runner\s+(?:disconnect|fail)|connection\s+refused|rate\s?limit|HTTP\s*404)/i],
    ["test", /(\baccuracy\s+test\b|assert.*\b(?:fail|error)\b|\bflaky\s+test\b|\bregression\b)/i],
    ["compat", /(\bdeprecated\b|\bremoved\b.*\b(?:in|from)\b|\brenamed\b.*\bto\b|no\s+longer\s+exists|incompatible)/i],
    ["code", /(\bImportError\b|\bAttributeError\b|\bModuleNotFoundError\b|undefined\s+name|not\s+defined|has\s+no\s+attribute)/i],
  ];
}

function classifyPipeline(wfName) {
  if (!PIPELINE_PATTERNS) return "other";
  for (const [pt, pats] of Object.entries(PIPELINE_PATTERNS)) {
    for (const p of pats) { if (p.test(wfName)) return pt; }
  }
  return "other";
}

let ciCharts = {};
let activeTab = "analysis";

function reportUrl(path) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}_=${Date.now()}`;
}

function fetchReportJson(path) {
  return fetch(reportUrl(path), { cache: "no-store" });
}

function resetLoadedData() {
  allReports = [];
  allAnalyses = [];
  allJobs = [];
  historicalJobs = [];
  ciMetadata = null;
  ciCoverage = null;
  ciMetadataLoaded = false;
  ciWorkflowRuns = [];
}

function refreshDashboard() {
  resetLoadedData();
  destroyCharts();
  Object.values(ciCharts).forEach(c => c.destroy());
  ciCharts = {};
  loadReports();
  if (activeTab === "health") loadHealthTab(true);
}

function classifyJob(analysis, jobName) {
  const text = [analysis.root_cause || "", (analysis.error_snippets || []).join(" "), jobName].join(" ");
  if (!CATEGORY_RULES) return "other";
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
    if (el.dataset.tab === "health") el.textContent = t("tabHealth");
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
  // Pipeline filter labels
  ["pipelineFilter", "ciPipelineFilter"].forEach(id => {
    const sel = document.getElementById(id);
    if (sel) {
      sel.options[0].text = t("allPipelines");
      for (let i = 1; i < sel.options.length; i++) {
        sel.options[i].text = t("pipeline_" + sel.options[i].value) || sel.options[i].value;
      }
    }
  });
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
    renderReports();  // Re-apply filters when switching back to this tab
  } else if (name === "ci-stats") {
    if (allJobs.length) renderCIStats();
  } else if (name === "health") {
    loadHealthTab();
  }
}

// ── Data Loading ──

async function loadReports() {
  applyI18n();
  document.getElementById("reportList").innerHTML = `<div class="loading">${t("loading")}</div>`;

  try {
    await loadCiMetadata();
    const resp = await fetchReportJson(INDEX_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    allReports = data.reports || [];
    renderDataSourceBanner(data);
    renderMetrics();
    renderReports();
    loadAnalysesData();
  } catch (err) {
    document.getElementById("reportList").innerHTML =
      `<div class="loading" style="color:var(--critical)">${t("loadFailed")}<br><small>${err.message}</small></div>`;
  }
}

async function loadCiMetadata() {
  if (ciMetadataLoaded) return ciMetadata;
  ciMetadataLoaded = true;
  try {
    const resp = await fetchReportJson(CI_RUNS_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    ciMetadata = await resp.json();
    ciCoverage = ciMetadata.coverage || null;
    try {
      const coverageResp = await fetchReportJson(COVERAGE_URL);
      if (coverageResp.ok) ciCoverage = await coverageResp.json();
    } catch (e) {
      // coverage.json is optional for older static exports.
    }
    const seenJobs = new Set();
    const jobs = [];
    ciWorkflowRuns = (ciMetadata.runs || []).map(run => {
      const runJobs = [];
      for (const job of run.jobs || []) {
        const jobId = job.job_id || `${run.run_id}:${job.job_name}:${job.started_at || ""}`;
        if (seenJobs.has(jobId)) continue;
        seenJobs.add(jobId);

        const started = job.started_at ? new Date(job.started_at) : null;
        const completed = job.completed_at ? new Date(job.completed_at) : null;
        const created = run.created_at ? new Date(run.created_at) : started;
        const item = {
          job_name: job.job_name,
          job_id: jobId,
          conclusion: normalizeConclusion(job.conclusion || run.conclusion),
          workflow_name: run.workflow_name,
          pipeline_type: run.pipeline_type || classifyPipeline(run.workflow_name),
          run_id: run.run_id,
          branch: run.branch,
          started_at: job.started_at,
          completed_at: job.completed_at,
          duration: started && completed ? Math.max(0, (completed - started) / 1000) : null,
          queue_time: started && created ? Math.max(0, (started - created) / 1000) : null,
          url: run.url,
          source: "ci_metadata",
        };
        jobs.push(item);
        runJobs.push(item);
      }
      return { ...run, jobs: runJobs };
    });
    allJobs = jobs;
  } catch (e) {
    ciMetadata = null;
    ciCoverage = null;
    ciWorkflowRuns = [];
  }
  return ciMetadata;
}

function normalizeConclusion(value) {
  if (!value) return "other";
  if (value === "completed") return "success";
  return value;
}

function formatTimestamp(value) {
  if (!value) return "unknown";
  return new Date(value).toLocaleString(currentLang === "zh" ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderDataSourceBanner(indexData) {
  const el = document.getElementById("dataSourceBanner");
  if (!el) return;
  const reportCount = allReports.length;
  const historicalTime = indexData?.generated_at ? formatTimestamp(indexData.generated_at) : "unknown";

  let ciText = "Current CI metadata unavailable; CI Execution falls back to historical failure reports.";
  if (ciMetadata) {
    const jobs = allJobs || [];
    const measured = jobs.filter(j => j.conclusion === "success" || j.conclusion === "failure").length;
    const skipped = jobs.filter(j => j.conclusion === "skipped").length;
    const pending = jobs.filter(j => ["queued", "in_progress", "pending"].includes(j.conclusion)).length;
    const byPipeline = ciMetadata.measured_jobs_by_pipeline || {};
    const target = ciMetadata.min_measured_per_pipeline || 0;
    const executionDates = ciMetadata.execution_dates || [];
    const executionTarget = ciMetadata.min_execution_days || 0;
    const inventoryCount = ciMetadata.run_inventory_count || ciMetadata.runs?.length || 0;
    const jobDetailRuns = ciMetadata.job_detail_runs_collected || ciMetadata.runs?.length || 0;
    const coverage = ciMetadata.job_detail_coverage_percent;
    const jobCoverage = ciCoverage?.job_details || null;
    const selection = ciMetadata.job_detail_selection;
    const targetText = target
      ? ` · target ${target}/pipeline (${Object.entries(byPipeline).map(([k, v]) => `${k}:${v}`).join(", ")})`
      : "";
    const dateText = executionDates.length
      ? ` | ${executionDates.length}${executionTarget ? `/${executionTarget}` : ""} execution day(s): ${executionDates[0]}..${executionDates[executionDates.length - 1]}`
      : "";
    const inventoryText = ciMetadata.collection_strategy === "date_partition"
      ? ` | inventory ${ciCoverage?.run_inventory?.total || inventoryCount} runs | job details ${jobCoverage?.collected_runs || jobDetailRuns}/${jobCoverage?.total_runs || inventoryCount}${jobCoverage?.coverage_percent !== undefined ? ` (${jobCoverage.coverage_percent}%, ${jobCoverage.quality})` : coverage !== undefined ? ` (${coverage}%)` : ""}${selection ? ` ${selection}` : ""}`
      : ` | ${ciMetadata.runs?.length || 0}/${ciMetadata.limit || "?"} runs`;
    ciText = `Current CI metadata: ${formatTimestamp(ciMetadata.generated_at)}${inventoryText} | ${measured}/${jobs.length} measured jobs | ${skipped} skipped | ${pending} pending${targetText}`;
    ciText += dateText;
  }

  el.innerHTML = `
    <div><strong>CI Execution / Health:</strong> ${escapeHtml(ciText)}</div>
    <div><strong>Problem Analysis:</strong> historical failure reports · ${reportCount} reports · generated ${escapeHtml(historicalTime)}</div>
    <div><strong>Refresh:</strong> reloads static JSON artifacts only; dynamic collection must update reports separately.</div>
  `;
}

async function loadAnalysesData() {
  await loadRules(); // ensure classification rules are loaded
  allAnalyses = [];
  historicalJobs = [];
  const seenJobIds = new Set();
  for (const r of allReports) {
    let data = null;
    try {
      const resp = await fetchReportJson(r.json_path);
      if (!resp.ok) continue;
      data = await resp.json();

      // Enrich report with CI execution time + pipeline types
      let earliestRun = null;
      const reportPTypes = new Set();
      for (const run of data.runs || []) {
        if (!earliestRun || run.created_at < earliestRun) earliestRun = run.created_at;
        const pt = run.pipeline_type || classifyPipeline(run.workflow_name);
        reportPTypes.add(pt);
      }
      if (earliestRun) r._ci_date = earliestRun;
      r._pipeline_types = [...reportPTypes];

      // Populate allJobs FIRST (needed by analysis enrichment below)
      for (const run of data.runs || []) {
        for (const job of run.jobs || []) {
          if (seenJobIds.has(job.job_id)) continue;
          seenJobIds.add(job.job_id);
          if (job.started_at && job.completed_at) {
            const started = new Date(job.started_at);
            const completed = new Date(job.completed_at);
            const created = new Date(run.created_at || job.started_at);
          historicalJobs.push({
              job_name: job.job_name,
              job_id: job.job_id,
              conclusion: job.conclusion,
              workflow_name: run.workflow_name,
              pipeline_type: run.pipeline_type || classifyPipeline(run.workflow_name),
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
    } catch (e) {
      continue;
    }

    // Now enrich analyses with pipeline type (allJobs is populated)
    try {
      for (const a of data?.analyses || []) {
        if (a.confidence > 0) {
          a._pr_number = r.pr_number;
          a._pr_title = r.pr_title;
          a._analyzed_at = r.analyzed_at;
          a._category = classifyJob(a, a.job_name);
          const parts = a.job_name.split(" / ");
          a._workflow = parts[0] || "unknown";
          const matchedJob = historicalJobs.find(j => j.job_id === a.job_id);
          a._pipeline_type = matchedJob ? matchedJob.pipeline_type : classifyPipeline(a.job_name);
          allAnalyses.push(a);
        }
      }
    } catch (e) { /* skip */ }
  }

  if (allAnalyses.length) {
    renderMetrics();
    renderCharts();
    renderReports();
  }
  if (!ciMetadata) allJobs = historicalJobs;
  if (allJobs.length && activeTab === "ci-stats") renderCIStats();
}

// ── Filtered Data Helpers ──

function getActiveFilters() {
  return {
    severity: document.getElementById("severityFilter")?.value || "",
    category: document.getElementById("categoryFilter")?.value || "",
    pipeline: document.getElementById("pipelineFilter")?.value || "",
  };
}

function getFilteredAnalyses() {
  const f = getActiveFilters();
  return allAnalyses.filter(a => {
    if (f.severity && a.severity !== f.severity) return false;
    if (f.category && a._category !== f.category) return false;
    // Pipeline: filter by the PR's pipeline types (enriched on load)
    if (f.pipeline && a._pipeline_type !== f.pipeline) return false;
    return true;
  });
}

// ── Metrics (Analysis Tab) ──

function renderMetrics() {
  const filtered = getFilteredAnalyses();
  const base = filtered.length ? filtered : allAnalyses;

  // ── Pipeline-level stats from allJobs ──
  const ptStats = {};
  const jobPool = historicalJobs.length ? historicalJobs : [];
  jobPool.forEach(j => {
    const pt = j.pipeline_type || "other";
    if (!ptStats[pt]) ptStats[pt] = { workflows: new Set(), runs: new Set(), total: 0, failed: 0 };
    ptStats[pt].workflows.add(j.workflow_name);
    ptStats[pt].runs.add(j.workflow_name + "::" + j.run_id);
    ptStats[pt].total++;
    if (j.conclusion === "failure") ptStats[pt].failed++;
  });

  // ── Severity counts from analyses ──
  const totalJobs = base.length;
  let crit = 0, high = 0, med = 0, low = 0, confSum = 0;
  base.forEach(a => {
    if (a.severity === "critical") crit++;
    else if (a.severity === "high") high++;
    else if (a.severity === "medium") med++;
    else low++;
    confSum += (a.confidence || 0);
  });
  const avgConf = totalJobs > 0 ? Math.round(confSum / totalJobs) : 0;

  // Pipeline metric cards
  const ptOrder = ["pr_e2e", "nightly", "other"];
  let ptCards = "";
  ptOrder.forEach(pt => {
    const s = ptStats[pt];
    if (!s || !s.total) return;
    const label = t("pipeline_" + pt) || pt;
    ptCards += `<div class="metric-card clickable" onclick="showPipelineDetail('${pt}')">
      <div class="metric-value">${s.failed}</div>
      <div class="metric-label">${label}</div>
      <div style="font-size:10px;color:var(--text-dim);margin-top:3px">${s.workflows.size} WF · ${s.runs.size} Runs · ${s.total} Jobs</div>
    </div>`;
  });

  document.getElementById("metrics").innerHTML = `
    ${ptCards}
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
  const data = allAnalyses.length ? (getFilteredAnalyses().length ? getFilteredAnalyses() : allAnalyses) : [];
  if (!data.length) return;
  renderSeverityChart(data);
  renderWorkflowChart(data);
  renderCategoryChart(data);
}

function renderSeverityChart(filtered) {
  const counts = { critical: 0, high: 0, medium: 0, low: 0 };
  filtered.forEach(a => { counts[a.severity] = (counts[a.severity] || 0) + 1; });
  const labels = [tSeverity("critical"), tSeverity("high"), tSeverity("medium"), tSeverity("low")];
  const data = [counts.critical, counts.high, counts.medium, counts.low];
  const colors = ["#dc2626", "#ea580c", "#ca8a04", "#16a34a"];
  const sevKeys = ["critical", "high", "medium", "low"];

  charts.severity = new Chart(document.getElementById("chartSeverity"), {
    type: "doughnut",
    data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: "#161b22", borderWidth: 2 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      onClick: (e, els) => { if (els.length) showDrillDown("severity", sevKeys[els[0].index], tSeverity(sevKeys[els[0].index])); },
      plugins: { legend: { position: "bottom", labels: { color: "#8b949e", padding: 16, font: { size: 12 } } } },
    },
  });
}

function renderWorkflowChart(filtered) {
  const wfCounts = {};
  filtered.forEach(a => { wfCounts[a._workflow] = (wfCounts[a._workflow] || 0) + 1; });
  const sorted = Object.entries(wfCounts).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const wfKeys = sorted.map(([k]) => k);

  charts.workflow = new Chart(document.getElementById("chartWorkflow"), {
    type: "bar",
    data: { labels: wfKeys, datasets: [{ data: sorted.map(([, v]) => v), backgroundColor: "#1f6feb", borderRadius: 4 }] },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, els) => { if (els.length) showDrillDown("workflow", wfKeys[els[0].index], wfKeys[els[0].index]); },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 } } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });
}

function renderCategoryChart(filtered) {
  const catCounts = {};
  filtered.forEach(a => { catCounts[a._category] = (catCounts[a._category] || 0) + 1; });
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
      responsive: true, maintainAspectRatio: false,
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
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "N/A";
  if (seconds < 60) return `${Math.round(seconds)}${t("ciSeconds")}`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}${t("ciMinutes")}`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function renderCIStats() {
  return renderCIStatsV2();
}

function renderCIStatsV2() {
  if (!allJobs.length) return;
  destroyCICharts();

  // Filter by pipeline type
  const ptFilter = document.getElementById("ciPipelineFilter")?.value || "";
  const jobs = ptFilter ? allJobs.filter(j => j.pipeline_type === ptFilter) : allJobs;

  // ── Job-level metrics ──
  const timedJobs = jobs.filter(j => j.duration !== null && j.duration !== undefined);
  const durations = timedJobs.map(j => j.duration).filter(d => d > 0);
  const queueTimes = jobs.map(j => j.queue_time).filter(q => q !== null && q !== undefined && q >= 0);
  const avgDur = durations.reduce((s, d) => s + d, 0) / (durations.length || 1);
  const totalJobs = jobs.length;
  const success = jobs.filter(j => j.conclusion === "success").length;
  const failure = jobs.filter(j => j.conclusion === "failure").length;
  const measured = success + failure;

  // ── Workflow-run-level metrics ──
  const wfKey = j => `${j.workflow_name}::${j.run_id}`;
  const wfGroups = {};
  jobs.forEach(j => { (wfGroups[wfKey(j)] ||= []).push(j); });

  _wfRuns = Object.values(wfGroups).map(jobs => {
    const starts = jobs.map(j => j.started_at ? new Date(j.started_at) : null).filter(Boolean);
    const ends = jobs.map(j => j.completed_at ? new Date(j.completed_at) : null).filter(Boolean);
    const firstStart = starts.length ? new Date(Math.min(...starts)) : null;
    const lastEnd = ends.length ? new Date(Math.max(...ends)) : firstStart;
    const wallClock = firstStart && lastEnd ? Math.max(0, (lastEnd - firstStart) / 1000) : null;
    const sumDur = jobs.reduce((s, j) => s + (j.duration || 0), 0);
    // Compute max concurrency: count overlapping jobs
    const events = [];
    jobs.forEach(j => {
      if (!j.started_at || !j.completed_at) return;
      events.push({ t: new Date(j.started_at), d: 1 });
      events.push({ t: new Date(j.completed_at), d: -1 });
    });
    events.sort((a, b) => a.t - b.t);
    let cur = 0, maxConc = 0;
    events.forEach(e => { cur += e.d; maxConc = Math.max(maxConc, cur); });
    return {
      workflow_name: jobs[0].workflow_name,
      run_id: jobs[0].run_id,
      jobs,
      wallClock,
      sumDur,
      jobCount: jobs.length,
      maxConcurrency: maxConc,
      parallelEfficiency: wallClock ? sumDur / wallClock : 0, // >1 means parallel
      success: jobs.filter(j => j.conclusion === "success").length,
      failure: jobs.filter(j => j.conclusion === "failure").length,
      total: jobs.length,
    };
  });

  const wcDurations = _wfRuns.map(w => w.wallClock).filter(d => d !== null && d !== undefined);
  const wfTotal = _wfRuns.length;
  const wfAvgWC = wcDurations.reduce((s, d) => s + d, 0) / (wcDurations.length || 1);
  const wfAvgJobs = _wfRuns.reduce((s, w) => s + w.jobCount, 0) / (wfTotal || 1);
  const wfAvgEfficiency = _wfRuns.reduce((s, w) => s + w.parallelEfficiency, 0) / (wfTotal || 1);

  // ── Metric cards: Job row + Workflow row ──
  document.getElementById("ciMetrics").innerHTML = `
    <div style="grid-column:1/-1;font-size:12px;color:var(--text-dim);margin-bottom:-8px">Job metrics ${ciMetadata ? "(current CI metadata)" : "(historical failure reports)"}</div>
    <div class="metric-card"><div class="metric-value">${totalJobs}</div><div class="metric-label">${t("ciTotalJobs")}</div></div>
    <div class="metric-card"><div class="metric-value">${measured}</div><div class="metric-label">Measured Jobs</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(avgDur)}</div><div class="metric-label">${t("ciAvgDuration")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(percentile(durations, 50))}</div><div class="metric-label">${t("ciJobP50")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(percentile(durations, 90))}</div><div class="metric-label">${t("ciJobP90")}</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(percentile(durations, 20))}</div><div class="metric-label">${t("ciJobP20")}</div></div>
    <div class="metric-card clickable" onclick="showQueueDetail()"><div class="metric-value">${fmtDuration(percentile(queueTimes, 50))}</div><div class="metric-label">${t("ciQueueTime")}</div></div>
    <div class="metric-card"><div class="metric-value">${measured ? Math.round(success / measured * 100) + "%" : "N/A"}</div><div class="metric-label">Measured Success Rate</div></div>
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
      responsive: true, maintainAspectRatio: false,
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
  jobs.forEach(j => {
    if (!wfQueue[j.workflow_name]) wfQueue[j.workflow_name] = [];
    if (j.queue_time !== null && j.queue_time !== undefined) wfQueue[j.workflow_name].push(j.queue_time);
  });
  const wfSorted = Object.entries(wfQueue)
    .filter(([, v]) => v.length)
    .map(([k, v]) => [k, v.reduce((s, d) => s + d, 0) / v.length])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);

  ciCharts.queue = new Chart(document.getElementById("chartQueue"), {
    type: "bar",
    data: {
      labels: wfSorted.map(([k]) => k),
      datasets: [{ data: wfSorted.map(([, v]) => v), backgroundColor: "#d29922", borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 }, callback: v => fmtDuration(v) } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });

  // Success rate by workflow (with actual success/fail counts)
  const wfResults = {};
  jobs.forEach(j => {
    if (!wfResults[j.workflow_name]) wfResults[j.workflow_name] = { success: 0, failure: 0, skipped: 0, pending: 0 };
    const c = j.conclusion || "skipped";
    if (["queued", "in_progress", "pending"].includes(c)) wfResults[j.workflow_name].pending++;
    else wfResults[j.workflow_name][c] = (wfResults[j.workflow_name][c] || 0) + 1;
  });
  const wfRates = Object.entries(wfResults)
    .map(([k, v]) => ({ name: k, measured: (v.success || 0) + (v.failure || 0), ...v }))
    .sort((a, b) => b.measured - a.measured || (b.failure || 0) - (a.failure || 0))
    .slice(0, 10);

  ciCharts.success = new Chart(document.getElementById("chartSuccess"), {
    type: "bar",
    data: {
      labels: wfRates.map(w => w.name),
      datasets: [
        { label: t("ciSuccess"), data: wfRates.map(w => w.success), backgroundColor: "#16a34a" },
        { label: t("ciFailed"), data: wfRates.map(w => w.failure), backgroundColor: "#dc2626" },
        { label: t("ciSkipped"), data: wfRates.map(w => w.skipped), backgroundColor: "#8b949e" },
        { label: "pending", data: wfRates.map(w => w.pending), backgroundColor: "#ca8a04" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 10 }, maxRotation: 45 } },
        y: { stacked: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 } } },
      },
    },
  });

  // Slowest jobs
  const slowest = [...timedJobs].sort((a, b) => b.duration - a.duration).slice(0, 10);
  ciCharts.slowest = new Chart(document.getElementById("chartSlowest"), {
    type: "bar",
    data: {
      labels: slowest.map(j => j.job_name.length > 40 ? j.job_name.slice(0, 40) + "..." : j.job_name),
      datasets: [{ data: slowest.map(j => j.duration), backgroundColor: slowest.map(j => j.conclusion === "failure" ? "#dc2626" : j.conclusion === "success" ? "#16a34a" : "#8b949e"), borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
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

  const rows = _wfRuns.sort((a, b) => (b.wallClock || 0) - (a.wallClock || 0));
  tbody.innerHTML = rows.map((w, i) => {
    const conclusions = new Set(w.jobs.map(j => j.conclusion));
    const statusBadge = w.failure > 0
      ? `<span class="badge badge-critical">FAIL</span>`
      : w.success === w.total
        ? `<span class="badge badge-low">PASS</span>`
        : conclusions.has("queued") || conclusions.has("in_progress") || conclusions.has("pending")
          ? `<span class="badge badge-medium">RUNNING</span>`
          : conclusions.has("skipped") && w.success === 0
            ? `<span class="badge badge-other">SKIPPED</span>`
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
      <td>${fmtDuration(w.sumDur / Math.max(1, w.jobCount))}</td>
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
  const pipeline = document.getElementById("pipelineFilter")?.value || "";
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

  // Pipeline filter: use enriched report data (works immediately)
  if (pipeline) {
    filtered = filtered.filter(r => r._pipeline_types && r._pipeline_types.includes(pipeline));
  }

  if (!filtered.length) { el.innerHTML = `<div class="empty">${t("noReports")}</div>`; return; }

  el.innerHTML = filtered.map(r => {
    const ciDate = r._ci_date || r.analyzed_at;
    const date = new Date(ciDate).toLocaleDateString(currentLang === "zh" ? "zh-CN" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
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
    const resp = await fetchReportJson(report.json_path);
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
  // Show CI execution time from runs, fall back to analysis time
  let ciExecTime = data.analyzed_at;
  if (data.runs && data.runs.length) {
    const earliest = data.runs.reduce((min, r) => r.created_at && r.created_at < min ? r.created_at : min, data.runs[0].created_at || "");
    if (earliest) ciExecTime = earliest;
  }
  html += `<div class="meta-line">${t("analyzed")}: ${new Date(ciExecTime).toLocaleString(dateLocale)}</div>`;
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
      const effort = a.effort || "";
      const effortBadge = effort ? `<span class="badge badge-effort-${effort}">${t("effort_"+effort) || effort}</span>` : "";
      html += `<h4><span class="badge badge-${a.severity}">${tSeverity(a.severity)}</span> <span class="badge badge-${cat}">${tCategory(cat)}</span> ${effortBadge} ${escapeHtml(a.job_name)} <small style="color:var(--text-dim)">(${t("confidence")}: ${a.confidence}%)</small></h4>`;
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
  const base = getFilteredAnalyses().length ? getFilteredAnalyses() : allAnalyses;
  let matches;
  if (filterType === "severity") matches = base.filter(a => a.severity === filterValue);
  else if (filterType === "workflow") matches = base.filter(a => a._workflow === filterValue);
  else if (filterType === "all") matches = base;
  else matches = base.filter(a => a._category === filterValue);

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
      // Use CI execution time from the PR's report
      const pr = allReports.find(r => r.pr_number === a._pr_number);
      const ciDate = pr?._ci_date || a._analyzed_at;
      const date = new Date(ciDate).toLocaleDateString(dateLocale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
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

function onAnalysisFilterChange() {
  if (activeTab !== "analysis") return;
  renderMetrics();
  if (allAnalyses.length) renderCharts();
  renderReports();
}

document.getElementById("searchInput").addEventListener("input", renderReports);
document.getElementById("severityFilter").addEventListener("change", onAnalysisFilterChange);
document.getElementById("categoryFilter").addEventListener("change", onAnalysisFilterChange);
const pipeFilter = document.getElementById("pipelineFilter");
if (pipeFilter) pipeFilter.addEventListener("change", onAnalysisFilterChange);

// ── Boot ──

applyI18n();
loadReports();
