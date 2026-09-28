import React, { useRef, useState } from "react";
import { api } from "../api.js";
import { EXTRA_EQUIPMENT, EXTRA_EQUIPMENT_NAMES, NO_EXTRA_LABEL, MAIN_EQUIPMENT, TRANSPORTS, transportLabel } from "../constants.js";
import EquipmentInput from "./EquipmentInput.jsx";
import WarningsModal from "./WarningsModal.jsx";

const emptyForm = {
  name: "",
  shift_start: "2026-08-17T08:00",
  shift_end: "2026-08-17T20:00",
  transport: "car",
  district: "",
  equipment: [],
};

const emptyImport = {
  district: "",          // заполняется автоматически из файла
  shift_start: "2026-08-17T08:00",
  shift_end: "2026-08-17T20:00",
};

// Читает район из файла бригад на стороне браузера (тот же формат, что и на
// сервере): под таблицей строка «Район», а в следующей — название района.
async function readDistrictFromFile(file) {
  const buf = await file.arrayBuffer();
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(buf);
  } catch (_) {
    text = new TextDecoder("windows-1251").decode(buf);
  }
  const rows = text.replace(/^\uFEFF/, "").split(/\r?\n/).map((line) => line.split(";").map((c) => c.trim()));
  for (let i = 1; i < rows.length; i++) {
    if ((rows[i][0] || "").toLowerCase() !== "район") continue;
    if (rows[i][1]) return rows[i][1];
    for (let j = i + 1; j < rows.length; j++) {
      if (rows[j][0]) return rows[j][0];
    }
  }
  return "";
}

