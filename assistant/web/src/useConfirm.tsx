import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { ConfirmDialog } from "./ConfirmDialog";

export type ConfirmRequest = {
  title: string;
  description: string;
  confirmLabel?: string;
  onConfirm: () => void | Promise<void>;
};

const ConfirmContext = createContext<(request: ConfirmRequest) => void>(() => undefined);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<ConfirmRequest | null>(null);

  const ask = useCallback((request: ConfirmRequest) => {
    setPending(request);
  }, []);

  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      <ConfirmDialog
        open={pending !== null}
        title={pending?.title ?? ""}
        description={pending?.description ?? ""}
        confirmLabel={pending?.confirmLabel}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          const action = pending?.onConfirm;
          setPending(null);
          void action?.();
        }}
      />
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): (request: ConfirmRequest) => void {
  return useContext(ConfirmContext);
}

export function confirmedPayload(extra: Record<string, unknown> = {}): string {
  return JSON.stringify({ confirmed: true, ...extra });
}
