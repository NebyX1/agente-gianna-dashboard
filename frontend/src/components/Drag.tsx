import type { ReactNode } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
export function Draggable({
  id,
  label,
  children,
  wholeCard = false,
  overlay = false,
  disabled = false,
}: {
  id: string;
  label: string;
  children: ReactNode;
  wholeCard?: boolean;
  overlay?: boolean;
  disabled?: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({
      id,
      disabled,
      attributes: {
        role: wholeCard ? "group" : "button",
        roleDescription: "Elemento arrastrable",
      },
    });
  return (
    <div
      ref={setNodeRef}
      style={{
        transform:
          wholeCard || overlay ? undefined : CSS.Translate.toString(transform),
        opacity: isDragging ? 0.25 : 1,
      }}
      className={`drag-item${wholeCard ? " drag-ticket" : ""}${isDragging ? " is-dragging" : ""}`}
      {...(wholeCard ? attributes : {})}
      {...(wholeCard ? listeners : {})}
      role={wholeCard ? "group" : undefined}
      aria-label={wholeCard ? label : undefined}
      data-testid={wholeCard ? `draggable-${id}` : undefined}
      onPointerDown={
        wholeCard
          ? (event) => {
              if (
                (event.target as HTMLElement).closest(
                  "a, button, input, select, textarea",
                )
              )
                return;
              listeners?.onPointerDown?.(event);
            }
          : undefined
      }
      onKeyDown={
        wholeCard
          ? (event) => {
              if (event.target !== event.currentTarget) return;
              listeners?.onKeyDown?.(event);
            }
          : undefined
      }
    >
      <button
        type="button"
        className="drag-handle"
        {...attributes}
        {...listeners}
        role="button"
        aria-label={label}
        data-testid={id}
        disabled={disabled}
      >
        <GripVertical size={20} />
      </button>
      {children}
    </div>
  );
}
export function Droppable({
  id,
  className = "",
  children,
}: {
  id: string;
  className?: string;
  children: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div
      ref={setNodeRef}
      data-testid={id}
      className={`${className} ${isOver ? "drop-over" : ""}`}
    >
      {children}
    </div>
  );
}
