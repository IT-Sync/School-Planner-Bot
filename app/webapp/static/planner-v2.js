const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();
const initData = tg?.initData || '';
const $ = (id) => document.getElementById(id);
const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const state = {
  user: null,
  profiles: [],
  pid: null,
  date: null,
  view: 'schedule',
  mode: 'day',
  week: null,
  tasks: [],
  bells: [],
  filter: 'active',
  controller: null,
  request: 0
};
let dirty = false;
let saving = false;
let confirmationOpen = false;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'class') node.className = value;
    else if (key === 'checked' || key === 'disabled' || key === 'selected') node[key] = Boolean(value);
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity))
    if (child != null) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
const button = (text, action, cls = 'button secondary', attrs = {}) => el('button', {
  type: 'button',
  class: cls,
  onclick: async ev => {
    const b = ev.currentTarget;
    if (b.disabled) return;
    b.disabled = true;
    try {
      await attempt(action);
    } finally {
      b.disabled = false;
    }
  },
  ...attrs
}, text);
const field = (label, node, hint) => el('label', {
  class: 'field'
}, label, node, hint ? el('small', {}, hint) : null);
const input = (name, value = '', type = 'text', attrs = {}) => el('input', {
  name,
  value: value ?? '',
  type,
  ...attrs
});
const select = (name, value, options) => el('select', {
  name
}, options.map(([v, t]) => el('option', {
  value: v,
  selected: String(value) === String(v)
}, t)));
const profile = () => state.profiles.find(p => p.id === state.pid);
const editable = () => profile()?.role !== 'viewer';
const path = (suffix = '', pid = state.pid) => `/api/profiles/${pid}${suffix}`;
const clock = t => (t || '').slice(0, 5);
const isoDay = d => new Date(`${d}T12:00:00Z`).getUTCDay() || 7;

function addDays(d, n) {
  const v = new Date(`${d}T12:00:00Z`);
  v.setUTCDate(v.getUTCDate() + n);
  return v.toISOString().slice(0, 10);
}
const monday = d => addDays(d, 1 - isoDay(d));
const localToday = () => new Intl.DateTimeFormat('sv-SE', {
  timeZone: state.user?.timezone || 'Europe/Moscow'
}).format(new Date());
const dateLabel = (d, options = {
  day: 'numeric',
  month: 'long'
}) => new Date(`${d}T12:00:00Z`).toLocaleDateString('ru-RU', {
  timeZone: 'UTC',
  ...options
});

function localMinutes() {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: state.user?.timezone || 'Europe/Moscow',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }).format(new Date());
}

function toast(text, action, label = 'Отменить', error = false) {
  const box = el('div', {
    class: `toast ${error?'error':''}`
  }, el('span', {}, text));
  if (action) box.append(button(label, async () => {
    await action();
    box.remove();
  }, ''));
  $('toast-region').append(box);
  setTimeout(() => box.remove(), action ? 15000 : 6500);
}
async function attempt(action) {
  try {
    await action();
  } catch (e) {
    if (e.name !== 'AbortError') toast(e.message, null, '', true);
  }
}
async function api(url, options = {}) {
  const headers = {
    'X-Telegram-Init-Data': initData,
    ...options.headers
  };
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'same-origin'
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({
      detail: response.status === 413 ? 'Файл слишком большой' : 'Не удалось выполнить запрос. Попробуйте ещё раз.'
    }));
    const detail = data.detail;
    const error = new Error(Array.isArray(detail) ? detail.map(item => typeof item === 'string' ? item : item.msg).join('\n') : (detail || 'Ошибка запроса'));
    error.status = response.status;
    if (response.status === 401) error.message = 'Сессия истекла. Откройте планер заново из Telegram.';
    throw error;
  }
  return response.status === 204 ? null : response.json();
}
const send = (url, method, body) => api(url, {
  method,
  body: body === undefined ? undefined : JSON.stringify(body)
});

function loading() {
  $('main').setAttribute('aria-busy', 'true');
  $('main').replaceChildren(el('div', {
    class: 'loading-panel'
  }, el('div', {
    class: 'skeleton skeleton-heading'
  }), el('div', {
    class: 'skeleton skeleton-card'
  }), el('div', {
    class: 'skeleton skeleton-card'
  })));
}
async function refresh(boot = false) {
  state.controller?.abort();
  state.controller = new AbortController();
  const serial = ++state.request,
    signal = state.controller.signal;
  loading();
  try {
    if (boot) {
      const data = await api('/api/bootstrap', {
        signal
      });
      if (serial !== state.request) return;
      state.user = data.user;
      state.profiles = data.profiles;
      if (!state.profiles.some(p => p.id === state.pid)) state.pid = data.default_profile_id;
      state.date ||= localToday();
    }
    const pid = state.pid,
      start = monday(state.date);
    const [week, tasks, bells] = await Promise.all([api(path(`/week?start=${start}`, pid), {
      signal
    }), api(path('/tasks', pid), {
      signal
    }), api(path('/bells', pid), {
      signal
    })]);
    if (serial !== state.request || pid !== state.pid) return;
    state.week = week;
    state.tasks = tasks.tasks;
    state.bells = bells.slots;
    render();
  } catch (error) {
    if (error.name === 'AbortError') return;
    $('main').replaceChildren(el('div', {
      class: 'empty-state'
    }, el('h2', {}, 'Не удалось открыть расписание'), el('p', {}, error.message), button('Повторить', () => refresh(boot))));
  } finally {
    if (serial === state.request) $('main').setAttribute('aria-busy', 'false');
  }
}

function hero(title, subtitle) {
  return el('div', {
    class: 'hero'
  }, el('div', {
    class: 'hero-copy'
  }, el('span', {
    class: 'eyebrow'
  }, profile()?.name || 'Семейный ежедневник'), el('h1', {}, title), el('p', {}, subtitle)), el('div', {
    class: 'hero-stamp',
    'aria-hidden': 'true'
  }, el('strong', {}, state.date?.slice(-2)), el('span', {}, dateLabel(state.date, {
    month: 'short'
  }))));
}

