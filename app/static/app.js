let settings = null;

const statusBox = document.getElementById("status");
const JOB_LABELS = {
  provider_health_check: "巡源",
  daily_fetch: "搜集",
  dingtalk_ai_table_push: "入库",
  backfill_publish_dates: "校时",
  dedupe_news: "合并",
  daily_remind: "催审",
  weekly_publish: "出刊与回执",
};

function jobLabel(jobName) {
  return JOB_LABELS[jobName] || jobName;
}

function showStatus(message, ok = true) {
  statusBox.textContent = message;
  statusBox.className = `status ${ok ? "ok" : "error"}`;
}

function getByPath(object, path) {
  return path.split(".").reduce((current, key) => current?.[key], object);
}

function setByPath(object, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  const target = keys.reduce((current, key) => current[key], object);
  target[last] = value;
}

function fillFields() {
  document.querySelectorAll("[data-path]").forEach((field) => {
    const value = getByPath(settings, field.dataset.path);
    if (field.type === "checkbox") {
      field.checked = Boolean(value);
    } else if (field.tagName === "SELECT") {
      field.value = value ?? "";
    } else if (field.dataset.json !== undefined) {
      field.value = JSON.stringify(value, null, 2);
    } else {
      field.value = value ?? "";
    }
  });
  renderSchedule();
}

function collectFields() {
  const next = structuredClone(settings);
  document.querySelectorAll("[data-path]").forEach((field) => {
    let value;
    if (field.type === "checkbox") {
      value = field.checked;
    } else if (field.tagName === "SELECT") {
      value = field.value;
    } else if (field.type === "number") {
      value = Number(field.value);
    } else if (field.dataset.json !== undefined) {
      value = JSON.parse(field.value || "null");
    } else {
      value = field.value;
    }
    setByPath(next, field.dataset.path, value);
  });
  return next;
}

function renderSchedule() {
  const labels = {
    daily_fetch: "搜集：每日新闻处理",
    daily_remind: "催审：每日审核提醒",
    weekly_publish: "出刊：每周发布与回执",
  };
  const host = document.getElementById("scheduleFields");
  host.innerHTML = "";
  Object.entries(labels).forEach(([key, label]) => {
    const task = settings.schedule[key];
    const node = document.createElement("div");
    node.className = "task";
    node.innerHTML = `
      <h3>${label}</h3>
      <label class="check"><input type="checkbox" data-path="schedule.${key}.enabled"> 启用</label>
      <label>小时<input type="number" min="0" max="23" data-path="schedule.${key}.hour"></label>
      <label>分钟<input type="number" min="0" max="59" data-path="schedule.${key}.minute"></label>
      <label>Weekday JSON<textarea data-json data-path="schedule.${key}.weekdays">${JSON.stringify(task.weekdays)}</textarea></label>
    `;
    host.appendChild(node);
  });
  document.querySelectorAll("#scheduleFields [data-path]").forEach((field) => {
    const value = getByPath(settings, field.dataset.path);
    if (field.type === "checkbox") field.checked = Boolean(value);
    else if (field.dataset.json !== undefined) field.value = JSON.stringify(value);
    else field.value = value;
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail || JSON.stringify(body));
  }
  return body;
}

async function load() {
  settings = await api("/settings");
  fillFields();
  await loadRuntime();
  await loadRuns();
  showStatus("设置已加载");
}

document.getElementById("saveBtn").addEventListener("click", async () => {
  try {
    settings = await api("/settings", { method: "PUT", body: JSON.stringify(collectFields()) });
    fillFields();
    showStatus("设置已保存");
  } catch (error) {
    showStatus(error.message, false);
  }
});

document.getElementById("resetBtn").addEventListener("click", async () => {
  if (!confirm("恢复默认设置会清除已保存密钥。继续？")) return;
  settings = await api("/settings/reset", { method: "POST", body: "{}" });
  fillFields();
  showStatus("已恢复默认设置");
});

