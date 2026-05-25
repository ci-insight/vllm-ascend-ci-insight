const INDEX_URL = "reports/index.json";
let allReports = [];

function applyI18n() {
  document.title = t("title");
  document.getElementById("pageTitle").textContent = t("title");
  document.getElementById("searchInput").placeholder = t("searchPlaceholder");
  document.getElementById("refreshBtn").textContent = t("refresh");
  document.getElementById("langToggle").textContent = t("lang");

  const sevSel = document.getElementById("severityFilter");
  sevSel.options[0].text = t("allSeverities");
  for (let i = 1; i < sevSel.options.length; i++) {
    sevSel.options[i].text = tSeverity(sevSel.options[i].value);
  }
}

async function loadReports() {
  applyI18n();
  const el = document.getElementById("reportList");
  el.innerHTML = `<div class="loading">${t("loading")}</div>`;

  try {
    const resp = await fetch(INDEX_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    allReports = data.reports || [];
    renderReports();
    updateStats();
  } catch (err) {
    el.innerHTML = `<div class="loading" style="color:var(--critical)">
      ${t("loadFailed")}
      <br><br><small>${err.message}</small>
    </div>`;
  }
}

function renderReports() {
  const search = (document.getElementById("searchInput").value || "").toLowerCase();
  const severity = document.getElementById("severityFilter").value;
  const el = document.getElementById("reportList");

  let filtered = allReports.filter(r => {
    const text = `${r.pr_number} ${r.pr_title}`.toLowerCase();
    if (search && !text.includes(search)) return false;
    if (severity && r.top_severity !== severity) return false;
    return true;
  });

  if (!filtered.length) {
    el.innerHTML = `<div class="empty">${t("noReports")}</div>`;
    return;
  }

  el.innerHTML = filtered.map(r => {
    const date = new Date(r.analyzed_at).toLocaleString(currentLang === "zh" ? "zh-CN" : "en-US");
    const badge = `<span class="badge badge-${r.top_severity}">${tSeverity(r.top_severity)}</span>`;
    return `
      <div class="report-card" onclick="openDetail(${r.pr_number})">
        <div class="card-header">
          <span class="card-title">#${r.pr_number} ${escapeHtml(r.pr_title)}</span>
          <div class="card-meta">
            <span>${r.failed_job_count} ${t("failed")}</span>
            ${badge}
            <span>${date}</span>
          </div>
        </div>
      </div>`;
  }).join("");
}

function updateStats() {
  const total = allReports.length;
  const critical = allReports.filter(r => r.top_severity === "critical").length;
  const high = allReports.filter(r => r.top_severity === "high").length;
  document.getElementById("stats").textContent =
    `${total} ${t("reports")} | ${critical} ${tSeverity("critical")} | ${high} ${tSeverity("high")}`;
}

async function openDetail(prNumber) {
  const report = allReports.find(r => r.pr_number === prNumber);
  if (!report) return;

  const modal = document.getElementById("detailModal");
  document.getElementById("detailContent").innerHTML = `<div class="loading">${t("loading")}</div>`;
  modal.classList.add("open");

  try {
    const resp = await fetch(report.json_path);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderDetail(data);
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
      if (run.jobs) {
        run.jobs.forEach(j => {
          const sevClass = j.conclusion === "failure" ? "badge-high" : "badge-low";
          html += `<div class="meta-line" style="margin-left:16px">
            <span class="badge ${sevClass}">${j.conclusion}</span> ${escapeHtml(j.job_name)}
          </div>`;
        });
      }
    });
  }

  html += `<h3>${t("analysis")} (${analyses.length} ${t("failedJobs")})</h3>`;
  if (!analyses.length) {
    html += `<div class="empty">${t("noAnalysis")}</div>`;
  } else {
    analyses.forEach(a => {
      html += `<h4>[${tSeverity(a.severity)}] ${escapeHtml(a.job_name)} <small style="color:var(--text-dim)">(${t("confidence")}: ${a.confidence}%)</small></h4>`;
      html += `<div class="root-cause">${escapeHtml(a.root_cause || t("noRootCause"))}</div>`;

      if (a.error_snippets && a.error_snippets.length) {
        html += `<div><strong>${t("errorSnippets")}</strong></div>`;
        a.error_snippets.forEach(s => {
          html += `<div class="snippet">${escapeHtml(s)}</div>`;
        });
      }

      if (a.related_files && a.related_files.length) {
        html += `<div><strong>${t("relatedFiles")}</strong></div>`;
        html += '<ul class="file-list">';
        a.related_files.forEach(f => {
          html += `<li>${escapeHtml(f)}</li>`;
        });
        html += "</ul>";
      }

      if (a.fix_suggestions && a.fix_suggestions.length) {
        html += `<div><strong>${t("fixSuggestions")}</strong></div>`;
        html += '<ul class="suggestions">';
        a.fix_suggestions.forEach(s => {
          html += `<li>${escapeHtml(s)}</li>`;
        });
        html += "</ul>";
      }
    });
  }

  document.getElementById("detailContent").innerHTML = html;
}

function closeDetail() {
  document.getElementById("detailModal").classList.remove("open");
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

document.getElementById("searchInput").addEventListener("input", renderReports);
document.getElementById("severityFilter").addEventListener("change", renderReports);

applyI18n();
loadReports();
