import { AnimatePresence, motion } from 'framer-motion';
import { TriangleAlert, CircleCheck, Info, X, CircleX } from 'lucide-react';
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';

type Tone = 'success' | 'info' | 'warning' | 'error';

interface Toast {
  id: number;
  title: string;
  description?: string;
  tone: Tone;
}

interface ToastValue {
  notify: (toast: Omit<Toast, 'id'>) => void;
}

const ToastContext = createContext<ToastValue | null>(null);

const TONES: Record<Tone, { icon: typeof Info; color: string }> = {
  success: { icon: CircleCheck, color: '#34d399' },
  info: { icon: Info, color: '#60a5fa' },
  warning: { icon: TriangleAlert, color: '#f5b544' },
  error: { icon: CircleX, color: '#f26b6b' },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((current) => current.filter((toast) => toast.id !== id)), []);

  const notify = useCallback(
    (toast: Omit<Toast, 'id'>) => {
      const id = nextId.current++;
      setToasts((current) => [...current.slice(-3), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), 4200);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-4 z-[70] flex flex-col items-end gap-2 sm:left-auto sm:w-96" aria-live="polite">
        <AnimatePresence initial={false}>
          {toasts.map((toast) => {
            const { icon: Icon, color } = TONES[toast.tone];
            return (
              <motion.div
                key={toast.id}
                layout
                initial={{ opacity: 0, y: 16, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, x: 24, transition: { duration: 0.18 } }}
                className="glass pointer-events-auto flex w-full items-start gap-3 !bg-ink-850/90 p-3.5 pr-2.5"
              >
                <Icon className="mt-0.5 size-4 shrink-0" style={{ color }} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-fg">{toast.title}</p>
                  {toast.description && <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{toast.description}</p>}
                </div>
                <button
                  type="button"
                  onClick={() => dismiss(toast.id)}
                  className="rounded-md p-1 text-fg-subtle transition hover:bg-white/5 hover:text-fg"
                  aria-label="Dismiss notification"
                >
                  <X className="size-3.5" />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used inside ToastProvider');
  return context;
}
