import { CircleSlash, History, Radio, TestTube } from 'lucide-react';
import { cn } from '../../lib/format';
import type { DataModeTone } from '../../lib/waterSource';

const TONE_STYLES: Record<DataModeTone | 'unavailable', string> = {
  live: 'border-risk-low/25 bg-risk-low/10 text-risk-low',
  historical: 'border-risk-moderate/25 bg-risk-moderate/10 text-risk-moderate',
  demo: 'border-info/25 bg-info/10 text-info',
  unavailable: 'border-black/10 bg-black/[0.04] text-fg-subtle',
};

const TONE_ICONS: Record<DataModeTone | 'unavailable', typeof Radio> = {
  live: Radio,
  historical: History,
  demo: TestTube,
  unavailable: CircleSlash,
};

/**
 * Reusable data-provenance badge (LIVE SENSOR / HISTORICAL DATASET / DEMO DATA / UNAVAILABLE).
 * Communicates source type through an icon + text label, never through color alone.
 */
export function DataModeBadge({
  label,
  tone,
  size = 'sm',
  className,
}: {
  label: string;
  tone: DataModeTone | 'unavailable';
  size?: 'sm' | 'md';
  className?: string;
}) {
  const Icon = TONE_ICONS[tone];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-semibold tracking-wider whitespace-nowrap uppercase',
        TONE_STYLES[tone],
        size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-[11px]',
        className,
      )}
    >
      <Icon className={size === 'sm' ? 'size-3' : 'size-3.5'} aria-hidden />
      {label}
    </span>
  );
}
