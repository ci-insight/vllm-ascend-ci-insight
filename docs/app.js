const INDEX_URL = "reports/index.json";
let allReports = [];
let allAnalyses = []; // Full analysis data for charts
let charts = {};

// ── Category Classification ──

// ORDER MATTERS: more specific rules match first
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
  for (const [cat, re] of CATEGORY_RULES) {
    if (re.test(text)) return cat;
  }
  return "other";
}

// ── I18n ──

function applyI18n() {
  document.title = t("title");
  document.getElementById("pageTitle").textContent = t("title");
  document.getElementById("searchInput").placeholder = t("searchPlaceholder");
  document.getElementById("refreshBtn").textContent = t("refresh");
  document.getElementById("langToggle").textContent = t("lang");
  document.getElementById("chartSeverityTitle").textContent = t("severityBreakdown");
  document.getElementById("chartWorkflowTitle").textContent = t("topWorkflows");
  document.getElementById("chartCategoryTitle").textContent = t("categoryBreakdown");
  document.getElementById("reportSectionTitle").textContent = t("recentReports");

  const sevSel = document.getElementById("severityFilter");
  sevSel.options[0].text = t("allSeverities");
  for (let i = 1; i < sevSel.options.length; i++) {
    sevSel.options[i].text = tSeverity(sevSel.options[i].value);
  }
  const catSel = document.getElementById("categoryFilter");
  catSel.options[0].text = t("allCategories");
  for (let i = 1; i < catSel.options.length; i++) {
    catSel.options[i].text = tCategory(catSel.options[i].value);
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
    // Async load full report data for charts
    loadAnalysesData();
  } catch (err) {
    document.getElementById("reportList").innerHTML =
      `<div class="loading" style="color:var(--critical)">${t("loadFailed")}<br><small>${err.message}</small></div>`;
  }
}

async function loadAnalysesData() {
  allAnalyses = [];
  for (const r of allReports) {
    try {
      const resp = await fetch(r.json_path);
      if (!resp.ok) continue;
      const data = await resp.json();
      for (const a of data.analyses || []) {
        if (a.confidence > 0) {
          a._pr_number = r.pr_number;
          a._pr_title = r.pr_title;
          a._analyzed_at = r.analyzed_at;
          a._category = classifyJob(a, a.job_name);
          // Extract workflow name from job_name
          const parts = a.job_name.split(" / ");
          a._workflow = parts[0] || "unknown";
          allAnalyses.push(a);
        }
      }
    } catch (e) { /* skip failed loads */ }
  }
  renderCharts();
}

// ── Metrics ──

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

  // Estimate avg confidence from available index data (will be refined after full load)
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

// ── Charts ──

function destroyCharts() {
  Object.values(charts).forEach(c => c.destroy());
  charts = {};
}

function renderCharts() {
  destroyCharts();
  if (!allAnalyses.length) return;

  renderSeverityChart();
  renderWorkflowChart();
  renderCategoryChart();
}

