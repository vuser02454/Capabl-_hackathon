/**
 * Coordinator Agent
 *   Input:      AirAgentResult + WaterAgentResult + WasteAgentResult (any may be missing)
 *   Processing: cross-signal reasoning -> risk aggregation -> priority identification
 *   Output:     CoordinatorResult
 *
 * It only ever sees specialist reports, never raw sensor/provider data.
 */
import { clamp, formatNumber, joinAnd, riskLevelFor, roundHalfUp } from '../../lib/risk';
import type {
  ContributingFactor,
  CoordinatorInput,
  CoordinatorResult,
  Recommendation,
  RiskLevel,
  SignalContribution,
  SpecialistAgentId,
  SpecialistResult,
} from '../../types/agents';
import { AppError } from '../errors';
import type { Agent, AgentTrace } from './agent';

export const COORDINATOR_WEIGHTS: Record<SpecialistAgentId, number> = { air: 0.38, water: 0.27, waste: 0.35 };
const CORRELATION_BOOST = 0.03;
const MISSING_CONFIDENCE_PENALTY = 0.1;
const MAX_FACTORS = 3;
const ORDER: SpecialistAgentId[] = ['air', 'water', 'waste'];

const HIGH_PHRASE: Record<SpecialistAgentId, string> = { air: 'air pollution', water: 'water-quality degradation', waste: 'litter density' };
const MODERATE_PHRASE: Record<SpecialistAgentId, string> = {
  air: 'air quality shows moderate deterioration',
  water: 'water-quality indicators show moderate degradation',
  waste: 'litter levels are moderately elevated',
};
const LOW_PHRASE: Record<SpecialistAgentId, string> = {
  air: 'air quality remains within acceptable limits',
  water: 'water-quality indicators remain within acceptable limits',
  waste: 'litter levels remain low',
};

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

type Candidate = [number, Omit<Recommendation, 'priority' | 'urgency'>];

export class CoordinatorAgent implements Agent<CoordinatorInput, CoordinatorResult> {
  readonly id = 'coordinator' as const;
  readonly name = 'Coordinator Agent';

  async run(input: CoordinatorInput, trace: AgentTrace): Promise<CoordinatorResult> {
    const reports = ORDER.map((id) => [id, input[id]] as const).filter(
      (entry): entry is readonly [SpecialistAgentId, SpecialistResult] => entry[1] !== null,
    );
    if (!reports.length) throw new AppError('ANALYSIS_FAILED', 'Coordinator received no specialist reports to assess.');
    const missing = ORDER.filter((id) => input[id] === null);
    trace.log(`Received reports from ${reports.length} specialist agent${reports.length !== 1 ? 's' : ''}`);

    const weightTotal = reports.reduce((sum, [id]) => sum + COORDINATOR_WEIGHTS[id], 0);
    const contributions: SignalContribution[] = reports
      .map(([id, report]) => ({
        agent: id,
        riskLevel: report.riskLevel,
        riskScore: report.riskScore,
        weight: roundHalfUp(COORDINATOR_WEIGHTS[id] / weightTotal, 3),
        contribution: roundHalfUp((COORDINATOR_WEIGHTS[id] / weightTotal) * report.riskScore, 3),
      }))
      .sort((a, b) => b.contribution - a.contribution);
    const baseScore = reports.reduce((sum, [id, report]) => sum + (COORDINATOR_WEIGHTS[id] / weightTotal) * report.riskScore, 0);

    trace.log('Performing cross-signal reasoning...');
    const levelOf = (id: SpecialistAgentId): RiskLevel | undefined => input[id]?.riskLevel;
    const highs = ORDER.filter((id) => levelOf(id) === 'HIGH');
    const moderates = ORDER.filter((id) => levelOf(id) === 'MODERATE');
    const lows = ORDER.filter((id) => levelOf(id) === 'LOW');

    const adjustment = highs.length >= 2 ? CORRELATION_BOOST * (highs.length - 1) : 0;
    const overall = roundHalfUp(clamp(baseScore + adjustment));
    const overallLevel = riskLevelFor(overall);

    const insights = this.insights(input, highs, adjustment, missing);
    const rawConfidence = reports.reduce((sum, [id, report]) => sum + (COORDINATOR_WEIGHTS[id] / weightTotal) * report.confidence, 0);
    const confidence = roundHalfUp(clamp(rawConfidence - MISSING_CONFIDENCE_PENALTY * missing.length));
    trace.log(`Risk aggregation · ${(overall * 100).toFixed(0)}% overall (${overallLevel})`);

    const factors: ContributingFactor[] = [];
    for (const c of contributions) {
      const report = input[c.agent];
      if (report && report.findings.length && report.riskLevel !== 'LOW') {
        factors.push({ agent: c.agent, label: report.findings[0].label, detail: report.findings[0].detail });
      }
    }

    const recommendations = this.recommendations(input, overall, overallLevel);
    trace.log(`Identified ${recommendations.length} prioritized actions`);
    trace.log('Environmental risk assessment completed');

    return {
      agent: 'coordinator',
      location: input.location,
      overallRiskLevel: overallLevel,
      overallScore: overall,
      confidence,
      reasoning: this.reasoning(overallLevel, highs, moderates, lows, missing),
      crossSignalInsights: insights,
      contributingFactors: factors.slice(0, MAX_FACTORS),
      contributions,
      crossSignalAdjustment: roundHalfUp(adjustment, 3),
      dominantAgents: highs.length ? highs : moderates.length ? [contributions[0].agent] : [],
      inputsReceived: reports.map(([id]) => id),
      missingInputs: missing,
      recommendations,
      timestamp: new Date().toISOString(),
    };
  }

