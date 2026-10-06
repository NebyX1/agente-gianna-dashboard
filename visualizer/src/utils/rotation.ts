export function capacity(width: number, height: number) {
  const columns =
    width >= 3000
      ? 4
      : width >= 1600
        ? 3
        : width >= 1000
          ? 3
          : width >= 640
            ? 2
            : 1;
  // Leave room for the institutional header, spotlight and screen controls.
  const reserve = width >= 3000 ? 800 : 500;
  const cardStep = width >= 3000 ? 320 : 180;
  const rows = Math.max(1, Math.floor((height - reserve) / cardStep));
  return { columns, rows, size: columns * rows };
}
export function pageItems<T>(items: T[], page: number, size: number) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = page % pages;
  return {
    items: items.slice(current * size, (current + 1) * size),
    page: current,
    pages,
  };
}
