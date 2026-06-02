// Health Overview Tab
const HEALTH_URL = "reports/health.json";
const ALERTS_URL = "reports/alerts.json";
const SNAPSHOTS_URL = "reports/daily-snapshots.json";
let healthData = null;
let alertsData = null;
let snapshotsData = null;
let healthCharts = {};

async function loadHealthTab() {
  try {
    if (typeof loadCiMetadata === "function") await loadCiMetadata();
    const [hResp, aResp, sResp] = await Promise.all([
      fetch(HEALTH_URL),
      fetch(ALERTS_URL),
      fetch(SNAPSHOTS_URL),
    ]);
    if (hResp.ok) healthData = await hResp.json();
    if (aResp.ok) alertsData = await aResp.json();
    if (sResp.ok) snapshotsData = await sResp.json();
    renderHealthUI();
  } catch (e) {
    document.getElementById("healthContent").innerHTML =
      `<div class="loading" style="color:var(--critical)">Failed to load health data. Run ascend first.</div>`;
  }
}

function destroyHealthCharts() {
  Object.values(healthCharts).forEach(c => c.destroy());
  healthCharts = {};
}

function renderHealthUI() {
  destroyHealthCharts();
  if (!healthData) return;

  const pipelines = healthData.pipelines || {};
  const alerts = alertsData?.alerts || [];
  const overall = healthData.overall || {};
  const completeSample = healthData.data_quality?.complete_success_sample !== false;
  const qualityWarning = healthData.data_quality?.warning || "";

  // Alert banners
  let alertHtml = "";
  if (!completeSample) {
    alertHtml += `<div class="alert-banner" style="border-left: 3px solid var(--medium); background: rgba(202,138,4,0.1)">
      <strong>[DATA]</strong> ${escapeHtml(qualityWarning || "This view is based on failed reports only.")}
    </div>`;
  }
  if (alerts.length) {
    alertHtml += alerts.map(a => {
      const bg = a.severity === "critical" ? "var(--critical)" : "var(--medium)";
      return `<div class="alert-banner" style="border-left: 3px solid ${bg}; background: rgba(${a.severity==='critical'?'220,38,38':'202,138,4'}, 0.1)">
        <strong>[${a.severity.toUpperCase()}]</strong> ${a.message}
      </div>`;
    }).join("");
  }

  // Health score cards
  let cardsHtml = "";
  const ptypes = ["pr_e2e", "nightly", "other"];
  for (const pt of ptypes) {
    const p = pipelines[pt];
    if (!p) continue;
    const label = { pr_e2e: "PR CI", nightly: "Nightly", weekly: "Weekly", other: "Other" }[pt] || pt;
    const scoreText = completeSample && p.health_score !== null ? p.health_score : "N/A";
    const sampleText = (p.measured_total || 0) === 0
      ? `no completed jobs · ${p.total || 0} total`
      : `${completeSample ? `${p.success_rate}% SR` : `${p.success_rate}% observed`} · ${p.measured_total || 0}/${p.total || 0} measured`;
    cardsHtml += `<div class="metric-card clickable" onclick="showPipelineDetail('${pt}')" style="border-left:3px solid ${p.rating_color}">
      <div class="metric-value" style="color:${p.rating_color}">${scoreText}</div>
      <div class="metric-label">${label}</div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:4px">${(p.measured_total || 0) === 0 ? `no measured success/failure jobs · ${p.total || 0} total` : `${completeSample ? `${p.success_rate}% SR` : `${p.success_rate}% observed`} · ${p.measured_total || 0}/${p.total || 0} measured`}</div>
    </div>`;
  }

  // Worst workflows
  const wfHealth = {};
  if (allJobs.length) {
    allJobs.forEach(j => {
      if (!wfHealth[j.workflow_name]) wfHealth[j.workflow_name] = { total: 0, success: 0 };
      if (j.conclusion !== "success" && j.conclusion !== "failure") return;
      wfHealth[j.workflow_name].total++;
      if (j.conclusion === "success") wfHealth[j.workflow_name].success++;
    });
  }
  const worst = Object.entries(wfHealth)
    .map(([k, v]) => ({ name: k, rate: v.total ? v.success / v.total * 100 : 0, total: v.total }))
    .sort((a, b) => a.rate - b.rate)
    .slice(0, 5);

  document.getElementById("healthContent").innerHTML = `
    ${alertHtml}
    <section class="metrics" id="healthMetrics">
      ${cardsHtml}
    </section>
    <section class="charts">
      <div class="chart-box">
        <h3>${t("ciSuccessRate")} Trend (7d)</h3>
        <canvas id="chartHSuccess"></canvas>
      </div>
      <div class="chart-box">
        <h3>Failure Count Trend (7d)</h3>
        <canvas id="chartHFailure"></canvas>
      </div>
      <div class="chart-box">
        <h3>Health Score Trend (7d)</h3>
        <canvas id="chartHHealth"></canvas>
      </div>
      <div class="chart-box">
        <h3>Worst Workflows (by Success Rate)</h3>
        <canvas id="chartHWorst"></canvas>
      </div>
    </section>
    ${alerts.length ? `<section class="report-section"><h3>Active Alerts (${alerts.length})</h3>
      ${alerts.map(a => `<div class="report-card" style="cursor:default"><div class="card-left"><span class="badge badge-${a.severity==='critical'?'critical':'medium'}">${a.severity}</span> <span>${a.rule_name}: ${a.message}</span></div></div>`).join("")}
    </section>` : ""}
  `;

  renderHealthCharts(pipelines, worst);
}

