import type { MeasurementStatus, RiskLevel } from '../types/agents';

export const MODERATE_THRESHOLD = 0.4;
export const HIGH_THRESHOLD = 0.7;

export const clamp = (value: number, low = 0, high = 1) => Math.max(low, Math.min(high, value));

/** Same rounding as backend round_half_up. */
export const roundHalfUp = (value: number, digits = 2) => {
  const factor = 10 ** digits;
  return Math.floor(value * factor + 0.5) / factor;
};

export function riskLevelFor(score: number): RiskLevel {
  if (score >= HIGH_THRESHOLD) return 'HIGH';
  if (score >= MODERATE_THRESHOLD) return 'MODERATE';
  return 'LOW';
}

export function joinAnd(items: string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

export const formatNumber = (value: number) => String(value);

export interface RiskStyle {
  label: string;
  color: string;
  text: string;
  badge: string;
  soft: string;
}

export const RISK_STYLES: Record<RiskLevel, RiskStyle> = {
  LOW: {
    label: 'Low',
    color: '#34d399',
    text: 'text-risk-low',
    badge: 'border-risk-low/25 bg-risk-low/10 text-risk-low',
    soft: 'bg-risk-low/[0.06]',
  },
  MODERATE: {
    label: 'Moderate',
    color: '#f5b544',
    text: 'text-risk-moderate',
    badge: 'border-risk-moderate/25 bg-risk-moderate/10 text-risk-moderate',
    soft: 'bg-risk-moderate/[0.06]',
  },
  HIGH: {
    label: 'High',
    color: '#f26b6b',
    text: 'text-risk-high',
    badge: 'border-risk-high/25 bg-risk-high/10 text-risk-high',
    soft: 'bg-risk-high/[0.06]',
  },
};

export const MEASUREMENT_STATUS_STYLES: Record<MeasurementStatus, { label: string; color: string; text: string }> = {
  normal: { label: 'Normal', color: '#34d399', text: 'text-risk-low' },
  elevated: { label: 'Elevated', color: '#f5b544', text: 'text-risk-moderate' },
  critical: { label: 'Critical', color: '#f26b6b', text: 'text-risk-high' },
  missing: { label: 'Missing', color: '#66727b', text: 'text-fg-subtle' },
};
