import { useMutation, useQuery } from "@tanstack/react-query";
import { errorMessage, get, patch } from "../axios";
import { queryClient } from "../queryClient";
import { useFeedback } from "../../components/Feedback";
import type { Catalogs, Page, Status, Ticket } from "../../types";
export const useCatalogs = () =>
  useQuery({
    queryKey: ["catalogs"],
    queryFn: () => get<Catalogs>("/catalogs"),
    staleTime: 30000,
  });
export const useTickets = (
  params: Record<string, string | number>,
  archived = false,
  paused = false,
) =>
  useQuery({
    queryKey: ["tickets", archived, params],
    queryFn: () =>
      get<Page<Ticket>>(
        archived ? "/admin/tickets/archived" : "/tickets",
        params,
      ),
    refetchInterval: paused ? false : 5000,
    refetchOnWindowFocus: !paused,
  });
export function refreshTickets() {
  return Promise.all(
    ["tickets", "ticket", "history", "statistics", "catalogs", "admin"].map(
      (key) => queryClient.invalidateQueries({ queryKey: [key] }),
    ),
  );
}
export function useStatusChange() {
  return useMutation({
    mutationKey: ["ticket-status"],
    mutationFn: ({
      ticket,
      status,
      note,
    }: {
      ticket: Ticket;
      status: Status;
      note?: string;
    }) =>
      patch<Ticket>(`/tickets/${ticket.id}/status`, {
        status,
        note,
        version: ticket.version,
      }),
    onMutate: async ({ ticket, status }) => {
      await queryClient.cancelQueries({ queryKey: ["tickets"] });
      const snapshots = queryClient.getQueriesData<Page<Ticket>>({
        queryKey: ["tickets"],
      });
      queryClient.setQueriesData<Page<Ticket>>(
        { queryKey: ["tickets"] },
        (previous) =>
          previous
            ? {
                ...previous,
                items: previous.items.map((t) =>
                  t.id === ticket.id ? { ...t, status } : t,
                ),
              }
            : previous,
      );
      return snapshots;
    },
    onError: (error, _, snapshots) => {
      snapshots?.forEach(([key, data]) => queryClient.setQueryData(key, data));
      useFeedback
        .getState()
        .show(
          errorMessage(error) +
            " Se recargará el estado del servidor para verificar el resultado.",
          true,
        );
    },
    onSuccess: () => useFeedback.getState().show("Estado actualizado"),
    onSettled: () => refreshTickets(),
  });
}
