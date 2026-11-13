import { type ReactNode, useId } from "react";

export function CascadeNav({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <nav className="cascade-nav" aria-label={label} id={id}>
      {children}
    </nav>
  );
}

export function CascadeItem({
  active,
  onClick,
  children,
  index,
}: {
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
  index: number;
}) {
  return (
    <button
      type="button"
      className="cascade-item"
      style={{ ["--i" as string]: index }}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
    >
      <span className="cascade-key">{children}</span>
    </button>
  );
}
