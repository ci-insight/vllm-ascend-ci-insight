const I18N = {
  en: {
    title: "vllm-ascend CI Insight",
    searchPlaceholder: "Search PR title, number...",
    allSeverities: "All Severities",
    allCategories: "All Categories",
    severity: {
      critical: "Critical",
      high: "High",
      medium: "Medium",
      low: "Low",
      unknown: "Unknown",
    },
    category: {
      code: "Code Bug",
      build: "Build/CI Script",
      infra: "Infrastructure",
      test: "Test Case",
      lint: "Lint/Format",
      compat: "Compatibility",
      perf: "Performance",
      other: "Other",
    },
    refresh: "Refresh",
    loading: "Loading...",
    loadFailed: "Failed to load reports.",
    noReports: "No reports found.",
    failed: "failed",
    reports: "reports",
    totalPRs: "PRs Analyzed",
    totalJobs: "Failed Jobs",
    avgConf: "Avg Confidence",
    severityBreakdown: "Severity Breakdown",
    topWorkflows: "Top Failing Workflows",
    categoryBreakdown: "Category Breakdown",
    dailyTrend: "Daily Failure Trend",
    recentReports: "Recent Reports",
    pr: "PR",
    jobs: "Jobs",
    severityLabel: "Severity",
    categoryLabel: "Category",
    date: "Date",
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
    chartLoading: "Loading charts...",
    classified: "classified",
    unclassified: "unclassified",
  },
  zh: {
    title: "vllm-ascend CI 智能诊断",
    searchPlaceholder: "搜索 PR 标题、编号...",
    allSeverities: "全部严重度",
    allCategories: "全部分类",
    severity: {
      critical: "严重",
      high: "高",
      medium: "中",
      low: "低",
      unknown: "未知",
    },
    category: {
      code: "业务代码问题",
      build: "工程脚本问题",
      infra: "基础设施问题",
      test: "测试用例问题",
      lint: "代码规范问题",
      compat: "兼容性问题",
      perf: "性能问题",
      other: "其他",
    },
    refresh: "刷新",
    loading: "加载中...",
    loadFailed: "加载报告失败。",
    noReports: "暂无报告。",
    failed: "个失败",
    reports: "份报告",
    totalPRs: "分析 PR 数",
    totalJobs: "失败任务数",
    avgConf: "平均置信度",
    severityBreakdown: "严重度分布",
    topWorkflows: "失败最多的 Workflow",
    categoryBreakdown: "问题分类统计",
    dailyTrend: "每日失败趋势",
    recentReports: "最近报告",
    pr: "PR",
    jobs: "任务",
    severityLabel: "严重度",
    categoryLabel: "分类",
    date: "日期",
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
    chartLoading: "图表加载中...",
    classified: "已分类",
    unclassified: "未分类",
  },
};

let currentLang = localStorage.getItem("ascend-lang") || "en";

function t(key) {
  return I18N[currentLang]?.[key] || I18N.en[key] || key;
}

function tSeverity(sev) {
  return I18N[currentLang]?.severity?.[sev] || sev;
}

function tCategory(cat) {
  return I18N[currentLang]?.category?.[cat] || cat;
}

function toggleLang() {
  currentLang = currentLang === "zh" ? "en" : "zh";
  localStorage.setItem("ascend-lang", currentLang);
  document.getElementById("langToggle").textContent = t("lang");
  location.reload();
}
