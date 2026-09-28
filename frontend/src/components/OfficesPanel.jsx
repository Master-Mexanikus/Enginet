import React, { useState } from "react";
import { api } from "../api.js";

export default function OfficesPanel({ offices, onChange, notify, withErrorToast }) {
  const [editingId, setEditingId] = useState(null);
  const [nameDraft, setNameDraft] = useState("");

  const startEdit = (o) => {
    setEditingId(o.id);
    setNameDraft(o.name);
  };

  const saveEdit = withErrorToast(async (id) => {
    if (!nameDraft.trim()) return;
    await api.updateOffice(id, { name: nameDraft.trim() });
    setEditingId(null);
    await onChange();
    notify("Название офиса обновлено");
  });

  const remove = withErrorToast(async (id) => {
    await api.deleteOffice(id);
    await onChange();
    notify("Офис удалён");
  });

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">Офисы</div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Список офисов</div>
        {offices.length === 0 ? (
          <div className="empty-state">
            Пока нет ни одного офиса — импортируйте файл заявок во вкладке «Заявки»
          </div>
        ) : (
          <div className="table-scroll"><table>
            <thead>
              <tr>
                <th>Название</th>
                <th>Адрес</th>
                <th>Координаты</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {offices.map((o) => (
                <tr key={o.id}>
                  <td>
                    {editingId === o.id ? (
                      <input value={nameDraft} onChange={(e) => setNameDraft(e.target.value)} />
                    ) : (
                      o.name
                    )}
                  </td>
                  <td>{o.address}</td>
                  <td className="mono">
                    {o.point ? `${o.point.lat.toFixed(4)}, ${o.point.lon.toFixed(4)}` : "—"}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      {editingId === o.id ? (
                        <>
                          <button className="btn btn-sm btn-primary" onClick={() => saveEdit(o.id)}>
                            Сохранить
                          </button>
                          <button className="btn btn-sm" onClick={() => setEditingId(null)}>
                            Отмена
                          </button>
                        </>
                      ) : (
                        <>
                          <button className="btn btn-sm" onClick={() => startEdit(o)}>
                            Переименовать
                          </button>
                          <button className="btn btn-sm btn-danger" onClick={() => remove(o.id)}>
                            Удалить
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </>
  );
}