function render() {
  $('profile-button').disabled = false;
  $('profile-name').textContent = profile()?.name || 'Профиль';
  $('profile-avatar').textContent = (profile()?.name || 'Ш')[0];
  $('profile-avatar').style.backgroundColor = profile()?.color || '';
  document.querySelectorAll('[data-view]').forEach(b => {
    b.classList.toggle('active', b.dataset.view === state.view);
    if (b.dataset.view === state.view) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
  const unfinished = state.tasks.filter(t => !t.completed).length;
  $('task-count').textContent = unfinished;
  $('task-count').classList.toggle('hidden', !unfinished);
  $('main').replaceChildren(state.view === 'tasks' ? renderTasks() : state.view === 'settings' ? renderSettings() : renderSchedule());
}

function changeDate(date) {
  state.date = date;
  if (state.week?.days.some(d => d.date === date)) render();
  else return refresh();
}

function renderSchedule() {
  const day = state.week.days.find(d => d.date === state.date) || {
    entries: [],
    warnings: [],
    holidays: []
  };
  const active = day.entries.filter(e => !e.cancelled);
  const toolbar = el('div', {
    class: 'agenda-toolbar'
  }, el('div', {
    class: 'date-tools'
  }, button('‹', () => changeDate(addDays(state.date, state.mode === 'week' ? -7 : -1)), 'icon-button', {
    'aria-label': 'Предыдущий день'
  }), button('Сегодня', () => changeDate(localToday()), 'small-button'), button('›', () => changeDate(addDays(state.date, state.mode === 'week' ? 7 : 1)), 'icon-button', {
    'aria-label': 'Следующий день'
  })), el('div', {
    class: 'segmented'
  }, ['day', 'week'].map(mode => button(mode === 'day' ? 'День' : 'Неделя', () => {
    state.mode = mode;
    render();
  }, mode === state.mode ? 'active' : ''))));
  const strip = el('div', {
    class: 'week-strip'
  }, state.week.days.map(d => button([el('span', {}, weekdays[d.weekday - 1]), el('strong', {}, d.date.slice(-2)), d.entries.some(e => !e.cancelled) ? el('i', {
    class: 'day-dot'
  }) : null], () => changeDate(d.date), `day-button ${d.date===state.date?'active':''} ${d.date===localToday()?'today':''}`, {
    'aria-label': dateLabel(d.date),
    'aria-pressed': d.date === state.date
  })));
  const agenda = el('section', {
    class: 'panel agenda-panel',
    'aria-label': 'Расписание'
  }, toolbar, strip);
  if (state.mode === 'week') {
    agenda.append(el('div', {
      class: 'week-grid'
    }, state.week.days.map(d => el('section', {
      class: 'week-card'
    }, el('div', {
      class: 'row'
    }, el('h3', {}, dateLabel(d.date, {
      weekday: 'long',
      day: 'numeric',
      month: 'short'
    })), editable() ? button('+', () => eventForm(null, d.date), 'icon-button', {
      'aria-label': `Добавить ${weekdays[d.weekday-1]}`
    }) : null), d.entries.length ? d.entries.map(e => button(`${clock(e.start_time)}  ${e.label}${e.cancelled?' · отменено':''}`, () => eventForm(e, d.date), `week-event ${e.cancelled?'cancelled':''}`)) : el('p', {
      class: 'empty'
    }, 'Свободный день')))));
  } else {
    agenda.append(el('div', {
      class: 'day-heading row'
    }, el('h2', {}, dateLabel(state.date, {
      weekday: 'long',
      day: 'numeric',
      month: 'long'
    })), editable() ? button('Копировать день', copyDayForm, 'text-button') : null));
    if (day.holidays.length) agenda.append(el('p', {
      class: 'notice holiday-banner'
    }, '☀ ', day.holidays.map(h => h.name).join(', ')));
    for (const warning of day.warnings) agenda.append(el('p', {
      class: 'notice warning'
    }, warning.message));
    agenda.append(day.entries.length ? el('div', {
      class: 'timeline'
    }, day.entries.map(e => eventCard(e, state.date))) : el('div', {
      class: 'empty-state'
    }, el('span', {
      class: 'empty-symbol'
    }, '✦'), el('h3', {}, 'Здесь пока свободно'), el('p', {}, 'Добавьте урок или кружок — и день обретёт свой ритм.')));
    if (editable()) agenda.append(button('+ Добавить занятие', () => eventForm(null, state.date), 'button full'));
    else agenda.append(el('p', {
      class: 'read-only-note'
    }, 'У вас доступ только для просмотра.'));
  }
  const now = localMinutes();
  const next = state.date === localToday() ? active.find(e => clock(e.end_time) > now) : active[0];
  const focus = el('section', {
    class: 'focus-card'
  }, el('span', {
    class: 'eyebrow'
  }, next ? (clock(next.start_time) <= now && state.date === localToday() ? 'Сейчас идёт' : 'Следующее занятие') : 'Время для себя'), el('h2', {}, next?.label || 'Все дела позади'), el('div', {
    class: 'focus-time'
  }, next ? clock(next.start_time) : '☀'), el('p', {}, next?.location || 'Пусть в расписании останется место для отдыха.'), el('div', {
    class: 'focus-bottom'
  }, next ? `До ${clock(next.end_time)} · ${next.type==='lesson'?'Урок':'Кружок'}` : 'Хорошего дня!'));
  const stats = el('section', {
    class: 'panel sidebar-section'
  }, el('h3', {}, 'Этот день'), el('div', {
    class: 'stats-line'
  }, el('div', {}, el('strong', {}, active.length), el('small', {}, 'занятий')), el('div', {}, el('strong', {}, active.length ? clock(active.at(-1).end_time) : '—'), el('small', {}, 'конец дня'))));
  const actions = el('section', {
    class: 'panel sidebar-section side-links'
  }, el('h3', {}, 'Под рукой'), button('Домашние задания →', () => {
    state.view = 'tasks';
    render();
  }, 'text-button'), editable() ? button('Поделиться расписанием →', shareForm, 'text-button') : null, button('Импортировать расписание →', () => importForm(), 'text-button'));
  return el('div', {}, hero('Каждому дню — свой план.', `${dateLabel(state.date,{month:'long',year:'numeric'})} · ${state.user.timezone}`), el('div', {
    class: 'workspace'
  }, agenda, el('aside', {
    class: 'sidebar'
  }, focus, stats, actions)));
}

function eventCard(e, date) {
  const current = date === localToday() && !e.cancelled && clock(e.start_time) <= localMinutes() && clock(e.end_time) > localMinutes();
  return el('article', {
    class: `event ${e.cancelled?'cancelled':''}`
  }, el('div', {
    class: 'event-time'
  }, clock(e.start_time), el('small', {}, clock(e.end_time))), button([el('div', {
    class: 'event-line'
  }, el('strong', {
    class: 'event-name'
  }, e.label), el('span', {
    class: `badge ${e.type}`
  }, e.cancelled ? 'Отменено' : current ? 'Сейчас' : e.type === 'lesson' ? 'Урок' : 'Кружок')), el('div', {
    class: 'event-details'
  }, [e.location, e.subtitle, e.is_override ? 'Замена на эту дату' : null, e.event_date ? 'Разовое занятие' : null].filter(Boolean).map(t => el('span', {}, t)))], () => eventForm(e, date), `event-card ${e.type} ${current?'current':''}`, {
    'aria-label': `${e.label}, ${clock(e.start_time)}${editable()?', редактировать':''}`
  }));
}

function openSheet(title, content) {
  dirty = false;
  $('sheet-title').textContent = title;
  $('sheet-body').replaceChildren(content);
  if (!$('sheet').open) $('sheet').showModal();
  $('sheet-body').scrollTop = 0;
  tg?.BackButton?.show();
}

function askConfirmation(message, confirmLabel = 'Продолжить') {
  if (confirmationOpen) return Promise.resolve(false);
  confirmationOpen = true;
  return new Promise(resolve => {
    const finish = answer => {
      overlay.remove();
      confirmationOpen = false;
      resolve(answer);
    };
    const cancel = el('button', {
      type: 'button',
      class: 'button secondary',
      onclick: () => finish(false)
    }, 'Остаться');
    const confirm = el('button', {
      type: 'button',
      class: 'button danger',
      onclick: () => finish(true)
    }, confirmLabel);
    const overlay = el('div', {
      class: 'confirm-overlay',
      role: 'alertdialog',
      'aria-modal': 'true',
      'aria-labelledby': 'confirm-title',
      onkeydown: event => {
        if (event.key === 'Escape') finish(false);
      }
    }, el('div', {
      class: 'confirm-card'
    }, el('span', {
      class: 'eyebrow'
    }, 'Несохранённые изменения'), el('h3', {
      id: 'confirm-title'
    }, message), el('div', {
      class: 'confirm-actions'
    }, cancel, confirm)));
    $('sheet').append(overlay);
    cancel.focus();
  });
}

async function closeSheet(force = false) {
  if (saving) return false;
  if (!force && dirty && !await askConfirmation('Закрыть без сохранения изменений?', 'Закрыть')) return false;
  if ($('sheet').open) $('sheet').close();
  dirty = false;
  tg?.BackButton?.hide();
  return true;
}

function formShell(onSubmit) {
  const error = el('div', {
    class: 'form-error hidden',
    role: 'alert'
  });
  const form = el('form', {
    class: 'form-stack'
  }, error);
  form.addEventListener('input', () => {
    dirty = true;
  });
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    if (saving) return;
    saving = true;
    error.classList.add('hidden');
    const submits = [...form.querySelectorAll('button')];
    submits.forEach(b => b.disabled = true);
    try {
      await onSubmit(new FormData(form), form);
      dirty = false;
    } catch (e) {
      error.textContent = e.message;
      error.classList.remove('hidden');
      error.scrollIntoView({
        block: 'nearest'
      });
    } finally {
      saving = false;
      submits.forEach(b => b.disabled = false);
    }
  });
  return form;
}

