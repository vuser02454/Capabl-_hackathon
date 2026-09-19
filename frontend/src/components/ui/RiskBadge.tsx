import { cn } from '../../lib/format';
import { RISK_STYLES } from '../../lib/risk';
import type { RiskLevel } from '../../types/agents';

interface RiskBadgeProps {
  level: RiskLevel | null | undefined;
  size?: 'sm' | 'md';
  suffix?: string;
  pulse?: boolean;
  className?: string;
  /** Text shown when there is no level (defaults to "Pending"). */
  emptyLabel?: string;
}

export function RiskBadge({ level, size = 'sm', suffix, pulse = false, className, emptyLabel = 'Pending' }: RiskBadgeProps) {
  if (!level) {
    return (
      <span className={cn('inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-semibold tracking-wider text-fg-subtle uppercase', className)}>
        <span className="size-1.5 rounded-full bg-fg-subtle" />
        {emptyLabel}
      </span>
    );
  }
  const style = RISK_STYLES[level];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-semibold tracking-wider whitespace-nowrap uppercase',
        style.badge,
        size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-[11px]',
        className,
      )}
    >
      <span className="relative flex size-1.5">
        {pulse && <span className="absolute inset-0 animate-pulse-ring rounded-full" style={{ background: style.color }} />}
        <span className="relative size-1.5 rounded-full" style={{ background: style.color }} />
      </span>
      {level}
      {suffix && ` ${suffix}`}
    </span>
  );
}