  private reasoning(level: RiskLevel, highs: SpecialistAgentId[], moderates: SpecialistAgentId[], lows: SpecialistAgentId[], missing: SpecialistAgentId[]): string {
    const elevated = highs.length + moderates.length;
    const opening =
      level === 'HIGH'
        ? elevated >= 2
          ? 'Multiple environmental indicators show elevated risk.'
          : 'A single dominant indicator is driving elevated environmental risk.'
        : level === 'MODERATE'
          ? 'Environmental indicators show moderate overall risk.'
          : 'Environmental indicators are largely within acceptable ranges.';

    let body: string;
    if (highs.length) {
      const verb = highs.length > 1 ? 'are the dominant risk factors' : 'is the dominant risk factor';
      const tail = moderates.length ? moderates.map((id) => MODERATE_PHRASE[id]) : lows.map((id) => LOW_PHRASE[id]);
      body = `${capitalise(joinAnd(highs.map((id) => HIGH_PHRASE[id])))} ${verb}${tail.length ? `, while ${joinAnd(tail)}.` : '.'}`;
    } else if (moderates.length) {
      const verb = moderates.length > 1 ? 'are the main concerns' : 'is the main concern';
      const tail = lows.map((id) => LOW_PHRASE[id]);
      body = `${capitalise(joinAnd(moderates.map((id) => HIGH_PHRASE[id])))} ${verb}${tail.length ? `, while ${joinAnd(tail)}.` : '.'}`;
    } else {
      body = 'No specialist agent reported indicators above guideline thresholds.';
    }

    let text = `${opening} ${body}`;
    if (missing.length) text += ` The ${joinAnd(missing)} assessment is unavailable, so confidence is reduced.`;
    return text;
  }

  private insights(input: CoordinatorInput, highs: SpecialistAgentId[], adjustment: number, missing: SpecialistAgentId[]): string[] {
    const insights: string[] = [];
    const { air, water, waste } = input;
    if (adjustment > 0) {
      insights.push(`Correlated high-risk signals from the ${joinAnd(highs)} agents add ${(adjustment * 100).toFixed(0)} points to the aggregate score.`);
    }
    if (waste && water && waste.riskLevel !== 'LOW' && water.turbidity !== null && water.turbidity > 5) {
      insights.push('Litter density alongside elevated turbidity suggests surface runoff may be carrying waste into the nearby water body.');
    }
    if (air && waste && air.riskLevel === 'HIGH' && waste.counts.plastic >= 8) {
      insights.push('High PM2.5 near a plastic-heavy litter zone warrants a check for open waste burning.');
    }
    if (water && water.sensorStatus === 'degraded') {
      insights.push('Water assessment relies on partial sensor data; one or more probes are not reporting.');
    }
    if (missing.length) {
      insights.push(`No report received from the ${joinAnd(missing)} agent; its weight was redistributed.`);
    }
    return insights;
  }

