const BASE = "http://localhost:8000/api";

// Действия могут вызывать полный пересчёт плана с реальными запросами к
// Yandex Router — не мгновенно. Таймаут щедрый (2 минуты), но конечный,
// иначе при сетевом сбое кнопка "зависает" до перезагрузки страницы.
const REQUEST_TIMEOUT_MS = 120_000;

// Глобальный индикатор "идёт запрос" (не завязан на конкретную кнопку) —
// App.jsx подписывается на него, чтобы показать общий индикатор ожидания.
let activeRequests = 0;
const loadingListeners = new Set();

function setActiveRequests(delta) {
  activeRequests += delta;
  loadingListeners.forEach((fn) => fn(activeRequests));
}

export function subscribeToLoading(fn) {
  loadingListeners.add(fn);
  return () => loadingListeners.delete(fn);
}

// silent: true — фоновый запрос (опрос статуса раз в 15 с), который не должен
// включать индикатор загрузки. Именно он раньше вызывал «прыгающее» окно
// загрузки, появлявшееся на секунду на любой вкладке без действий пользователя.
async function request(path, { silent = false, ...options } = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  if (!silent) setActiveRequests(1);
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
      signal: controller.signal,
      ...options,
    });
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(
        "Сервер слишком долго не отвечает (более 2 минут) — возможно, идёт большой пересчёт плана " +
          "с реальными запросами к Router API. Подождите и обновите страницу, либо проверьте backend."
      );
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
    if (!silent) setActiveRequests(-1);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch (_) {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  status: () => request("/status", { silent: true }),

  // офисы
  listOffices: () => request("/offices"),
  updateOffice: (id, body) => request(`/offices/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteOffice: (id) => request(`/offices/${id}`, { method: "DELETE" }),

  // инженеры
  listEngineers: () => request("/engineers"),
  listDistricts: () => request("/districts"),
  getSimulationTime: () => request("/simulation-time", { silent: true }),
  setSimulationTime: (time) => request("/simulation-time", { method: "PUT", body: JSON.stringify({ time }) }),
  listEquipment: () => request("/equipment"),
  // Импорт бригад из файла: район/смена/транспорт — общие параметры на весь файл
  importEngineers: (file, params) => {
    const form = new FormData();
    form.append("file", file);
    for (const [k, v] of Object.entries(params)) form.append(k, v);
    return request("/engineers/import", { method: "POST", body: form });
  },
  createEngineer: (body) => request("/engineers", { method: "POST", body: JSON.stringify(body) }),
  updateEngineer: (id, body) => request(`/engineers/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteEngineer: (id) => request(`/engineers/${id}`, { method: "DELETE" }),
  setUnavailable: (id, reason) =>
    request(`/engineers/${id}/unavailable`, { method: "POST", body: JSON.stringify({ reason }) }),
  setAvailable: (id) => request(`/engineers/${id}/available`, { method: "POST" }),

  // заявки
  listRequests: () => request("/requests"),
  createRequest: (body) => request("/requests", { method: "POST", body: JSON.stringify(body) }),
  updateRequest: (id, body) => request(`/requests/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteRequest: (id) => request(`/requests/${id}`, { method: "DELETE" }),
  restoreDeletedRequest: (id) => request(`/requests/${id}/restore`, { method: "POST" }),
  importFiles: (fileList) => {
    const form = new FormData();
    for (const f of fileList) form.append("files", f);
    return request("/requests/import", { method: "POST", body: form });
  },

  // план
  buildPlan: () => request("/plan/build", { method: "POST" }),
  getPlan: () => request("/plan"),

  // события
  eventNewRequest: (body) => request("/events/new-request", { method: "POST", body: JSON.stringify(body) }),
  eventCancelRequest: (id) => request(`/events/cancel-request/${id}`, { method: "POST" }),
  eventRestoreRequest: (id) => request(`/events/restore-request/${id}`, { method: "POST" }),
};
