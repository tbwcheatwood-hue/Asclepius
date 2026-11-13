import { useRef, type ButtonHTMLAttributes, type PointerEvent } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "default";
};

export function FluidButton({ variant = "default", className = "", children, onPointerMove, onPointerDown, type = "button", ...props }: Props) {
  const ref = useRef<HTMLButtonElement>(null);

  const move = (event: PointerEvent<HTMLButtonElement>) => {
    const el = ref.current;
    if (!el || document.documentElement.dataset.motion === "reduce") return;
    const rect = el.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 100;
    const y = ((event.clientY - rect.top) / rect.height) * 100;
    el.style.setProperty("--mx", `${x}%`);
    el.style.setProperty("--my", `${y}%`);
    onPointerMove?.(event);
  };

  const down = (event: PointerEvent<HTMLButtonElement>) => {
    const el = ref.current;
    if (el) {
      const rect = el.getBoundingClientRect();
      el.style.setProperty("--cx", `${((event.clientX - rect.left) / rect.width) * 100}%`);
      el.style.setProperty("--cy", `${((event.clientY - rect.top) / rect.height) * 100}%`);
      el.classList.add("is-pressed");
    }
    onPointerDown?.(event);
  };

  const up = () => ref.current?.classList.remove("is-pressed");

  return (
    <button
      ref={ref}
      type={type}
      className={`fluid-btn ${variant === "primary" ? "fluid-btn-primary" : ""} ${className}`.trim()}
      onPointerMove={move}
      onPointerDown={down}
      onPointerUp={up}
      onPointerLeave={up}
      {...props}
    >
      <span className="fluid-btn-surface">{children}</span>
    </button>
  );
}
