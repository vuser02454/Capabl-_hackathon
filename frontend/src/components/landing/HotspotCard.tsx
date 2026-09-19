/**
 * Floating readout for one environmental zone.
 *
 * Values come straight from the specialist agent's report. When an agent has not produced a
 * report yet the card says "Awaiting analysis" rather than showing a placeholder number, and
 * simulated reports are labelled so a demo run is never mistaken for a live reading.
 */
import { motion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';
import { cn } from '../../lib/format';
import { RISK_STYLES } from '../../lib/risk';
import type { HotspotData } from './environmentState';

const ENTER_LABEL: Record<string, string> = { air: 'Explore', water: 'Explore', waste: 'Inspect' };

export function HotspotCard({
  data,
  onEnter,
  className,
  compact = false,
}: {
  data: HotspotData;
  onEnter: () => void;
  className?: string;
  compact?: boolean;
}) {
  const risk = data.riskLevel ? RISK_STYLES[data.riskLevel] : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 6, scale: 0.98 }}
      transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
      className={cn('glass w-64 overflow-hidden bg-ink-950/88 p-0 text-left shadow-[0_18px_44px_-18px_rgb(0_0_0/0.9)]', className)}
      style={{ borderColor: `${data.color}33` }}
    >
      <div className="h-px w-full" style={{ background: `linear-gradient(90deg, transparent, ${data.color}, transparent)` }} />

      <div className="p-3.5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-[13px] font-semibold" style={{ color: data.color }}>
              {data.title}
            </p>
            <p className="mt-0.5 text-[11px] text-fg-muted">{data.subtitle}</p>
          </div>
          {data.isMock && (
            <span className="shrink-0 rounded-md border border-white/10 bg-white/[0.05] px-1.5 py-0.5 text-[9px] font-semibold tracking-wider text-fg-subtle">
              DEMO
            </span>
          )}
        </div>

        {data.hasData ? (
          <dl className={cn('mt-3 grid gap-x-3 gap-y-1.5', compact ? 'grid-cols-2' : 'grid-cols-1')}>
            {data.readouts.map((readout) => (
              <div key={readout.label} className="flex items-baseline justify-between gap-3 border-b border-white/[0.05] pb-1 last:border-0">
                <dt className="text-[10px] font-medium tracking-wider text-fg-subtle uppercase">{readout.label}</dt>
                <dd
                  className={cn(
                    'tabular text-[12.5px] font-semibold',
                    readout.tone === 'risk' && risk ? risk.text : 'text-fg',
                  )}
                >
                  {readout.value ?? '—'}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-2 text-[11px] text-fg-muted">
            Awaiting analysis
          </p>
        )}

        {data.note && <p className="mt-2 truncate text-[10px] text-fg-muted/80">{data.note}</p>}

        <button
          type="button"
          onClick={onEnter}
          className="mt-3 flex w-full items-center justify-between rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[11px] font-semibold text-fg transition-colors hover:bg-white/[0.09] focus-visible:ring-2 focus-visible:ring-brand/60 focus-visible:outline-none"
        >
          {ENTER_LABEL[data.id] ?? 'Explore'}
          <ArrowRight className="size-3.5" />
        </button>
      </div>
    </motion.div>
  );
}