function saveButton(label = 'Сохранить') {
  return el('div', {
    class: 'sticky-action'
  }, el('button', {
    type: 'submit',
    class: 'button full'
  }, label));
}
async function saved(text = 'Изменения сохранены') {
  saving = false;
  closeSheet(true);
  toast(text);
  await refresh();
}
async function eventForm(entry, date, duplicate = false) {
  if (!editable()) {
    openSheet(entry.label, el('div', {
      class: 'form-stack'
    }, el('p', {}, `${clock(entry.start_time)} — ${clock(entry.end_time)}`), el('p', {}, entry.location || ''), el('p', {}, entry.subtitle || ''), el('p', {
      class: 'form-hint'
    }, 'Доступ только для просмотра')));
    return;
  }
  const pid = state.pid;
  const base = entry && !duplicate ? await api(path(`/events/${entry.id}`, pid)) : entry;
  const defaultStart = entry ? clock(entry.start_time) : '08:30';
  const start = input('start_time', defaultStart, 'time', {
    required: true
  });
  const end = input('end_time', entry ? clock(entry.end_time) : '09:15', 'time', {
    required: true
  });
  const label = input('label', entry?.label || '', 'text', {
    required: true,
    maxlength: 200,
    placeholder: 'Например, математика'
  });
  const scope = select('scope', entry && !duplicate && !base.event_date ? 'once' : base?.event_date ? 'dated' : 'weekly', entry && !duplicate && !base.event_date ? [
    ['once', `Только ${dateLabel(date)}`],
    ['weekly', 'Каждую неделю']
  ] : [
    ['weekly', 'Каждую неделю'],
    ['dated', 'Один раз, в конкретную дату']
  ]);
  const day = select('weekday', base?.weekday || isoDay(date), weekdays.map((d, i) => [i + 1, d]));
  const ondate = input('event_date', base?.event_date || date, 'date', {
    required: true
  });
  const kind = select('type', entry?.type || 'lesson', [
    ['lesson', 'Урок'],
    ['extra', 'Кружок']
  ]);
  const location = input('location', entry?.location || '', 'text', {
    maxlength: 200,
    placeholder: 'Кабинет или адрес'
  });
  const subtitle = input('subtitle', entry?.subtitle || '', 'text', {
    maxlength: 1000,
    placeholder: 'Преподаватель, что взять с собой'
  });
  const form = formShell(async data => {
    const values = Object.fromEntries(data);
    const targetDate = values.scope === 'dated' ? values.event_date : null;
    const payload = {
      type: values.type,
      label: values.label,
      weekday: targetDate ? isoDay(targetDate) : Number(values.weekday),
      start_time: values.start_time,
      end_time: values.end_time,
      location: values.location || null,
      subtitle: values.subtitle || null,
      event_date: targetDate
    };
    if (payload.end_time <= payload.start_time) throw new Error('Окончание должно быть позже начала.');
    let result;
    if (entry && !duplicate && values.scope === 'once') {
      const {
        weekday,
        event_date,
        ...override
      } = payload;
      result = await send(path(`/events/${entry.id}/exceptions`, pid), 'POST', {
        ...override,
        date,
        cancelled: false
      });
    } else result = await send(path(entry && !duplicate ? `/events/${entry.id}` : '/events', pid), entry && !duplicate ? 'PUT' : 'POST', payload);
    await saved(entry && !duplicate ? 'Занятие обновлено' : 'Занятие добавлено');
    if (result.warnings?.length) toast('Обратите внимание: занятие пересекается с уроком или кружком.');
  });
  const daysField = field('День недели', day);
  const dateField = field('Дата', ondate);
  const updateScope = () => {
    daysField.hidden = scope.value !== 'weekly';
    dateField.hidden = scope.value !== 'dated';
    ondate.required = scope.value === 'dated';
  };
  scope.addEventListener('change', () => {
    updateScope();
    if (entry && !duplicate) {
      const src = scope.value === 'weekly' ? base : entry;
      label.value = src.label;
      start.value = clock(src.start_time);
      end.value = clock(src.end_time);
      kind.value = src.type;
      location.value = src.location || '';
      subtitle.value = src.subtitle || '';
    }
  });
  updateScope();
  form.append(field('Название занятия', label), el('div', {
    class: 'field-row'
  }, field('Тип', kind), field('Повторение', scope)), daysField, dateField, el('div', {
    class: 'field-row'
  }, field('Начало', start), field('Окончание', end)), el('div', {
    class: 'duration-presets'
  }, [30, 45, 60, 90].map(n => button(`${n} мин`, () => {
    const [h, m] = start.value.split(':').map(Number);
    const value = h * 60 + m + n;
    if (value >= 1440) {
      toast('Занятие должно закончиться до полуночи.');
      return;
    }
    end.value = `${String(Math.floor(value/60)).padStart(2,'0')}:${String(value%60).padStart(2,'0')}`;
    dirty = true;
  }, ''))));
  if (state.bells.length) {
    const bells = select('bell', '', [
      ['', 'Выбрать урок по звонкам'], ...state.bells.map((b, i) => [i, `${i+1}. ${clock(b.start_time)}–${clock(b.end_time)}`])
    ]);
    bells.addEventListener('change', () => {
      if (bells.value !== '') {
        start.value = clock(state.bells[+bells.value].start_time);
        end.value = clock(state.bells[+bells.value].end_time);
        dirty = true;
      }
    });
    form.append(field('Шаблон звонков', bells));
  }
  form.append(el('details', {
    class: 'optional-fields'
  }, el('summary', {}, 'Кабинет, преподаватель и заметки'), field('Где проходит', location), field('Комментарий', subtitle)), saveButton());
  if (entry && !duplicate) {
    const actions = el('div', {
      class: 'form-actions'
    }, button('Дублировать', () => eventForm(entry, date, true), 'button secondary'));
    if (!base.event_date) actions.append(button(entry.is_override ? 'Вернуть обычное занятие' : 'Отменить на эту дату', async () => {
      if (entry.is_override) await send(path(`/events/${entry.id}/exceptions/${date}`, pid), 'DELETE');
      else await send(path(`/events/${entry.id}/exceptions`, pid), 'POST', {
        date,
        cancelled: true
      });
      await saved();
    }, 'button secondary'));
    actions.append(button('Удалить занятие', () => confirmSheet('Удалить занятие?', base.event_date ? 'Разовое занятие будет удалено.' : 'Будет удалена вся повторяющаяся серия.', async () => {
      await send(path(`/events/${entry.id}`, pid), 'DELETE');
      closeSheet(true);
      await refresh();
      toast('Занятие удалено', async () => {
        await send(path(`/events/${entry.id}/restore`, pid), 'POST');
        await refresh();
      });
    }), 'button danger'));
    form.append(actions);
  }
  openSheet(entry && !duplicate ? 'Изменить занятие' : 'Новое занятие', form);
}

