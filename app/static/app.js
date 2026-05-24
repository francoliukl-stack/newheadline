let settings = null;

const statusBox = document.getElementById("status");

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
    daily_fetch: "每日抓取",
    daily_remind: "每日提醒",
    weekly_publish: "周报生成",
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

load().catch((error) => showStatus(error.message, false));
