import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage, get } from "../api/axios";
import { useCatalogs } from "../api/hooks/useTickets";
import type { Group, Summary } from "../types";
function Distribution({ title, rows }: { title: string; rows: Group[] }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <section className="panel">
      <h2>{title}</h2>
      <table className="table distribution">
        <thead>
          <tr>
            <th scope="col">Categoría</th>
            <th scope="col">Tickets</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <th scope="row">
                {row.name}
                <div
                  className="bar"
                  style={{ width: `${(row.count / max) * 100}%` }}
                  aria-hidden="true"
                />
              </th>
              <td>{row.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="muted">Sin datos para el período</p>}
    </section>
  );
}
export function StatisticsPage() {
  const [params, setParams] = useState<Record<string, string>>({});
  const catalogs = useCatalogs();
  const summary = useQuery({
    queryKey: ["statistics", "summary", params],
    queryFn: () => get<Summary>("/statistics/summary", params),
  });
  const problems = useQuery({
    queryKey: ["statistics", "problems", params],
    queryFn: () => get<{ items: Group[] }>("/statistics/problems", params),
  });
  const filter = (key: string, value: string) =>
    setParams((previous) => {
      const next = { ...previous };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });
  return (
    <section>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ANÁLISIS DEL SERVICIO</span>
          <h1>Problemas que se repiten</h1>
          <p className="muted">
            Datos de todas las solicitudes registradas, incluidos tickets
            ocultos.
          </p>
        </div>
      </div>
      <div className="toolbar">
        <label>
          Desde
          <input
            type="date"
            className="input"
            onChange={(e) => filter("from", e.target.value)}
          />
        </label>
        <label>
          Hasta
          <input
            type="date"
            className="input"
            onChange={(e) => filter("to", e.target.value)}
          />
        </label>
        <label>
          Origen
          <select
            className="select"
            onChange={(e) => filter("origin_unit_id", e.target.value)}
          >
            <option value="">Todos</option>
            {catalogs.data?.org_units.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Destino
          <select
            className="select"
            onChange={(e) => filter("destination_unit_id", e.target.value)}
          >
            <option value="">Todos</option>
            {catalogs.data?.org_units
              .filter((u) => u.can_receive_tickets)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Tipo
          <select
            className="select"
            onChange={(e) => filter("problem_type_id", e.target.value)}
          >
            <option value="">Todos</option>
            {catalogs.data?.problem_types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {summary.isPending && <p role="status">Calculando estadísticas…</p>}
      {summary.isError && <p role="alert">{errorMessage(summary.error)}</p>}
      {summary.data && (
        <>
          <div className="metrics">
            {[
              ["Registrados", summary.data.created],
              ["Resueltos", summary.data.resolved],
              ["Cancelados", summary.data.cancelled],
              ["Ocultos", summary.data.archived],
              [
                "Tiempo promedio de resolución",
                summary.data.average_resolution_seconds === null
                  ? "Sin datos"
                  : `${(summary.data.average_resolution_seconds / 3600).toFixed(1)} h`,
              ],
            ].map(([label, value]) => (
              <div className="panel" key={label}>
                <span className="muted">{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <p className="report-definition">{summary.data.definition}</p>
          <div className="stats-grid">
            <Distribution
              title="Por tipo de problema"
              rows={problems.data?.items ?? []}
            />
            <Distribution title="Por origen" rows={summary.data.origins} />
            <Distribution
              title="Por destino"
              rows={summary.data.destinations}
            />
            <section className="panel">
              <h2>Altas por día</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Día (Montevideo)</th>
                    <th>Tickets registrados</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.data.daily.map((d) => (
                    <tr key={d.date}>
                      <td>{d.date}</td>
                      <td>{d.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section className="panel">
              <h2>Activos actuales</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Estado</th>
                    <th>Tickets</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summary.data.active_by_status).map(
                    ([state, count]) => (
                      <tr key={state}>
                        <td>
                          {catalogs.data?.statuses.find((s) => s.code === state)
                            ?.label ?? state}
                        </td>
                        <td>{count}</td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </section>
          </div>
        </>
      )}
      {problems.isError && <p role="alert">{errorMessage(problems.error)}</p>}
    </section>
  );
}