function confirmSheet(title, text, action) {
  openSheet(title, el('div', {
    class: 'form-stack'
  }, el('p', {}, text), button('Подтвердить', action, 'button danger'), button('Отмена', () => closeSheet(true))));
}

function dayChecks(name, values) {
  return el('div', {
    class: 'day-checks'
  }, weekdays.map((d, i) => el('label', {
    class: 'day-check'
  }, input(name, i + 1, 'checkbox', {
    checked: values.includes(i + 1)
  }), el('span', {}, d))));
}

function typeChecks() {
  return el('div', {
    class: 'field-row'
  }, ['lesson', 'extra'].map(t => el('label', {
    class: 'checkbox-label'
  }, input('types', t, 'checkbox', {
    checked: true
  }), t === 'lesson' ? 'Уроки' : 'Кружки')));
}

function copyDayForm() {
  const pid = state.pid;
  const form = formShell(async data => {
    const payload = {
      source_weekday: +data.get('source_weekday'),
      target_weekdays: data.getAll('days').map(Number),
      types: data.getAll('types'),
      mode: data.get('mode')
    };
    const preview = await send(path('/copy-day', pid), 'POST', {
      ...payload,
      preview: true
    });
    confirmSheet('Скопировать день?', `Будет добавлено ${preview.created} занятий${preview.removed?`, заменено ${preview.removed}`:''}.`, async () => {
      await send(path('/copy-day', pid), 'POST', payload);
      await saved('День скопирован');
    });
  });
  form.append(field('Откуда', select('source_weekday', isoDay(state.date), weekdays.map((d, i) => [i + 1, d]))), el('p', {
    class: 'form-hint'
  }, 'Выберите дни назначения, кроме исходного.'), dayChecks('days', []), typeChecks(), field('Как копировать', select('mode', 'merge', [
    ['merge', 'Добавить к существующим'],
    ['replace', 'Заменить выбранные типы занятий']
  ])), saveButton('Посмотреть изменения'));
  openSheet('Копировать день', form);
}

