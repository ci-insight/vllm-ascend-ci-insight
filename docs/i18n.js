const I18N = {
  en: {
    title: "vllm-ascend CI Insight",
    searchPlaceholder: "Search PR title, number...",
    allSeverities: "All Severities",
    severity: {
      critical: "Critical",
      high: "High",
      medium: "Medium",
      low: "Low",
      unknown: "Unknown",
    },
    refresh: "Refresh",
    loading: "Loading reports...",
    loadFailed: "Failed to load reports. Run ascend to generate reports first.",
    noReports: "No reports found.",
    failed: "failed",
    reports: "reports",
    affectedRuns: "Affected CI Runs",
    noRuns: "No runs recorded.",
    analysis: "Analysis",
    failedJobs: "failed jobs",
    noAnalysis: "No analysis results.",
    errorSnippets: "Error Snippets:",
    rootCause: "Root Cause",
    relatedFiles: "Related Files:",
    fixSuggestions: "Fix Suggestions:",
    noRootCause: "No root cause analysis.",
    detailFailed: "Failed to load",
    author: "Author",
    analyzed: "Analyzed",
    lang: "中文",
    confidence: "confidence",
  },
  zh: {
    title: "vllm-ascend CI 智能诊断",
    searchPlaceholder: "搜索 PR 标题、编号...",
    allSeverities: "全部严重度",
    severity: {
      critical: "严重",
      high: "高",
      medium: "中",
      low: "低",
      unknown: "未知",
    },
    refresh: "刷新",
    loading: "加载报告中...",
    loadFailed: "加载失败，请先运行 ascend 生成报告。",
    noReports: "暂无报告。",
    failed: "个失败",
    reports: "份报告",
    affectedRuns: "受影响 CI 运行",
    noRuns: "无运行记录。",
    analysis: "分析结果",
    failedJobs: "个失败任务",
    noAnalysis: "无分析结果。",
    errorSnippets: "关键错误片段：",
    rootCause: "根因分析",
    relatedFiles: "关联文件：",
    fixSuggestions: "修复建议：",
    noRootCause: "暂无根因分析。",
    detailFailed: "加载失败",
    author: "作者",
    analyzed: "分析时间",
    lang: "English",
    confidence: "置信度",
  },
};

let currentLang = localStorage.getItem("ascend-lang") || "en";

function t(key) {
  return I18N[currentLang]?.[key] || I18N.en[key] || key;
}

function tSeverity(sev) {
  return I18N[currentLang]?.severity?.[sev] || sev;
}

function toggleLang() {
  currentLang = currentLang === "zh" ? "en" : "zh";
  localStorage.setItem("ascend-lang", currentLang);
  document.getElementById("langToggle").textContent = t("lang");
  loadReports(); // re-render
}
