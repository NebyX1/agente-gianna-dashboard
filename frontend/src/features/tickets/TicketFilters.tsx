import { useState } from "react";
import { Search, SlidersHorizontal, LayoutGrid, List, X } from "lucide-react";
import type { Catalogs } from "../../types";
export type TicketParams = Record<string, string | number>;

export function TicketFilters({
  params,
  catalogs,
  view,
  onFilter,
  onReset,
  onView,
}: {
  params: TicketParams;
  catalogs?: Catalogs;
  view: "board" | "list";
  onFilter: (key: string, value: string) => void;
  onReset: () => void;
  onView: (view: "board" | "list") => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const advancedCount = [
    "origin_unit_id",
    "destination_unit_id",
    "problem_type_id",
    "from",
    "to",
  ].filter((key) => params[key]).length;
  return (
    <div className="ticket-filters">
      <div className="toolbar board-toolbar">
        <div className="search-control">
          <Search size={17} />
          <input
            aria-label="Buscar tickets por código o descripción"
            className="input"
            placeholder="Buscar tickets…"
            value={params.q ?? ""}
            onChange={(event) => onFilter("q", event.target.value)}
          />
          {params.q && (
            <button
              className="search-clear"
              aria-label="Limpiar búsqueda"
              onClick={() => onFilter("q", "")}
            >
              <X size={14} />
            </button>
          )}
        </div>
        <select
          aria-label="Filtrar por estado"
          className="select status-filter"
          value={params.status ?? ""}
          onChange={(event) => onFilter("status", event.target.value)}
        >
          <option value="active">Tickets activos</option>
          <option value="">Todos los estados</option>
          {catalogs?.statuses.map((status) => (
            <option key={status.code} value={status.code}>
              {status.label}
            </option>
          ))}
        </select>
        <button
          className={`btn filter-toggle${expanded ? " is-selected" : ""}`}
          aria-expanded={expanded}
          aria-controls="advanced-filters"
          onClick={() => setExpanded(!expanded)}
        >
          <SlidersHorizontal size={16} />
          Filtros
          {advancedCount > 0 && (
            <span className="filter-count">{advancedCount}</span>
          )}
        </button>
        <div className="view-switch">
          <button
            aria-label="Vista de tablero"
            title="Vista de tablero"
            aria-pressed={view === "board"}
            onClick={() => onView("board")}
          >
            <LayoutGrid size={17} />
          </button>
          <button
            aria-label="Vista de lista"
            title="Vista de lista"
            aria-pressed={view === "list"}
            onClick={() => onView("list")}
          >
            <List size={18} />
          </button>
        </div>
      </div>
      {expanded && (
        <div className="advanced-filters" id="advanced-filters">
          <label>
            Origen
            <select
              className="select"
              aria-label="Filtrar por origen"
              value={params.origin_unit_id ?? ""}
              onChange={(event) =>
                onFilter("origin_unit_id", event.target.value)
              }
            >
              <option value="">Todos los orígenes</option>
              {catalogs?.org_units.map((unit) => (
                <option key={unit.id} value={unit.id}>
                  {unit.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Destino
            <select
              className="select"
              aria-label="Filtrar por destino"
              value={params.destination_unit_id ?? ""}
              onChange={(event) =>
                onFilter("destination_unit_id", event.target.value)
              }
            >
              <option value="">Todos los destinos</option>
              {catalogs?.org_units
                .filter((unit) => unit.can_receive_tickets)
                .map((unit) => (
                  <option key={unit.id} value={unit.id}>
                    {unit.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Tipo
            <select
              className="select"
              aria-label="Filtrar por tipo"
              value={params.problem_type_id ?? ""}
              onChange={(event) =>
                onFilter("problem_type_id", event.target.value)
              }
            >
              <option value="">Todos los tipos</option>
              {catalogs?.problem_types.map((type) => (
                <option key={type.id} value={type.id}>
                  {type.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Desde
            <input
              className="input"
              type="date"
              value={params.from ?? ""}
              onChange={(event) => onFilter("from", event.target.value)}
            />
          </label>
          <label>
            Hasta
            <input
              className="input"
              type="date"
              value={params.to ?? ""}
              onChange={(event) => onFilter("to", event.target.value)}
            />
          </label>
          <button className="btn btn-ghost" onClick={onReset}>
            <X size={14} />
            Limpiar
          </button>
        </div>
      )}
    </div>
  );
}
