import { useState } from "react";
import { ArrowRight, Zap } from "lucide-react";
import { DragOverlay } from "@dnd-kit/core";
import { Modal } from "../../components/Modal";
import { Draggable, Droppable } from "../../components/Drag";
import type { Catalogs, ProblemType } from "../../types";

export function QuickCreate({
  catalogs,
  onChoose,
  onClose,
  draggingType,
}: {
  catalogs: Catalogs;
  onChoose: (defaults: {
    problem_type_id?: number;
    origin_unit_id?: number;
  }) => void;
  onClose: () => void;
  draggingType: ProblemType | null;
}) {
  const [typeSearch, setTypeSearch] = useState("");
  const [unitSearch, setUnitSearch] = useState("");
  const [selected, setSelected] = useState<number>();
  return (
    <Modal title="Creación rápida" onClose={onClose}>
      <p className="modal-intro">
        Elegí un tipo y un origen, o arrastrá el tipo sobre el área solicitante.
      </p>
      <div className="creation-grid">
        <div>
          <label htmlFor="type-search">Tipo de problema</label>
          <input
            className="input"
            id="type-search"
            value={typeSearch}
            onChange={(event) => setTypeSearch(event.target.value)}
            placeholder="Buscar tipo…"
          />
          <div className="catalog-cards">
            {catalogs.problem_types
              .filter((type) =>
                type.name
                  .toLocaleLowerCase()
                  .includes(typeSearch.toLocaleLowerCase()),
              )
              .map((type) => (
                <Draggable
                  key={type.id}
                  id={`problem-${type.id}`}
                  label={`Arrastrar ${type.name}`}
                  overlay
                >
                  <button
                    className={`catalog-card${selected === type.id ? " selected" : ""}`}
                    aria-pressed={selected === type.id}
                    onClick={() => setSelected(type.id)}
                  >
                    {type.name}
                  </button>
                </Draggable>
              ))}
          </div>
        </div>
        <div>
          <label htmlFor="unit-search">Origen solicitante</label>
          <input
            className="input"
            id="unit-search"
            value={unitSearch}
            onChange={(event) => setUnitSearch(event.target.value)}
            placeholder="Buscar área…"
          />
          <div className="catalog-cards origins-grid">
            {catalogs.org_units
              .filter((unit) =>
                unit.name
                  .toLocaleLowerCase()
                  .includes(unitSearch.toLocaleLowerCase()),
              )
              .map((unit) => (
                <Droppable key={unit.id} id={`origin-${unit.id}`}>
                  <button
                    className="catalog-card origin"
                    onClick={() =>
                      onChoose({
                        origin_unit_id: unit.id,
                        problem_type_id: selected,
                      })
                    }
                  >
                    <span>
                      {unit.name}
                      <small>
                        {
                          {
                            area: "Área",
                            office: "Oficina",
                            municipality: "Municipio",
                          }[unit.kind]
                        }
                      </small>
                    </span>
                    <ArrowRight size={14} />
                  </button>
                </Droppable>
              ))}
          </div>
        </div>
      </div>
      <DragOverlay dropAnimation={null}>
        {draggingType && (
          <div className="quick-drag-preview" data-testid="quick-drag-preview">
            <Zap size={17} />
            {draggingType.name}
          </div>
        )}
      </DragOverlay>
    </Modal>
  );
}
