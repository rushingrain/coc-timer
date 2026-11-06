(() => {
  let pendingForms = null;
  let pendingScroll = null;
  const dashboardClocks = new WeakMap();
  const gameClocks = new WeakMap();
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

  function formatGameDuration(milliseconds) {
    if (milliseconds <= 0) return "已完成";
    const totalMinutes = Math.floor(milliseconds / 60000);
    const days = Math.floor(totalMinutes / 1440);
    const hours = Math.floor(totalMinutes / 60) % 24;
    const minutes = totalMinutes % 60;
    const parts = [];
    if (days) parts.push(days + " 天");
    if (hours) parts.push(hours + " 小时");
    if (minutes) parts.push(minutes + " 分钟");
    return parts.length ? parts.join(" ") : "1 分钟";
  }

  function dashboardNow() {
    const dashboard = document.getElementById("dashboard");
    if (!dashboard) return Date.now();
    const serverNow = Date.parse(dashboard.dataset.serverNow);
    if (!dashboardClocks.has(dashboard) || dashboardClocks.get(dashboard).serverNow !== serverNow) {
      dashboardClocks.set(dashboard, {
        serverNow: Number.isNaN(serverNow) ? Date.now() : serverNow,
        startedAt: performance.now(),
      });
    }
    const clock = dashboardClocks.get(dashboard);
    return clock.serverNow + performance.now() - clock.startedAt;
  }

  function gameRemaining(element, now) {
    if (!gameClocks.has(element) || gameClocks.get(element).source !== element.dataset.gameClock) {
      const clock = JSON.parse(element.dataset.gameClock);
      clock.source = element.dataset.gameClock;
      clock.anchorAt = Date.parse(element.closest("#dashboard").dataset.serverNow);
      clock.boosts = clock.boosts.map((boost) => ({
        startsAt: Date.parse(boost.starts_at),
        endsAt: Date.parse(boost.ends_at),
        multiplier: boost.multiplier,
      }));
      gameClocks.set(element, clock);
    }
    const clock = gameClocks.get(element);
    let remaining = clock.remaining_ms - Math.max(0, now - clock.anchorAt);
    clock.boosts.forEach((boost) => {
      const overlap = Math.max(0, Math.min(now, boost.endsAt) - Math.max(clock.anchorAt, boost.startsAt));
      remaining -= overlap * (boost.multiplier - 1);
    });
    return Math.max(0, remaining);
  }

  function chinaTimeParts(milliseconds) {
    return Object.fromEntries(
      clockFormatter.formatToParts(new Date(milliseconds)).map((part) => [part.type, part.value]),
    );
  }

  function formatChinaTime(milliseconds) {
    const pieces = chinaTimeParts(milliseconds);
    return pieces.year + "-" + pieces.month + "-" + pieces.day + " " + pieces.hour + ":" + pieces.minute + ":" + pieces.second;
  }

  function finishWindow(finishAt, now, today) {
    if (finishAt <= now) return null;
    const finish = chinaTimeParts(finishAt);
    const hour = Number(finish.hour);
    if (hour >= 23 || hour < 7) return "night";
    if (finish.year === today.year && finish.month === today.month && finish.day === today.day) return "today";
    return null;
  }

  function tick() {
    const now = dashboardNow();
    const today = chinaTimeParts(now);
    document.querySelectorAll("[data-game-countdown]").forEach((element) => {
      element.textContent = formatGameDuration(gameRemaining(element, now));
    });
    const upcoming = [];
    document.querySelectorAll("[data-countdown]").forEach((element) => {
      const finishAt = Date.parse(element.dataset.finishAt);
      if (!Number.isNaN(finishAt)) {
        element.textContent = formatCountdown(finishAt - now);
        const card = element.closest(".slot-card");
        const completionWindow = finishWindow(finishAt, now, today);
        card.querySelectorAll("[data-finish-notice]").forEach((notice) => {
          notice.hidden = notice.dataset.finishNotice !== completionWindow;
        });
        if (finishAt > now) {
          upcoming.push(finishAt);
        } else {
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
    const sourceCard = sourceForm ? sourceForm.closest(".slot-card") : null;
    const scrollState = {
      top: window.scrollY,
      cardAction: sourceCard ? sourceCard.querySelector(".task-form").getAttribute("action") : null,
      cardTop: sourceCard ? sourceCard.getBoundingClientRect().top : null,
    };
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
    pendingForms = { taskForms, boostValues, submittedAction: sourceAction, scrollState };
  }

  function restoreForms() {
    if (!pendingForms) return;
    const scrollState = pendingForms.scrollState;
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
    pendingScroll = scrollState;
    pendingForms = null;
  }

  function restoreScroll() {
    if (!pendingScroll) return;
    const scrollState = pendingScroll;
    pendingScroll = null;
    window.requestAnimationFrame(() => {
      const cardForm = scrollState.cardAction && Array.from(document.querySelectorAll(".task-form"))
        .find((form) => form.getAttribute("action") === scrollState.cardAction);
      const card = cardForm && cardForm.closest(".slot-card");
      const top = card ? scrollState.top + card.getBoundingClientRect().top - scrollState.cardTop : scrollState.top;
      window.scrollTo(window.scrollX, top);
    });
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
  document.addEventListener("htmx:afterSettle", restoreScroll);
  syncBoostMode();
  tick();
  window.setInterval(tick, 1000);
})();
