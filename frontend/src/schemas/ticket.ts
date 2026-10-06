import { z } from "zod";
export const ticketSchema = z.object({
  origin_unit_id: z.number().int().positive("Seleccioná un origen"),
  destination_unit_id: z
    .number()
    .int()
    .positive("Seleccioná un destino habilitado"),
  problem_type_id: z.number().int().positive("Seleccioná un tipo"),
  description: z
    .string()
    .trim()
    .min(10, "Ingresá al menos 10 caracteres")
    .max(4000, "Máximo 4000 caracteres"),
  occurred_at: z
    .string()
    .refine(
      (v) =>
        !v ||
        (/([+-]\d{2}:\d{2}|Z)$/.test(v) &&
          Number.isFinite(Date.parse(v)) &&
          Date.parse(v) <= Date.now()),
      "Seleccioná una fecha y hora de inicio que no sea futura",
    )
    .optional(),
});
export type TicketFormValues = z.infer<typeof ticketSchema>;