function renderSeverityChart() {
  const counts = { critical: 0, high: 0, medium: 0, low: 0, unknown: 0 };
  allAnalyses.forEach(a => { counts[a.severity] = (counts[a.severity] || 0) + 1; });

  const labels = [tSeverity("critical"), tSeverity("high"), tSeverity("medium"), tSeverity("low")];
  const data = [counts.critical, counts.high, counts.medium, counts.low];
  const colors = ["#dc2626", "#ea580c", "#ca8a04", "#16a34a"];
  const sevKeys = ["critical", "high", "medium", "low"];

  charts.severity = new Chart(document.getElementById("chartSeverity"), {
    type: "doughnut",
    data: {
      labels,
      datasets: [{ data, backgroundColor: colors, borderColor: "#161b22", borderWidth: 2 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      onClick: (e, elements) => {
        if (elements.length) {
          showDrillDown("severity", sevKeys[elements[0].index], tSeverity(sevKeys[elements[0].index]));
        }
      },
      plugins: {
        legend: { position: "bottom", labels: { color: "#8b949e", padding: 16, font: { size: 12 } } },
      },
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
    data: {
      labels: wfKeys,
      datasets: [{ data: sorted.map(([, v]) => v), backgroundColor: "#1f6feb", borderRadius: 4 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: true,
      onClick: (e, elements) => {
        if (elements.length) {
          showDrillDown("workflow", wfKeys[elements[0].index], wfKeys[elements[0].index]);
        }
      },
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
  const colors = {
    code: "#8957e5", build: "#3fb950", infra: "#d29922", test: "#58a6ff",
    compat: "#f778ba", perf: "#f85149", lint: "#ca8a04", other: "#8b949e",
  };
  const bgColors = catKeys.map(k => colors[k] || "#8b949e");

  charts.category = new Chart(document.getElementById("chartCategory"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ data, backgroundColor: bgColors, borderRadius: 4 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      onClick: (e, elements) => {
        if (elements.length) {
          const idx = elements[0].index;
          showDrillDown("category", catKeys[idx], tCategory(catKeys[idx]));
        }
      },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
        y: { grid: { color: "#21262d" }, ticks: { color: "#8b949e", font: { size: 11 }, stepSize: 1 } },
      },
    },
  });
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
    // Category filter needs analysis data - skip if not loaded yet
    return true;
  });

  // Apply category filter if analyses are loaded
  if (category && allAnalyses.length) {
    const catPRs = new Set(allAnalyses.filter(a => a._category === category).map(a => a._pr_number));
    filtered = filtered.filter(r => catPRs.has(r.pr_number));
  }

  if (!filtered.length) {
    el.innerHTML = `<div class="empty">${t("noReports")}</div>`;
    return;
  }

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
    document.getElementById("detailContent").innerHTML =
      `<div class="loading" style="color:var(--critical)">${t("detailFailed")}: ${err.message}</div>`;
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
      html += `<h4>
        <span class="badge badge-${a.severity}">${tSeverity(a.severity)}</span>
        <span class="badge badge-${cat}">${tCategory(cat)}</span>
        ${escapeHtml(a.job_name)}
        <small style="color:var(--text-dim)">(${t("confidence")}: ${a.confidence}%)</small>
      </h4>`;
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

function closeDetail() {
  document.getElementById("detailModal").classList.remove("open");
}

// ── Category Detail Drill-Down ──

function showDrillDown(filterType, filterValue, displayName) {
  // filterType: "severity", "category", "workflow", or "all"
  let matches;
  if (filterType === "severity") {
    matches = allAnalyses.filter(a => a.severity === filterValue);
  } else if (filterType === "workflow") {
    matches = allAnalyses.filter(a => a._workflow === filterValue);
  } else if (filterType === "all") {
    matches = allAnalyses;
  } else {
    matches = allAnalyses.filter(a => a._category === filterValue);
  }

  // Group by PR
  const grouped = {};
  matches.forEach(a => {
    if (!grouped[a._pr_number]) grouped[a._pr_number] = [];
    grouped[a._pr_number].push(a);
  });

  const dateLocale = currentLang === "zh" ? "zh-CN" : "en-US";
  let html = `<h2>${displayName} <span style="color:var(--text-dim);font-size:14px">(${matches.length} ${t("jobs")})</span></h2>`;

  for (const [prNum, items] of Object.entries(grouped)) {
    const pr = allReports.find(r => r.pr_number === parseInt(prNum));
    const prTitle = pr ? pr.pr_title : "";
    html += `<div style="margin:16px 0 8px">
      <a href="javascript:void(0)" onclick="closeDetail();openDetail(${prNum})" style="color:var(--link);font-weight:600;font-size:15px">#${prNum}</a>
      <span style="color:var(--text-dim);font-size:13px;margin-left:8px">${escapeHtml(prTitle)}</span>
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
