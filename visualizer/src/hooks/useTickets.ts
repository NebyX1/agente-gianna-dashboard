import { useQuery } from "@tanstack/react-query";
import { get } from "../api/axios";
import { env } from "../config/env";
import { useAuth } from "../store/auth";
import type { DisplayTicket, StatusDefinition } from "../types";
export type DisplayData = {
  items: DisplayTicket[];
  total: number;
  generated_at: string;
};
export function useTickets(destination: string) {
  const token = useAuth((s) => s.token);
  return useQuery({
    queryKey: ["display-tickets", destination],
    queryFn: () =>
      get<DisplayData>(
        "/display/tickets",
        destination ? { destination_unit_id: destination } : {},
      ),
    enabled: !!token,
    refetchInterval: env.refreshMs,
    refetchIntervalInBackground: true,
    staleTime: 0,
    retry: false,
  });
}
export function useDisplayConfig() {
  return useQuery({
    queryKey: ["display-config"],
    queryFn: () =>
      get<{
        statuses: StatusDefinition[];
        destinations: { id: number; name: string }[];
      }>("/display/config"),
    staleTime: 60000,
  });
}