function renderTasks() {
  const filters = el('div', {
    class: 'chips'
  }, [
    ['active', 'Нужно сделать'],
    ['done', 'Готово'],
    ['all', 'Все']
  ].map(([value, label]) => button(label, () => {
    state.filter = value;
    render();
  }, `chip ${state.filter===value?'active':''}`)));
  const tasks = state.tasks.filter(t => state.filter === 'all' || (state.filter === 'done') === t.completed);
  return el('div', {}, hero('Дела, которые по плечу.', 'Домашние задания, материалы и маленькие победы.'), el('div', {
    class: 'section-toolbar'
  }, filters, editable() ? button('+ Добавить задание', () => taskForm(), 'button') : null), el('div', {
    class: 'tasks-layout'
  }, el('div', {
    class: 'task-list'
  }, tasks.length ? tasks.map(t => el('article', {
    class: `task-card ${t.completed?'completed':''}`
  }, el('input', {
    type: 'checkbox',
    checked: t.completed,
    disabled: !editable(),
    'aria-label': `Выполнено: ${t.title}`,
    onchange: async ev => {
      try {
        await send(path(`/tasks/${t.id}`), 'PATCH', {
          completed: ev.target.checked
        });
        await refresh();
      } catch (e) {
        ev.target.checked = !ev.target.checked;
        toast(e.message, null, '', true);
      }
    }
  }), button([el('div', {
    class: 'task-meta'
  }, t.subject || 'Без предмета', el('span', {
    class: t.due_date < localToday() && !t.completed ? 'overdue' : ''
  }, dateLabel(t.due_date))), el('h3', {
    class: 'task-title'
  }, t.title), t.description ? el('p', {
    class: 'task-description'
  }, t.description) : null, t.attachments.length ? el('small', {}, `📎 Файлов: ${t.attachments.length}`) : null], () => taskForm(t), 'task-content'))) : el('div', {
    class: 'empty-state'
  }, el('span', {
    class: 'empty-symbol'
  }, '✓'), el('h2', {}, state.filter === 'done' ? 'Первые победы впереди' : 'Всё под контролем'), el('p', {}, 'Здесь появятся задания выбранного профиля.'))), el('aside', {
    class: 'sidebar'
  }, el('section', {
    class: 'panel sidebar-section'
  }, el('span', {
    class: 'eyebrow'
  }, 'Маленькими шагами'), el('h3', {}, 'Сначала самое важное'), el('p', {}, 'Отмечайте выполненное и прикладывайте материалы, чтобы всё нужное было рядом.'), el('div', {
    class: 'stats-line'
  }, el('div', {}, el('strong', {}, state.tasks.filter(t => t.completed).length), el('small', {}, 'готово')), el('div', {}, el('strong', {}, state.tasks.filter(t => !t.completed).length), el('small', {}, 'осталось')))))));
}
async function downloadAttachment(attachment, pid) {
  const response = await fetch(path(`/attachments/${attachment.id}`, pid), {
    headers: {
      'X-Telegram-Init-Data': initData
    }
  });
  if (!response.ok) throw new Error('Не удалось скачать файл');
  const url = URL.createObjectURL(await response.blob());
  const link = el('a', {
    href: url,
    download: attachment.filename
  }, 'Скачать');
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function taskForm(task = null) {
  const pid = state.pid;
  let savedTaskId = task?.id;
  let uploaded = 0;
  const files = input('files', '', 'file', {
    multiple: true,
    accept: '.pdf,.png,.jpg,.jpeg,.webp,.txt'
  });
  const form = formShell(async data => {
    const payload = {
      title: data.get('title'),
      subject: data.get('subject') || null,
      description: data.get('description') || '',
      due_date: data.get('due_date'),
      completed: data.has('completed')
    };
    const result = await send(path(savedTaskId ? `/tasks/${savedTaskId}` : '/tasks', pid), savedTaskId ? 'PATCH' : 'POST', payload);
    savedTaskId = result.id;
    for (; uploaded < files.files.length; uploaded++) {
      const body = new FormData();
      body.set('file', files.files[uploaded]);
      await api(path(`/tasks/${savedTaskId}/attachments`, pid), {
        method: 'POST',
        body
      });
    }
    await saved('Задание сохранено');
  });
  form.append(field('Что нужно сделать', input('title', task?.title || '', 'text', {
    required: true,
    maxlength: 200
  })), el('div', {
    class: 'field-row'
  }, field('Предмет', input('subject', task?.subject || '', 'text', {
    maxlength: 200
  })), field('Срок выполнения', input('due_date', task?.due_date || addDays(localToday(), 1), 'date', {
    required: true
  }))), field('Подробности', el('textarea', {
    name: 'description',
    maxlength: 10000
  }, task?.description || '')), el('label', {
    class: 'checkbox-label'
  }, input('completed', '1', 'checkbox', {
    checked: task?.completed
  }), 'Уже выполнено'));
  for (const a of task?.attachments || []) form.append(el('div', {
    class: 'attachment-row',
    'data-attachment': a.id
  }, button(`${a.filename} · ${Math.ceil(a.size/1024)} КБ`, () => downloadAttachment(a, pid), ''), editable() ? button('×', async () => {
    await send(path(`/attachments/${a.id}`, pid), 'DELETE');
    task.attachments = task.attachments.filter(f => f.id !== a.id);
    form.querySelector(`[data-attachment="${a.id}"]`)?.remove();
  }, 'icon-button', {
    'aria-label': 'Удалить файл'
  }) : null));
  if (editable()) {
    form.append(field('Материалы', files, 'До 5 файлов, каждый до 5 МБ. PDF, изображения или TXT.'), saveButton());
    if (task) form.append(button('Удалить задание', () => confirmSheet('Удалить задание?', 'Прикреплённые файлы также будут удалены.', async () => {
      await send(path(`/tasks/${task.id}`, pid), 'DELETE');
      await saved('Задание удалено');
    }), 'button danger'));
  } else form.querySelectorAll('input,textarea').forEach(n => n.disabled = true);
  openSheet(task ? 'Домашнее задание' : 'Новое задание', form);
}

function renderSettings() {
  const form = formShell(async data => {
    state.user = await send('/api/me', 'PATCH', {
      timezone: data.get('timezone'),
      reminder_minutes: +data.get('reminder_minutes'),
      evening_time: data.get('evening_time') || null,
      reminders_enabled: data.has('reminders_enabled'),
      default_profile_id: +data.get('default_profile_id')
    });
    state.date = localToday();
    toast('Настройки сохранены');
    await refresh();
  });
  form.append(field('Профиль при открытии и для /today', select('default_profile_id', state.user.default_profile_id, state.profiles.map(p => [p.id, p.name]))), field('Часовой пояс', input('timezone', state.user.timezone, 'text', {
    required: true,
    list: 'timezones'
  }), 'Один часовой пояс для сайта и Telegram-бота.'), el('datalist', {
    id: 'timezones'
  }, ['Europe/Moscow', 'Europe/Amsterdam', 'Europe/Kaliningrad', 'Asia/Yekaterinburg', 'Asia/Novosibirsk', 'Asia/Vladivostok', 'UTC'].map(v => el('option', {
    value: v
  }))), el('label', {
    class: 'checkbox-label'
  }, input('reminders_enabled', '1', 'checkbox', {
    checked: state.user.reminders_enabled
  }), 'Напоминания в Telegram'), field('Напомнить за', select('reminder_minutes', state.user.reminder_minutes, [
    [0, 'В момент начала'],
    [5, '5 минут'],
    [10, '10 минут'],
    [15, '15 минут'],
    [30, '30 минут'],
    [60, '1 час'],
    [120, '2 часа']
  ])), field('Вечерний план на завтра', input('evening_time', clock(state.user.evening_time), 'time'), 'Оставьте пустым, чтобы отключить вечернюю сводку.'), el('p', {
    class: 'form-hint'
  }, 'Сначала отправьте /start боту. Уведомления приходят по доступным вам профилям, только когда включены.'), saveButton());
  const profilePanel = el('section', {
    class: 'panel settings-panel'
  }, el('span', {
    class: 'eyebrow'
  }, 'Семья'), el('h2', {}, 'Каждому — свой план'), state.profiles.map(p => button([el('span', {
    class: 'avatar'
  }, p.name[0]), el('span', {}, p.name, el('small', {}, p.role === 'owner' ? 'Владелец' : p.role === 'editor' ? 'Можно редактировать' : 'Только просмотр')), p.id === state.pid ? '✓' : '→'], () => switchProfile(p.id), 'profile-row')), button('+ Добавить профиль', () => profileForm(), 'button secondary full'), button('Принять приглашение', () => joinForm(), 'text-button'));
  const tools = el('section', {
    class: 'panel settings-panel'
  }, el('span', {
    class: 'eyebrow'
  }, profile().name), el('h2', {}, 'Настроить неделю'), el('div', {
    class: 'side-links'
  }, button('Каникулы и выходные', holidaysForm, 'text-button'), button('Расписание звонков', bellsForm, 'text-button'), button('Импорт расписания', () => importForm(), 'text-button'), button('Экспорт календаря (.ics)', exportCalendar, 'text-button'), button('Светлая / тёмная тема', () => {
    const dark = document.documentElement.dataset.theme !== 'dark';
    localStorage.setItem('planner-theme', dark ? 'dark' : 'light');
    applyTheme();
  }, 'text-button')));
  if (editable()) tools.append(button('Поделиться расписанием', shareForm, 'text-button'));
  if (profile().role === 'owner') tools.append(button('Изменить профиль', () => profileForm(profile()), 'text-button'), button('Доступ для семьи', membersForm, 'text-button'));
  return el('div', {}, hero('Планер в вашем ритме.', 'Профили, напоминания и привычные настройки.'), el('div', {
    class: 'settings-grid'
  }, el('section', {
    class: 'panel settings-panel'
  }, el('span', {
    class: 'eyebrow'
  }, 'Личные настройки'), el('h2', {}, 'Всё вовремя'), form), el('div', {
    class: 'form-stack'
  }, profilePanel, tools)));
}
async function switchProfile(pid) {
  if (dirty && !await askConfirmation('Переключить профиль без сохранения?', 'Переключить')) return;
  state.pid = pid;
  dirty = false;
  closeSheet(true);
  await refresh();
}

function profilesSheet() {
  openSheet('Профили', el('div', {
    class: 'form-stack'
  }, state.profiles.map(p => button(p.name + (p.id === state.pid ? ' ✓' : ''), () => switchProfile(p.id))), button('+ Новый профиль', () => profileForm(), 'button')));
}

function profileForm(p = null) {
  const form = formShell(async data => {
    const value = {
      name: data.get('name'),
      color: data.get('color')
    };
    const result = await send(p ? path('', p.id) : '/api/profiles', p ? 'PATCH' : 'POST', value);
    state.pid = result.id;
    saving = false;
    closeSheet(true);
    await refresh(true);
    toast('Профиль сохранён');
  });
  form.append(field('Имя ребёнка или название', input('name', p?.name || '', 'text', {
    required: true,
    maxlength: 80,
    placeholder: 'Например, Маша · 5Б'
  })), field('Цвет профиля', input('color', p?.color || '#d7b75f', 'color')), saveButton());
  if (p && !p.is_default) form.append(button('Удалить профиль', () => confirmSheet('Удалить профиль?', `Расписание и задания «${p.name}» будут удалены для всех участников.`, async () => {
    await send(path('', p.id), 'DELETE');
    closeSheet(true);
    state.pid = null;
    await refresh(true);
  }), 'button danger'));
  openSheet(p ? 'Изменить профиль' : 'Новый профиль', form);
}
async function holidaysForm() {
  const pid = state.pid;
  const result = await api(path('/holidays', pid));
  const content = el('div', {
    class: 'form-stack'
  }, el('p', {
    class: 'form-hint'
  }, 'Недельные занятия в выбранном диапазоне будут отменены. Разовые события остаются.'));
  for (const h of result.holidays) content.append(el('div', {
    class: 'holiday-row'
  }, el('div', {}, el('strong', {}, h.name), el('small', {}, `${dateLabel(h.start_date)} — ${dateLabel(h.end_date)}`)), editable() ? button('Удалить', async () => {
    await send(path(`/holidays/${h.id}`, pid), 'DELETE');
    await refresh();
    await holidaysForm();
  }, 'text-button') : null));
  if (editable()) {
    const form = formShell(async data => {
      await send(path('/holidays', pid), 'POST', {
        name: data.get('name'),
        start_date: data.get('start_date'),
        end_date: data.get('end_date'),
        types: data.getAll('types')
      });
      await saved('Каникулы добавлены');
    });
    form.append(field('Название', input('name', '', 'text', {
      required: true,
      maxlength: 120,
      placeholder: 'Осенние каникулы'
    })), el('div', {
      class: 'field-row'
    }, field('Начало', input('start_date', state.date, 'date', {
      required: true
    })), field('Окончание', input('end_date', addDays(state.date, 6), 'date', {
      required: true
    }))), typeChecks(), saveButton('Добавить каникулы'));
    form.querySelector('input[value="extra"]').checked = false;
    content.append(form);
  }
  openSheet('Каникулы и выходные', content);
}
async function bellsForm() {
  const pid = state.pid;
  const result = await api(path('/bells', pid));
  const rows = el('div', {
    class: 'form-stack'
  });

  function row(slot = {
    start_time: '08:30',
    end_time: '09:15'
  }) {
    const box = el('div', {
      class: 'bell-row'
    }, el('span', {}, '↔'), input('start', clock(slot.start_time), 'time', {
      required: true
    }), input('end', clock(slot.end_time), 'time', {
      required: true
    }));
    box.append(button('×', () => {
      box.remove();
      dirty = true;
    }, 'icon-button', {
      'aria-label': 'Удалить звонок'
    }));
    rows.append(box);
  }
  result.slots.forEach(row);
  const form = formShell(async () => {
    const slots = [...rows.children].map(r => ({
      start_time: r.querySelector('[name=start]').value,
      end_time: r.querySelector('[name=end]').value
    }));
    await send(path('/bells', pid), 'PUT', {
      slots
    });
    await saved('Расписание звонков сохранено');
  });
  form.append(el('p', {
    class: 'form-hint'
  }, 'Эти интервалы можно выбрать при добавлении урока.'), rows);
  if (editable()) form.append(button('+ Добавить интервал', () => {
    if (rows.children.length < 20) row();
  }, 'button secondary'), button('Создать 6 уроков по 45 минут', () => {
    rows.replaceChildren();
    for (let i = 0; i < 6; i++) {
      const m = 510 + i * 55;
      row({
        start_time: `${String(Math.floor(m/60)).padStart(2,'0')}:${String(m%60).padStart(2,'0')}`,
        end_time: `${String(Math.floor((m+45)/60)).padStart(2,'0')}:${String((m+45)%60).padStart(2,'0')}`
      });
    }
    dirty = true;
  }, 'text-button'), saveButton());
  else form.querySelectorAll('input,button').forEach(n => n.disabled = true);
  openSheet('Расписание звонков', form);
}

function linkOutput(url) {
  const copy = input('link', url, 'text', {
    readonly: true
  });
  return el('div', {
    class: 'copy-output'
  }, copy, button('Копировать', async () => {
    try {
      await navigator.clipboard.writeText(url);
      toast('Ссылка скопирована');
    } catch {
      copy.focus();
      copy.select();
      toast('Скопируйте выделенную ссылку.');
    }
  }, 'button secondary'));
}
async function membersForm() {
  const pid = state.pid;
  const data = await api(path('/members', pid));
  const content = el('div', {
    class: 'form-stack'
  }, el('p', {
    class: 'form-hint'
  }, 'Редактор может менять расписание и задания. Наблюдатель может только читать. Приглашение одноразовое.'));
  for (const m of data.members) content.append(el('div', {
    class: 'row'
  }, el('span', {}, `${m.user_id} · ${m.role==='owner'?'владелец':m.role==='editor'?'редактор':'наблюдатель'}`), m.role !== 'owner' ? button('Закрыть доступ', () => confirmSheet('Закрыть доступ?', `Участник ${m.user_id} потеряет доступ к этому профилю.`, async () => {
    await send(path(`/members/${m.user_id}`, pid), 'DELETE');
    await membersForm();
  }), 'text-button') : null));
  for (const i of data.invites) content.append(el('div', {
    class: 'row'
  }, el('small', {}, `Приглашение ${i.role} до ${new Date(i.expires_at).toLocaleDateString('ru-RU')}`), button('Отозвать', async () => {
    await send(path(`/invites/${i.id}`, pid), 'DELETE');
    await membersForm();
  }, 'text-button')));
  const form = formShell(async data => {
    const result = await send(path('/invites', pid), 'POST', {
      role: data.get('role')
    });
    openSheet('Приглашение в семью', el('div', {
      class: 'form-stack'
    }, el('p', {}, 'Отправьте ссылку участнику. Она даёт доступ только к этому профилю.'), linkOutput(new URL(result.url, location.origin).href)));
  });
  form.append(field('Права нового участника', select('role', 'editor', [
    ['editor', 'Редактирование'],
    ['viewer', 'Только просмотр']
  ])), saveButton('Создать приглашение'));
  content.append(form);
  openSheet('Доступ для семьи', content);
}

function tokenFrom(value, key) {
  try {
    const url = new URL(value);
    return url.searchParams.get(key) || url.searchParams.get('start')?.replace(new RegExp(key === 'share' ? '^(share|planner)_' : `^${key}_`), '') || value;
  } catch {
    return value.trim();
  }
}

function joinForm(token = '') {
  const form = formShell(async data => {
    const result = await send(`/api/invites/${encodeURIComponent(tokenFrom(data.get('token'),'invite'))}/join`, 'POST');
    state.pid = result.id;
    saving = false;
    closeSheet(true);
    await refresh(true);
    toast('Вы присоединились к профилю');
  });
  form.append(field('Ссылка или код приглашения', input('token', token, 'text', {
    required: true
  })), el('p', {
    class: 'form-hint'
  }, 'Ваше личное расписание останется без изменений.'), saveButton('Присоединиться'));
  openSheet('Принять приглашение', form);
}
async function shareForm() {
  const pid = state.pid;
  const content = el('div', {
    class: 'form-stack'
  });
  const form = formShell(async data => {
    const result = await send(path('/shares', pid), 'POST', {
      types: data.getAll('types'),
      weekdays: data.getAll('days').map(Number)
    });
    openSheet('Расписание готово к отправке', el('div', {
      class: 'form-stack'
    }, el('p', {}, `В ссылке ${result.count} занятий. Получатель увидит предварительный просмотр перед импортом.`), linkOutput(new URL(result.url, location.origin).href), el('p', {
      class: 'form-hint'
    }, `Действует до ${new Date(result.expires_at).toLocaleString('ru-RU')}. Это копия расписания без домашних заданий.`)));
  });
  form.append(el('p', {}, 'Выберите, чем поделиться'), dayChecks('days', [1, 2, 3, 4, 5, 6, 7]), typeChecks(), saveButton('Создать ссылку'));
  content.append(form);
  const active = await api(path('/shares', pid));
  for (const share of active.shares) content.append(el('div', {
    class: 'row'
  }, el('small', {}, `Ссылка от ${new Date(share.created_at).toLocaleDateString('ru-RU')}`), button('Отозвать', async () => {
    await send(path(`/shares/${share.id}`, pid), 'DELETE');
    await shareForm();
  }, 'text-button')));
  openSheet('Поделиться расписанием', content);
}

function importForm(token = '') {
  const form = formShell(async data => {
    const value = tokenFrom(data.get('token'), 'share');
    const result = await api(`/api/shares/${encodeURIComponent(value)}`);
    const preview = el('div', {
      class: 'share-preview'
    }, result.entries.map(e => el('p', {}, `${weekdays[e.weekday-1]} · ${clock(e.start_time)}–${clock(e.end_time)} · ${e.label}`)));
    const confirm = formShell(async values => {
      const payload = {
        profile_id: +values.get('profile_id'),
        mode: values.get('mode')
      };
      const plan = await send(`/api/shares/${encodeURIComponent(value)}/import`, 'POST', {
        ...payload,
        preview: true
      });
      confirmSheet('Импортировать расписание?', `Будет добавлено ${plan.created} занятий${plan.removed?`, заменено ${plan.removed}`:''}.`, async () => {
        await send(`/api/shares/${encodeURIComponent(value)}/import`, 'POST', payload);
        state.pid = payload.profile_id;
        await saved('Расписание импортировано');
      });
    });
    confirm.append(el('p', {}, `Расписание «${result.profile_name}»`), preview, field('Куда импортировать', select('profile_id', state.pid, state.profiles.filter(p => p.role !== 'viewer').map(p => [p.id, p.name]))), field('Способ импорта', select('mode', 'merge', [
      ['merge', 'Добавить занятия'],
      ['replace', 'Заменить выбранные в ссылке дни и типы']
    ])), saveButton('Проверить импорт'));
    openSheet('Предварительный просмотр', confirm);
  });
  form.append(field('Ссылка или код расписания', input('token', token, 'text', {
    required: true
  })), saveButton('Посмотреть расписание'));
  openSheet('Импорт расписания', form);
}
async function exportCalendar() {
  const response = await fetch(path(`/calendar.ics?start=${monday(state.date)}`), {
    headers: {
      'X-Telegram-Init-Data': initData
    }
  });
  if (!response.ok) throw new Error('Не удалось экспортировать календарь');
  const url = URL.createObjectURL(await response.blob());
  const a = el('a', {
    href: url,
    download: 'school-planner.ics'
  });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function applyTheme() {
  const saved = localStorage.getItem('planner-theme');
  document.documentElement.dataset.theme = saved || (tg?.colorScheme === 'dark' ? 'dark' : window.matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
}

function viewport() {
  document.documentElement.style.setProperty('--viewport-height', `${window.visualViewport?.height||window.innerHeight}px`);
}

function launch(config, message) {
  $('main').replaceChildren(el('div', {
    class: 'launch-page'
  }, el('span', {
    class: 'brand-mark',
    'aria-hidden': 'true'
  }, 'ш.'), el('h1', {}, 'Ваша неделя начинается здесь.'), el('p', {}, message || 'Откройте планер из Telegram, чтобы увидеть своё расписание и задания.'), config.bot_username ? el('a', {
    class: 'button',
    href: `https://t.me/${encodeURIComponent(config.bot_username)}${new URLSearchParams(location.search).get('invite')?'?start=invite_'+encodeURIComponent(new URLSearchParams(location.search).get('invite')):new URLSearchParams(location.search).get('share')?'?start=planner_'+encodeURIComponent(new URLSearchParams(location.search).get('share')):''}`
  }, 'Открыть бота') : el('p', {}, 'Перейдите в чат с ботом и нажмите «Открыть планер».')));
  $('main').setAttribute('aria-busy', 'false');
}
async function boot() {
  applyTheme();
  viewport();
  window.visualViewport?.addEventListener('resize', viewport);
  window.addEventListener('resize', viewport);
  tg?.onEvent('themeChanged', applyTheme);
  $('sheet-close').addEventListener('click', () => closeSheet());
  $('sheet').addEventListener('cancel', ev => {
    ev.preventDefault();
    closeSheet();
  });
  tg?.BackButton?.onClick(() => closeSheet());
  $('sheet').addEventListener('click', e => {
    if (e.target === $('sheet')) {
      const r = $('sheet').getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) closeSheet();
    }
  });
  $('profile-button').addEventListener('click', profilesSheet);
  document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', async () => {
    if (state.week) {
      if (dirty && !await askConfirmation('Перейти без сохранения изменений?', 'Перейти')) return;
      dirty = false;
      state.view = b.dataset.view;
      render();
    }
  }));
  window.addEventListener('beforeunload', ev => {
    if (dirty) {
      ev.preventDefault();
      ev.returnValue = '';
    }
  });
  const config = await api('/api/public-config');
  if (!initData && !config.dev_mode) {
    launch(config);
    return;
  }
  await refresh(true);
  if (!state.user) return;
  const params = new URLSearchParams(location.search);
  let invite = params.get('invite'),
    share = params.get('share');
  const start = tg?.initDataUnsafe?.start_param;
  if (start?.startsWith('invite_')) invite = start.slice(7);
  if (start?.startsWith('share_')) share = start.slice(6);
  if (start?.startsWith('planner_')) share = start.slice(8);
  if (invite) joinForm(invite);
  else if (share) importForm(share);
  if (invite || share) history.replaceState(null, '', location.pathname);
  let previousDay = localToday();
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && state.user && !dirty && !$('sheet').open) {
      const today = localToday();
      if (state.date === previousDay) state.date = today;
      previousDay = today;
      attempt(() => refresh(true));
    }
  });
  setInterval(() => {
    if (!document.hidden && state.user && !$('sheet').open && state.view === 'schedule') {
      const today = localToday();
      if (today !== previousDay) {
        if (state.date === previousDay) state.date = today;
        previousDay = today;
        attempt(() => refresh());
      } else render();
    }
  }, 60000);
}
boot().catch(error => launch({}, error.message));
