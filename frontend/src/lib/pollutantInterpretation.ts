/**
 * Health thresholds comparison and interpretation logic.
 *
 * Implements strict guards:
 *   1. Units must match.
 *   2. Averaging periods must match.
 *   3. Authoritative WHO 2021 AQG and Indian CPCB NAAQS are handled separately.
 *   4. Does NOT make "100% safe" claims; reports "Within WHO guideline reference".
 */

export interface ComparisonEvaluation {
  status: 'compatible' | 'mismatch_units' | 'mismatch_averaging_period' | 'missing_data';
  isCompatible: boolean;
  ratio: number | null;
  difference: number | null;
  percentageDifference: number | null;
  interpretationLabel: string | null;
  interpretationDescription: string | null;
  note: string;
}

export function normalizeUnit(unit: string): string {
  return unit
    .trim()
    .toLowerCase()
    .replace(/µ/g, 'u')
    .replace(/μ/g, 'u')
    .replace(/³/g, '3')
    .replace(/\s+/g, '');
}

export function normalizePeriod(period?: string | null): string {
  if (!period) return '';
  const p = period.trim().toLowerCase().replace(/_/g, '-').replace(/\s+/g, '-');
  if (['24h', '24hr', '24-hr', '24-hour', 'daily', 'day'].includes(p)) return '24-hour';
  if (['8h', '8hr', '8-hr', '8-hour'].includes(p)) return '8-hour';
  if (['1h', '1hr', '1-hr', '1-hour', 'hourly'].includes(p)) return '1-hour';
  if (['annual', 'year', '1y', '1-year'].includes(p)) return 'annual';
  if (['instantaneous', 'spot', 'real-time', 'instant'].includes(p)) return 'instantaneous';
  return p;
}

export function evaluateComparison(
  measuredValue: number | null | undefined,
  measuredUnit: string,
  measuredPeriod: string | null | undefined,
  referenceValue: number | null | undefined,
  referenceUnit: string,
  referencePeriod: string,
  subScore?: number | null,
): ComparisonEvaluation {
  if (measuredValue === null || measuredValue === undefined || referenceValue === null || referenceValue === undefined || referenceValue <= 0) {
    return {
      status: 'missing_data',
      isCompatible: false,
      ratio: null,
      difference: null,
      percentageDifference: null,
      interpretationLabel: null,
      interpretationDescription: null,
      note: 'Measurement or guideline reference unavailable.',
    };
  }

  // Guard 1: Unit compatibility
  if (normalizeUnit(measuredUnit) !== normalizeUnit(referenceUnit)) {
    return {
      status: 'mismatch_units',
      isCompatible: false,
      ratio: null,
      difference: null,
      percentageDifference: null,
      interpretationLabel: null,
      interpretationDescription: null,
      note: `Unit mismatch: measured in ${measuredUnit} while reference is in ${referenceUnit}.`,
    };
  }

  // Guard 2: Averaging period compatibility
  const normMeasPeriod = normalizePeriod(measuredPeriod);
  const normRefPeriod = normalizePeriod(referencePeriod);

  if (!normMeasPeriod || normMeasPeriod !== normRefPeriod) {
    return {
      status: 'mismatch_averaging_period',
      isCompatible: false,
      ratio: null,
      difference: null,
      percentageDifference: null,
      interpretationLabel: null,
      interpretationDescription: null,
      note: 'Comparable WHO reference unavailable for this averaging period.',
    };
  }

  const ratio = Math.round((measuredValue / referenceValue) * 100) / 100;
  const difference = Math.round((measuredValue - referenceValue) * 100) / 100;
  const percentageDifference = Math.round(((measuredValue - referenceValue) / referenceValue) * 1000) / 10;

  let interpretationLabel: string;
  let interpretationDescription: string;

  if ((subScore != null && subScore >= 0.7) || ratio >= 3.0) {
    interpretationLabel = 'CRITICAL';
    interpretationDescription = 'Significantly above reference (Critical)';
  } else if (ratio >= 2.0) {
    interpretationLabel = 'SIGNIFICANTLY ABOVE REFERENCE';
    interpretationDescription = 'Significantly above the reference';
  } else if (ratio > 1.0) {
    interpretationLabel = 'ABOVE GUIDELINE REFERENCE';
    interpretationDescription = 'Above the WHO guideline reference';
  } else {
    interpretationLabel = 'WITHIN GUIDELINE REFERENCE';
    interpretationDescription = 'Within the WHO guideline reference';
  }

  return {
    status: 'compatible',
    isCompatible: true,
    ratio,
    difference,
    percentageDifference,
    interpretationLabel,
    interpretationDescription,
    note: `${ratio}× the reference (${difference >= 0 ? '+' : ''}${difference} ${measuredUnit}, ${percentageDifference >= 0 ? '+' : ''}${percentageDifference}%)`,
  };
}
