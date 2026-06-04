// Health Overview Tab
const HEALTH_URL = "reports/health.json";
const ALERTS_URL = "reports/alerts.json";
const SNAPSHOTS_URL = "reports/daily-snapshots.json";
let healthData = null;
let alertsData = null;
let snapshotsData = null;
let healthCharts = {};

async function loadHealthTab(force = false) {
  try {
    if (force) {
      healthData = null;
      alertsData = null;
      snapshotsData = null;
    }
    if (typeof loadCiMetadata === "function") await loadCiMetadata();
    if (!allAnalyses.length && allReports.length && typeof loadAnalysesData === "function") {
      await loadAnalysesData();
    }
    const [hResp, aResp, sResp] = await Promise.all([
      fetchReportJson(HEALTH_URL),
      fetchReportJson(ALERTS_URL),
      fetchReportJson(SNAPSHOTS_URL),
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
    const hasMeasured = (p.measured_total || 0) > 0;
    const observedRuns = p.workflow_runs ?? ciWorkflowRuns.filter(run => (run.pipeline_type || classifyPipeline(run.workflow_name)) === pt).length;
    const scoreText = completeSample && p.health_score !== null
      ? p.health_score
      : hasMeasured
        ? observedRuns
        : "No data";
    const labelText = completeSample ? `${label} ${t("healthScoreLabel")}` : `${label} workflows`;
    const valueColor = completeSample && p.health_score !== null ? p.rating_color : "var(--text)";
    const sampleText = (p.measured_total || 0) === 0
      ? `${observedRuns} workflow runs | no completed jobs | ${p.total || 0} total jobs`
      : `${observedRuns} workflow runs | ${completeSample ? `${t("successRateLabel")} ${p.success_rate}%` : `${p.success_rate}% observed`} | ${p.measured_total || 0}/${p.total || 0} measured jobs`;
    cardsHtml += `<div class="metric-card clickable" onclick="showPipelineDetail('${pt}')" style="border-left:3px solid ${p.rating_color}">
      <div class="metric-value" style="color:${valueColor}">${scoreText}</div>
      <div class="metric-label">${labelText}</div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:4px">${sampleText}</div>
      <div style="font-size:11px;margin-top:6px">${relatedAiBadge({ pipeline: pt })}</div>
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

  const concentration = buildFailureConcentration();
  const concentrationHtml = `
    <section class="metrics health-ops-grid">
      <div class="metric-card">
        <div class="metric-value">${concentration.totalFailures}</div>
        <div class="metric-label">Collected Failures</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${concentration.topWorkflowShare}%</div>
        <div class="metric-label">Top 5 Workflow Failure Share</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${concentration.topJobShare}%</div>
        <div class="metric-label">Top 10 Job Failure Share</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">${concentration.interpretation}</div>
        <div class="metric-label">Failure Concentration</div>
      </div>
    </section>`;

  document.getElementById("healthContent").innerHTML = `
    ${alertHtml}
    <section class="metrics" id="healthMetrics">
      ${cardsHtml}
    </section>
    ${concentrationHtml}
    <section class="charts">
      <div class="chart-box">
        <h3>${t("ciSuccessRate")} by CI Execution Date (7d)</h3>
        <canvas id="chartHSuccess"></canvas>
      </div>
      <div class="chart-box">
        <h3>Failure Count by CI Execution Date (7d)</h3>
        <canvas id="chartHFailure"></canvas>
      </div>
      <div class="chart-box">
        <h3>Health Score Snapshot Trend (7d)</h3>
        <canvas id="chartHHealth"></canvas>
      </div>
      <div class="chart-box">
        <h3>Worst Workflows (by Success Rate)</h3>
        <canvas id="chartHWorst"></canvas>
      </div>
      <div class="chart-box">
        <h3>Workflow Failure Contribution (Top 10)</h3>
        <canvas id="chartHWorkflowFailure"></canvas>
      </div>
      <div class="chart-box">
        <h3>Job Failure Contribution (Top 10)</h3>
        <canvas id="chartHJobFailure"></canvas>
      </div>
      <div class="chart-box">
        <h3>Lowest Job Success Rate (Top 10)</h3>
        <canvas id="chartHJobSuccess"></canvas>
      </div>
      <div class="chart-box">
        <h3>Workflow Duration / Queue (Top 10)</h3>
        <canvas id="chartHWorkflowDuration"></canvas>
      </div>
      <div class="chart-box">
        <h3>Workflow Stability Matrix</h3>
        <canvas id="chartHWorkflowStability"></canvas>
      </div>
      <div class="chart-box">
        <h3>Job Duration Variability (Top 10)</h3>
        <canvas id="chartHJobVariability"></canvas>
      </div>
      <div class="chart-box full">
        <h3>Queue P50 / P90 by CI Execution Date</h3>
        <canvas id="chartHQueueTrend"></canvas>
      </div>
      <div class="chart-box full">
        <h3>Skipped / Cancelled / Pending by Pipeline</h3>
        <canvas id="chartHNeutral"></canvas>
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

  const executionTrendSource = getExecutionTrendSource(pipelines);
  const snapshotTrendSource = getSnapshotTrendSource(pipelines);

  // Merge all dates across pipeline types
  const executionDates = collectTrendDates(executionTrendSource);
  const snapshotDates = collectTrendDates(snapshotTrendSource);

  // Success rate trend
  const srDatasets = Object.entries(executionTrendSource)
    .filter(([, entries]) => entries && entries.length)
    .map(([pt, entries]) => ({
      label: labels[pt] || pt,
      data: executionDates.map(d => {
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
    data: { labels: executionDates, datasets: srDatasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8b949e", font: { size: 10 } } },
        y: { min: 0, max: 100, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => v + "%" } },
      },
    },
  });

  // Failure count trend
  const failDatasets = Object.entries(executionTrendSource)
    .filter(([, entries]) => entries && entries.length)
    .map(([pt, entries]) => ({
      label: labels[pt] || pt,
      data: executionDates.map(d => { const found = entries.find(t => t.date === d); return found ? (found.failure || 0) : null; }),
      borderColor: colors[pt] || "#8b949e",
      backgroundColor: "transparent",
      tension: 0.3,
      spanGaps: true,
    }));

  healthCharts.failure = new Chart(document.getElementById("chartHFailure"), {
    type: "line",
    data: { labels: executionDates, datasets: failDatasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8b949e", font: { size: 10 } } },
        y: { beginAtZero: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e", stepSize: 1 } },
      },
    },
  });

  // Health score trend
  const hDatasets = Object.entries(snapshotTrendSource)
    .filter(([, entries]) => entries && entries.length)
    .map(([pt, entries]) => ({
      label: labels[pt] || pt,
      data: snapshotDates.map(d => { const found = entries.find(t => t.date === d); return found ? found.health_score : null; }),
      borderColor: colors[pt] || "#8b949e",
      backgroundColor: "transparent",
      tension: 0.3,
      spanGaps: true,
    }));

  healthCharts.health = new Chart(document.getElementById("chartHHealth"), {
    type: "line",
    data: { labels: snapshotDates, datasets: hDatasets },
    options: {
      responsive: true, maintainAspectRatio: false,
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
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, els) => { if (els.length) showWorkflowHealthDetail(worstNames[els[0].index]); },
      plugins: { legend: { display: false } },
      scales: {
        x: { max: 100, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => v + "%" } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });

  const workflowFailures = buildWorkflowFailureContribution();
  const workflowFailureNames = workflowFailures.map(w => w.name);
  healthCharts.workflowFailure = new Chart(document.getElementById("chartHWorkflowFailure"), {
    type: "bar",
    data: {
      labels: workflowFailures.map(w => w.name.length > 28 ? w.name.slice(0, 25) + "..." : w.name),
      datasets: [{ data: workflowFailures.map(w => w.failure), backgroundColor: "#dc2626", borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, els) => { if (els.length) showWorkflowHealthDetail(workflowFailureNames[els[0].index]); },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: item => `${item.raw} failures | ${workflowFailures[item.dataIndex].share}% of collected failures` } },
      },
      scales: {
        x: { beginAtZero: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e", precision: 0 } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });

  const jobFailures = buildJobFailureContribution();
  healthCharts.jobFailure = new Chart(document.getElementById("chartHJobFailure"), {
    type: "bar",
    data: {
      labels: jobFailures.map(j => j.label.length > 34 ? j.label.slice(0, 31) + "..." : j.label),
      datasets: [{ data: jobFailures.map(j => j.failure), backgroundColor: "#ea580c", borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, els) => {
        if (!els.length) return;
        const job = jobFailures[els[0].index];
        showRelatedAiAnalysesFromHealth(job.pipeline, job.workflow, job.jobName, "");
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: items => jobFailures[items[0].dataIndex]?.jobName || "",
            afterTitle: items => {
              const job = jobFailures[items[0].dataIndex];
              return job ? `${job.workflow} | measured ${job.measured}` : "";
            },
            label: item => `${item.raw} failures | ${jobFailures[item.dataIndex].share}% of collected failures`,
          },
        },
      },
      scales: {
        x: { beginAtZero: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e", precision: 0 } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });

  const lowestJobs = buildLowestJobSuccessRates();
  healthCharts.jobSuccess = new Chart(document.getElementById("chartHJobSuccess"), {
    type: "bar",
    data: {
      labels: lowestJobs.map(j => j.label.length > 34 ? j.label.slice(0, 31) + "..." : j.label),
      datasets: [{ data: lowestJobs.map(j => j.successRate), backgroundColor: lowestJobs.map(j => j.successRate < 50 ? "#dc2626" : j.successRate < 75 ? "#ca8a04" : "#16a34a"), borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, els) => {
        if (!els.length) return;
        const job = lowestJobs[els[0].index];
        showRelatedAiAnalysesFromHealth(job.pipeline, job.workflow, job.jobName, "");
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: items => lowestJobs[items[0].dataIndex]?.jobName || "",
            afterTitle: items => {
              const job = lowestJobs[items[0].dataIndex];
              return job ? `${job.workflow} | measured ${job.measured}` : "";
            },
            label: item => `${item.raw}% success | ${lowestJobs[item.dataIndex].failure} failures`,
          },
        },
      },
      scales: {
        x: { min: 0, max: 100, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => v + "%" } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });

  const neutral = buildNeutralOutcomeDistribution();
  healthCharts.neutral = new Chart(document.getElementById("chartHNeutral"), {
    type: "bar",
    data: {
      labels: neutral.labels,
      datasets: [
        { label: "Skipped", data: neutral.skipped, backgroundColor: "#8b949e" },
        { label: "Cancelled", data: neutral.cancelled, backgroundColor: "#f85149" },
        { label: "Pending", data: neutral.pending, backgroundColor: "#ca8a04" },
        { label: "Other", data: neutral.other, backgroundColor: "#8957e5" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } },
        tooltip: { callbacks: { footer: () => "Excluded from measured success rate" } },
      },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: "#c9d1d9" } },
        y: { stacked: true, beginAtZero: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e" } },
      },
    },
  });

  const durationQueue = buildWorkflowDurationQueue();
  healthCharts.workflowDuration = new Chart(document.getElementById("chartHWorkflowDuration"), {
    type: "bar",
    data: {
      labels: durationQueue.map(w => w.name.length > 28 ? w.name.slice(0, 25) + "..." : w.name),
      datasets: [
        { label: "Avg Wall-Clock", data: durationQueue.map(w => w.avgWallClock), backgroundColor: "#58a6ff", borderRadius: 4 },
        { label: "Max Queue", data: durationQueue.map(w => w.maxQueue), backgroundColor: "#ca8a04", borderRadius: 4 },
      ],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, els) => { if (els.length) showWorkflowHealthDetail(durationQueue[els[0].index].name); },
      plugins: {
        legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: item => `${item.dataset.label}: ${fmtDuration(item.raw)}`,
            afterTitle: items => {
              const w = durationQueue[items[0].dataIndex];
              return w ? `${w.runs} workflow runs | ${w.jobs} jobs` : "";
            },
          },
        },
      },
      scales: {
        x: { beginAtZero: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => fmtDuration(v) } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });

  const stability = buildWorkflowStabilityMatrix();
  const stabilityNames = stability.map(w => w.name);
  healthCharts.workflowStability = new Chart(document.getElementById("chartHWorkflowStability"), {
    type: "bubble",
    data: {
      datasets: [{
        label: "Workflows",
        data: stability.map(w => ({ x: w.successRate, y: w.measured, r: w.radius })),
        backgroundColor: stability.map(w => w.successRate < 50 ? "rgba(220,38,38,0.7)" : w.successRate < 75 ? "rgba(202,138,4,0.7)" : "rgba(22,163,74,0.65)"),
        borderColor: stability.map(w => w.successRate < 50 ? "#dc2626" : w.successRate < 75 ? "#ca8a04" : "#16a34a"),
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      onClick: (e, els) => { if (els.length) showWorkflowHealthDetail(stabilityNames[els[0].index]); },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: items => stability[items[0].dataIndex]?.name || "",
            label: item => {
              const w = stability[item.dataIndex];
              return `${w.successRate}% success | ${w.failure} failures | ${w.measured} measured jobs`;
            },
          },
        },
      },
      scales: {
        x: { min: 0, max: 100, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => v + "%" }, title: { display: true, text: "Success Rate", color: "#8b949e" } },
        y: { type: "logarithmic", min: 1, grid: { color: "#21262d" }, ticks: { color: "#8b949e" }, title: { display: true, text: "Measured Jobs", color: "#8b949e" } },
      },
    },
  });

  const variableJobs = buildJobDurationVariability();
  healthCharts.jobVariability = new Chart(document.getElementById("chartHJobVariability"), {
    type: "bar",
    data: {
      labels: variableJobs.map(j => j.label.length > 34 ? j.label.slice(0, 31) + "..." : j.label),
      datasets: [{ data: variableJobs.map(j => j.ratio), backgroundColor: "#8957e5", borderRadius: 4 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: items => variableJobs[items[0].dataIndex]?.jobName || "",
            afterTitle: items => {
              const job = variableJobs[items[0].dataIndex];
              return job ? `${job.workflow} | samples ${job.samples}` : "";
            },
            label: item => `P90/P50 ${item.raw}x | P50 ${fmtDuration(variableJobs[item.dataIndex].p50)} | P90 ${fmtDuration(variableJobs[item.dataIndex].p90)}`,
          },
        },
      },
      scales: {
        x: { beginAtZero: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => `${v}x` } },
        y: { grid: { display: false }, ticks: { color: "#c9d1d9", font: { size: 11 } } },
      },
    },
  });

  const queueTrend = buildQueueTrendByExecutionDate();
  healthCharts.queueTrend = new Chart(document.getElementById("chartHQueueTrend"), {
    type: "line",
    data: {
      labels: queueTrend.map(d => d.date),
      datasets: [
        { label: "Queue P50", data: queueTrend.map(d => d.p50), borderColor: "#58a6ff", backgroundColor: "transparent", tension: 0.3 },
        { label: "Queue P90", data: queueTrend.map(d => d.p90), borderColor: "#ca8a04", backgroundColor: "transparent", tension: 0.3 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { color: "#8b949e", font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: item => `${item.dataset.label}: ${fmtDuration(item.raw)}`,
            afterBody: items => {
              const row = queueTrend[items[0].dataIndex];
              return row ? `${row.samples} queued job samples` : "";
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#8b949e" } },
        y: { beginAtZero: true, grid: { color: "#21262d" }, ticks: { color: "#8b949e", callback: v => fmtDuration(v) } },
      },
    },
  });

  // Also add clicks to trend charts
  ["chartHSuccess", "chartHFailure", "chartHHealth"].forEach(id => {
    const chart = healthCharts[id === "chartHSuccess" ? "success" : id === "chartHFailure" ? "failure" : "health"];
    // Trend charts show overview; clicking any chart on this tab shows pipeline detail
  });
}

// Pipeline Detail Drill-Down

function buildWorkflowFailureContribution() {
  const byWorkflow = {};
  allJobs.forEach(j => {
    if (!byWorkflow[j.workflow_name]) byWorkflow[j.workflow_name] = { name: j.workflow_name, failure: 0 };
    if (j.conclusion === "failure") byWorkflow[j.workflow_name].failure++;
  });
  const totalFailures = Object.values(byWorkflow).reduce((sum, w) => sum + w.failure, 0);
  return Object.values(byWorkflow)
    .filter(w => w.failure > 0)
    .map(w => ({ ...w, share: totalFailures ? Math.round(w.failure / totalFailures * 100) : 0 }))
    .sort((a, b) => b.failure - a.failure)
    .slice(0, 10);
}

function buildFailureConcentration() {
  const workflowFailures = buildWorkflowFailureContribution();
  const jobFailures = buildJobFailureContribution();
  const totalFailures = allJobs.filter(j => j.conclusion === "failure").length;
  const topWorkflowFailures = workflowFailures.slice(0, 5).reduce((sum, w) => sum + w.failure, 0);
  const topJobFailures = jobFailures.slice(0, 10).reduce((sum, j) => sum + j.failure, 0);
  const topWorkflowShare = totalFailures ? Math.round(topWorkflowFailures / totalFailures * 100) : 0;
  const topJobShare = totalFailures ? Math.round(topJobFailures / totalFailures * 100) : 0;
  const interpretation = topWorkflowShare >= 70 ? "Focused" : topWorkflowShare >= 40 ? "Mixed" : "Broad";
  return { totalFailures, topWorkflowShare, topJobShare, interpretation };
}

function buildJobFailureContribution() {
  const byJob = {};
  allJobs.forEach(j => {
    if (j.conclusion !== "success" && j.conclusion !== "failure") return;
    const key = `${j.workflow_name}::${j.job_name}`;
    if (!byJob[key]) {
      const label = typeof compactJobLabel === "function" ? compactJobLabel(j) : `${j.workflow_name} / ${j.job_name}`;
      byJob[key] = {
        pipeline: j.pipeline_type || "",
        workflow: j.workflow_name,
        jobName: j.job_name,
        label,
        success: 0,
        failure: 0,
      };
    }
    byJob[key][j.conclusion]++;
  });
  const totalFailures = Object.values(byJob).reduce((sum, j) => sum + j.failure, 0);
  return Object.values(byJob)
    .map(j => {
      const measured = j.success + j.failure;
      return { ...j, measured, share: totalFailures ? Math.round(j.failure / totalFailures * 100) : 0 };
    })
    .filter(j => j.failure > 0)
    .sort((a, b) => b.failure - a.failure || b.measured - a.measured)
    .slice(0, 10);
}

function buildLowestJobSuccessRates(minMeasured = 5) {
  const byJob = {};
  allJobs.forEach(j => {
    if (j.conclusion !== "success" && j.conclusion !== "failure") return;
    const key = `${j.workflow_name}::${j.job_name}`;
    if (!byJob[key]) {
      const label = typeof compactJobLabel === "function" ? compactJobLabel(j) : `${j.workflow_name} / ${j.job_name}`;
      byJob[key] = {
        pipeline: j.pipeline_type || "",
        workflow: j.workflow_name,
        jobName: j.job_name,
        label,
        success: 0,
        failure: 0,
      };
    }
    byJob[key][j.conclusion]++;
  });
  return Object.values(byJob)
    .map(j => {
      const measured = j.success + j.failure;
      return { ...j, measured, successRate: measured ? Math.round(j.success / measured * 100) : 0 };
    })
    .filter(j => j.measured >= minMeasured)
    .sort((a, b) => a.successRate - b.successRate || b.failure - a.failure || b.measured - a.measured)
    .slice(0, 10);
}

function buildNeutralOutcomeDistribution() {
  const labelsByType = { pr_e2e: "PR CI", nightly: "Nightly", build: "Build", other: "Other" };
  const order = ["pr_e2e", "nightly", "build", "other"];
  const buckets = {};
  order.forEach(pt => { buckets[pt] = { skipped: 0, cancelled: 0, pending: 0, other: 0 }; });
  allJobs.forEach(j => {
    const pt = j.pipeline_type || "other";
    if (!buckets[pt]) buckets[pt] = { skipped: 0, cancelled: 0, pending: 0, other: 0 };
    if (j.conclusion === "skipped") buckets[pt].skipped++;
    else if (j.conclusion === "cancelled") buckets[pt].cancelled++;
    else if (["queued", "in_progress", "pending"].includes(j.conclusion)) buckets[pt].pending++;
    else if (j.conclusion !== "success" && j.conclusion !== "failure") buckets[pt].other++;
  });
  const keys = order.filter(pt => buckets[pt] && Object.values(buckets[pt]).some(v => v > 0));
  return {
    labels: keys.map(pt => labelsByType[pt] || pt),
    skipped: keys.map(pt => buckets[pt].skipped),
    cancelled: keys.map(pt => buckets[pt].cancelled),
    pending: keys.map(pt => buckets[pt].pending),
    other: keys.map(pt => buckets[pt].other),
  };
}

function buildWorkflowDurationQueue() {
  const byRun = {};
  allJobs.forEach(j => {
    const key = `${j.workflow_name}::${j.run_id}`;
    if (!byRun[key]) byRun[key] = { name: j.workflow_name, jobs: [] };
    byRun[key].jobs.push(j);
  });
  const byWorkflow = {};
  Object.values(byRun).forEach(run => {
    const starts = run.jobs.map(j => j.started_at ? new Date(j.started_at) : null).filter(Boolean);
    const ends = run.jobs.map(j => j.completed_at ? new Date(j.completed_at) : null).filter(Boolean);
    if (!starts.length || !ends.length) return;
    const wallClock = Math.max(0, (new Date(Math.max(...ends)) - new Date(Math.min(...starts))) / 1000);
    const queueTimes = run.jobs.map(j => j.queue_time).filter(q => q !== null && q !== undefined && q >= 0);
    const maxQueue = queueTimes.length ? Math.max(...queueTimes) : 0;
    if (!byWorkflow[run.name]) byWorkflow[run.name] = { name: run.name, wallClocks: [], queues: [], jobs: 0 };
    byWorkflow[run.name].wallClocks.push(wallClock);
    byWorkflow[run.name].queues.push(maxQueue);
    byWorkflow[run.name].jobs += run.jobs.length;
  });
  return Object.values(byWorkflow)
    .map(w => ({
      name: w.name,
      avgWallClock: w.wallClocks.length ? w.wallClocks.reduce((s, v) => s + v, 0) / w.wallClocks.length : 0,
      maxQueue: w.queues.length ? Math.max(...w.queues) : 0,
      runs: w.wallClocks.length,
      jobs: w.jobs,
    }))
    .sort((a, b) => b.avgWallClock - a.avgWallClock || b.maxQueue - a.maxQueue)
    .slice(0, 10);
}

function buildWorkflowStabilityMatrix(minMeasured = 5) {
  const byWorkflow = {};
  allJobs.forEach(j => {
    if (j.conclusion !== "success" && j.conclusion !== "failure") return;
    if (!byWorkflow[j.workflow_name]) byWorkflow[j.workflow_name] = { name: j.workflow_name, success: 0, failure: 0 };
    byWorkflow[j.workflow_name][j.conclusion]++;
  });
  return Object.values(byWorkflow)
    .map(w => {
      const measured = w.success + w.failure;
      const successRate = measured ? Math.round(w.success / measured * 100) : 0;
      return {
        ...w,
        measured,
        successRate,
        radius: Math.max(4, Math.min(22, Math.sqrt(w.failure + 1) * 2.5)),
      };
    })
    .filter(w => w.measured >= minMeasured)
    .sort((a, b) => b.failure - a.failure || b.measured - a.measured)
    .slice(0, 40);
}

function buildJobDurationVariability(minSamples = 5) {
  const byJob = {};
  allJobs.forEach(j => {
    if (!j.duration || j.duration <= 0) return;
    const key = `${j.workflow_name}::${j.job_name}`;
    if (!byJob[key]) {
      const label = typeof compactJobLabel === "function" ? compactJobLabel(j) : `${j.workflow_name} / ${j.job_name}`;
      byJob[key] = { workflow: j.workflow_name, jobName: j.job_name, label, durations: [] };
    }
    byJob[key].durations.push(j.duration);
  });
  return Object.values(byJob)
    .filter(j => j.durations.length >= minSamples)
    .map(j => {
      const p50 = percentile(j.durations, 50);
      const p90 = percentile(j.durations, 90);
      return {
        ...j,
        samples: j.durations.length,
        p50,
        p90,
        ratio: Number((p90 / Math.max(p50, 1)).toFixed(1)),
      };
    })
    .sort((a, b) => b.ratio - a.ratio || b.p90 - a.p90)
    .slice(0, 10);
}

function buildQueueTrendByExecutionDate() {
  const byDate = {};
  allJobs.forEach(j => {
    if (j.queue_time === null || j.queue_time === undefined || j.queue_time < 0) return;
    const rawDate = j.completed_at || j.started_at || j.run_created_at;
    if (!rawDate) return;
    const date = rawDate.slice(0, 10);
    if (!byDate[date]) byDate[date] = [];
    byDate[date].push(j.queue_time);
  });
  return Object.entries(byDate)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, values]) => ({
      date,
      samples: values.length,
      p50: percentile(values, 50),
      p90: percentile(values, 90),
    }));
}

function getExecutionTrendSource(pipelines) {
  if (snapshotsData?.execution_trends) return snapshotsData.execution_trends;
  const trendSource = {};
  Object.entries(pipelines).forEach(([pt, p]) => {
    if (p.daily_trend && p.daily_trend.length) trendSource[pt] = p.daily_trend;
  });
  return trendSource;
}

function getSnapshotTrendSource(pipelines) {
  if (snapshotsData?.pipeline_types) return snapshotsData.pipeline_types;
  const trendSource = {};
  Object.entries(pipelines).forEach(([pt, p]) => {
    if (p.daily_trend && p.daily_trend.length) {
      trendSource[pt] = p.daily_trend.map(d => ({
        ...d,
        health_score: d.health_score ?? d.health ?? null,
      }));
    }
  });
  return trendSource;
}

function collectTrendDates(trendSource) {
  const dates = new Set();
  Object.values(trendSource).forEach(entries => entries.forEach(d => dates.add(d.date)));
  return [...dates].sort();
}

function jobsByRunCount(jobs) {
  return new Set(jobs.map(j => `${j.workflow_name || ""}::${j.run_id || ""}`)).size;
}

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
  const scoreText = completeSample && p.health_score !== null
    ? `${p.health_score}/100`
    : `${p.success_rate}% observed`;
  let html = `<h2>${label} Pipeline <span style="color:${p.rating_color};font-size:18px">${scoreText}</span></h2>`;
  html += `<div style="display:flex;gap:16px;margin:12px 0;flex-wrap:wrap">
    <div class="metric-card"><div class="metric-value">${p.workflow_runs ?? jobsByRunCount(jobs)}</div><div class="metric-label">Workflow Runs</div></div>
    <div class="metric-card"><div class="metric-value">${p.total}</div><div class="metric-label">Total Jobs</div></div>
    <div class="metric-card"><div class="metric-value">${p.measured_total || 0}</div><div class="metric-label">Measured Jobs</div></div>
    <div class="metric-card"><div class="metric-value">${p.success_rate}%</div><div class="metric-label">${completeSample ? "Success Rate" : "Observed Success"}</div></div>
    <div class="metric-card"><div class="metric-value">${p.failure}</div><div class="metric-label">Failures</div></div>
    <div class="metric-card"><div class="metric-value">${p.skipped || 0}</div><div class="metric-label">Skipped</div></div>
    <div class="metric-card"><div class="metric-value">${p.cancelled || 0}</div><div class="metric-label">Cancelled</div></div>
    <div class="metric-card"><div class="metric-value">${p.pending || 0}</div><div class="metric-label">Pending</div></div>
    <div class="metric-card"><div class="metric-value">${p.recent_24h_failures || 0}</div><div class="metric-label">24h Failures</div></div>
  </div>`;

  html += `<div class="ai-context-box">
    <div><strong>AI explanation context</strong> <span style="color:var(--text-dim)">AI-derived from failed samples only</span></div>
    <div style="margin-top:6px">${relatedAiBadge({ pipeline: ptype })}</div>
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
    html += `<div style="margin:12px 0 4px;font-weight:600;font-size:14px">${escapeHtml(wf)} <span style="color:var(--text-dim);font-weight:400">(${wJobs.length} failures)</span>
      <span style="font-weight:400;margin-left:8px">${relatedAiBadge({ pipeline: ptype, workflow: wf })}</span>
    </div>`;
    wJobs.slice(0, 5).forEach(j => {
      const runUrl = `https://github.com/vllm-project/vllm-ascend/actions/runs/${j.run_id}`;
      html += `<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin:4px 0;font-size:13px">
        <span class="badge badge-${j.conclusion === 'failure' ? 'critical' : 'medium'}">${j.conclusion}</span>
        <span style="margin-left:8px">${escapeHtml(j.job_name.length > 60 ? j.job_name.slice(0, 60) + '...' : j.job_name)}</span>
        <a href="${runUrl}" target="_blank" style="color:var(--link);margin-left:8px;font-size:12px">Run -&gt;</a>
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

  let html = `<h2>${escapeHtml(wfName)} <span style="font-size:16px;color:${sr < 50 ? 'var(--critical)' : sr < 75 ? 'var(--medium)' : 'var(--low)'}">${t("successRateLabel")} ${sr}%</span></h2>`;
  html += `<div style="display:flex;gap:16px;margin:12px 0;flex-wrap:wrap">
    <div class="metric-card"><div class="metric-value">${total}</div><div class="metric-label">Total Jobs</div></div>
    <div class="metric-card"><div class="metric-value">${success.length}</div><div class="metric-label">Success</div></div>
    <div class="metric-card critical"><div class="metric-value">${failed.length}</div><div class="metric-label">Failed</div></div>
    <div class="metric-card"><div class="metric-value">${fmtDuration(jobs.reduce((s,j) => s + j.duration, 0) / Math.max(1, total))}</div><div class="metric-label">Avg Duration</div></div>
  </div>`;

  const pipeline = jobs[0]?.pipeline_type || "";
  html += `<div class="ai-context-box">
    <div><strong>AI explanation context</strong> <span style="color:var(--text-dim)">AI-derived from failed samples only</span></div>
    <div style="margin-top:6px">${relatedAiBadge({ pipeline, workflow: wfName })}</div>
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
      <a href="${runUrl}" target="_blank" style="color:var(--link);margin-left:8px;font-size:12px">Run -&gt;</a>
      ${j.conclusion === "failure" ? `<span style="margin-left:8px">${relatedAiBadge({ pipeline: j.pipeline_type, workflow: j.workflow_name, jobName: j.job_name, jobId: j.job_id })}</span>` : ""}
    </div>`;
  });

  document.getElementById("detailContent").innerHTML = html;
  document.getElementById("detailModal").classList.add("open");
}
