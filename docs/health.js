// Health Overview Tab
const HEALTH_URL = "reports/health.json";
const ALERTS_URL = "reports/alerts.json";
const INTERFERENCE_URL = "reports/interference.json";
let healthData = null;
let alertsData = null;
let healthCharts = {};

async function loadHealthTab() {
  try {
    const [hResp, aResp] = await Promise.all([
      fetch(HEALTH_URL),
      fetch(ALERTS_URL),
    ]);
    if (hResp.ok) healthData = await hResp.json();
    if (aResp.ok) alertsData = await aResp.json();
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

  // Alert banners
  let alertHtml = "";
  if (alerts.length) {
    alertHtml = alerts.map(a => {
      const bg = a.severity === "critical" ? "var(--critical)" : "var(--medium)";
      return `<div class="alert-banner" style="border-left: 3px solid ${bg}; background: rgba(${a.severity==='critical'?'220,38,38':'202,138,4'}, 0.1)">
        <strong>[${a.severity.toUpperCase()}]</strong> ${a.message}
      </div>`;
    }).join("");
  }

  // Health score cards
  let cardsHtml = "";
  const ptypes = ["pr_e2e", "nightly", "weekly", "other"];
  for (const pt of ptypes) {
    const p = pipelines[pt];
    if (!p) continue;
    const label = { pr_e2e: "PR CI", nightly: "Nightly", weekly: "Weekly", other: "Other" }[pt] || pt;
    cardsHtml += `<div class="metric-card clickable" style="border-left:3px solid ${p.rating_color}">
      <div class="metric-value" style="color:${p.rating_color}">${p.health_score}</div>
      <div class="metric-label">${label}</div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:4px">${p.success_rate}% SR · ${p.trend === "up" ? "↗" : p.trend === "down" ? "↘" : "→"}</div>
    </div>`;
  }

  // Worst workflows
  const wfHealth = {};
  if (allJobs.length && allAnalyses.length) {
    allJobs.forEach(j => {
      if (!wfHealth[j.workflow_name]) wfHealth[j.workflow_name] = { total: 0, success: 0 };
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

  // Success rate trend
  const allDates = new Set();
  Object.values(pipelines).forEach(p => (p.daily_trend || []).forEach(d => allDates.add(d.date)));
  const dates = [...allDates].sort();

  const srDatasets = Object.entries(pipelines)
    .filter(([, p]) => p.daily_trend && p.daily_trend.length)
    .map(([pt, p]) => ({
      label: labels[pt] || pt,
      data: dates.map(d => {
        const found = p.daily_trend.find(t => t.date === d);
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
  const failDatasets = Object.entries(pipelines)
    .filter(([, p]) => p.daily_trend && p.daily_trend.length)
    .map(([pt, p]) => ({
      label: labels[pt] || pt,
      data: dates.map(d => { const found = p.daily_trend.find(t => t.date === d); return found ? found.failure : null; }),
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
  const hDatasets = Object.entries(pipelines)
    .filter(([, p]) => p.daily_trend && p.daily_trend.length)
    .map(([pt, p]) => ({
      label: labels[pt] || pt,
      data: dates.map(d => { const found = p.daily_trend.find(t => t.date === d); return found ? found.health : null; }),
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
  healthCharts.worst = new Chart(document.getElementById("chartHWorst"), {
    type: "bar",
    data: {
      labels: worst.map(w => w.name.length > 25 ? w.name.slice(0, 25) + "..." : w.name),
      datasets: [{ data: worst.map(w => w.rate), backgroundColor: worst.map(w => w.rate < 50 ? "#dc2626" : w.rate < 75 ? "#ca8a04" : "#16a34a"), borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { max: 100, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => v + "%" } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });
}
