import axios from "axios";
import { env } from "../config/env";
import { useAuth } from "../store/auth";
import { queryClient } from "./queryClient";
import type { Envelope } from "../types";
export const api = axios.create({
  baseURL: env.apiUrl,
  timeout: 12000,
  withCredentials: false,
});
api.interceptors.request.use((config) => {
  const token = useAuth.getState().token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  config.headers["X-Request-ID"] = crypto.randomUUID();
  return config;
});
export function clearSession(reason?: string) {
  useAuth.getState().clear(reason);
  queryClient.clear();
}
api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (
      axios.isAxiosError(error) &&
      useAuth.getState().token &&
      (error.response?.status === 401 ||
        (env.display && error.response?.status === 403))
    )
      clearSession(
        error.response?.status === 403
          ? "Esta cuenta ya no tiene permiso para ver la pantalla."
          : "La sesión venció o fue revocada. Iniciá sesión nuevamente.",
      );
    return Promise.reject(error);
  },
);
type ErrorBody = {
  error?: {
    message?: string;
    code?: string;
    errors?: Record<string, string[]>;
  };
  meta?: { request_id?: string };
};
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError<ErrorBody>(error)) {
    const body = error.response?.data;
    return body?.error?.message
      ? `${body.error.message}${body.meta?.request_id ? " · Solicitud " + body.meta.request_id : ""}`
      : "No se pudo confirmar la operación. Revisá la conexión y reintentá con los mismos datos.";
  }
  return error instanceof Error ? error.message : "Ocurrió un error";
}
export function fieldErrors(error: unknown) {
  return axios.isAxiosError<ErrorBody>(error)
    ? (error.response?.data.error?.errors ?? {})
    : {};
}
export async function get<T>(
  path: string,
  params?: Record<string, string | number>,
) {
  return (await api.get<Envelope<T>>(path, { params })).data.data;
}
export async function post<T>(path: string, body: unknown, key?: string) {
  return (
    await api.post<Envelope<T>>(
      path,
      body,
      key ? { headers: { "Idempotency-Key": key } } : {},
    )
  ).data.data;
}
export async function patch<T>(path: string, body: unknown) {
  return (await api.patch<Envelope<T>>(path, body)).data.data;
}
