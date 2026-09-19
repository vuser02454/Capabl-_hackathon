import { LoaderCircle } from 'lucide-react';
import { cn } from '../../lib/format';

interface LoadingStateProps {
  label?: string;
  variant?: 'inline' | 'block' | 'skeleton';
  lines?: number;
  className?: string;
}

export function LoadingState({ label = 'Loading…', variant = 'inline', lines = 3, className }: LoadingStateProps) {
  if (variant === 'skeleton') {
    return (
      <div className={cn('space-y-2.5', className)} aria-busy="true" aria-label={label}>
        {Array.from({ length: lines }, (_, index) => (
          <div key={index} className="skeleton h-3" style={{ width: `${92 - index * 17}%` }} />
        ))}
      </div>
    );
  }

  if (variant === 'block') {
    return (
      <div className={cn('flex min-h-40 flex-col items-center justify-center gap-3 text-center', className)} aria-busy="true">
        <span className="relative grid size-10 place-items-center">
          <span className="absolute inset-0 animate-spin-slow rounded-full border border-dashed border-brand/40" />
          <LoaderCircle className="size-4 animate-spin text-brand" />
        </span>
        <p className="text-xs text-fg-muted">{label}</p>
      </div>
    );
  }

  return (
    <span className={cn('inline-flex items-center gap-2 text-xs text-fg-muted', className)} aria-busy="true">
      <LoaderCircle className="size-3.5 animate-spin text-brand" />
      {label}
    </span>
  );
}