function renderHealthCharts(pipelines, worst) {
  const colors = { pr_e2e: "#58a6ff", nightly: "#3fb950", weekly: "#ca8a04", other: "#8b949e" };
  const labels = { pr_e2e: "PR CI", nightly: "Nightly", weekly: "Weekly", other: "Other" };

  // Use snapshot data for long-term trends, fallback to health.json daily_trend
  let trendSource = {};
  if (snapshotsData && snapshotsData.pipeline_types) {
    trendSource = snapshotsData.pipeline_types; // long-term from SQLite aggregator
  } else {
    // Fallback: convert health.json daily_trend to snapshot format
    Object.entries(pipelines).forEach(([pt, p]) => {
      if (p.daily_trend && p.daily_trend.length) {
        trendSource[pt] = p.daily_trend;
      }
    });
  }

  // Merge all dates across pipeline types
  const allDates = new Set();
  Object.values(trendSource).forEach(entries => entries.forEach(d => allDates.add(d.date)));
  const dates = [...allDates].sort();

  // Success rate trend
  const srDatasets = Object.entries(trendSource)
    .filter(([, entries]) => entries && entries.length)
    .map(([pt, entries]) => ({
      label: labels[pt] || pt,
      data: dates.map(d => {
        const found = entries.find(t => t.date === d);
        return found ? found.success_rate : null;
      }),
      borderColor: colors[pt] || "#8b949e",
      backgroundColor: "transparent",
      tension: 0.3,
      spanGaps: true,
    }));

  healthCharts.success = new Chart(document.getElementById("chartHSuccess"), {
    type: "line",
    data: { labels: dates, datasets: srDatasets },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8b949e", font: { size: 10 } } },
        y: { min: 0, max: 100, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => v + "%" } },
      },
    },
  });

  // Failure count trend
  const failDatasets = Object.entries(trendSource)
    .filter(([, entries]) => entries && entries.length)
    .map(([pt, entries]) => ({
      label: labels[pt] || pt,
      data: dates.map(d => { const found = entries.find(t => t.date === d); return found ? (found.failure || 0) : null; }),
      borderColor: colors[pt] || "#8b949e",
      backgroundColor: "transparent",
      tension: 0.3,
      spanGaps: true,
    }));

  healthCharts.failure = new Chart(document.getElementById("chartHFailure"), {
    type: "line",
    data: { labels: dates, datasets: failDatasets },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8b949e", font: { size: 10 } } },
        y: { beginAtZero: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e", stepSize: 1 } },
      },
    },
  });

  // Health score trend
  const hDatasets = Object.entries(trendSource)
    .filter(([, entries]) => entries && entries.length)
    .map(([pt, entries]) => ({
      label: labels[pt] || pt,
      data: dates.map(d => { const found = entries.find(t => t.date === d); return found ? found.health_score : null; }),
      borderColor: colors[pt] || "#8b949e",
      backgroundColor: "transparent",
      tension: 0.3,
      spanGaps: true,
    }));

  healthCharts.health = new Chart(document.getElementById("chartHHealth"), {
    type: "line",
    data: { labels: dates, datasets: hDatasets },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8b949e", font: { size: 10 } } },
        y: { min: 0, max: 100, grid: { color: "#21262d" }, ticks: { color: "#8b949e" } },
      },
    },
  });

  // Worst workflows
  const worstNames = worst.map(w => w.name);
  healthCharts.worst = new Chart(document.getElementById("chartHWorst"), {
    type: "bar",
    data: {
      labels: worst.map(w => w.name.length > 25 ? w.name.slice(0, 25) + "..." : w.name),
      datasets: [{ data: worst.map(w => w.rate), backgroundColor: worst.map(w => w.rate < 50 ? "#dc2626" : w.rate < 75 ? "#ca8a04" : "#16a34a"), borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: true,
      onClick: (e, els) => { if (els.length) showWorkflowHealthDetail(worstNames[els[0].index]); },
      plugins: { legend: { display: false } },
      scales: {
        x: { max: 100, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => v + "%" } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });

  // Also add clicks to trend charts
  ["chartHSuccess", "chartHFailure", "chartHHealth"].forEach(id => {
    const chart = healthCharts[id === "chartHSuccess" ? "success" : id === "chartHFailure" ? "failure" : "health"];
    // Trend charts show overview; clicking any chart on this tab shows pipeline detail
  });
}

// ── Pipeline Detail Drill-Down ──

function showPipelineDetail(ptype) {
  const pipelines = healthData?.pipelines || {};
  const p = pipelines[ptype];
  if (!p) return;

  const label = { pr_e2e: "PR CI", nightly: "Nightly", weekly: "Weekly", other: "Other" }[ptype] || ptype;
  const jobs = allJobs.filter(j => j.pipeline_type === ptype);
  const failed = jobs.filter(j => j.conclusion === "failure");

  // Group failed jobs by workflow
  const byWF = {};
  failed.forEach(j => {
    if (!byWF[j.workflow_name]) byWF[j.workflow_name] = [];
    byWF[j.workflow_name].push(j);
  });

  const completeSample = healthData?.data_quality?.complete_success_sample !== false;
  const scoreText = completeSample && p.health_score !== null ? `${p.health_score}/100` : "N/A";
  let html = `<h2>${label} Pipeline <span style="color:${p.rating_color};font-size:18px">${scoreText}</span></h2>`;
  html += `<div style="display:flex;gap:16px;margin:12px 0;flex-wrap:wrap">
    <div class="metric-card"><div class="metric-value">${p.total}</div><div class="metric-label">Total Jobs</div></div>
    <div class="metric-card"><div class="metric-value">${p.measured_total || 0}</div><div class="metric-label">Measured Jobs</div></div>
    <div class="metric-card"><div class="metric-value">${p.success_rate}%</div><div class="metric-label">${completeSample ? "Success Rate" : "Observed Success"}</div></div>
    <div class="metric-card"><div class="metric-value">${p.failure}</div><div class="metric-label">Failures</div></div>
    <div class="metric-card"><div class="metric-value">${p.skipped || 0}</div><div class="metric-label">Skipped</div></div>
    <div class="metric-card"><div class="metric-value">${p.cancelled || 0}</div><div class="metric-label">Cancelled</div></div>
    <div class="metric-card"><div class="metric-value">${p.recent_24h_failures || 0}</div><div class="metric-label">24h Failures</div></div>
  </div>`;

  // Consecutive failure details
  if (p.consecutive_details && p.consecutive_details.length) {
    html += `<h3>Consecutive Failures</h3>`;
    p.consecutive_details.forEach(c => {
      html += `<div class="alert-banner" style="margin:4px 0"><strong>${c.workflow}</strong>: ${c.streak} consecutive failures (penalty: -${c.penalty})</div>`;
    });
  }

  // Failed jobs by workflow
  html += `<h3>Failed Jobs by Workflow (${failed.length} total)</h3>`;
  for (const [wf, wJobs] of Object.entries(byWF).sort((a, b) => b[1].length - a[1].length)) {
    html += `<div style="margin:12px 0 4px;font-weight:600;font-size:14px">${escapeHtml(wf)} <span style="color:var(--text-dim);font-weight:400">(${wJobs.length} failures)</span></div>`;
    wJobs.slice(0, 5).forEach(j => {
      const runUrl = `https://github.com/vllm-project/vllm-ascend/actions/runs/${j.run_id}`;
      html += `<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin:4px 0;font-size:13px">
        <span class="badge badge-${j.conclusion === 'failure' ? 'critical' : 'medium'}">${j.conclusion}</span>
        <span style="margin-left:8px">${escapeHtml(j.job_name.length > 60 ? j.job_name.slice(0, 60) + '...' : j.job_name)}</span>
        <a href="${runUrl}" target="_blank" style="color:var(--link);margin-left:8px;font-size:12px">Run ↗</a>
        <span style="color:var(--text-dim);margin-left:8px;font-size:12px">${fmtDuration(j.duration)}</span>
      </div>`;
    });
    if (wJobs.length > 5) html += `<div style="color:var(--text-dim);font-size:12px;padding:4px">... and ${wJobs.length - 5} more</div>`;
  }

  document.getElementById("detailContent").innerHTML = html;
  document.getElementById("detailModal").classList.add("open");
}

function showWorkflowHealthDetail(wfName) {
  const jobs = allJobs.filter(j => j.workflow_name === wfName);
  const failed = jobs.filter(j => j.conclusion === "failure");
  const success = jobs.filter(j => j.conclusion === "success");
  const total = jobs.length;
  const sr = total ? Math.round(success.length / total * 100) : 0;

  let html = `<h2>${escapeHtml(wfName)} <span style="font-size:16px;color:${sr < 50 ? 'var(--critical)' : sr < 75 ? 'var(--medium)' : 'var(--low)'}">${sr}% SR</span></h2>`;
  html += `<div style="display:flex;gap:16px;margin:12px 0;flex-wrap:wrap">
    <div class="metric-card"><div class="metric-value">${total}</div><div class="metric-label">Total Jobs</div></div>
    <div class="metric-card"><div class="metric-value">${success.length}</div><div class="metric-label">Success</div></div>
    <div class="metric-card critical"><div class="metric-value">${failed.length}</div><div class="metric-label">Failed</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(jobs.reduce((s,j) => s + j.duration, 0) / Math.max(1, total))}</div><div class="metric-label">Avg Duration</div></div>
  </div>`;

  // Show all jobs (newest first)
  html += `<h3>Jobs</h3>`;
  const sorted = [...jobs].sort((a, b) => new Date(b.started_at || 0) - new Date(a.started_at || 0));
  sorted.forEach(j => {
    const runUrl = `https://github.com/vllm-project/vllm-ascend/actions/runs/${j.run_id}`;
    const date = new Date(j.started_at).toLocaleDateString(currentLang === "zh" ? "zh-CN" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    html += `<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin:4px 0;font-size:13px">
      <span class="badge badge-${j.conclusion === 'failure' ? 'critical' : j.conclusion === 'success' ? 'low' : 'other'}">${j.conclusion}</span>
      <span style="margin-left:8px">${escapeHtml(j.job_name.length > 50 ? j.job_name.slice(0, 50) + '...' : j.job_name)}</span>
      <span style="color:var(--text-dim);margin-left:8px;font-size:12px">${fmtDuration(j.duration)}</span>
      <span style="color:var(--text-dim);margin-left:8px;font-size:12px">${date}</span>
      <a href="${runUrl}" target="_blank" style="color:var(--link);margin-left:8px;font-size:12px">Run ↗</a>
    </div>`;
  });

  document.getElementById("detailContent").innerHTML = html;
  document.getElementById("detailModal").classList.add("open");
}
