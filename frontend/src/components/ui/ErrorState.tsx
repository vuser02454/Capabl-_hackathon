import { TriangleAlert, FlaskConical, RotateCw } from 'lucide-react';
import { cn } from '../../lib/format';
import type { AppError } from '../../services/errors';
import { Button } from './Button';

interface ErrorStateProps {
  title?: string;
  message?: string;
  error?: AppError | null;
  onRetry?: () => void;
  onSwitchToDemo?: () => void;
  compact?: boolean;
  className?: string;
}

const API_CODES = new Set(['API_UNAVAILABLE', 'API_TIMEOUT', 'PROVIDER_NOT_CONFIGURED']);

export function ErrorState({ title, message, error, onRetry, onSwitchToDemo, compact = false, className }: ErrorStateProps) {
  const heading = title ?? error?.title ?? 'Something went wrong';
  const body = message ?? error?.message ?? 'Please try again.';
  const showDemo = onSwitchToDemo && (!error || API_CODES.has(error.code));

  return (
    <div
      role="alert"
      className={cn(
        'flex gap-3 rounded-2xl border border-risk-high/20 bg-risk-high/[0.045]',
        compact ? 'items-start p-4' : 'flex-col items-center justify-center p-8 text-center',
        className,
      )}
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-risk-high/20 bg-risk-high/10 text-risk-high">
        <TriangleAlert className="size-[18px]" />
      </span>
      <div className={cn('min-w-0', compact && 'flex-1')}>
        <h4 className="text-sm font-semibold text-fg">{heading}</h4>
        <p className={cn('mt-1 text-xs leading-relaxed text-fg-muted', !compact && 'mx-auto max-w-md')}>{body}</p>
        {(onRetry || showDemo) && (
          <div className={cn('mt-3 flex flex-wrap gap-2', !compact && 'justify-center')}>
            {onRetry && (
              <Button size="sm" icon={RotateCw} onClick={onRetry}>
                Retry
              </Button>
            )}
            {showDemo && (
              <Button size="sm" variant="ghost" icon={FlaskConical} onClick={onSwitchToDemo}>
                Switch to Demo Mode
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
