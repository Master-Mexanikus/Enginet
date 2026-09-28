import React, { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, useMap } from "react-leaflet";
import L from "leaflet";
import { engineerColor, statusBadge } from "../constants.js";

// Карта растягивается по высоте расписания — при изменении размера контейнера
// Leaflet сам не пересчитывается, поэтому следим через ResizeObserver.
function AutoResize() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(el);
    return () => ro.disconnect();
  }, [map]);
  return null;
}

// Иконки офисов через divIcon — без внешних картинок (не тянем спрайты Leaflet по сети)
function officeIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="width:14px;height:14px;border-radius:3px;background:#E9ECF1;border:2px solid #12151A;"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

export default function MapView({ offices, engineerList, requests, plan }) {
  const requestsById = useMemo(() => {
    const map = {};
    requests.forEach((r) => (map[r.id] = r));
    return map;
  }, [requests]);

  const center = useMemo(() => {
    const points = [];
    offices.forEach((o) => o.point && points.push([o.point.lat, o.point.lon]));
    if (plan) {
      Object.values(plan.routes).forEach((r) =>
        r.stops.forEach((s) => s.point && points.push([s.point.lat, s.point.lon]))
      );
    }
    if (points.length === 0) return [55.75, 37.6]; // Москва по умолчанию
    const lat = points.reduce((a, p) => a + p[0], 0) / points.length;
    const lon = points.reduce((a, p) => a + p[1], 0) / points.length;
    return [lat, lon];
  }, [offices, plan]);

  return (
    <MapContainer center={center} zoom={11} className="map-container" scrollWheelZoom attributionControl={false}>
      <AutoResize />
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {offices.map(
        (o) =>
          o.point && (
            <Marker key={o.id} position={[o.point.lat, o.point.lon]} icon={officeIcon()}>
              <Popup>Офис: {o.name}<br />{o.address}</Popup>
            </Marker>
          )
      )}

      {plan &&
        engineerList.map((eng, idx) => {
          const route = plan.routes[eng.id];
          if (!route || route.stops.length === 0) return null;
          const color = engineerColor(idx);
          const office = offices.find((o) => o.id === eng.office_id);

          // Геометрия дороги приходит от Router API по участкам
          // (route.stops[i].polyline); если её нет (fallback или сеть
          // недоступна) — рисуем прямую линию между точками участка.
          let prevPoint = office?.point ? [office.point.lat, office.point.lon] : null;
          const linePoints = prevPoint ? [prevPoint] : [];
          route.stops.forEach((s) => {
            if (!s.point) return;
            const here = [s.point.lat, s.point.lon];
            if (s.polyline && s.polyline.length > 0) {
              linePoints.push(...s.polyline);
            } else if (prevPoint) {
              linePoints.push(here);
            } else {
              linePoints.push(here);
            }
            prevPoint = here;
          });

          return (
            <React.Fragment key={eng.id}>
              <Polyline positions={linePoints} pathOptions={{ color, weight: 3, opacity: 0.8 }} />
              {route.stops.map((s, i) => (
                <CircleMarker
                  key={s.request_id}
                  center={[s.point.lat, s.point.lon]}
                  radius={7}
                  pathOptions={{ color: "#12151A", weight: 1, fillColor: color, fillOpacity: 1 }}
                >
                  <Popup>
                    <b>{eng.name}</b>, остановка {i + 1}
                    <br />
                    {s.address}
                    <br />
                    {s.status === "assigned" && statusBadge(s.status, s.dispatch_phase) && (
                      <>
                        Статус: {statusBadge(s.status, s.dispatch_phase).label}
                        <br />
                      </>
                    )}
                    Прибытие: {s.arrival_time.slice(11, 16)}, начало работы: {s.service_start.slice(11, 16)}
                  </Popup>
                </CircleMarker>
              ))}
            </React.Fragment>
          );
        })}

      {plan &&
        plan.unassigned.map((u) => {
          const req = requestsById[u.request_id];
          if (!req || !req.point) return null;
          return (
            <CircleMarker
              key={u.request_id}
              center={[req.point.lat, req.point.lon]}
              radius={6}
              pathOptions={{ color: "#E1584A", weight: 2, fillColor: "#12151A", fillOpacity: 0.4 }}
            >
              <Popup>
                <b>Не назначена</b>
                <br />
                {req.address}
                <br />
                {u.explanation}
              </Popup>
            </CircleMarker>
          );
        })}
    </MapContainer>
  );
}
