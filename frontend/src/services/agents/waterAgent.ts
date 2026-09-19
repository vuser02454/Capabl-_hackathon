/**
 * Water Quality Agent
 *   Input:      sensor readings
 *   Processing: validation -> threshold analysis -> risk calculation
 *   Output:     WaterAgentResult
 */
import type { LocationProfile } from '../../data/locations';
import { clamp, formatNumber, riskLevelFor, roundHalfUp } from '../../lib/risk';
import type { Finding, Measurement, WaterAgentResult } from '../../types/agents';
import { AppError } from '../errors';
import type { WaterSensorSource } from '../providers/waterSensorSource';
import type { Agent, AgentTrace } from './agent';

type ParameterKey = 'ph' | 'turbidity' | 'temperature';

interface WaterParameter {
  key: ParameterKey;
  label: string;
  unit: string;
  weight: number;
  validRange: [number, number];
  threshold: number;
  thresholdLabel: string;
  subScore: (value: number) => number;
  exceeds: (value: number) => boolean;
}

const PARAMETERS: WaterParameter[] = [
  { key: 'ph', label: 'pH', unit: '', weight: 0.2, validRange: [0, 14], threshold: 6.5, thresholdLabel: 'BIS 6.5–8.5',
    subScore: (v) => clamp(Math.abs(v - 7) / 1.5), exceeds: (v) => v < 6.5 || v > 8.5 },
  { key: 'turbidity', label: 'Turbidity', unit: 'NTU', weight: 0.55, validRange: [0, 4000], threshold: 5, thresholdLabel: 'BIS permissible',
    subScore: (v) => clamp(v / 21), exceeds: (v) => v > 5 },
  { key: 'temperature', label: 'Temperature', unit: '°C', weight: 0.25, validRange: [-5, 60], threshold: 26, thresholdLabel: 'Thermal stress',
    subScore: (v) => clamp((v - 18) / 14), exceeds: (v) => v > 26 },
];

const BASE_CONFIDENCE = 0.85;
const MISSING_PENALTY = 0.2;

function describe(key: ParameterKey, value: number): [string, string] {
  if (key === 'ph') {
    return [value < 6.5 ? 'Acidic water pH' : 'Alkaline water pH', `pH ${formatNumber(value)} · outside BIS range 6.5–8.5`];
  }
  if (key === 'turbidity') {
    return ['Increased water turbidity', `${formatNumber(value)} NTU · ${(value / 5).toFixed(1)}× BIS permissible limit`];
  }
  return ['Elevated water temperature', `${formatNumber(value)} °C · reduces dissolved oxygen`];
}

export class WaterQualityAgent implements Agent<LocationProfile, WaterAgentResult> {
  readonly id = 'water' as const;
  readonly name = 'Water Quality Agent';
  private readonly source: WaterSensorSource;

  constructor(source: WaterSensorSource) {
    this.source = source;
  }

  async run(location: LocationProfile, trace: AgentTrace): Promise<WaterAgentResult> {
    const reading = await this.source.getLatest(location);
    trace.log(`Processed sensor readings · ${reading.sensorName} (${reading.sensorId})`);

    const measurements: Measurement[] = [];
    const findings: Finding[] = [];
    const warnings: string[] = [];
    let weighted = 0;
    let weightTotal = 0;

    for (const p of PARAMETERS) {
      let value = reading[p.key];
      const [low, high] = p.validRange;
      if (value !== null && !(value >= low && value <= high)) {
        warnings.push(`Rejected out-of-range ${p.label} reading (${formatNumber(value)})`);
        value = null;
      } else if (value === null) {
        warnings.push(`${p.label} reading missing from sensor ${reading.sensorId}`);
      }

      if (value === null) {
        measurements.push({ key: p.key, label: p.label, value: null, unit: p.unit, threshold: p.threshold, thresholdLabel: p.thresholdLabel, subScore: null, status: 'missing' });
        continue;
      }

      const subScore = p.subScore(value);
      weighted += p.weight * subScore;
      weightTotal += p.weight;
      const exceeds = p.exceeds(value);
      measurements.push({
        key: p.key,
        label: p.label,
        value,
        unit: p.unit,
        threshold: p.threshold,
        thresholdLabel: p.thresholdLabel,
        subScore: roundHalfUp(subScore),
        status: subScore >= 0.7 ? 'critical' : exceeds ? 'elevated' : 'normal',
      });
      if (exceeds) {
        const [label, detail] = describe(p.key, value);
        findings.push({ code: `water.${p.key}`, label, detail, impact: roundHalfUp(p.weight * subScore, 3) });
      }
    }

    const valid = PARAMETERS.length - warnings.length;
    if (valid === 0) {
      throw new AppError('SENSOR_DATA_UNAVAILABLE', `Sensor ${reading.sensorId} returned no usable readings.`);
    }
    trace.log(`Validated ${valid}/${PARAMETERS.length} readings${warnings.length ? ` · ${warnings.length} missing` : ''}`);
    trace.log('Threshold analysis against BIS 10500 limits');

    const score = roundHalfUp(weighted / weightTotal);
    const level = riskLevelFor(score);
    trace.log(`Risk assessment completed · ${level}`);

    return {
      agent: 'water',
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
      sensorId: reading.sensorId,
      sensorName: reading.sensorName,
      sensorStatus: warnings.length ? 'degraded' : reading.status,
      ph: reading.ph,
      turbidity: reading.turbidity,
      temperature: reading.temperature,
    };
  }
}
