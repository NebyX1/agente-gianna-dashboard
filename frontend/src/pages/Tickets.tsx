import { useState } from "react";
import { useIsMutating } from "@tanstack/react-query";
import {
  DndContext,
  DragOverlay,
  pointerWithin,
  rectIntersection,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { Plus, Zap, LoaderCircle, Inbox, PanelsTopLeft } from "lucide-react";
import {
  useCatalogs,
  useTickets,
  useStatusChange,
} from "../api/hooks/useTickets";
import { errorMessage } from "../api/axios";
import { TicketForm } from "../components/TicketForm";
import { StatusChange } from "../components/StatusChange";
import { useFeedback } from "../components/Feedback";
import { TicketCard } from "../features/tickets/TicketCard";
import { TicketBoard } from "../features/tickets/TicketBoard";
import { TicketList } from "../features/tickets/TicketList";
import {
  TicketFilters,
  type TicketParams,
} from "../features/tickets/TicketFilters";
import { QuickCreate } from "../features/tickets/QuickCreate";
import { statusDropAction } from "../features/tickets/dragPolicy";
import { boardKeyboardCoordinates } from "../features/tickets/keyboardDrag";
import type { ProblemType, Status, Ticket } from "../types";

const initialParams: TicketParams = { status: "active", per_page: 60, page: 1 };
type CreateDefaults = { problem_type_id?: number; origin_unit_id?: number };
export function TicketsPage() {
  const catalogs = useCatalogs();
  const [params, setParams] = useState<TicketParams>(initialParams);
  const [view, setView] = useState<"board" | "list">("board");
  const [quick, setQuick] = useState(false);
  const [form, setForm] = useState<CreateDefaults | null>(null);
  const [change, setChange] = useState<{
    ticket: Ticket;
    target?: Status;
  } | null>(null);
  const [dragging, setDragging] = useState<Ticket | null>(null);
  const [draggingType, setDraggingType] = useState<ProblemType | null>(null);
  const tickets = useTickets(
    params,
    false,
    !!dragging || quick || !!form || !!change,
  );
  const mutation = useStatusChange();
  const busy = useIsMutating({ mutationKey: ["ticket-status"] }) > 0;
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: boardKeyboardCoordinates }),
  );
  const statuses = catalogs.data?.statuses ?? [];
  const label = (status: Status) =>
    statuses.find((item) => item.code === status)?.label ?? status;
  const filter = (key: string, value: string) =>
    setParams((previous) => {
      const next: TicketParams = { ...previous, page: 1 };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });
  function create(defaults: CreateDefaults) {
    setQuick(false);
    setForm(defaults);
  }
  function onDragEnd(event: DragEndEvent) {
    setDragging(null);
    setDraggingType(null);
    if (!event.over || busy) return;
    const active = String(event.active.id);
    const over = String(event.over.id);
    if (active.startsWith("problem-") && over.startsWith("origin-"))
      create({
        problem_type_id: Number(active.slice(8)),
        origin_unit_id: Number(over.slice(7)),
      });
    if (active.startsWith("ticket-") && over.startsWith("column-")) {
      const ticket =
        dragging ??
        tickets.data?.items.find((item) => item.id === Number(active.slice(7)));
      const target = statuses.find((item) => item.code === over.slice(7))?.code;
      if (!ticket || !target) return;
      switch (statusDropAction(ticket.status, target, statuses)) {
        case "reject":
          useFeedback
            .getState()
            .show("Ese cambio de estado no está permitido", true);
          break;
        case "note":
          setChange({ ticket, target });
          break;
        case "move":
          mutation.mutate({ ticket, status: target });
          break;
      }
    }
  }
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={(args) => {
        const prefix = String(args.active.id).startsWith("ticket-")
          ? "column-"
          : "origin-";
        const scoped = {
          ...args,
          droppableContainers: args.droppableContainers.filter((container) =>
            String(container.id).startsWith(prefix),
          ),
        };
        const pointer = pointerWithin(scoped);
        return pointer.length ? pointer : rectIntersection(scoped);
      }}
      onDragStart={(event) => {
        setDragging(
          tickets.data?.items.find(
            (ticket) => `ticket-${ticket.id}` === String(event.active.id),
          ) ?? null,
        );
        setDraggingType(
          catalogs.data?.problem_types.find(
            (type) => `problem-${type.id}` === String(event.active.id),
          ) ?? null,
        );
      }}
      onDragEnd={onDragEnd}
      onDragCancel={() => {
        setDragging(null);
        setDraggingType(null);
      }}
      accessibility={{
        screenReaderInstructions: {
          draggable:
            "Presioná espacio para arrastrar, usá las flechas y soltá con espacio. Escape cancela. También podés usar Cambiar estado.",
        },
      }}
    >
      <section className="tickets-page">
        <div className="page-heading board-heading">
          <div>
            <span className="eyebrow board-eyebrow">
              <PanelsTopLeft size={14} aria-hidden="true" />
              TABLERO DE TRABAJO
            </span>
            <h1>Solicitudes del equipo</h1>
            <p className="muted">Gestioná los pedidos y su avance.</p>
          </div>
          <div className="heading-actions">
            <button
              className="btn btn-ghost"
              onClick={() => setQuick(true)}
              disabled={!catalogs.data}
            >
              <Zap size={16} />
              Creación rápida
            </button>
            <button
              className="btn btn-primary"
              onClick={() => setForm({})}
              disabled={!catalogs.data}
              data-testid="new-ticket"
            >
              <Plus size={18} />
              Nuevo ticket
            </button>
          </div>
        </div>
        {catalogs.isError && (
          <p className="notice" role="alert">
            {errorMessage(catalogs.error)}{" "}
            <button className="btn" onClick={() => void catalogs.refetch()}>
              Reintentar catálogos
            </button>
          </p>
        )}
        <TicketFilters
          params={params}
          catalogs={catalogs.data}
          view={view}
          onFilter={filter}
          onReset={() => setParams(initialParams)}
          onView={setView}
        />
        {tickets.isError && (
          <div className="notice" role="alert">
            {errorMessage(tickets.error)}{" "}
            {tickets.data && "Datos anteriores; pueden estar desactualizados."}
            <button className="btn" onClick={() => void tickets.refetch()}>
              Reintentar
            </button>
          </div>
        )}
        {tickets.isPending && (
          <div className="board-loading" role="status">
            <LoaderCircle className="spin" size={22} />
            Cargando tickets…
          </div>
        )}
        {tickets.data && (
          <>
            <div className="results-line">
              <span>
                <strong>{tickets.data.total}</strong> solicitudes
              </span>
              {busy && (
                <span className="saving-state" role="status">
                  <LoaderCircle className="spin" size={14} />
                  Guardando cambio…
                </span>
              )}
              {tickets.data.pages > 1 && (
                <span className="muted">
                  Página {tickets.data.page} de {tickets.data.pages}
                </span>
              )}
            </div>
            {view === "board" ? (
              <TicketBoard
                tickets={tickets.data.items}
                statuses={statuses}
                activeOnly={params.status === "active"}
                busy={busy}
                onCreate={() => setForm({})}
                onChange={(ticket) => setChange({ ticket })}
              />
            ) : (
              <TicketList
                tickets={tickets.data.items}
                label={label}
                onChange={(ticket) => setChange({ ticket })}
                busy={busy}
              />
            )}
            {tickets.data.total === 0 && view === "list" && (
              <div className="empty">
                <Inbox size={30} />
                <h2>No hay solicitudes para estos filtros</h2>
                <p>Registrá un ticket nuevo o ajustá la búsqueda.</p>
              </div>
            )}
            {tickets.data.pages > 1 && (
              <div className="pagination">
                <button
                  className="btn"
                  disabled={tickets.data.page <= 1}
                  onClick={() =>
                    setParams((previous) => ({
                      ...previous,
                      page: Number(previous.page) - 1,
                    }))
                  }
                >
                  Anterior
                </button>
                <span>
                  Página {tickets.data.page} de {tickets.data.pages}
                </span>
                <button
                  className="btn"
                  disabled={tickets.data.page >= tickets.data.pages}
                  onClick={() =>
                    setParams((previous) => ({
                      ...previous,
                      page: Number(previous.page) + 1,
                    }))
                  }
                >
                  Siguiente
                </button>
              </div>
            )}
          </>
        )}
        {quick && catalogs.data && (
          <QuickCreate
            catalogs={catalogs.data}
            draggingType={draggingType}
            onChoose={create}
            onClose={() => setQuick(false)}
          />
        )}
        {form && catalogs.data && (
          <TicketForm
            catalogs={catalogs.data}
            defaults={form}
            onClose={() => setForm(null)}
          />
        )}
        {change && (
          <StatusChange
            ticket={change.ticket}
            target={change.target}
            statuses={statuses}
            onClose={() => setChange(null)}
          />
        )}
      </section>
      {!quick && (
        <DragOverlay dropAnimation={null}>
          {dragging && (
            <TicketCard
              ticket={dragging}
              label={label(dragging.status)}
              preview
            />
          )}
        </DragOverlay>
      )}
    </DndContext>
  );
}
