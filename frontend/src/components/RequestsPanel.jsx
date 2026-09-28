import React, { useRef, useState } from "react";
import { api } from "../api.js";
import { EXTRA_EQUIPMENT, EXTRA_EQUIPMENT_NAMES, NO_EXTRA_LABEL, SKILLS, STATUS_BADGE, statusBadge, TRANSPORTS, skillLabel, transportLabel } from "../constants.js";
import EquipmentInput from "./EquipmentInput.jsx";
import UrgentCheckbox from "./UrgentCheckbox.jsx";
import WarningsModal from "./WarningsModal.jsx";

const emptyForm = {
  address: "",
  district: "",
  window_start: "2026-08-17T10:00",
  window_end: "2026-08-17T12:00",
  skill: "local",
  reason: "",
  duration_min: 60,
  urgent: false,
  required_transport: "",
  required_equipment: [],
  connection_type: "",
};

export default function RequestsPanel({ requests, districts, equipmentList = [], onChange, onOfficesChange, onPlanChange, notify, withErrorToast }) {
  const fileInput = useRef(null);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editDraft, setEditDraft] = useState(null);
  const [warningsModal, setWarningsModal] = useState(null);
  // районы изначально свёрнуты: здесь хранятся только РАЗВЁРНУТЫЕ
  const [expandedDistricts, setExpandedDistricts] = useState(() => new Set());

  const doImport = withErrorToast(async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setBusy(true);
    try {
      const res = await api.importFiles(files);
      await onChange();
      await onOfficesChange();
      await onPlanChange();
      const dup = res.skipped_duplicate_requests
        ? ` Пропущено как дубликаты (уже были импортированы ранее): ${res.skipped_duplicate_requests}.`
        : "";
      notify(
        `Импортировано заявок: ${res.requests_imported}. Создано офисов: ${res.created_offices.length}` +
          `${res.reused_offices.length ? ` (переиспользовано существующих: ${res.reused_offices.length})` : ""}.${dup}`
      );
      if (res.warnings.length) setWarningsModal(res.warnings);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  });

  const submitManual = withErrorToast(async (e) => {
    e.preventDefault();
    if (!form.address.trim()) {
      notify("Забыли указать адрес заявки", "error");
      return;
    }
    if (!form.district.trim()) {
      notify("Забыли указать район заявки", "error");
      return;
    }
    setBusy(true);
    try {
      await api.createRequest({ ...form, required_transport: form.required_transport || null, connection_type: form.connection_type || null });
      setForm(emptyForm);
      await onChange();
      await onPlanChange();
      notify("Заявка добавлена и сразу распределена (если нашёлся подходящий инженер)");
    } finally {
      setBusy(false);
    }
  });

  const startEdit = (r) => {
    setEditingId(r.id);
    setEditDraft({
      window_start: r.window_start.slice(0, 16),
      window_end: r.window_end.slice(0, 16),
      duration_min: r.duration_min,
      urgent: r.urgent,
      required_transport: r.required_transport || "",
      required_equipment: r.required_equipment || [],
      connection_type: r.connection_type || "",
    });
  };

  const saveEdit = withErrorToast(async (id) => {
    await api.updateRequest(id, {
      window_start: editDraft.window_start,
      window_end: editDraft.window_end,
      duration_min: Number(editDraft.duration_min),
      urgent: editDraft.urgent,
      required_transport: editDraft.required_transport || null,
      clear_required_transport: !editDraft.required_transport,
      required_equipment: editDraft.required_equipment,
      connection_type: editDraft.connection_type || null,
      clear_connection_type: !editDraft.connection_type,
    });
    setEditingId(null);
    await onChange();
    await onPlanChange();
    notify("Заявка обновлена, план пересчитан");
  });

  const cancelRequest = withErrorToast(async (id) => {
    await api.eventCancelRequest(id);
    await onChange();
    await onPlanChange();
    notify("Заявка отменена, план пересчитан");
  });

  const restoreRequest = withErrorToast(async (id) => {
    await api.eventRestoreRequest(id);
    await onChange();
    await onPlanChange();
    notify("Заявка возвращена и снова участвует в распределении");
  });

  // --- группировка по району ---
  const grouped = {};
  for (const r of requests) {
    const key = r.district || "— без района —";
    (grouped[key] = grouped[key] || []).push(r);
  }
  // порядок в группе: в работе → в пути → отправлена → не назначена → завершена → отменена
  const phaseRank = (r) => {
    if (r.status === "assigned") {
      return { in_progress: 0, en_route: 1, sent: 2, completed: 4 }[r.dispatch_phase ?? "sent"] ?? 2;
    }
    return r.status === "unassigned" ? 3 : 5;
  };
  for (const key of Object.keys(grouped)) {
    grouped[key].sort((x, y) => phaseRank(x) - phaseRank(y) || String(x.window_start).localeCompare(String(y.window_start)));
  }
  const districtNames = Object.keys(grouped).sort((a, b) => a.localeCompare(b, "ru"));

  const toggleCollapsed = (district) => {
    setExpandedDistricts((prev) => {
      const next = new Set(prev);
      next.has(district) ? next.delete(district) : next.add(district);
      return next;
    });
  };

  const renderTable = (list) => {
    // срочные заявки — наверх списка, порядок внутри групп иначе сохраняется
    const sorted = [...list].sort((a, b) => (b.urgent ? 1 : 0) - (a.urgent ? 1 : 0));
    return (
    <div className="table-scroll"><table className="wide">
      <thead>
        <tr>
          <th>Адрес</th>
          <th>Район</th>
          <th>Тип заявки</th>
          <th>Окно</th>
          <th>Длит.</th>
          <th>Доп. оборудование</th>
          <th>Оборудование</th>
          <th>Срочная</th>
          <th>Статус</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => {
          const editing = editingId === r.id;
          return (
            <tr key={r.id}>
              <td style={{ maxWidth: 220 }}>{r.address}</td>
              <td><span className="badge badge-neutral">{r.district || "—"}</span></td>
              <td>{skillLabel(r.skill)}</td>
              <td className="mono">
                {editing ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <input
                      type="datetime-local"
                      value={editDraft.window_start}
                      onChange={(e) => setEditDraft({ ...editDraft, window_start: e.target.value })}
                    />
                    <input
                      type="datetime-local"
                      value={editDraft.window_end}
                      onChange={(e) => setEditDraft({ ...editDraft, window_end: e.target.value })}
                    />
                  </div>
                ) : (
                  `${r.window_start.slice(11, 16)}–${r.window_end.slice(11, 16)}`
                )}
              </td>
              <td className="mono">
                {editing ? (
                  <input
                    type="number"
                    style={{ width: 60 }}
                    value={editDraft.duration_min}
                    onChange={(e) => setEditDraft({ ...editDraft, duration_min: e.target.value })}
                  />
                ) : (
                  `${r.duration_min} мин`
                )}
              </td>
              <td style={{ minWidth: 150 }}>
                {editing ? (
                  <select
                    value={editDraft.connection_type}
                    onChange={(e) => setEditDraft({ ...editDraft, connection_type: e.target.value })}
                  >
                    <option value="">{NO_EXTRA_LABEL}</option>
                    {EXTRA_EQUIPMENT.map((x) => (
                      <option key={x.key} value={x.key}>{x.label}</option>
                    ))}
                  </select>
                ) : r.connection_type ? (
                  <span className="badge badge-info">{r.connection_type}</span>
                ) : (
                  <span className="mono" title={NO_EXTRA_LABEL}>—</span>
                )}
              </td>
              <td style={{ minWidth: 150 }}>
                {editing ? (
                  <EquipmentInput
                    value={editDraft.required_equipment}
                    onChange={(required_equipment) => setEditDraft({ ...editDraft, required_equipment })}
                    suggestions={equipmentList.filter((x) => !EXTRA_EQUIPMENT_NAMES.includes(x))}
                  />
                ) : r.required_equipment && r.required_equipment.length > 0 ? (
                  <div className="equip-list">
                    {r.required_equipment.map((item) => (
                      <span className="badge badge-neutral" key={item}>{item}</span>
                    ))}
                  </div>
                ) : (
                  <span className="mono">—</span>
                )}
              </td>
              <td>
                {editing ? (
                  <UrgentCheckbox
                    id={`urgent-${r.id}`}
                    checked={editDraft.urgent}
                    onChange={(urgent) => setEditDraft({ ...editDraft, urgent })}
                  />
                ) : r.urgent ? (
                  <span className="badge badge-accent">срочно</span>
                ) : (
                  <span className="mono">—</span>
                )}
              </td>
              <td>
                <span className={`badge ${statusBadge(r.status, r.dispatch_phase).cls}`}>{statusBadge(r.status, r.dispatch_phase).label}</span>
              </td>
              <td>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {editing ? (
                    <>
                      <button className="btn btn-sm btn-primary" onClick={() => saveEdit(r.id)}>
                        Сохранить
                      </button>
                      <button className="btn btn-sm" onClick={() => setEditingId(null)}>
                        Отмена
                      </button>
                    </>
                  ) : (
                    <>
                      <button className="btn btn-sm" onClick={() => startEdit(r)}>
                        Изменить
                      </button>
                      {r.status !== "cancelled" && (
                        <button
                          className="btn btn-sm btn-danger"
                          title="Событие: заявка отменяется прямо сейчас, план пересчитывается"
                          onClick={() => cancelRequest(r.id)}
                        >
                          Отменить
                        </button>
                      )}
                      {r.status === "cancelled" && (
                        <button
                          className="btn btn-sm btn-primary"
                          title="Вернуть заявку обратно в пул и сразу попробовать распределить"
                          onClick={() => restoreRequest(r.id)}
                        >
                          Вернуть
                        </button>
                      )}
                    </>
                  )}
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table></div>
    );
  };

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">Заявки</div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Импорт файлов</div>
        <input
          ref={fileInput}
          type="file"
          accept=".csv,.json"
          multiple
          onChange={doImport}
          disabled={busy}
          className="file-input-prominent"
        />
      </div>

      <div className="card">
        <div className="card-title">Добавить заявку вручную</div>
        <form onSubmit={submitManual}>
          <div className="form-grid form-grid-12">
            <div className="form-field span-8">
              <label>Адрес</label>
              <input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
            </div>
            <div className="form-field span-4">
              <label>Район</label>
              <input
                list="known-districts-req"
                value={form.district}
                onChange={(e) => setForm({ ...form, district: e.target.value })}
              />
              <datalist id="known-districts-req">
                {districts.map((d) => (
                  <option key={d} value={d} />
                ))}
              </datalist>
            </div>
            <div className="form-field span-3">
              <label>Тип заявки</label>
              <select value={form.skill} onChange={(e) => setForm({ ...form, skill: e.target.value })}>
                {SKILLS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field span-3">
              <label>Начало окна</label>
              <input
                type="datetime-local"
                value={form.window_start}
                onChange={(e) => setForm({ ...form, window_start: e.target.value })}
              />
            </div>
            <div className="form-field span-3">
              <label>Конец окна</label>
              <input
                type="datetime-local"
                value={form.window_end}
                onChange={(e) => setForm({ ...form, window_end: e.target.value })}
              />
            </div>
            <div className="form-field span-3">
              <label>Длительность, мин</label>
              <input
                type="number"
                min={5}
                value={form.duration_min}
                onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })}
              />
            </div>
            <div className="form-field span-4">
              <label>Доп. оборудование (FMC / FTTB)</label>
              <select
                value={form.connection_type}
                onChange={(e) => setForm({ ...form, connection_type: e.target.value })}
              >
                <option value="">{NO_EXTRA_LABEL}</option>
                {EXTRA_EQUIPMENT.map((x) => (
                  <option key={x.key} value={x.key}>{x.label}</option>
                ))}
              </select>
            </div>
            <div className="form-field span-8">
              <label>Требуемые инструменты (опционально)</label>
              <EquipmentInput
                value={form.required_equipment}
                onChange={(required_equipment) => setForm({ ...form, required_equipment })}
                suggestions={equipmentList.filter((x) => !EXTRA_EQUIPMENT_NAMES.includes(x))}
              />
            </div>
          </div>
          <div className="form-actions form-actions-row">
            <button className="btn btn-primary" disabled={busy} type="submit">
              Добавить заявку
            </button>
            <UrgentCheckbox
              id="urgent-new"
              checked={form.urgent}
              onChange={(urgent) => setForm({ ...form, urgent })}
              label="Срочная заявка"
            />
          </div>
        </form>
      </div>

      <div className="card">
        <div className="card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>Заявки по районам (всего {requests.length})</span>
          {districtNames.length > 1 && (
            <div style={{ display: "flex", gap: 6 }}>
              <button className="btn btn-sm" onClick={() => setExpandedDistricts(new Set(districtNames))}>
                Развернуть все
              </button>
              <button className="btn btn-sm" onClick={() => setExpandedDistricts(new Set())}>
                Свернуть все
              </button>
            </div>
          )}
        </div>
        {requests.length === 0 && (
          <div className="empty-state">Заявок пока нет — импортируйте файл или добавьте вручную</div>
        )}
      </div>

      {districtNames.map((district) => {
        const list = grouped[district];
        const isCollapsed = !expandedDistricts.has(district);
        return (
          <div className="card" key={district}>
            <div
              className="card-title"
              style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
              onClick={() => toggleCollapsed(district)}
            >
              <span>
                <span style={{ marginRight: 8 }}>{isCollapsed ? "▸" : "▾"}</span>
                Район: {district}
                <span className="badge badge-neutral" style={{ marginLeft: 10 }}>
                  {list.length}
                </span>
                <span className="badge badge-ok" style={{ marginLeft: 6 }}>
                  назначено: {list.filter((r) => r.status === "assigned").length}
                </span>
                <span className="badge badge-danger" style={{ marginLeft: 6 }}>
                  отменено: {list.filter((r) => r.status === "cancelled").length}
                </span>
              </span>
            </div>
            {!isCollapsed && renderTable(list)}
          </div>
        );
      })}

      {warningsModal && <WarningsModal warnings={warningsModal} onClose={() => setWarningsModal(null)} />}
    </>
  );
}
