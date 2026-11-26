import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react';

export interface ToastMessage {
  id: string;
  type: 'success' | 'error' | 'info' | 'warning';
  title: string;
  message?: string;
}

export function ToastStack({ toasts, onDismiss }: { toasts: ToastMessage[]; onDismiss: (id: string) => void }) {
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

/**
 * Errors stay until dismissed (their message is often needed to act on);
 * other toasts close after 6.5 s, paused while hovered or focused (WCAG 2.2.1).
 */
function Toast({ toast, onDismiss }: { toast: ToastMessage; onDismiss: (id: string) => void }) {
  const [paused, setPaused] = useState(false);
  const persistent = toast.type === 'error';
  useEffect(() => {
    if (persistent || paused) return;
    const timer = window.setTimeout(() => onDismiss(toast.id), 6500);
    return () => window.clearTimeout(timer);
  }, [toast.id, onDismiss, paused, persistent]);

  const Icon = toast.type === 'success' ? CheckCircle2 : toast.type === 'error' ? XCircle : toast.type === 'warning' ? AlertTriangle : Info;
  return (
    <div
      className={`toast toast-${toast.type}`}
      role={persistent ? 'alert' : undefined}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <Icon size={18} aria-hidden="true" />
      <div className="toast-text">
        <strong>{toast.title}</strong>
        {toast.message && <span>{toast.message}</span>}
      </div>
      <button type="button" className="icon-button" onClick={() => onDismiss(toast.id)} aria-label={`Dismiss notification: ${toast.title}`} title="Dismiss">
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
