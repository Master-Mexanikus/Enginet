import React, { useState } from "react";
import MapView from "./MapView.jsx";
import { engineerColor, statusBadge } from "../constants.js";

function km(meters) {
  return (meters / 1000).toFixed(1);
}

export default function PlanPanel({
  plan, engineers, requests, offices,
  onPlanChange, notify, withErrorToast,
}) {
  const [expanded, setExpanded] = useState(new Set());
  // Группы районов в "Не распределены" изначально свёрнуты — сначала
  // просто видно счётчик, сами заявки открываются по клику.
  const [expandedDistricts, setExpandedDistricts] = useState(() => new Set());
  // Расписание по каждому инженеру изначально свёрнуто — разворачивается
  // по клику на треугольник, так же, как группы "Не распределены".
  const [expandedEngineers, setExpandedEngineers] = useState(() => new Set());

  const toggleExplain = (requestId) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(requestId) ? next.delete(requestId) : next.add(requestId);
      return next;
    });
  };

  const toggleDistrict = (district) => {
    setExpandedDistricts((prev) => {
      const next = new Set(prev);
      next.has(district) ? next.delete(district) : next.add(district);
      return next;
    });
  };

  const toggleEngineer = (engId) => {
    setExpandedEngineers((prev) => {
      const next = new Set(prev);
      next.has(engId) ? next.delete(engId) : next.add(engId);
      return next;
    });
  };

  // Свободные (без заявок) и недоступные бригады автоматически уходят вниз
  // списка; порядок внутри групп сохраняется. Цвет маршрута привязан к
  // исходному индексу бригады — он совпадает с цветом на карте.
  const sortedEngineers = engineers
    .map((eng, idx) => ({ eng, idx }))
    .sort((a, b) => {
      const busy = (x) => (x.eng.available && plan?.routes[x.eng.id]?.stops.length > 0 ? 0 : 1);
      return busy(a) - busy(b) || a.idx - b.idx;
    });

  // группировка нераспределённых заявок по району — так же, как на вкладке "Заявки"
  const unassignedGrouped = {};
  if (plan) {
    for (const u of plan.unassigned) {
      const req = requests.find((r) => r.id === u.request_id);
      const key = req?.district || "— без района —";
      (unassignedGrouped[key] = unassignedGrouped[key] || []).push({ ...u, address: req?.address });
    }
  }
  const unassignedDistricts = Object.keys(unassignedGrouped).sort((a, b) => a.localeCompare(b, "ru"));

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">План</div>
        </div>
      </div>

      {!plan ? (
        <div className="card">
          <div className="empty-state">
            Плана пока нет — как только появится хотя бы один офис (импортируйте файл заявок)
            и один инженер, план построится сам.
          </div>
        </div>
      ) : (
        <>
          <div className="plan-grid">
            <div className="plan-map-col">
              <MapView offices={offices} engineerList={engineers} requests={requests} plan={plan} />
            </div>

            <div className="plan-side">
              <div className="card">
                <div
                  className="card-title"
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}
                >
                  <span>Расписание инженеров</span>
                  <span className="mono" style={{ fontWeight: 400, fontSize: 12, color: "var(--text-secondary)" }}>
                    суммарный пробег: {km(plan.metrics.total_distance_meters)} км
                  </span>
                </div>
                {engineers.length === 0 ? (
                  <div className="empty-state">Пока нет ни одного инженера</div>
                ) : (
                  sortedEngineers.map(({ eng, idx }) => {
                    const route = plan.routes[eng.id];
                    const hasStops = route && route.stops.length > 0;
                    const isExpanded = expandedEngineers.has(eng.id);
                    return (
                      <div className="route-block" key={eng.id}>
                        <div
                          className="route-block-header"
                          style={{ cursor: hasStops ? "pointer" : "default" }}
                          onClick={() => hasStops && toggleEngineer(eng.id)}
                        >
                          <span className="rb-arrow">{hasStops ? (isExpanded ? "▾" : "▸") : ""}</span>
                          <span className="rb-dot" style={{ background: engineerColor(idx) }} />
                          <span className="rb-name" title={eng.name}>{eng.name}</span>
                          <span className="rb-district">
                            <span className="badge badge-neutral">{eng.district}</span>
                          </span>
                          <span className="rb-status">
                            {!eng.available ? (
                              <span className="badge badge-danger">недоступен</span>
                            ) : !hasStops ? (
                              <span className="badge badge-ok">свободен</span>
                            ) : (
                              <span className="badge badge-neutral">заявок: {route.stops.length}</span>
                            )}
                          </span>
                          <span className="mono rb-km">{km(route ? route.total_distance_meters : 0)} км</span>
                        </div>
                        {hasStops && isExpanded &&
                          route.stops.map((s) => {
                            const explanation = plan.explanations[s.request_id];
                            return (
                              <div key={s.request_id}>
                                <div className="route-stop">
                                  <span className="stop-time">{s.service_start.slice(11, 16)}</span>
                                  <span style={{ flex: 1 }}>{s.address}</span>
                                  {s.status === "assigned" && (() => {
                                    const b = statusBadge(s.status, s.dispatch_phase);
                                    return b ? <span className={`badge ${b.cls}`}>{b.label}</span> : null;
                                  })()}
                                  {explanation && (
                                    <button
                                      className="btn btn-sm"
                                      title="Почему назначено именно так"
                                      onClick={(e) => { e.stopPropagation(); toggleExplain(s.request_id); }}
                                    >
                                      ?
                                    </button>
                                  )}
                                </div>
                                {expanded.has(s.request_id) && explanation && (
                                  <div className="unassigned-reason" style={{ marginBottom: 8 }}>
                                    {explanation.explanation}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-title">Не распределены ({plan.unassigned.length})</div>
            {plan.unassigned.length === 0 ? (
              <div className="empty-state">Все заявки распределены</div>
            ) : (
              <div className="unassigned-grid">
                {unassignedDistricts.map((district) => {
                  const items = unassignedGrouped[district];
                  const isExpanded = expandedDistricts.has(district);
                  return (
                    <React.Fragment key={district}>
                      <div
                        className="unassigned-district-header"
                        onClick={() => toggleDistrict(district)}
                      >
                        <span>{isExpanded ? "▾" : "▸"}</span>
                        <span>{district}</span>
                        <span className="badge badge-danger">{items.length}</span>
                      </div>
                      {isExpanded &&
                        items.map((u) => (
                          <div className="unassigned-item" key={u.request_id}>
                            <div>{u.address || u.request_id}</div>
                            <div className="unassigned-reason">{u.explanation}</div>
                          </div>
                        ))}
                    </React.Fragment>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