  private recommendations(input: CoordinatorInput, overall: number, overallLevel: RiskLevel): Recommendation[] {
    const { air, water, waste } = input;
    const candidates: Candidate[] = [];

    if (waste && waste.riskLevel !== 'LOW') {
      candidates.push([waste.riskScore, {
        id: 'inspect-waste', title: 'Inspect waste accumulation zone', agent: 'waste', actionLabel: 'Dispatch crew',
        explanation: `${waste.totalObjects} objects detected at ${waste.sourceName}, ${waste.counts.plastic} of them plastic. Dispatch a sanitation crew and trace the source.`,
      }]);
    }

    if (water && water.sensorStatus === 'degraded') {
      candidates.push([Math.max(water.riskScore, 0.5) * 0.95, {
        id: 'restore-sensor', title: 'Restore water sensor telemetry', agent: 'water', actionLabel: 'Open ticket',
        explanation: `${water.sensorName} is reporting partial data. Inspect probes and connectivity on ${water.sensorId}.`,
      }]);
    } else if (water && water.riskLevel !== 'LOW') {
      const turbidity = water.turbidity !== null && water.turbidity > 5
        ? `Turbidity at ${formatNumber(water.turbidity)} NTU exceeds the 5 NTU permissible limit`
        : 'Water indicators are drifting from safe ranges';
      candidates.push([water.riskScore * 0.95, {
        id: 'investigate-water', title: 'Investigate nearby water source', agent: 'water', actionLabel: 'Schedule sampling',
        explanation: `${turbidity} at ${water.sensorName}. Collect a grab sample for lab validation.`,
      }]);
    }

    if (overallLevel !== 'LOW') {
      candidates.push([overall * 0.7, {
        id: 'increase-monitoring', title: 'Increase environmental monitoring frequency', agent: 'all', actionLabel: 'Update cadence',
        explanation: 'Raise sampling cadence from 60 to 15 minutes across all agents for the next 24 hours to confirm the trend.',
      }]);
    }

    if (air && air.riskLevel === 'HIGH') {
      const pm = air.pm25 !== null
        ? `PM2.5 at ${formatNumber(air.pm25)} µg/m³ is ${(air.pm25 / 15).toFixed(1)}× the WHO guideline`
        : 'Air pollution is at a high-risk level';
      candidates.push([air.riskScore * 0.65, {
        id: 'air-advisory', title: 'Issue air-quality health advisory', agent: 'air', actionLabel: 'Draft advisory',
        explanation: `${pm}. Notify sensitive groups near ${air.stationName} and review traffic controls.`,
      }]);
    } else if (air && air.riskLevel === 'MODERATE') {
      candidates.push([air.riskScore * 0.6, {
        id: 'air-watch', title: 'Monitor air-quality trend', agent: 'air', actionLabel: 'Set alert',
        explanation: `Air quality at ${air.stationName} is moderate. Watch for sustained increases over the next 12 hours.`,
      }]);
    }

    if (!candidates.length) {
      candidates.push([0.1, {
        id: 'routine', title: 'Maintain routine monitoring', agent: 'all', actionLabel: 'Acknowledge',
        explanation: 'All indicators are within acceptable limits. Continue the standard sampling schedule.',
      }]);
    }

    return [...candidates]
      .sort((a, b) => b[0] - a[0])
      .map(([score, data], index) => ({
        ...data,
        priority: index + 1,
        urgency: index === 0 && score >= 0.6 ? 'Immediate' : score >= 0.45 ? 'Within 24h' : 'Routine',
      }));
  }
}
