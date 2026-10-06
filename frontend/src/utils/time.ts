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

// Native datetime-local fields are wall times, independent of the device's zone.
export function toDateInput(value: string, timeZone = "America/Montevideo") {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}
export function fromDateInput(value: string, timeZone = "America/Montevideo") {
  if (!value) return "";
  const wall = Date.parse(`${value}Z`);
  let instant = wall;
  for (let step = 0; step < 2; step++) {
    const inZone = Date.parse(
      `${toDateInput(new Date(instant).toISOString(), timeZone)}Z`,
    );
    instant += wall - inZone;
  }
  return new Date(instant).toISOString();
}
