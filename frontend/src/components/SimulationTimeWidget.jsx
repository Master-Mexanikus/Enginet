import React, { useEffect, useState } from "react";
import { api } from "../api.js";

// Симулированное «сейчас» для авто-статусов заявки (Отправлено → В пути →
// В работе → Завершено). Само не идёт: диспетчер выставляет время вручную. Реальные
// часы не подходят — тестовые данные привязаны к фиксированной дате сценария.
export default function SimulationTimeWidget({ value, onChange, notify, withErrorToast }) {
  const [draft, setDraft] = useState(value ? value.slice(0, 16) : "");

  useEffect(() => {
    setDraft(value ? value.slice(0, 16) : "");
  }, [value]);

  const apply = withErrorToast(async (time) => {
    await api.setSimulationTime(time);
    await onChange();
    notify(time ? "Симулированное время обновлено" : "Симулированное время сброшено");
  });

  const shift = (minutes) => {
    const base = draft || "2026-08-17T08:00";
    const d = new Date(base.length === 16 ? `${base}:00` : base);
    d.setMinutes(d.getMinutes() + minutes);
    const pad = (n) => String(n).padStart(2, "0");
    const local = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    setDraft(local);
    apply(local);
  };

  return (
    <div className="sim-widget">
      <div className="sim-widget-title">Симулированное время</div>
      <div>
        Сейчас:{" "}
        <span className="sim-widget-value">{value ? value.slice(0, 16).replace("T", " ") : "не задано"}</span>
      </div>
      <input
        type="datetime-local"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          apply(e.target.value);
        }}
      />
      <div className="sim-widget-row">
        <button className="btn btn-sm" onClick={() => shift(-30)} title="Сдвинуть на 30 минут назад">
          −30 мин
        </button>
        <button className="btn btn-sm" onClick={() => shift(30)} title="Сдвинуть на 30 минут вперёд">
          +30 мин
        </button>
      </div>
      <div className="sim-widget-row">
        <button className="btn sim-widget-reset" disabled={!value} onClick={() => apply(null)}>
          Сбросить
        </button>
      </div>
    </div>
  );
}
