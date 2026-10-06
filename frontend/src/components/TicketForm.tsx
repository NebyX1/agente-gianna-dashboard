import { useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import axios from "axios";
import { errorMessage, fieldErrors, patch, post } from "../api/axios";
import { refreshTickets } from "../api/hooks/useTickets";
import { ticketSchema, type TicketFormValues } from "../schemas/ticket";
import { Modal } from "./Modal";
import { useFeedback } from "./Feedback";
import { formatDate, fromDateInput, toDateInput } from "../utils/time";
import type { Catalogs, Ticket, TicketInput } from "../types";
export function TicketForm({
  catalogs,
  defaults,
  initial: initialProp,
  preview = false,
  onClose,
}: {
  catalogs: Catalogs;
  defaults?: Partial<TicketFormValues>;
  initial?: Ticket;
  preview?: boolean;
  onClose: () => void;
}) {
  const initial = useRef(initialProp).current;
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors, isSubmitting },
  } = useForm<TicketFormValues>({
    resolver: zodResolver(ticketSchema),
    defaultValues: {
      origin_unit_id: initial?.origin_unit_id ?? 0,
      destination_unit_id:
        initial?.destination_unit_id ??
        catalogs.default_destination_unit_id ??
        0,
      problem_type_id: initial?.problem_type_id ?? 0,
      description: initial?.description ?? "",
      occurred_at: initial?.occurred_at ?? "",
      ...defaults,
    },
  });
  const attempt = useRef<{ key: string; body: TicketInput } | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [message, setMessage] = useState("");
  const origins =
    initial && !catalogs.org_units.some((u) => u.id === initial.origin.id)
      ? [...catalogs.org_units, initial.origin]
      : catalogs.org_units;
  const destinations =
    initial && !catalogs.org_units.some((u) => u.id === initial.destination.id)
      ? [...catalogs.org_units, initial.destination]
      : catalogs.org_units;
  const types =
    initial &&
    !catalogs.problem_types.some((t) => t.id === initial.problem_type.id)
      ? [...catalogs.problem_types, initial.problem_type]
      : catalogs.problem_types;
  const close = () => {
    if (uncertain || isSubmitting) {
      setMessage(
        "Primero confirmá el resultado del intento pendiente con el botón de reintento.",
      );
      return;
    }
    onClose();
  };
  return (
    <Modal
      title={preview ? "Vista previa de Gianna" : initial ? `Editar ${initial.code}` : "Nuevo ticket"}
      onClose={close}
    >
      <p className="modal-intro">
        {preview ? "Borrador sin enviar. Confirmá con Gianna o tomá el control desde su consola." : "Contá qué sucede y seleccioná el equipo responsable."}
      </p>
      <form
        data-testid="ticket-form"
        data-gianna-mode={preview ? "preview" : "manual"}
        className="ticket-form"
        onSubmit={(event) => {
          if (preview) { event.preventDefault(); return; }
          return handleSubmit(async (values) => {
          if (preview || isSubmitting) return;
          const body: TicketInput = {
            ...values,
            occurred_at: values.occurred_at || null,
          };
          if (!initial && !attempt.current)
            attempt.current = { key: crypto.randomUUID(), body };
          setMessage("");
          try {
            const ticket = initial
              ? await patch<Ticket>(`/tickets/${initial.id}`, {
                  ...body,
                  version: initial.version,
                })
              : await post<Ticket>(
                  "/tickets",
                  attempt.current?.body ?? body,
                  attempt.current?.key,
                );
            attempt.current = null;
            setUncertain(false);
            await refreshTickets();
            useFeedback
              .getState()
              .show(
                `${initial ? "Actualizado" : "Creado"} ${ticket.code} · ${formatDate(ticket.created_at)}`,
              );
            onClose();
          } catch (err) {
            const fields = fieldErrors(err);
            for (const key of [
              "origin_unit_id",
              "destination_unit_id",
              "problem_type_id",
              "description",
              "occurred_at",
            ] as const)
              if (fields[key])
                setError(
                  key,
                  { message: fields[key].join(". ") },
                  { shouldFocus: true },
                );
            const status = axios.isAxiosError(err)
              ? err.response?.status
              : undefined;
            const unknownResult = !status || status >= 500;
            setUncertain(!initial && unknownResult);
            if (!unknownResult) attempt.current = null;
            setMessage(
              errorMessage(err) +
                (initial
                  ? " Recargá el detalle para verificar el resultado antes de volver a guardar."
                  : unknownResult
                    ? " Conservamos la clave y los datos. Reintentá para confirmar sin duplicar."
                    : ""),
            );
            if (initial) await refreshTickets();
          }
        })(event);
        }}
      >
        <div className="form-grid">
          <div className="form-field">
            <label htmlFor="origin">Origen del pedido</label>
            <select
              id="origin"
              className="select"
              {...register("origin_unit_id", { valueAsNumber: true })}
              aria-invalid={!!errors.origin_unit_id}
              disabled={preview || uncertain}
            >
              <option value={0}>Seleccioná un origen</option>
              {origins.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                  {!u.is_active ? " (inactivo)" : ""}
                </option>
              ))}
            </select>
            {errors.origin_unit_id && (
              <p className="field-error" role="alert">
                {errors.origin_unit_id.message}
              </p>
            )}
          </div>
          <div className="form-field">
            <label htmlFor="destination">Destino responsable</label>
            <select
              id="destination"
              className="select"
              {...register("destination_unit_id", { valueAsNumber: true })}
              aria-invalid={!!errors.destination_unit_id}
              disabled={preview || uncertain}
            >
              <option value={0}>Seleccioná un destino</option>
              {destinations
                .filter(
                  (u) =>
                    u.can_receive_tickets ||
                    u.id === initial?.destination_unit_id,
                )
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                    {!u.is_active ? " (inactivo)" : ""}
                  </option>
                ))}
            </select>
            {errors.destination_unit_id && (
              <p className="field-error" role="alert">
                {errors.destination_unit_id.message}
              </p>
            )}
          </div>
          <div className="form-field form-field-wide">
            <label htmlFor="type">Tipo de problema</label>
            <select
              id="type"
              className="select"
              {...register("problem_type_id", { valueAsNumber: true })}
              aria-invalid={!!errors.problem_type_id}
              disabled={preview || uncertain}
            >
              <option value={0}>Seleccioná un tipo</option>
              {types.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            {errors.problem_type_id && (
              <p className="field-error" role="alert">
                {errors.problem_type_id.message}
              </p>
            )}
          </div>
        </div>
        <div className="form-field">
          <label htmlFor="description">Descripción del problema</label>
          <textarea
            id="description"
            className="textarea"
            {...register("description")}
            aria-invalid={!!errors.description}
            aria-describedby="description-help"
            disabled={preview || uncertain}
            data-testid="ticket-description"
            placeholder="Describí el problema…"
            maxLength={4000}
          />
          <small id="description-help">
            Incluí los detalles que ayuden a resolverlo. Entre 10 y 4000
            caracteres.
          </small>
          {errors.description && (
            <p className="field-error" role="alert">
              {errors.description.message}
            </p>
          )}
        </div>
        <details className="form-optional">
          <summary>Agregar fecha de inicio</summary>
          <div className="form-field">
            <label htmlFor="occurred">
              Inicio del problema (hora de Montevideo)
            </label>
            <Controller
              name="occurred_at"
              control={control}
              render={({ field }) => (
                <input
                  {...field}
                  id="occurred"
                  className="input"
                  type="datetime-local"
                  value={toDateInput(field.value ?? "")}
                  onChange={(event) =>
                    field.onChange(fromDateInput(event.target.value))
                  }
                  disabled={preview || uncertain}
                />
              )}
            />
            {errors.occurred_at && (
              <p className="field-error" role="alert">
                {errors.occurred_at.message}
              </p>
            )}
          </div>
        </details>
        {message && (
          <p role="alert" className="form-error">
            {message}
          </p>
        )}
        {!destinations.some((u) => u.can_receive_tickets && u.is_active) && (
          <p role="alert" className="notice">
            No hay destinos habilitados. Un administrador debe habilitar una
            unidad en Catálogos.
          </p>
        )}
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={close}
            disabled={isSubmitting || uncertain}
          >
            Cancelar
          </button>
          <button
            className="btn btn-primary"
            disabled={
              preview || isSubmitting ||
              !destinations.some((u) => u.can_receive_tickets && u.is_active)
            }
            data-testid="ticket-submit"
          >
            {isSubmitting
              ? "Guardando…"
              : uncertain
                ? "Reintentar el mismo intento"
                : initial
                  ? "Guardar cambios"
                  : "Crear ticket"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
