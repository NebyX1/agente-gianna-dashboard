import { create } from "zustand";
type FeedbackState = {
  message: string;
  failed: boolean;
  show: (message: string, failed?: boolean) => void;
};
export const useFeedback = create<FeedbackState>((set) => ({
  message: "",
  failed: false,
  show: (message, failed = false) => set({ message, failed }),
}));
export function Feedback() {
  const { message, failed, show } = useFeedback();
  return message ? (
    <div
      className={`feedback alert ${failed ? "alert-error" : "alert-success"}`}
      role={failed ? "alert" : "status"}
    >
      <span>{message}</span>
      <button
        className="btn btn-ghost"
        aria-label="Cerrar aviso"
        onClick={() => show("")}
      >
        ×
      </button>
    </div>
  ) : null;
}
