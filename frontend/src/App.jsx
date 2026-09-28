import React, { useCallback, useEffect, useState } from "react";
import SimulationTimeWidget from "./components/SimulationTimeWidget.jsx";
import { api, subscribeToLoading } from "./api.js";
import OfficesPanel from "./components/OfficesPanel.jsx";
import EngineersPanel from "./components/EngineersPanel.jsx";
import RequestsPanel from "./components/RequestsPanel.jsx";
import PlanPanel from "./components/PlanPanel.jsx";

const TABS = [
  { id: "offices", label: "Офисы" },
  { id: "engineers", label: "Инженеры" },
  { id: "requests", label: "Заявки" },
  { id: "plan", label: "План" },
];

export default function App() {
  const [tab, setTab] = useState("requests");
  const [toast, setToast] = useState(null);
  const [actionToast, setActionToast] = useState(null);
  const [status, setStatus] = useState(null);
  const [loadingCount, setLoadingCount] = useState(0);
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("enginet-theme") || "dark";
    } catch (_) {
      return "dark";
    }
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
    let meta = document.querySelector('meta[name="color-scheme"]');
    if (!meta) { meta = document.createElement("meta"); meta.name = "color-scheme"; document.head.appendChild(meta); }
    meta.content = theme;
    try {
      localStorage.setItem("enginet-theme", theme);
    } catch (_) {
      /* ignore, например приватный режим браузера */
    }
  }, [theme]);

  const [offices, setOffices] = useState([]);
  const [engineers, setEngineers] = useState([]);
  const [requests, setRequests] = useState([]);
  const [plan, setPlan] = useState(null);
  const [districts, setDistricts] = useState([]);
  const [simulationTime, setSimulationTime] = useState(null);
  const [equipmentList, setEquipmentList] = useState([]);

  // Тосты с кнопкой-действием (например "Вернуть") живут в отдельном канале
  // от обычных уведомлений, иначе рутинное уведомление затёрло бы кнопку
  // раньше времени. Пропадает по таймеру или по клику на саму кнопку.
  const notify = useCallback((message, kind = "success", action = null) => {
    if (action) {
      const token = Date.now() + Math.random();
      setActionToast({ message, kind, action, token });
      setTimeout(() => setActionToast((cur) => (cur && cur.token === token ? null : cur)), 10000);
    } else {
      setToast({ message, kind });
      setTimeout(() => setToast(null), 4500);
    }
  }, []);

  const refreshOffices = useCallback(async () => {
    setOffices(await api.listOffices());
  }, []);
  const refreshEngineers = useCallback(async () => {
    setEngineers(await api.listEngineers());
  }, []);
  const refreshRequests = useCallback(async () => {
    setRequests(await api.listRequests());
  }, []);
  const refreshDistricts = useCallback(async () => {
    setDistricts(await api.listDistricts());
  }, []);
  const refreshEquipment = useCallback(async () => {
    try {
      setEquipmentList(await api.listEquipment());
    } catch (_) {
      /* подсказки оборудования не критичны */
    }
  }, []);
  const refreshSimulationTime = useCallback(async () => {
    try {
      setSimulationTime((await api.getSimulationTime()).time);
    } catch (_) { /* не критично */ }
  }, []);
  const refreshPlan = useCallback(async () => {
    api.status().then(setStatus).catch(() => {});   // подхватить флаг plan_building
    try {
      setPlan(await api.getPlan());
    } catch (_) {
      setPlan(null);
    }
  }, []);
  const refreshAll = useCallback(async () => {
    await Promise.all([
      refreshOffices(), refreshEngineers(), refreshRequests(), refreshDistricts(), refreshPlan(),
      refreshEquipment(), refreshSimulationTime(),
    ]);
  }, [refreshOffices, refreshEngineers, refreshRequests, refreshDistricts, refreshPlan, refreshEquipment, refreshSimulationTime]);

  useEffect(() => {
    refreshAll();
    api.status().then(setStatus).catch(() => {});
    const interval = setInterval(() => api.status().then(setStatus).catch(() => {}), 15000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  useEffect(() => subscribeToLoading(setLoadingCount), []);

  // Фоновый пересчёт плана (после импорта): опрашиваем сервер, пока он идёт,
  // и подтягиваем свежие заявки и план, когда закончил.
  const planBuilding = !!(status && status.plan_building);
  useEffect(() => {
    if (!planBuilding) return undefined;
    const t = setInterval(async () => {
      try {
        const st = await api.status();
        setStatus(st);
        if (!st.plan_building) {
          await Promise.all([refreshRequests(), refreshPlan(), refreshEngineers()]);
          notify("План пересчитан");
        }
      } catch (_) { /* повторим на следующем тике */ }
    }, 2000);
    return () => clearInterval(t);
  }, [planBuilding]); // eslint-disable-line react-hooks/exhaustive-deps

  // Индикатор загрузки показывается только если ожидание затянулось (>500 мс):
  // быстрые запросы больше не заставляют окно мигать на долю секунды.
  const [showLoading, setShowLoading] = useState(false);
  useEffect(() => {
    if (loadingCount === 0) {
      setShowLoading(false);
      return undefined;
    }
    const t = setTimeout(() => setShowLoading(true), 500);
    return () => clearTimeout(t);
  }, [loadingCount > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  const withErrorToast = useCallback(
    (fn) => async (...args) => {
      try {
        return await fn(...args);
      } catch (err) {
        notify(err.message || "Что-то пошло не так", "error");
        throw err;
      }
    },
    [notify]
  );

  return (
    <div className="app-shell">
      {showLoading && <div className="top-loading-bar" />}
      <aside className="sidebar">
        <div className="sidebar-title">Диспетчер маршрутов</div>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`nav-item ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            <span className="nav-count">
              {t.id === "offices" && offices.length}
              {t.id === "engineers" && engineers.length}
              {t.id === "requests" && requests.length}
            </span>
          </button>
        ))}

        <div className="theme-switch-row">
          <span className="theme-switch-label">{theme === "dark" ? "Тёмная тема" : "Светлая тема"}</span>
          <label className="switch" title="Переключить тёмную/светлую тему">
            <input
              type="checkbox"
              aria-label="Тёмная тема"
              checked={theme === "dark"}
              onChange={(e) => setTheme(e.target.checked ? "dark" : "light")}
            />
            <span className="slider" />
          </label>
        </div>

        <SimulationTimeWidget
          value={simulationTime}
          onChange={async () => {
            await Promise.all([refreshSimulationTime(), refreshRequests(), refreshPlan()]);
          }}
          notify={notify}
          withErrorToast={withErrorToast}
        />

        {status && (
          <div className="sidebar-status">
            <div>
              <span className={`status-dot ${status.geocoding_fallback ? "fallback" : "live"}`} />
              Геокодинг: {status.geocoding_fallback ? "fallback (нет ключа)" : "Yandex API"}
            </div>
            <div style={{ marginTop: 6 }}>
              <span className={`status-dot ${status.routing_fallback ? "fallback" : "live"}`} />
              Маршруты: {status.routing_fallback ? "fallback (нет ключа)" : "Yandex API"}
            </div>
          </div>
        )}
      </aside>

      <main className="main">
        {tab === "offices" && (
          <OfficesPanel
            offices={offices}
            onChange={refreshOffices}
            notify={notify}
            withErrorToast={withErrorToast}
          />
        )}
        {tab === "engineers" && (
          <EngineersPanel
            engineers={engineers}
            offices={offices}
            districts={districts}
            equipmentList={equipmentList}
            plan={plan}
            onChange={async () => {
              await refreshEngineers();
              await refreshEquipment();
            }}
            onPlanChange={refreshPlan}
            notify={notify}
            withErrorToast={withErrorToast}
          />
        )}
        {tab === "requests" && (
          <RequestsPanel
            requests={requests}
            districts={districts}
            equipmentList={equipmentList}
            onChange={async () => {
              await refreshRequests();
              await refreshDistricts();
              await refreshEquipment();
            }}
            onOfficesChange={refreshOffices}
            onPlanChange={refreshPlan}
            notify={notify}
            withErrorToast={withErrorToast}
          />
        )}
        {tab === "plan" && (
          <PlanPanel
            plan={plan}
            engineers={engineers}
            requests={requests}
            offices={offices}
            onPlanChange={refreshPlan}
            notify={notify}
            withErrorToast={withErrorToast}
          />
        )}
      </main>

      {(showLoading || planBuilding) && (
        <div className="loading-pill">
          <div className="spinner" aria-hidden="true">
            <div /><div /><div /><div /><div /><div />
          </div>
          Идёт обработка…
        </div>
      )}

      {toast && (
        <div className={`toast ${toast.kind}`}>
          <span>{toast.message}</span>
        </div>
      )}
      {actionToast && (
        <div className={`toast ${actionToast.kind} toast-action`}>
          <span>{actionToast.message}</span>
          <button
            className="btn btn-sm btn-primary"
            onClick={() => {
              actionToast.action.onClick();
              setActionToast(null);
            }}
          >
            {actionToast.action.label}
          </button>
        </div>
      )}
    </div>
  );
}
