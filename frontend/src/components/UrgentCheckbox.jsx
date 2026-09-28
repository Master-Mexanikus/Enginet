import React from "react";

// Чекбокс «Срочная заявка» — «неоморфный» вариант (см. .neo-check в styles.css),
// перекрашенный под тёмную/светлую тему.
export default function UrgentCheckbox({ checked, onChange, label, id }) {
  return (
    <label className="neo-check-row" htmlFor={id}>
      <span className="neo-check">
        <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span className="checkmark" />
      </span>
      {label && <span className="neo-check-label">{label}</span>}
    </label>
  );
}
