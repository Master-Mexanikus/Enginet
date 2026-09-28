import React from "react";

// Выбор оборудования из списка известного (файлы бригад/заявок + виды
// работ), клик включает/выключает позицию. Ручного ввода нет — сравнение
// на сервере точное, список исключает опечатки.
export default function EquipmentInput({ value, onChange, suggestions = [] }) {
  const options = [...suggestions];
  value.forEach((v) => {
    if (!options.includes(v)) options.push(v);
  });

  const toggle = (item) =>
    onChange(value.includes(item) ? value.filter((v) => v !== item) : [...value, item]);

  if (options.length === 0) {
    return <div className="equip-empty">Список оборудования пока пуст</div>;
  }

  return (
    <div className="equip-picker">
      {options.map((item) => (
        <button
          type="button"
          key={item}
          className={`chip ${value.includes(item) ? "selected" : ""}`}
          aria-pressed={value.includes(item)}
          onClick={() => toggle(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}
