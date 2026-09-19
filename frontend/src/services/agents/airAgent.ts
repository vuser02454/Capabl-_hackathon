/**
 * Air Quality Agent
 *   Input:      location
 *   Tools:      AirQualitySource
 *   Processing: normalisation -> risk calculation -> anomaly detection
 *   Output:     AirAgentResult
 */
import type { LocationProfile } from '../../data/locations';
import { clamp, formatNumber, riskLevelFor, roundHalfUp } from '../../lib/risk';
import type { AirAgentResult, Finding, Measurement } from '../../types/agents';
import { AppError } from '../errors';
import { generateHistory } from '../history';
import type { AirQualitySource } from '../providers/airQualitySource';
import type { Agent, AgentTrace } from './agent';

type PollutantKey = 'pm25' | 'pm10' | 'no2' | 'o3';

const POLLUTANTS: Array<{ key: PollutantKey; label: string; weight: number; reference: number; guideline: number; finding: string }> = [
  { key: 'pm25', label: 'PM2.5', weight: 0.55, reference: 100, guideline: 15, finding: 'Elevated PM2.5' },
  { key: 'pm10', label: 'PM10', weight: 0.25, reference: 180, guideline: 45, finding: 'Elevated PM10' },
  { key: 'no2', label: 'NO₂', weight: 0.12, reference: 80, guideline: 25, finding: 'Elevated NO₂' },
  { key: 'o3', label: 'O₃', weight: 0.08, reference: 100, guideline: 100, finding: 'Elevated ozone' },
];

const NAQI: Record<'pm25' | 'pm10', Array<[number, number, number, number]>> = {
  pm25: [[0, 30, 0, 50], [31, 60, 51, 100], [61, 90, 101, 200], [91, 120, 201, 300], [121, 250, 301, 400], [251, 500, 401, 500]],
  pm10: [[0, 50, 0, 50], [51, 100, 51, 100], [101, 250, 101, 200], [251, 350, 201, 300], [351, 430, 301, 400], [431, 1000, 401, 500]],
};
const AQI_CATEGORIES: Array<[number, string]> = [[50, 'Good'], [100, 'Satisfactory'], [200, 'Moderate'], [300, 'Poor'], [400, 'Very Poor'], [500, 'Severe']];

const ANOMALY_RATIO = 1.15;
const BASE_CONFIDENCE = 0.95;
const MISSING_PENALTY = 0.15;

function subIndex(key: 'pm25' | 'pm10', concentration: number): number {
  for (const [cLo, cHi, iLo, iHi] of NAQI[key]) {
    if (concentration <= cHi) {
      const c = Math.max(concentration, cLo);
      return iLo + ((iHi - iLo) * (c - cLo)) / (cHi - cLo);
    }
  }
  return 500;
}

function aqiCategory(aqi: number): string {
  return AQI_CATEGORIES.find(([upper]) => aqi <= upper)?.[1] ?? 'Severe';
}

export class AirQualityAgent implements Agent<LocationProfile, AirAgentResult> {
  readonly id = 'air' as const;
  readonly name = 'Air Quality Agent';
  private readonly source: AirQualitySource;

  constructor(source: AirQualitySource) {
    this.source = source;
  }

  async run(location: LocationProfile, trace: AgentTrace): Promise<AirAgentResult> {
    trace.log(`Querying ${this.source.name} for nearest station`);
    const reading = await this.source.getLatest(location);
    trace.log(`Retrieved latest environmental data · ${reading.stationName}`);

    const measurements: Measurement[] = [];
    const findings: Finding[] = [];
    const warnings: string[] = [];
    let weighted = 0;
    let weightTotal = 0;

    for (const p of POLLUTANTS) {
      const value = reading[p.key];
      if (value === null || value < 0) {
        warnings.push(`${p.label} reading unavailable from ${reading.stationName}`);
        measurements.push({ key: p.key, label: p.label, value: null, unit: 'µg/m³', threshold: p.guideline, thresholdLabel: 'WHO guideline', subScore: null, status: 'missing' });
        continue;
      }
      const subScore = clamp(value / p.reference);
      weighted += p.weight * subScore;
      weightTotal += p.weight;
      const exceeds = value > p.guideline;
      measurements.push({
        key: p.key,
        label: p.label,
        value,
        unit: 'µg/m³',
        threshold: p.guideline,
        thresholdLabel: 'WHO guideline',
        subScore: roundHalfUp(subScore),
        status: subScore >= 0.7 ? 'critical' : exceeds ? 'elevated' : 'normal',
      });
      if (exceeds) {
        findings.push({
          code: `air.${p.key}`,
          label: p.finding,
          detail: `${formatNumber(value)} µg/m³ · ${(value / p.guideline).toFixed(1)}× WHO guideline`,
          impact: roundHalfUp(p.weight * subScore, 3),
        });
      }
    }

    if (weightTotal === 0) {
      throw new AppError('SENSOR_DATA_UNAVAILABLE', `${reading.stationName} returned no valid pollutant readings.`);
    }
    trace.log(`Normalized ${POLLUTANTS.length - warnings.length} pollutants against WHO guidelines`);

    const indices: Array<[number, string]> = [];
    if (reading.pm25 !== null) indices.push([subIndex('pm25', reading.pm25), 'PM2.5']);
    if (reading.pm10 !== null) indices.push([subIndex('pm10', reading.pm10), 'PM10']);
    const dominant = indices.length ? indices.reduce((best, item) => (item[0] > best[0] ? item : best)) : null;
    const aqi = dominant ? roundHalfUp(dominant[0], 0) : null;

    const anomalies: string[] = [];
    const baselineSeries = generateHistory(location, '24h')
      .slice(0, -1)
      .map((point) => point.pm25)
      .filter((value): value is number => value !== null);
    if (reading.pm25 !== null && baselineSeries.length) {
      const baseline = baselineSeries.reduce((sum, value) => sum + value, 0) / baselineSeries.length;
      const ratio = baseline ? reading.pm25 / baseline : 0;
      if (ratio >= ANOMALY_RATIO) anomalies.push(`PM2.5 is ${ratio.toFixed(1)}× its 24-hour baseline`);
    }
    trace.log(`Anomaly scan vs 24-h baseline · ${anomalies.length} flagged`);

    const score = roundHalfUp(weighted / weightTotal);
    const level = riskLevelFor(score);
    trace.log(`Risk assessment completed · ${level}`);

    return {
      agent: 'air',
      location: location.name,
      riskLevel: level,
      riskScore: score,
      confidence: roundHalfUp(clamp(BASE_CONFIDENCE - MISSING_PENALTY * warnings.length)),
      timestamp: reading.observedAt,
      dataSource: reading.provider,
      isMock: reading.isMock,
      measurements,
      findings: [...findings].sort((a, b) => b.impact - a.impact),
      warnings,
      stationId: reading.stationId,
      stationName: reading.stationName,
      pm25: reading.pm25,
      pm10: reading.pm10,
      no2: reading.no2,
      o3: reading.o3,
      aqi,
      aqiCategory: aqi === null ? null : aqiCategory(aqi),
      dominantPollutant: dominant ? dominant[1] : null,
      anomalies,
    };
  }
}
