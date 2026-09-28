import React from "react";
import { warningTypeLabel } from "../constants.js";

export default function WarningsModal({ warnings, onClose }) {
  if (!warnings || warnings.length === 0) return null;

  // группируем по файлу, чтобы было понятно, где именно проблема
  const byFile = {};
  for (const w of warnings) {
    (byFile[w.file] = byFile[w.file] || []).push(w);
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">Предупреждения при импорте ({warnings.length})</div>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>
        <div className="modal-body">
          {Object.entries(byFile).map(([file, items]) => (
            <div key={file} style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>{file}</div>
              <div className="table-scroll"><table>
                <thead>
                  <tr>
                    <th style={{ width: 90 }}>Строка</th>
                    <th style={{ width: 200 }}>Тип проблемы</th>
                    <th>Описание</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((w, i) => (
                    <tr key={i}>
                      <td className="mono">{w.line ?? "—"}</td>
                      <td>
                        <span className="badge badge-danger">{warningTypeLabel(w.type)}</span>
                      </td>
                      <td>{w.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
