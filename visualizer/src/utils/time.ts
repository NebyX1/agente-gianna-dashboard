export function formatDate(value: string, timeZone = "America/Montevideo") {
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value))
    throw new Error("Fecha sin zona horaria");
  return new Intl.DateTimeFormat("es-UY", {
    timeZone,
    dateStyle: "short",
    timeStyle: "short",
    hourCycle: "h23",
  }).format(new Date(value));
}
export function age(value: string, now = Date.now()) {
  const minutes = Math.max(0, Math.floor((now - Date.parse(value)) / 60000));
  return minutes < 60
    ? `${minutes} min`
    : minutes < 1440
      ? `${Math.floor(minutes / 60)} h`
      : `${Math.floor(minutes / 1440)} ${minutes < 2880 ? "día" : "días"}`;
}
