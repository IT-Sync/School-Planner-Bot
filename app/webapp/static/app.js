const telegram = window.Telegram?.WebApp;
if (telegram) {
  telegram.ready();
  telegram.expand();
}

const urlParams = new URLSearchParams(window.location.search);
const initDataFromQuery =
  urlParams.get("tgWebAppData") || urlParams.get("tg_web_app_data") || "";
const initData = telegram?.initData || initDataFromQuery || "";

const weekdayLabels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const todayDate = new Date();
const tomorrowDate = new Date(todayDate);
tomorrowDate.setDate(todayDate.getDate() + 1);

const state = {
  todayWeekday: getIsoWeekday(todayDate),
  tomorrowWeekday: getIsoWeekday(tomorrowDate),
  todayEntries: [],
  tomorrowEntries: [],
  week: {},
  editWeekday: getIsoWeekday(todayDate),
  editEntries: [],
  editingEntry: null,
};

function getIsoWeekday(date) {
  const wd = date.getDay();
  return wd === 0 ? 7 : wd;
}

function buildApiUrl(path) {
  const url = new URL(path, window.location.origin);
  if (initData) {
    url.searchParams.set("tg_web_app_data", initData);
  }
  return url.toString();
}

function normalizeTime(value) {
  if (!value) return "";
  if (value.length === 5 && value.includes(":")) return value;
  if (value.includes(":")) {
    const [hours, minutes] = value.split(":");
    return `${hours.padStart(2, "0")}:${(minutes ?? "00").padStart(2, "0")}`;
  }
  return value;
}

function fetchJSON(path, options = {}) {
  const url = buildApiUrl(path);
  const headers = {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": initData,
    ...(options.headers || {}),
  };
  if (!initData) {
    console.warn("Missing Telegram initData; requests will fail in production.");
  }
  return fetch(url, { ...options, headers }).then(async (response) => {
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail ?? "Ошибка запроса");
    }
    if (response.status === 204) return null;
    return response.json();
  });
}

async function loadToday() {
  const data = await fetchJSON(`/api/schedule/day?weekday=${state.todayWeekday}`);
  state.todayEntries = data.entries;
  renderDayView({
    entries: state.todayEntries,
    date: todayDate,
    weekday: state.todayWeekday,
    containerId: "day-entries",
    dateLabelId: "selected-date",
    weekdayLabelId: "selected-weekday",
  });
}

async function loadTomorrow() {
  const data = await fetchJSON(`/api/schedule/day?weekday=${state.tomorrowWeekday}`);
  state.tomorrowEntries = data.entries;
  renderDayView({
    entries: state.tomorrowEntries,
    date: tomorrowDate,
    weekday: state.tomorrowWeekday,
    containerId: "tomorrow-entries",
    dateLabelId: "tomorrow-date",
    weekdayLabelId: "tomorrow-weekday",
  });
}

async function loadWeek() {
  const data = await fetchJSON("/api/schedule/week");
  state.week = data.week;
  renderWeek();
}

async function loadEditEntries(weekday) {
  state.editWeekday = weekday;
  const data = await fetchJSON(`/api/schedule/day?weekday=${weekday}`);
  state.editEntries = data.entries;
  highlightEditWeekday();
  renderEditEntries();
}

function renderDayView({ entries, date, weekday, containerId, dateLabelId, weekdayLabelId }) {
  document.getElementById(dateLabelId).textContent = date.toLocaleDateString("ru-RU");
  document.getElementById(weekdayLabelId).textContent = `(${weekdayLabels[weekday - 1]})`;
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  if (!entries.length) {
    container.innerHTML = '<p class="empty">На этот день пока ничего нет</p>';
    return;
  }
  entries.forEach((entry) => {
    const card = document.createElement("div");
    card.className = "entry-card";
    card.innerHTML = `
      <div class="time">${normalizeTime(entry.start_time)} – ${normalizeTime(entry.end_time)}</div>
      <div class="title">${entry.label}</div>
      <div class="meta">
        <span class="badge ${entry.type}">${entry.type === "lesson" ? "Урок" : "Кружок"}</span>
        ${entry.location ? `<span>${entry.location}</span>` : ""}
      </div>
      ${entry.subtitle ? `<div class="subtitle">${entry.subtitle}</div>` : ""}
    `;
    container.appendChild(card);
  });
}

