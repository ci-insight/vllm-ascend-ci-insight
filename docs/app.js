const INDEX_URL = "reports/index.json";

let allReports = [];

async function loadReports() {
  const el = document.getElementById("reportList");
  el.innerHTML = '<div class="loading">Loading reports...</div>';

  try {
    const resp = await fetch(INDEX_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    allReports = data.reports || [];
    renderReports();
    updateStats();
  } catch (err) {
    el.innerHTML = `<div class="loading" style="color:var(--critical)">
      Failed to load reports. Run ascend to generate reports first.
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
    el.innerHTML = '<div class="empty">No reports found.</div>';
    return;
  }

  el.innerHTML = filtered.map(r => {
    const date = new Date(r.analyzed_at).toLocaleString();
    const badge = `<span class="badge badge-${r.top_severity}">${r.top_severity}</span>`;
    return `
      <div class="report-card" onclick="openDetail(${r.pr_number})">
        <div class="card-header">
          <span class="card-title">#${r.pr_number} ${escapeHtml(r.pr_title)}</span>
          <div class="card-meta">
            <span>${r.failed_job_count} failed</span>
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
    `${total} reports | ${critical} critical | ${high} high`;
}

async function openDetail(prNumber) {
  const report = allReports.find(r => r.pr_number === prNumber);
  if (!report) return;

  const modal = document.getElementById("detailModal");
  document.getElementById("detailContent").innerHTML = '<div class="loading">Loading...</div>';
  modal.classList.add("open");

  try {
    const resp = await fetch(report.json_path);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderDetail(data);
  } catch (err) {
    document.getElementById("detailContent").innerHTML =
      `<div class="loading" style="color:var(--critical)">Failed to load: ${err.message}</div>`;
  }
}

function renderDetail(data) {
  const analyses = data.analyses || [];
  const runs = data.runs || [];

  let html = `<h2>#${data.pr_number} ${escapeHtml(data.pr_title)}</h2>`;
  html += `<div class="meta-line">Author: ${escapeHtml(data.pr_author)}</div>`;
  html += `<div class="meta-line">URL: <a href="${escapeHtml(data.pr_url)}" target="_blank">${escapeHtml(data.pr_url)}</a></div>`;
  html += `<div class="meta-line">Analyzed: ${new Date(data.analyzed_at).toLocaleString()}</div>`;

  // Run summary
  html += `<h3>Affected CI Runs</h3>`;
  if (!runs.length) {
    html += '<div class="meta-line">No runs recorded.</div>';
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

  // Analysis results
  html += `<h3>Analysis (${analyses.length} failed jobs)</h3>`;
  if (!analyses.length) {
    html += '<div class="empty">No analysis results.</div>';
  } else {
    analyses.forEach(a => {
      html += `<h4>[${a.severity.toUpperCase()}] ${escapeHtml(a.job_name)} <small style="color:var(--text-dim)">(confidence: ${a.confidence}%)</small></h4>`;

      html += `<div class="root-cause">${escapeHtml(a.root_cause || "No root cause analysis.")}</div>`;

      if (a.error_snippets && a.error_snippets.length) {
        html += "<div><strong>Error Snippets:</strong></div>";
        a.error_snippets.forEach(s => {
          html += `<div class="snippet">${escapeHtml(s)}</div>`;
        });
      }

      if (a.related_files && a.related_files.length) {
        html += "<div><strong>Related Files:</strong></div>";
        html += '<ul class="file-list">';
        a.related_files.forEach(f => {
          html += `<li>${escapeHtml(f)}</li>`;
        });
        html += "</ul>";
      }

      if (a.fix_suggestions && a.fix_suggestions.length) {
        html += "<div><strong>Fix Suggestions:</strong></div>";
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

// Filter handlers
document.getElementById("searchInput").addEventListener("input", renderReports);
document.getElementById("severityFilter").addEventListener("change", renderReports);

// Load on page start
loadReports();
