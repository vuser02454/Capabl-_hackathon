import type { TrendRange } from '../types/environment';

export const cn = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

export const pct = (score: number) => Math.round(score * 100);

export function formatValue(value: number | null | undefined, decimals?: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return decimals === undefined ? String(value) : value.toFixed(decimals);
}

export function formatClock(date: Date): string {
  return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function formatLongDate(date: Date): string {
  return date.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? '—'
    : date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}, ${formatTime(iso)}`;
}

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never';
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 10) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  return `${Math.round(minutes / 60)} h ago`;
}

export function trendAxisLabel(range: TrendRange, iso: string): string {
  const date = new Date(iso);
  if (range === '24h') return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  if (range === '7d') {
    return `${date.toLocaleDateString('en-GB', { weekday: 'short' })} ${date.toLocaleTimeString('en-GB', { hour: '2-digit' })}h`;
  }
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

export const RANGE_LABELS: Record<TrendRange, string> = {
  '24h': 'Last 24 hours',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
};

/** Relative change between first and last value, e.g. +0.18 for +18%. */
export function relativeChange(first: number | null | undefined, last: number | null | undefined): number | null {
  if (first === null || first === undefined || last === null || last === undefined || first === 0) return null;
  return (last - first) / first;
}