export default function EngineersPanel({ engineers, offices, districts, equipmentList = [], plan, onChange, onPlanChange, notify, withErrorToast }) {
  const [form, setForm] = useState(emptyForm);
  const importInput = useRef(null);
  const [importForm, setImportForm] = useState(emptyImport);
  const [importWarnings, setImportWarnings] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [districtHover, setDistrictHover] = useState(false);
  const [districtFocus, setDistrictFocus] = useState(false);

  const startEdit = (eng) => {
    setEditingId(eng.id);
    setForm({
      name: eng.name,
      shift_start: eng.shift_start.slice(0, 16),
      shift_end: eng.shift_end.slice(0, 16),
      transport: eng.transport,
      district: eng.district,
      equipment: eng.equipment || [],
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(emptyForm);
  };

  const submit = withErrorToast(async (e) => {
    e.preventDefault();
    if (!form.name.trim()) {
      notify("Забыли указать имя инженера", "error");
      return;
    }
    if (!form.equipment.some((x) => MAIN_EQUIPMENT.includes(x))) {
      notify("Выберите оборудование: для ремонта, подключения и/или аварийных работ — от него зависит тип заявок бригады", "error");
      return;
    }
    if (!form.district.trim()) {
      notify("Забыли указать район", "error");
      return;
    }
    setBusy(true);
    try {
      if (editingId) {
        await api.updateEngineer(editingId, form);
        notify("Профиль инженера обновлён");
      } else {
        await api.createEngineer(form);
        notify("Инженер добавлен");
      }
      cancelEdit();
      await onChange();
      await onPlanChange();
    } finally {
      setBusy(false);
    }
  });

  // Импорт бригад: район и транспорт берутся из файла (район не редактируется);
  // смена задаётся вручную, она общая для всех бригад файла. Файлов можно
  // выбрать сразу несколько — импортируются по очереди тем же эндпоинтом.
  const doImportEngineers = withErrorToast(async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    const resetInput = () => {
      if (importInput.current) importInput.current.value = "";
    };
    setBusy(true);
    let totalImported = 0;
    let totalDuplicates = 0;
    const districtsUsed = [];
    const warnings = [];
    let lastDistrict = "";
    try {
      for (const file of files) {
        const fileDistrict = await readDistrictFromFile(file);
        if (!fileDistrict) {
          notify(
            `Файл «${file.name}»: не найден район (под таблицей должна быть строка «Район», а под ней — название) — пропущен`,
            "error"
          );
          continue;
        }
        setImportForm((f) => ({ ...f, district: fileDistrict }));
        const res = await api.importEngineers(file, {
          shift_start: importForm.shift_start,
          shift_end: importForm.shift_end,
        });
        lastDistrict = res.district || fileDistrict;
        totalImported += res.engineers_imported;
        totalDuplicates += res.skipped_duplicates || 0;
        if (!districtsUsed.includes(lastDistrict)) districtsUsed.push(lastDistrict);
        if (res.warnings.length) warnings.push(...res.warnings);
      }
      setImportForm((f) => ({ ...f, district: lastDistrict || f.district }));
      await onChange();
      await onPlanChange();
      const dup = totalDuplicates ? ` Пропущено дубликатов: ${totalDuplicates}.` : "";
      const districtsLabel = districtsUsed.length ? ` (район${districtsUsed.length > 1 ? "ы" : ""}: ${districtsUsed.join(", ")})` : "";
      notify(`Импортировано бригад: ${totalImported}${districtsLabel}.${dup}`);
      if (warnings.length) setImportWarnings(warnings);
    } finally {
      setBusy(false);
      resetInput();
    }
  });

  const remove = withErrorToast(async (id) => {
    await api.deleteEngineer(id);
    await onChange();
    await onPlanChange();
    notify("Инженер удалён");
  });

  const markUnavailable = withErrorToast(async (id) => {
    await api.setUnavailable(id, "Недоступен");
    await onChange();
    await onPlanChange();
    notify("Инженер помечен недоступным, план пересчитан");
  });

  const markAvailable = withErrorToast(async (id) => {
    await api.setAvailable(id);
    await onChange();
    await onPlanChange();
    notify("Инженер снова доступен");
  });

  const [expandedDistricts, setExpandedDistricts] = useState(() => new Set());
  const toggleCollapsed = (d) =>
    setExpandedDistricts((prev) => {
      const next = new Set(prev);
      if (next.has(d)) next.delete(d); else next.add(d);
      return next;
    });
  const groupedEng = {};
  engineers.forEach((e) => { (groupedEng[e.district || "—"] = groupedEng[e.district || "—"] || []).push(e); });
  const districtNames = Object.keys(groupedEng).sort();

  const assignedCount = (engId) => (plan && plan.routes[engId] ? plan.routes[engId].stops.length : 0);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">Инженеры</div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Импорт бригад из файла</div>
        <div className="import-grid">
          <div className="form-field">
            <label>Район</label>
            <input
              value={importForm.district}
              readOnly
              className="input-readonly"
              placeholder="заполнится после выбора файлов"
            />
          </div>
          <div className="form-field">
            <label>Начало смены</label>
            <input
              type="datetime-local"
              value={importForm.shift_start}
              onChange={(e) => setImportForm({ ...importForm, shift_start: e.target.value })}
            />
          </div>
          <div className="form-field">
            <label>Конец смены</label>
            <input
              type="datetime-local"
              value={importForm.shift_end}
              onChange={(e) => setImportForm({ ...importForm, shift_end: e.target.value })}
            />
          </div>
        </div>
        <input
          ref={importInput}
          type="file"
          accept=".csv"
          multiple
          onChange={doImportEngineers}
          disabled={busy}
          className="file-input-prominent"
        />
      </div>

      <div className="card">
        <div className="card-title">{editingId ? "Редактировать профиль" : "Добавить инженера"}</div>
        <form onSubmit={submit}>
          <div className="form-grid">
            <div className="form-field">
              <label>Имя</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="form-field">
              <label>Район</label>
              <div
                className="hover-suggest"
                onMouseEnter={() => setDistrictHover(true)}
                onMouseLeave={() => setDistrictHover(false)}
              >
                <input
                  value={form.district}
                  onChange={(e) => setForm({ ...form, district: e.target.value })}
                  onFocus={() => setDistrictFocus(true)}
                  onBlur={() => setDistrictFocus(false)}
                  placeholder={districts.length ? "наведите мышью, чтобы увидеть районы" : "сначала импортируйте заявки"}
                />
                {(districtHover || districtFocus) && districts.length > 0 && (
                  <div className="hover-suggest-list">
                    {districts
                      .filter((d) => d.toLowerCase().includes(form.district.toLowerCase()))
                      .map((d) => (
                        <div
                          key={d}
                          className="hover-suggest-item"
                          // onMouseDown, а не onClick — срабатывает раньше onBlur поля,
                          // иначе список успевает закрыться до того, как клик засчитается
                          onMouseDown={() => setForm({ ...form, district: d })}
                        >
                          {d}
                        </div>
                      ))}
                    {districts.filter((d) => d.toLowerCase().includes(form.district.toLowerCase())).length === 0 && (
                      <div className="hover-suggest-empty">ничего не найдено</div>
                    )}
                  </div>
                )}
              </div>
            </div>
            <div className="form-field">
              <label>Начало смены</label>
              <input
                type="datetime-local"
                value={form.shift_start}
                onChange={(e) => setForm({ ...form, shift_start: e.target.value })}
              />
            </div>
            <div className="form-field">
              <label>Конец смены</label>
              <input
                type="datetime-local"
                value={form.shift_end}
                onChange={(e) => setForm({ ...form, shift_end: e.target.value })}
              />
            </div>
            <div className="form-field">
              <label>Транспорт</label>
              <select value={form.transport} onChange={(e) => setForm({ ...form, transport: e.target.value })}>
                {TRANSPORTS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>Оборудование</label>
              <EquipmentInput
                value={form.equipment.filter((x) => !EXTRA_EQUIPMENT_NAMES.includes(x))}
                onChange={(list) =>
                  setForm({ ...form, equipment: [...form.equipment.filter((x) => EXTRA_EQUIPMENT_NAMES.includes(x)), ...list] })
                }
                suggestions={equipmentList.filter((x) => !EXTRA_EQUIPMENT_NAMES.includes(x))}
              />
            </div>
            <div className="form-field">
              <label>Дополнительное оборудование (для FMC / FTTB)</label>
              <div className="skill-chips">
                <div
                  className={`chip ${!form.equipment.some((x) => EXTRA_EQUIPMENT_NAMES.includes(x)) ? "selected" : ""}`}
                  onClick={() => setForm({ ...form, equipment: form.equipment.filter((x) => !EXTRA_EQUIPMENT_NAMES.includes(x)) })}
                >
                  {NO_EXTRA_LABEL}
                </div>
                {EXTRA_EQUIPMENT.map((x) => (
                  <div
                    key={x.key}
                    className={`chip ${form.equipment.includes(x.label) ? "selected" : ""}`}
                    onClick={() =>
                      setForm({
                        ...form,
                        equipment: form.equipment.includes(x.label)
                          ? form.equipment.filter((e) => e !== x.label)
                          : [...form.equipment, x.label],
                      })
                    }
                  >
                    {x.label}
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="form-actions">
            <button className="btn btn-primary" disabled={busy} type="submit">
              {editingId ? "Сохранить" : "Добавить"}
            </button>
            {editingId && (
              <button className="btn" type="button" onClick={cancelEdit}>
                Отмена
              </button>
            )}
          </div>
        </form>
      </div>

      <div className="card">
        <div className="card-title">Список инженеров</div>
        {engineers.length === 0 ? (
          <div className="empty-state">Пока нет ни одного инженера</div>
        ) : (
          <>
            {districtNames.length > 1 && (
              <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
                <button type="button" className="btn btn-sm" onClick={() => setExpandedDistricts(new Set(districtNames))}>Развернуть все</button>
                <button type="button" className="btn btn-sm" onClick={() => setExpandedDistricts(new Set())}>Свернуть все</button>
              </div>
            )}
            {districtNames.map((district) => {
              const list = groupedEng[district];
              const isCollapsed = !expandedDistricts.has(district);
              return (
                <div key={district} className="eng-group">
                  <div className="eng-group-title" onClick={() => toggleCollapsed(district)}>
                    <span style={{ marginRight: 8 }}>{isCollapsed ? "▸" : "▾"}</span>
                    Район: {district}
                    <span className="badge badge-neutral" style={{ marginLeft: 10 }}>{list.length}</span>
                    <span className="badge badge-ok" style={{ marginLeft: 6 }}>в плане: {list.filter((e) => assignedCount(e.id) > 0).length}</span>
                  </div>
                  {!isCollapsed && (
          <div className="table-scroll"><table className="wide">
            <thead>
              <tr>
                <th>Имя</th>
                <th>Оборудование</th>
                <th>Доп. оборудование</th>
                <th>Район</th>
                <th>Смена</th>
                <th>Транспорт</th>
                <th>Офис</th>
                <th>Статус</th>
                <th>В плане</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((eng) => (
                <tr key={eng.id}>
                  <td>{eng.name}</td>
                  <td>
                    {eng.equipment && eng.equipment.filter((x) => !EXTRA_EQUIPMENT_NAMES.includes(x)).length > 0 ? (
                      <div className="equip-list">
                        {eng.equipment.filter((x) => !EXTRA_EQUIPMENT_NAMES.includes(x)).map((item) => (
                          <span className="badge badge-neutral" key={item}>{item}</span>
                        ))}
                      </div>
                    ) : (
                      <span className="mono">—</span>
                    )}
                  </td>
                  <td>
                    {EXTRA_EQUIPMENT.filter((x) => (eng.equipment || []).includes(x.label)).length > 0 ? (
                      EXTRA_EQUIPMENT.filter((x) => (eng.equipment || []).includes(x.label)).map((x) => (
                        <span className="badge badge-info" style={{ marginRight: 4 }} key={x.key}>{x.key}</span>
                      ))
                    ) : (
                      <span className="mono" title={NO_EXTRA_LABEL}>без доп.</span>
                    )}
                  </td>
                  <td><span className="badge badge-neutral">{eng.district}</span></td>
                  <td className="mono">
                    {eng.shift_start.slice(11, 16)}–{eng.shift_end.slice(11, 16)}
                  </td>
                  <td>{transportLabel(eng.transport)}</td>
                  <td>{offices.find((o) => o.id === eng.office_id)?.name || "—"}</td>
                  <td>
                    {eng.available ? (
                      <span className="badge badge-ok">доступен</span>
                    ) : (
                      <span className="badge badge-danger" title={eng.unavailable_reason}>
                        недоступен
                      </span>
                    )}
                  </td>
                  <td className="mono">{assignedCount(eng.id)}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <button className="btn btn-sm" onClick={() => startEdit(eng)}>
                        Изменить
                      </button>
                      {eng.available ? (
                        <button className="btn btn-sm btn-danger" onClick={() => markUnavailable(eng.id)}>
                          Недоступен
                        </button>
                      ) : (
                        <button className="btn btn-sm" onClick={() => markAvailable(eng.id)}>
                          Вернуть в строй
                        </button>
                      )}
                      <button className="btn btn-sm btn-danger" onClick={() => remove(eng.id)}>
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
                  )}
                </div>
              );
            })}
          </>
        )}
      </div>

      {importWarnings && <WarningsModal warnings={importWarnings} onClose={() => setImportWarnings(null)} />}
    </>
  );
}
