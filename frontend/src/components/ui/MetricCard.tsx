import { cn } from '../../lib/format';
import { MEASUREMENT_STATUS_STYLES } from '../../lib/risk';
import type { MeasurementStatus } from '../../types/agents';
import { AnimatedNumber } from './AnimatedNumber';
import { ProgressBar } from './primitives';

interface MetricCardProps {
  label: string;
  value: number | null;
  unit?: string;
  decimals?: number;
  status?: MeasurementStatus;
  progress?: number | null;
  hint?: string;
  size?: 'sm' | 'md';
  className?: string;
}

export function MetricCard({ label, value, unit, decimals, status, progress, hint, size = 'sm', className }: MetricCardProps) {
  const statusStyle = status ? MEASUREMENT_STATUS_STYLES[status] : null;
  const places = decimals ?? (value !== null && !Number.isInteger(value) ? 1 : 0);

  return (
    <div className={cn('rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5', className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[10.5px] font-medium tracking-normal text-fg-subtle uppercase">{label}</span>
        {statusStyle && (
          <span className="inline-flex items-center gap-1 text-[10px] text-fg-subtle" title={statusStyle.label}>
            <span className="size-1.5 rounded-full" style={{ background: statusStyle.color }} />
            <span className="sr-only">{statusStyle.label}</span>
          </span>
        )}
      </div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={cn('font-semibold tracking-tight text-fg', size === 'md' ? 'text-2xl' : 'text-lg')}>
          {value === null ? <span className="text-fg-subtle">—</span> : <AnimatedNumber value={value} decimals={places} />}
        </span>
        {unit && value !== null && <span className="text-[11px] text-fg-subtle">{unit}</span>}
      </div>
      {progress !== undefined && progress !== null && <ProgressBar value={progress} color={statusStyle?.color} height={3} className="mt-2" />}
      {hint && <p className="mt-1 truncate text-[10.5px] text-fg-subtle">{hint}</p>}
    </div>
  );
}
