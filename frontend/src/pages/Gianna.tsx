import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCatalogs } from "../api/hooks/useTickets";
import { useAuth } from "../store/auth";
import { TicketForm } from "../components/TicketForm";
import { ticketSchema, type TicketFormValues } from "../schemas/ticket";

type DraftPacket = { contract: "idl.gianna.form.v1"; draft_id: string; revision: number; actor_id: number; payload: TicketFormValues };

export function GiannaFormPage({ preview }: { preview: boolean }) {
  const catalogs = useCatalogs();
  const navigate = useNavigate();
  const user = useAuth((state) => state.user);
  const [packet, setPacket] = useState<DraftPacket | null>(null);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== window || event.data?.contract !== "idl.gianna.form.v1") return;
      const data = event.data as DraftPacket;
      if (data.actor_id !== user?.id || typeof data.draft_id !== "string" || !Number.isInteger(data.revision)) return;
      // Drafts may be incomplete. Validate each supplied field and reject unknown fields.
      const parsed = ticketSchema.partial().strict().safeParse(data.payload);
      if (!parsed.success) return;
      setPacket({ ...data, payload: parsed.data as TicketFormValues });
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [user?.id]);
  return <section data-testid={preview ? "gianna-preview" : "gianna-manual"}
    data-contract="idl.gianna.form.v1" data-actor-id={user?.id}
    data-draft-id={packet?.draft_id ?? ""} data-revision={packet?.revision ?? ""}>
    <h1>{preview ? "Borrador de Gianna" : "Registro manual"}</h1>
    {!packet && <p>Esperando el borrador. Todavía no hay datos para enviar.</p>}
    {packet && catalogs.data && <TicketForm key={`${packet.draft_id}-${packet.revision}`}
      catalogs={catalogs.data} defaults={packet.payload} preview={preview}
      onClose={() => navigate("/tickets", { replace: true })} />}
  </section>;
}
