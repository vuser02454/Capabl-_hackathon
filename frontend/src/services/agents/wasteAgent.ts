/**
 * Waste Detection Agent
 *   Input:      image / camera frame
 *   Processing: object detection -> waste classification -> density estimation
 *   Output:     WasteAgentResult
 */
import type { LocationProfile } from '../../data/locations';
import { clamp, riskLevelFor, roundHalfUp } from '../../lib/risk';
import type { Finding, Measurement, WasteAgentResult } from '../../types/agents';
import type { ImageInput, WasteDetectionSource } from '../providers/wasteDetectionSource';
import type { Agent, AgentTrace } from './agent';

const COUNT_REFERENCE = 24;
const PLASTIC_SHARE_REFERENCE = 0.65;
const COUNT_WEIGHT = 0.7;
const PLASTIC_WEIGHT = 0.3;

export interface WasteAgentInput {
  location: LocationProfile;
  image?: ImageInput;
}

export class WasteDetectionAgent implements Agent<WasteAgentInput, WasteAgentResult> {
  readonly id = 'waste' as const;
  readonly name = 'Waste Detection Agent';
  private readonly detector: WasteDetectionSource;

  constructor(detector: WasteDetectionSource) {
    this.detector = detector;
  }

  async run({ location, image }: WasteAgentInput, trace: AgentTrace): Promise<WasteAgentResult> {
    let output;
    if (image) {
      trace.log(`Received uploaded image · ${image.name}`);
      output = await this.detector.detectImage(image, location);
    } else {
      output = await this.detector.detectCameraFrame(location);
      trace.log(`Analyzed environmental image · ${output.sourceName} (${output.sourceId})`);
    }

    const { detections } = output;
    const counts = {
      plastic: detections.filter((d) => d.category === 'plastic').length,
      paper: detections.filter((d) => d.category === 'paper').length,
      other: detections.filter((d) => d.category === 'other').length,
    };
    const total = detections.length;
    trace.log(`${total} objects detected · ${output.model}`);
    trace.log(`Classified waste · plastic ${counts.plastic} · paper ${counts.paper} · other ${counts.other}`);

    const countScore = clamp(total / COUNT_REFERENCE);
    const plasticShare = total ? counts.plastic / total : 0;
    const plasticScore = clamp(plasticShare / PLASTIC_SHARE_REFERENCE);
    const densityIndex = roundHalfUp(total / COUNT_REFERENCE);
    trace.log(`Estimated litter density index · ${densityIndex.toFixed(2)}`);

    const findings: Finding[] = [];
    if (total >= 15) {
      findings.push({ code: 'waste.density', label: 'High litter concentration', detail: `${total} objects in frame · density index ${densityIndex.toFixed(2)}`, impact: roundHalfUp(COUNT_WEIGHT * countScore, 3) });
    } else if (total >= 8) {
      findings.push({ code: 'waste.density', label: 'Moderate litter accumulation', detail: `${total} objects in frame · density index ${densityIndex.toFixed(2)}`, impact: roundHalfUp(COUNT_WEIGHT * countScore, 3) });
    }
    if (total && plasticShare >= 0.5 && counts.plastic >= 3) {
      findings.push({ code: 'waste.plastic', label: 'Plastic-dominant waste', detail: `${counts.plastic} of ${total} objects (${(plasticShare * 100).toFixed(0)}%) are plastic`, impact: roundHalfUp(PLASTIC_WEIGHT * plasticScore, 3) });
    }

    const score = roundHalfUp(COUNT_WEIGHT * countScore + PLASTIC_WEIGHT * plasticScore);
    const level = riskLevelFor(score);
    trace.log(`Risk assessment completed · ${level}`);

    const measurements: Measurement[] = [
      { key: 'total', label: 'Detected objects', value: total, unit: '', threshold: 15, thresholdLabel: 'High density', subScore: roundHalfUp(countScore), status: total >= 15 ? 'critical' : total >= 8 ? 'elevated' : 'normal' },
      { key: 'plastic', label: 'Plastic', value: counts.plastic, unit: '', threshold: null, thresholdLabel: null, subScore: null, status: 'normal' },
      { key: 'paper', label: 'Paper', value: counts.paper, unit: '', threshold: null, thresholdLabel: null, subScore: null, status: 'normal' },
      { key: 'other', label: 'Other', value: counts.other, unit: '', threshold: null, thresholdLabel: null, subScore: null, status: 'normal' },
      { key: 'density', label: 'Density index', value: densityIndex, unit: '', threshold: 0.62, thresholdLabel: 'High density', subScore: null, status: 'normal' },
    ];

    return {
      agent: 'waste',
      location: location.name,
      riskLevel: level,
      riskScore: score,
      confidence: total ? roundHalfUp(detections.reduce((sum, d) => sum + d.confidence, 0) / total) : 0.9,
      timestamp: new Date().toISOString(),
      dataSource: this.detector.name,
      isMock: output.isMock,
      measurements,
      findings: [...findings].sort((a, b) => b.impact - a.impact),
      warnings: total ? [] : ['No waste objects detected in the image.'],
      sourceId: output.sourceId,
      sourceName: output.sourceName,
      inputType: output.inputType,
      model: output.model,
      totalObjects: total,
      counts,
      densityIndex,
      detections,
    };
  }
}
