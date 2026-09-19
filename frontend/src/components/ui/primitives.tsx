import { motion } from 'framer-motion';
import { Minus, TrendingDown, TrendingUp } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../../lib/format';
import { clamp } from '../../lib/risk';

export function StatusDot({ color, pulse = true, size = 8, className }: { color: string; pulse?: boolean; size?: number; className?: string }) {
  return (
    <span className={cn('relative inline-flex shrink-0', className)} style={{ width: size, height: size }}>
      {pulse && <span className="absolute inset-0 animate-pulse-ring rounded-full" style={{ background: color }} />}
      <span className="relative inline-flex rounded-full" style={{ width: size, height: size, background: color, boxShadow: `0 0 8px ${color}99` }} />
    </span>
  );
}

export function ProgressBar({
  value,
  color = '#2563eb',
  height = 4,
  className,
  markers,
}: {
  value: number;
  color?: string;
  height?: number;
  className?: string;
  markers?: number[];
}) {
  return (
    <div className={cn('relative w-full overflow-hidden rounded-full bg-black/[0.06]', className)} style={{ height }}>
      <motion.div
        className="h-full rounded-full"
        style={{ background: `linear-gradient(90deg, ${color}8c, ${color})` }}
        initial={{ width: 0 }}
        animate={{ width: `${clamp(value) * 100}%` }}
        transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
      />
      {markers?.map((marker) => (
        <span key={marker} className="absolute top-0 h-full w-0.5 bg-ink-950/90" style={{ left: `${marker * 100}%` }} />
      ))}
    </div>
  );
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  layoutId,
  ariaLabel,
}: {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
  layoutId: string;
  ariaLabel: string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="inline-flex rounded-lg border border-black/[0.07] bg-black/[0.03] p-0.5">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn('relative h-7 rounded-md px-2.5 text-xs font-medium transition-colors', active ? 'text-fg' : 'text-fg-subtle hover:text-fg-muted')}
          >
            {active && <motion.span layoutId={layoutId} className="absolute inset-0 rounded-md bg-black/[0.09] shadow-[inset_0_1px_0_rgb(255_255_255/0.06)]" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
            <span className="relative">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export function Switch({ checked, onChange, label, id }: { checked: boolean; onChange: (value: boolean) => void; label: string; id?: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-[22px] w-10 shrink-0 items-center rounded-full border transition-colors duration-200',
        checked ? 'justify-end border-brand/50 bg-brand/80' : 'justify-start border-black/10 bg-black/10',
      )}
    >
      <motion.span layout transition={{ type: 'spring', stiffness: 600, damping: 34 }} className="mx-[3px] size-4 rounded-full bg-white shadow-md" />
    </button>
  );
}

export function TrendDelta({ change, label = 'vs 24h ago', className }: { change: number | null; label?: string; className?: string }) {
  if (change === null) return <span className={cn('text-[11px] text-fg-subtle', className)}>No trend data</span>;
  const flat = Math.abs(change) < 0.02;
  const Icon = flat ? Minus : change > 0 ? TrendingUp : TrendingDown;
  const tone = flat ? 'text-fg-subtle' : change > 0 ? 'text-risk-high' : 'text-risk-low';
  return (
    <span className={cn('inline-flex items-center gap-1 text-[11px]', className)}>
      <Icon className={cn('size-3.5', tone)} aria-hidden />
      <span className={cn('font-medium tabular', tone)}>
        {change > 0 ? '+' : ''}
        {Math.round(change * 100)}%
      </span>
      <span className="text-fg-subtle">{label}</span>
    </span>
  );
}

export function SectionHeader({ title, subtitle, eyebrow, actions, className }: { title: ReactNode; subtitle?: ReactNode; eyebrow?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-end justify-between gap-3', className)}>
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-1 !text-brand/80">{eyebrow}</p>}
        <h2 className="text-[15px] font-semibold tracking-tight text-fg">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-fg-subtle">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Chip({ children, color, className, icon }: { children: ReactNode; color?: string; className?: string; icon?: ReactNode }) {
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 rounded-md border border-black/[0.08] bg-black/[0.04] px-1.5 py-0.5 text-[10.5px] font-medium text-fg-muted', className)}
      style={color ? { borderColor: `${color}33`, background: `${color}14` } : undefined}
    >
      {icon}
      {children}
    </span>
  );
}
