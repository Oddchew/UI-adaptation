const USER = "user_demo";

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function sendEvent(payload) {
  const body = { user_id: USER, interface_id: "ui_demo", ...payload };
  const data = await api("/api/event", { method: "POST", body: JSON.stringify(body) });
  applyUi(data.ui);
  renderModel(data.model);
  renderPackages(data.packages);
  return data;
}

function applyUi(ui) {
  if (!ui) return;
  const help = document.getElementById("help_panel");
  const helpState = ui.help_panel;
  if (helpState && helpState.visible) {
    help.hidden = false;
    document.getElementById("email").classList.add("invalid");
    document.getElementById("password").classList.add("invalid");
  }
  const main = ui.main_content;
  if (main && main.fontSize) {
    document.documentElement.style.setProperty("--font-size", main.fontSize + "px");
  }
  document.getElementById("ui-view").textContent = JSON.stringify(ui, null, 2);
}

function renderModel(m) {
  if (!m) {
    document.getElementById("model-view").textContent = "—";
    return;
  }
  document.getElementById("model-view").textContent = JSON.stringify(m, null, 2);
}

function renderPackages(pkgs) {
  document.getElementById("pkg-view").textContent = JSON.stringify(pkgs || [], null, 2);
}

async function refresh() {
  const [health, model, ui] = await Promise.all([
    api("/api/health"),
    api(`/api/model/${USER}`),
    api("/api/ui-state"),
  ]);
  const el = document.getElementById("health");
  if (health.ok) {
    el.textContent = health.sc ? "A + sc OK" : "A OK (memory)";
    el.className = "badge ok";
  } else {
    el.textContent = "не готов";
    el.className = "badge err";
  }
  renderModel(model.model);
  applyUi(ui.ui);
  renderPackages(ui.packages);
}

document.getElementById("demo-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("email").value.trim();
  if (!email || !email.includes("@")) {
    await sendEvent({
      event_type: "error",
      element_id: "email_input",
      error_code: "validation_email",
      message: "Некорректный email",
    });
    return;
  }
  await sendEvent({
    event_type: "successful_action",
    element_id: "btn_save",
    action_id: "save_profile",
  });
});

document.getElementById("btn-error").addEventListener("click", async () => {
  await sendEvent({
    event_type: "error",
    element_id: "email_input",
    error_code: "validation_email",
    message: "Смоделированная ошибка",
  });
});

document.getElementById("btn-help").addEventListener("click", async () => {
  await sendEvent({
    event_type: "help_request",
    element_id: "password_input",
    help_type: "tooltip",
  });
});

document.getElementById("theme").addEventListener("change", async (e) => {
  const v = e.target.value;
  document.body.classList.toggle("theme-dark", v === "dark");
  await sendEvent({
    event_type: "manual_override",
    element_id: "theme_select",
    property: "theme",
    old_value: v === "dark" ? "light" : "dark",
    new_value: v,
  });
});

document.getElementById("btn-refresh").addEventListener("click", () => refresh());
document.getElementById("btn-reset-b").addEventListener("click", async () => {
  await api("/api/reset-b", { method: "POST", body: "{}" });
  await refresh();
});

refresh().catch((err) => {
  document.getElementById("health").textContent = String(err.message || err);
  document.getElementById("health").className = "badge err";
});
