import { useEffect, useState } from "react";
import { env } from "../config/env";
export function connectionState(
  hasData: boolean,
  failed: boolean,
  lastSuccess: number,
  now: number,
  online: boolean,
) {
  if (!hasData) return failed || !online ? "error" : "loading";
  if (
    failed ||
    !online ||
    now - lastSuccess > Math.max(15000, env.refreshMs * 3)
  )
    return "stale";
  return "current";
}
export function useNow() {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}
export function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const online = () => setOnline(true);
    const offline = () => setOnline(false);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);
  return online;
}