function renderWeek() {
  const grid = document.getElementById("week-grid");
  grid.innerHTML = "";
  for (let weekday = 1; weekday <= 7; weekday += 1) {
    const entries = state.week[weekday] ?? [];
    const card = document.createElement("div");
    card.className = "week-card";
    card.innerHTML = `<strong>${weekdayLabels[weekday - 1]}</strong>`;
    if (!entries.length) {
      card.innerHTML += '<p class="empty">Нет записей</p>';
    } else {
      entries.forEach((entry) => {
        const row = document.createElement("div");
        row.className = "week-row";
        row.innerHTML = `<small>${entry.start_time}</small> ${entry.label}`;
        card.appendChild(row);
      });
    }
    grid.appendChild(card);
  }
}

function renderEditEntries() {
  const container = document.getElementById("edit-entries");
  container.innerHTML = "";
  if (!state.editEntries.length) {
    container.innerHTML = '<p class="empty">На этот день нет записей. Добавьте первую!</p>';
    return;
  }
  state.editEntries.forEach((entry) => {
    const card = document.createElement("div");
    card.className = "entry-card";
    card.innerHTML = `
      <div class="time">${normalizeTime(entry.start_time)} – ${normalizeTime(entry.end_time)}</div>
      <div class="title">${entry.label}</div>
      <div class="meta">
        <span class="badge ${entry.type}">${entry.type === "lesson" ? "Урок" : "Кружок"}</span>
        ${entry.location ? `<span>${entry.location}</span>` : ""}
      </div>
      <div class="actions">
        <button class="secondary" data-action="edit" data-id="${entry.id}" data-type="${entry.type}">Изменить</button>
        <button class="danger" data-action="delete" data-id="${entry.id}" data-type="${entry.type}">Удалить</button>
      </div>
    `;
    container.appendChild(card);
  });
}

function renderEditWeekdayButtons() {
  const container = document.getElementById("edit-weekdays");
  if (container.childElementCount) return;
  for (let weekday = 1; weekday <= 7; weekday += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = weekdayLabels[weekday - 1];
    button.dataset.weekday = weekday;
    button.addEventListener("click", () => loadEditEntries(weekday));
    container.appendChild(button);
  }
  highlightEditWeekday();
}

function highlightEditWeekday() {
  document.querySelectorAll("#edit-weekdays button").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.weekday) === state.editWeekday);
  });
}

function switchTab(tab) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id.startsWith(tab));
  });
  if (tab === "today") {
    loadToday();
  } else if (tab === "tomorrow") {
    loadTomorrow();
  } else if (tab === "week") {
    loadWeek();
  } else if (tab === "edit") {
    renderEditWeekdayButtons();
    loadEditEntries(state.editWeekday);
  }
}

function openModal(entry, weekdayOverride) {
  state.editingEntry = entry ?? null;
  const modal = document.getElementById("modal");
  modal.classList.remove("hidden");
  const form = document.getElementById("entry-form");
  const title = document.getElementById("modal-title");
  form.reset();
  const targetWeekday = weekdayOverride ?? state.editWeekday ?? state.todayWeekday;
  form.dataset.weekday = targetWeekday;
  const startDefault = entry ? normalizeTime(entry.start_time) : "08:00";
  const endDefault = entry ? normalizeTime(entry.end_time) : "08:45";
  if (entry) {
    title.textContent = "Редактирование записи";
    form.type.value = entry.type;
    form.label.value = entry.label;
    form.location.value = entry.location ?? "";
    form.subtitle.value = entry.subtitle ?? "";
  } else {
    title.textContent = "Новое занятие";
    form.type.value = "lesson";
    form.label.value = "";
    form.location.value = "";
    form.subtitle.value = "";
  }
  setPickerValue("start-picker", startDefault, { scrollIntoView: true });
  setPickerValue("end-picker", endDefault, { scrollIntoView: true });
  form.start_time.value = startDefault;
  form.end_time.value = endDefault;
}

function closeModal() {
  document.getElementById("modal").classList.add("hidden");
  state.editingEntry = null;
}

