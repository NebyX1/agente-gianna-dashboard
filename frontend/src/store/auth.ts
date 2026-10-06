import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "../types";
import { env } from "../config/env";
type Auth = {
  token: string | null;
  user: User | null;
  expiresAt: string | null;
  pending: string | null;
  reason: string | null;
  login: (token: string, user: User, expiresAt: string) => void;
  setPending: (pending: string | null) => void;
  clear: (reason?: string) => void;
};
export const useAuth = create<Auth>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      expiresAt: null,
      pending: null,
      reason: null,
      login: (token, user, expiresAt) =>
        set({ token, user, expiresAt, pending: null, reason: null }),
      setPending: (pending) => set({ pending }),
      clear: (reason) =>
        set({
          token: null,
          user: null,
          expiresAt: null,
          pending: null,
          reason: reason ?? null,
        }),
    }),
    {
      name: env.namespace,
      partialize: ({ token, user, expiresAt }) => ({ token, user, expiresAt }),
    },
  ),
);