document.getElementById("exportBtn").addEventListener("click", async () => {
  const exported = await api("/settings/export", { method: "POST", body: "{}" });
  const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "weekly-headlines-settings.json";
  link.click();
  URL.revokeObjectURL(url);
});

document.getElementById("importBtn").addEventListener("click", () => {
  document.getElementById("importFile").click();
});

document.getElementById("importFile").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const payload = JSON.parse(await file.text());
    settings = await api("/settings/import", { method: "POST", body: JSON.stringify(payload) });
    fillFields();
    showStatus("配置已导入");
  } catch (error) {
    showStatus(error.message, false);
  } finally {
    event.target.value = "";
  }
});

document.querySelectorAll("[data-test]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const type = button.dataset.test;
      const payload = type === "dingtalk" ? { target: button.dataset.target } : {};
      const result = await api(`/settings/test/${type}`, { method: "POST", body: JSON.stringify(payload) });
      showStatus(result.message, result.ok);
    } catch (error) {
      showStatus(error.message, false);
    }
  });
});

document.getElementById("statusBtn").addEventListener("click", async () => {
  const result = await api("/scheduler/status");
  document.getElementById("schedulerOutput").textContent = JSON.stringify(result, null, 2);
});

document.getElementById("dryRunBtn").addEventListener("click", async () => {
  const result = await api("/scheduler/install", { method: "POST", body: JSON.stringify({ dry_run: true }) });
  document.getElementById("schedulerOutput").textContent = JSON.stringify(result, null, 2);
});

document.getElementById("installBtn").addEventListener("click", async () => {
  const result = await api("/scheduler/install", { method: "POST", body: JSON.stringify({ dry_run: false }) });
  document.getElementById("schedulerOutput").textContent = JSON.stringify(result, null, 2);
  showStatus("定时任务已安装或更新");
});

async function loadRuntime() {
  const result = await api("/runtime/status");
  const lastRun = result.runs.last_run;
  document.getElementById("runtimeService").textContent = result.service.status;
  document.getElementById("runtimeProvider").textContent =
    `${result.search_provider.provider} / ${result.search_provider.fallback_provider}`;
  document.getElementById("runtimeLastJob").textContent = lastRun ? jobLabel(lastRun.job_name) : "暂无";
  document.getElementById("runtimeLastStatus").textContent = lastRun?.status || "暂无";
  document.getElementById("runtimeNextFetch").textContent = result.scheduler.daily_fetch.next_run || "未启用";
  document.getElementById("runtimeNextRemind").textContent = result.scheduler.daily_remind.next_run || "未启用";
  document.getElementById("runtimeNextPublish").textContent = result.scheduler.weekly_publish.next_run || "未启用";
  document.getElementById("runtimeCounts").textContent =
    `${result.runs.counts.success} / ${result.runs.counts.failed}`;
}

document.getElementById("runtimeBtn").addEventListener("click", async () => {
  try {
    await loadRuntime();
    await loadRuns();
    showStatus("运行情况已刷新");
  } catch (error) {
    showStatus(error.message, false);
  }
});

async function loadRuns() {
  const result = await api("/runs?limit=30");
  const body = document.getElementById("runsBody");
  body.innerHTML = "";
  result.runs.forEach((run) => {
    const row = document.createElement("tr");
    const usedProvider = run.metadata?.used_provider || run.provider || "";
    const message = run.error || run.message || "";
    row.innerHTML = `
      <td>${jobLabel(run.job_name)}</td>
      <td>${run.status}</td>
      <td>${run.started_at}</td>
      <td>${usedProvider}</td>
      <td>${run.result_count}</td>
      <td>${message}</td>
    `;
    body.appendChild(row);
  });
}

document.getElementById("runsBtn").addEventListener("click", async () => {
  try {
    await loadRuns();
    showStatus("运行日志已刷新");
  } catch (error) {
    showStatus(error.message, false);
  }
});

load().catch((error) => showStatus(error.message, false));
