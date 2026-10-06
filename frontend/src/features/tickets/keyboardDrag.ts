import {
  defaultKeyboardCoordinateGetter,
  type KeyboardCoordinateGetter,
} from "@dnd-kit/core";

export const boardKeyboardCoordinates: KeyboardCoordinateGetter = (
  event,
  args,
) => {
  if (!String(args.active).startsWith("ticket-"))
    return defaultKeyboardCoordinateGetter(event, args);
  if (!["ArrowRight", "ArrowLeft"].includes(event.code)) return;
  const { context, currentCoordinates } = args;
  const card = context.collisionRect ?? context.draggingNodeRect;
  if (!card) return;
  const columns = context.droppableContainers
    .getEnabled()
    .filter(
      (column) =>
        String(column.id).startsWith("column-") &&
        context.droppableRects.has(column.id),
    )
    .sort(
      (a, b) =>
        context.droppableRects.get(a.id)!.left -
        context.droppableRects.get(b.id)!.left,
    );
  const center = card.left + card.width / 2;
  const current = columns.findIndex((column) => {
    if (context.over) return column.id === context.over.id;
    const rect = context.droppableRects.get(column.id)!;
    return center >= rect.left && center <= rect.right;
  });
  if (current < 0) return;
  const next = columns[current + (event.code === "ArrowRight" ? 1 : -1)];
  const target = next && context.droppableRects.get(next.id);
  if (!target) return;
  event.preventDefault();
  return {
    x:
      currentCoordinates.x +
      target.left +
      (target.width - card.width) / 2 -
      card.left,
    y: currentCoordinates.y + target.top + 58 - card.top,
  };
};
