import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get, post, patch, errorMessage } from "../api/axios";
import { refreshTickets, useTickets } from "../api/hooks/useTickets";
import { Modal } from "../components/Modal";
import { useFeedback } from "../components/Feedback";
import { useAuth } from "../store/auth";
import type { OrgUnit, ProblemType, User } from "../types";
type RecordItem = OrgUnit | ProblemType | User;
export function AdminPage() {
  const { section = "org-units" } = useParams();
  const role = useAuth((s) => s.user?.role);
  const [editing, setEditing] = useState<RecordItem | "new" | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(1);
  const archived = useTickets({ page, per_page: 30 }, true);
  const data = useQuery({
    queryKey: ["admin", section],
    queryFn: () => get<{ items: RecordItem[] }>(`/admin/${section}`),
    enabled:
      ["org-units", "problem-types", "users"].includes(section) &&
      role === "admin",
  });
  const units = useQuery({
    queryKey: ["admin", "parents"],
    queryFn: () => get<{ items: OrgUnit[] }>("/admin/org-units"),
    enabled: role === "admin",
  });
  if (role !== "admin")
    return <div role="alert">Esta sección requiere rol administrador.</div>;
  const kind =
    section === "users"
      ? "usuario"
      : section === "org-units"
        ? "unidad"
        : "tipo de problema";
  const item = editing !== "new" ? editing : null;
  return (
    <section>
      <div className="page-heading">
        <div>
          <span className="eyebrow">CONFIGURACIÓN DEL SISTEMA</span>
          <h1>Administración</h1>
        </div>
      </div>
      <nav className="admin-tabs" aria-label="Secciones administrativas">
        {[
          ["org-units", "Unidades"],
          ["problem-types", "Tipos de problema"],
          ["users", "Usuarios"],
          ["archived", "Tickets ocultos"],
        ].map(([key, label]) => (
          <Link
            key={key}
            className={`btn ${section === key ? "btn-primary" : "btn-ghost"}`}
            to={`/admin/${key}`}
          >
            {label}
          </Link>
        ))}
      </nav>
      {section === "archived" ? (
        <section className="panel">
          <h2>Tickets ocultos</h2>
          <p className="muted">
            Conservan su estado e historial. Abrí el detalle para restaurarlos.
          </p>
          {archived.isError && (
            <p role="alert">{errorMessage(archived.error)}</p>
          )}
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Origen</th>
                  <th>Estado</th>
                  <th>Motivo</th>
                </tr>
              </thead>
              <tbody>
                {archived.data?.items.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <Link to={`/tickets/${t.id}`}>{t.code}</Link>
                    </td>
                    <td>{t.origin.name}</td>
                    <td>{t.status}</td>
                    <td>{t.archive_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {archived.data?.total === 0 && <p>No hay tickets ocultos.</p>}
          <div className="pagination">
            <button
              className="btn"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Anterior
            </button>
            <span>Página {page}</span>
            <button
              className="btn"
              disabled={page >= (archived.data?.pages ?? 1)}
              onClick={() => setPage((p) => p + 1)}
            >
              Siguiente
            </button>
          </div>
        </section>
      ) : (
        <section className="panel">
          <div className="flex justify-between items-center gap-4 mb-5">
            <h2>
              {
                {
                  users: "Usuarios",
                  "org-units": "Unidades solicitantes y responsables",
                  "problem-types": "Tipos de problema",
                }[section]
              }
            </h2>
            <button
              className="btn btn-primary"
              onClick={() => {
                setError("");
                setEditing("new");
              }}
            >
              Agregar {kind}
            </button>
          </div>
          {section === "users" && (
            <p className="notice">
              Entregá la contraseña inicial por un canal seguro. El
              restablecimiento se realiza con el comando CLI reset-password
              documentado; invalida todas las sesiones previas.
            </p>
          )}
          {data.isError && <p role="alert">{errorMessage(data.error)}</p>}
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Nombre</th>
                  <th>{section === "users" ? "Email / rol" : "Código"}</th>
                  <th>Habilitación</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {data.data?.items.map((row) => (
                  <tr key={row.id}>
                    <td>{row.name}</td>
                    <td>
                      {"email" in row ? `${row.email} · ${row.role}` : row.code}
                    </td>
                    <td>
                      {row.is_active ? "Activo" : "Inactivo"}
                      {"can_receive_tickets" in row &&
                        row.can_receive_tickets &&
                        " · Recibe tickets"}
                    </td>
                    <td>
                      <button
                        className="btn btn-ghost"
                        onClick={() => {
                          setError("");
                          setEditing(row);
                        }}
                      >
                        Editar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {editing && (
        <Modal
          title={`${editing === "new" ? "Agregar" : "Editar"} ${kind}`}
          onClose={() => {
            if (!busy) setEditing(null);
          }}
        >
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (busy) return;
              const form = new FormData(e.currentTarget);
              const payload: Record<string, unknown> = {
                name: form.get("name"),
                is_active: form.get("is_active") === "on",
              };
              if (editing === "new" && section !== "users")
                payload.code = form.get("code");
              if (section === "org-units") {
                payload.kind = form.get("kind");
                payload.can_receive_tickets =
                  form.get("can_receive_tickets") === "on";
                payload.parent_id = form.get("parent_id")
                  ? Number(form.get("parent_id"))
                  : null;
              }
              if (section === "problem-types")
                payload.description = form.get("description") || null;
              if (section === "users") {
                payload.role = form.get("role");
                if (editing === "new") {
                  payload.email = form.get("email");
                  payload.password = form.get("password");
                }
              }
              setBusy(true);
              setError("");
              try {
                if (editing === "new") await post(`/admin/${section}`, payload);
                else await patch(`/admin/${section}/${editing.id}`, payload);
                await refreshTickets();
                setEditing(null);
                useFeedback.getState().show("Configuración guardada");
              } catch (err) {
                setError(errorMessage(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            <label htmlFor="admin-name">Nombre</label>
            <input
              id="admin-name"
              className="input"
              name="name"
              defaultValue={item?.name}
              required
              minLength={2}
              maxLength={section === "users" ? 120 : 160}
            />
            {section !== "users" && (
              <>
                <label htmlFor="admin-code">Código (inmutable)</label>
                <input
                  id="admin-code"
                  className="input"
                  name="code"
                  defaultValue={item && "code" in item ? item.code : ""}
                  disabled={editing !== "new"}
                  required
                  pattern="[A-Z0-9_-]{1,32}"
                />
              </>
            )}
            {section === "org-units" && (
              <>
                <label htmlFor="admin-kind">Clase de unidad</label>
                <select
                  id="admin-kind"
                  name="kind"
                  className="select"
                  defaultValue={item && "kind" in item ? item.kind : "area"}
                >
                  <option value="area">Área</option>
                  <option value="office">Oficina</option>
                  <option value="municipality">Municipio</option>
                </select>
                <label htmlFor="admin-parent">Unidad padre (opcional)</label>
                <select
                  id="admin-parent"
                  name="parent_id"
                  className="select"
                  defaultValue={
                    item && "parent_id" in item ? (item.parent_id ?? "") : ""
                  }
                >
                  <option value="">Sin relación</option>
                  {units.data?.items
                    .filter((u) => u.id !== item?.id && u.is_active)
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                </select>
                <label className="check-label">
                  <input
                    name="can_receive_tickets"
                    type="checkbox"
                    className="checkbox"
                    defaultChecked={
                      !!(
                        item &&
                        "can_receive_tickets" in item &&
                        item.can_receive_tickets
                      )
                    }
                  />
                  Puede recibir tickets como destino
                </label>
              </>
            )}
            {section === "problem-types" && (
              <>
                <label htmlFor="admin-description">Descripción breve</label>
                <textarea
                  id="admin-description"
                  name="description"
                  className="textarea"
                  maxLength={400}
                  defaultValue={
                    item && "description" in item
                      ? (item.description ?? "")
                      : ""
                  }
                />
              </>
            )}
            {section === "users" && (
              <>
                {editing === "new" && (
                  <>
                    <label htmlFor="admin-email">Email</label>
                    <input
                      id="admin-email"
                      name="email"
                      type="email"
                      className="input"
                      required
                    />
                    <label htmlFor="admin-password">
                      Contraseña inicial (mínimo 12 caracteres)
                    </label>
                    <input
                      id="admin-password"
                      name="password"
                      type="password"
                      className="input"
                      required
                      minLength={12}
                      maxLength={256}
                      autoComplete="new-password"
                    />
                  </>
                )}
                <label htmlFor="admin-role">Rol</label>
                <select
                  id="admin-role"
                  name="role"
                  className="select"
                  defaultValue={item && "role" in item ? item.role : "operator"}
                >
                  <option value="admin">Administrador</option>
                  <option value="operator">Operador</option>
                  <option value="viewer">Visualizador</option>
                </select>
              </>
            )}
            <label className="check-label">
              <input
                name="is_active"
                type="checkbox"
                className="checkbox"
                defaultChecked={item?.is_active ?? true}
              />
              Activo
            </label>
            {error && (
              <p role="alert" className="form-error">
                {error}
              </p>
            )}
            <button className="btn btn-primary" disabled={busy}>
              Guardar
            </button>
          </form>
        </Modal>
      )}
    </section>
  );
}
