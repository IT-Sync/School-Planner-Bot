const initData = window.Telegram?.WebApp?.initData || "";
const initDataUnsafe = window.Telegram?.WebApp?.initDataUnsafe;
const weekdayLabels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const state = {
  weekday: new Date().getDay() || 7,
  entries: [],
  week: {},
  editingEntry: null,
};

function fetchJSON(url, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": initData,
    ...(options.headers || {}),
  };
  return fetch(url, { ...options, headers }).then(async (response) => {
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail ?? "Ошибка запроса");
    }
    if (response.status === 204) return null;
    return response.json();
  });
}

async function loadDay() {
  const data = await fetchJSON(`/api/schedule/day?weekday=${state.weekday}`);
  state.entries = data.entries;
  renderDay();
}

async function loadWeek() {
  const data = await fetchJSON("/api/schedule/week");
  state.week = data.week;
  renderWeek();
}

function renderDay() {
  const dateLabel = document.getElementById("selected-date");
  const weekdayLabel = document.getElementById("selected-weekday");
  const entriesContainer = document.getElementById("day-entries");
  dateLabel.textContent = new Date().toLocaleDateString("ru-RU");
  weekdayLabel.textContent = `(${weekdayLabels[state.weekday - 1]})`;
  entriesContainer.innerHTML = "";
  if (!state.entries.length) {
    entriesContainer.innerHTML = '<p class="empty">На этот день пока ничего нет</p>';
    return;
  }
  state.entries.forEach((entry) => {
    const card = document.createElement("div");
    card.className = "entry-card";
    card.innerHTML = `
      <div class="time">${entry.start_time} – ${entry.end_time}</div>
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
    entriesContainer.appendChild(card);
  });
}

function renderWeek() {
  const grid = document.getElementById("week-grid");
  grid.innerHTML = "";
  Object.entries(state.week).forEach(([weekday, entries]) => {
    const card = document.createElement("div");
    card.className = "week-card";
    card.innerHTML = `<strong>${weekdayLabels[weekday - 1]}</strong>`;
    entries.slice(0, 3).forEach((entry) => {
      const row = document.createElement("div");
      row.className = "week-row";
      row.innerHTML = `<small>${entry.start_time}</small> ${entry.label}`;
      card.appendChild(row);
    });
    card.addEventListener("click", () => {
      state.weekday = Number(weekday);
      switchTab("today");
      loadDay();
    });
    grid.appendChild(card);
  });
}

function switchTab(tab) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id.startsWith(tab));
  });
  if (tab === "week") loadWeek();
}

function openModal(entry) {
  state.editingEntry = entry ?? null;
  const modal = document.getElementById("modal");
  modal.classList.remove("hidden");
  const form = document.getElementById("entry-form");
  form.reset();
  if (entry) {
    form.type.value = entry.type;
    form.label.value = entry.label;
    form.location.value = entry.location ?? "";
    form.subtitle.value = entry.subtitle ?? "";
    setPickerValue("start-picker", entry.start_time);
    setPickerValue("end-picker", entry.end_time);
    form.start_time.value = entry.start_time;
    form.end_time.value = entry.end_time;
  } else {
    setPickerValue("start-picker", "08:00");
    setPickerValue("end-picker", "08:45");
    form.start_time.value = "08:00";
    form.end_time.value = "08:45";
  }
}

function closeModal() {
  document.getElementById("modal").classList.add("hidden");
  state.editingEntry = null;
}

function buildTimePicker(id) {
  const container = document.getElementById(id);
  for (let hour = 6; hour <= 22; hour += 1) {
    ["00", "15", "30", "45"].forEach((minute) => {
      const button = document.createElement("button");
      const label = `${hour.toString().padStart(2, "0")}:${minute}`;
      button.textContent = label;
      button.type = "button";
      button.addEventListener("click", () => {
        setPickerValue(id, label);
        const target = document.querySelector(`#entry-form input[name="${id === "start-picker" ? "start_time" : "end_time"}"]`);
        target.value = label;
      });
      container.appendChild(button);
    });
  }
}

function setPickerValue(id, value) {
  document.querySelectorAll(`#${id} button`).forEach((button) => {
    button.classList.toggle("active", button.textContent === value);
  });
}

async function handleFormSubmit(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  const payload = Object.fromEntries(formData);
  if (!payload.start_time || !payload.end_time) {
    alert("Выберите время занятия");
    return;
  }
  const body = JSON.stringify({
    weekday: state.weekday,
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
    await loadDay();
    if (window.Telegram?.WebApp?.MainButton) {
      window.Telegram.WebApp.HapticFeedback.impactOccurred("medium");
    }
  } catch (error) {
    alert(error.message);
  }
}

async function handleEntryAction(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const action = target.dataset.action;
  if (!action) return;
  const id = Number(target.dataset.id);
  const type = target.dataset.type;
  const entry = state.entries.find((item) => item.id === id);
  if (!entry) return;
  if (action === "edit") {
    openModal(entry);
  } else if (action === "delete") {
    if (!confirm("Удалить запись?")) return;
    try {
      await fetchJSON(`/api/schedule/item/${id}?type=${type}`, { method: "DELETE" });
      await loadDay();
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
}

function setupListeners() {
  document.getElementById("add-entry").addEventListener("click", () => openModal());
  document.getElementById("edit-day").addEventListener("click", () => openModal());
  document.getElementById("day-entries").addEventListener("click", handleEntryAction);
  document.getElementById("reset-schedule").addEventListener("click", () => alert("Функция в разработке"));
}

function renderAccountInfo() {
  const container = document.getElementById("account-info");
  const user = initDataUnsafe?.user;
  if (!user) {
    container.textContent = "Не удалось получить данные аккаунта";
    return;
  }
  container.innerHTML = `
    <strong>Аккаунт</strong>
    <p>${user.first_name ?? ""} ${user.last_name ?? ""}</p>
    <p>@${user.username ?? "—"}</p>
  `;
}

async function bootstrap() {
  buildTimePicker("start-picker");
  buildTimePicker("end-picker");
  setupTabs();
  setupModal();
  setupListeners();
  renderAccountInfo();
  await loadDay();
}

bootstrap();
