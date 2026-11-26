import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle, X } from 'lucide-react';

export interface ConfirmOptions {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Destructive actions get a red confirm button and initial focus on Cancel. */
  destructive?: boolean;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

interface Pending extends ConfirmOptions {
  resolve: (value: boolean) => void;
}

/**
 * Accessible confirmation dialog (WAI-ARIA alertdialog): modal, focus is
 * trapped inside, Escape or the scrim cancels, and focus returns to the
 * control that opened it.  Used for every irreversible action instead of
 * window.confirm, which cannot be styled or themed.
 */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const confirm = useCallback<Confirm>(
    (options) =>
      new Promise<boolean>((resolve) => {
        setPending((current) => {
          current?.resolve(false);
          return { ...options, resolve };
        });
      }),
    [],
  );
  const close = useCallback((value: boolean) => {
    setPending((current) => {
      current?.resolve(value);
      return null;
    });
  }, []);
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && <ConfirmDialog options={pending} onClose={close} />}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): Confirm {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error('useConfirm must be used inside ConfirmProvider');
  return context;
}

function ConfirmDialog({ options, onClose }: { options: ConfirmOptions; onClose: (value: boolean) => void }) {
  const titleId = useId();
  const bodyId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    (options.destructive ? cancelRef.current : confirmRef.current)?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose(false);
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled])'));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      if (opener && document.contains(opener)) opener.focus();
    };
  }, [onClose, options.destructive]);

  return (
    <div className="dialog-scrim" onMouseDown={(event) => event.target === event.currentTarget && onClose(false)}>
      <div
        ref={dialogRef}
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
      >
        <div className="dialog-head">
          {options.destructive && <AlertTriangle size={18} className="dialog-icon" aria-hidden="true" />}
          <h2 id={titleId}>{options.title}</h2>
          <button type="button" className="icon-button" onClick={() => onClose(false)} aria-label="Close dialog" title="Close">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div id={bodyId} className="dialog-body">{options.message}</div>
        <div className="dialog-actions">
          <button ref={cancelRef} type="button" className="btn" onClick={() => onClose(false)}>
            {options.cancelLabel ?? 'Cancel'}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={`btn ${options.destructive ? 'btn-danger' : 'btn-primary'}`}
            onClick={() => onClose(true)}
          >
            {options.confirmLabel ?? 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  );
}
