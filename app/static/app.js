(() => {
  let pendingForms = null;
  const clockFormatter = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });

  function formatCountdown(milliseconds) {
    if (milliseconds <= 0) return "已完成";
    let seconds = Math.ceil(milliseconds / 1000);
    const days = Math.floor(seconds / 86400);
    seconds %= 86400;
    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;
    const minutes = Math.floor(seconds / 60);
    seconds %= 60;
    return "还需 " + (days ? days + " 天 " : "") + String(hours).padStart(2, "0") + ":" + String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
  }

  function formatChinaTime(milliseconds) {
    const pieces = Object.fromEntries(
      clockFormatter.formatToParts(new Date(milliseconds)).map((part) => [part.type, part.value]),
    );
    return pieces.year + "-" + pieces.month + "-" + pieces.day + " " + pieces.hour + ":" + pieces.minute + ":" + pieces.second;
  }

  function tick() {
    const now = Date.now();
    const upcoming = [];
    document.querySelectorAll("[data-countdown]").forEach((element) => {
      const finishAt = Date.parse(element.dataset.finishAt);
      if (!Number.isNaN(finishAt)) {
        element.textContent = formatCountdown(finishAt - now);
        if (finishAt > now) {
          upcoming.push(finishAt);
        } else {
          const card = element.closest(".slot-card");
          const pill = card.querySelector(".status-pill");
          card.classList.add("is-complete");
          pill.classList.remove("running");
          pill.classList.add("done");
          pill.textContent = "已完成";
        }
      }
    });
    const count = document.querySelector("[data-active-count]");
    if (count) count.firstChild.textContent = upcoming.length + " ";
    const nextFinish = document.querySelector("[data-next-finish]");
    if (nextFinish) nextFinish.textContent = upcoming.length ? formatChinaTime(Math.min(...upcoming)) : "暂无进行中的任务";
    document.querySelectorAll("[data-boost-end]").forEach((element) => {
      if (Date.parse(element.dataset.boostEnd) <= now) element.remove();
    });
    const clearBoostsForm = document.querySelector("[data-clear-boosts-form]");
    if (clearBoostsForm) clearBoostsForm.hidden = !document.querySelector("[data-boost-end]");
    document.querySelectorAll("[data-clock='asia-shanghai']").forEach((element) => {
      element.textContent = formatChinaTime(now);
    });
  }

  function syncBoostMode() {
    document.querySelectorAll("[data-boost-mode]").forEach((select) => {
      const form = select.closest("form");
      const field = form.querySelector("[data-sync-field]");
      const syncing = select.value === "sync";
      field.hidden = !syncing;
      field.querySelectorAll("input").forEach((input) => {
        input.disabled = !syncing;
        input.required = syncing;
      });
    });
  }

  function captureForms(sourceForm) {
    const sourceAction = sourceForm ? sourceForm.getAttribute("action") : "";
    const clearedSlot = sourceAction.match(/^\/tasks\/([^/]+)\/clear$/);
    const taskForms = Array.from(document.querySelectorAll(".task-form"))
      .filter((form) => !clearedSlot || form.getAttribute("action") !== "/tasks/" + clearedSlot[1])
      .map((form) => ({
        action: form.getAttribute("action"),
        values: Object.fromEntries(Array.from(form.querySelectorAll("input[name]")).map((input) => [input.name, input.value])),
      }));
    const boostForm = document.querySelector(".boost-form");
    const boostValues = boostForm
      ? Object.fromEntries(Array.from(boostForm.querySelectorAll("select[name], input[name]")).map((input) => [input.name, input.value]))
      : null;
    pendingForms = { taskForms, boostValues, submittedAction: sourceAction };
  }

  function restoreForms() {
    if (!pendingForms) return;
    document.querySelectorAll(".task-form").forEach((form) => {
      const action = form.getAttribute("action");
      const saved = pendingForms.taskForms.find((item) => item.action === action);
      if (!saved) return;
      if (action === pendingForms.submittedAction && !form.querySelector(".field-error")) return;
      form.querySelectorAll("input[name]").forEach((input) => {
        input.value = saved.values[input.name] ?? "";
      });
    });
    const boostForm = document.querySelector(".boost-form");
    if (boostForm && pendingForms.boostValues) {
      boostForm.querySelectorAll("select[name], input[name]").forEach((input) => {
        input.value = pendingForms.boostValues[input.name] ?? input.value;
      });
    }
    pendingForms = null;
  }

  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-boost-mode]")) syncBoostMode();
  });
  document.addEventListener("htmx:beforeRequest", (event) => {
    const element = event.detail.elt;
    const sourceForm = element && element.closest ? element.closest("form") : null;
    if (sourceForm && sourceForm.closest("#dashboard")) captureForms(sourceForm);
  });
  document.addEventListener("htmx:afterSwap", () => {
    restoreForms();
    syncBoostMode();
    tick();
  });
  syncBoostMode();
  tick();
  window.setInterval(tick, 1000);
})();