function buildTimePicker(id) {
  const container = document.getElementById(id);
  for (let hour = 6; hour <= 22; hour += 1) {
    for (let minute = 0; minute < 60; minute += 5) {
      const button = document.createElement("button");
      const label = `${hour.toString().padStart(2, "0")}:${minute.toString().padStart(2, "0")}`;
      button.textContent = label;
      button.type = "button";
      button.addEventListener("click", () => {
        setPickerValue(id, label);
        const target = document.querySelector(
          `#entry-form input[name="${id === "start-picker" ? "start_time" : "end_time"}"]`,
        );
        target.value = label;
      });
      container.appendChild(button);
    }
  }
}

function setPickerValue(id, value, { scrollIntoView = false } = {}) {
  document.querySelectorAll(`#${id} button`).forEach((button) => {
    const isActive = button.textContent === value;
    button.classList.toggle("active", isActive);
    if (isActive && scrollIntoView) {
      button.scrollIntoView({ block: "center", inline: "nearest" });
    }
  });
}

function ensureFieldVisible(field) {
  const container = field.closest(".modal-content");
  if (!container) return;
  const padding = 24;
  const fieldRect = field.getBoundingClientRect();
  const containerRect = container.getBoundingClientRect();
  if (fieldRect.top < containerRect.top + padding) {
    container.scrollTop -= containerRect.top + padding - fieldRect.top;
  } else if (fieldRect.bottom > containerRect.bottom - padding) {
    container.scrollTop += fieldRect.bottom - (containerRect.bottom - padding);
  }
}

async function handleFormSubmit(event) {
  event.preventDefault();
  const form = event.target;
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData);
  if (!payload.start_time || !payload.end_time) {
    alert("Выберите время занятия");
    return;
  }
  const targetWeekday = Number(form.dataset.weekday || state.editWeekday || state.todayWeekday);
  const body = JSON.stringify({
    weekday: targetWeekday,
    type: payload.type,
    label: payload.label,
    start_time: payload.start_time,
    end_time: payload.end_time,
    location: payload.location || null,
    subtitle: payload.subtitle || null,
  });
  try {
    if (state.editingEntry) {
      await fetchJSON(`/api/schedule/item/${state.editingEntry.id}`, {
        method: "PUT",
        body,
      });
    } else {
      await fetchJSON("/api/schedule/day", {
        method: "POST",
        body,
      });
    }
    closeModal();
    await Promise.all([loadEditEntries(targetWeekday), loadToday(), loadTomorrow()]);
  } catch (error) {
    alert(error.message);
  }
}

async function handleEditAction(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const action = target.dataset.action;
  if (!action) return;
  const id = Number(target.dataset.id);
  const entry = state.editEntries.find((item) => item.id === id);
  if (!entry) return;
  if (action === "edit") {
    openModal(entry, state.editWeekday);
  } else if (action === "delete") {
    if (!confirm("Удалить запись?")) return;
    try {
      await fetchJSON(`/api/schedule/item/${id}?type=${entry.type}`, { method: "DELETE" });
      await Promise.all([loadEditEntries(state.editWeekday), loadToday(), loadTomorrow()]);
    } catch (error) {
      alert(error.message);
    }
  }
}

function setupTabs() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
}

function setupModal() {
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("modal").addEventListener("click", (event) => {
    if (event.target.id === "modal") closeModal();
  });
  document.getElementById("entry-form").addEventListener("submit", handleFormSubmit);
  document.querySelectorAll("#entry-form input, #entry-form select, #entry-form textarea").forEach((field) => {
    field.addEventListener("focus", () => ensureFieldVisible(field));
  });
}

function setupListeners() {
  document.getElementById("add-entry").addEventListener("click", () => openModal(null, state.editWeekday));
  document.getElementById("edit-entries").addEventListener("click", handleEditAction);
}

async function bootstrap() {
  buildTimePicker("start-picker");
  buildTimePicker("end-picker");
  setupTabs();
  setupModal();
  setupListeners();
  if (!initData) {
    const banner = document.createElement("div");
    banner.className = "card danger";
    banner.textContent =
      "initData отсутствует. Откройте WebApp через кнопку бота или задайте WEBAPP_DEV_USER_ID.";
    document.getElementById("app").prepend(banner);
  }
  await Promise.all([loadToday(), loadTomorrow()]);
}

bootstrap();
