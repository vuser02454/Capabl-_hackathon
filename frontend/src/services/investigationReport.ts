/**
 * The detailed report for one frame investigation.
 *
 * Everything in it comes from the investigation the backend produced. The report writer adds no
 * findings of its own — it formats what was decided, and where something is missing it says so
 * rather than leaving a gap the reader fills in optimistically.
 *
 * The geotag is written as place, time and date because that is what makes a report actionable to
 * whoever receives it. When location was denied the report says so plainly, so a reader never
 * assumes the coordinates were simply omitted for brevity.
 */
import type { FrameInvestigation } from '../types/agents';

const RULE = '='.repeat(72);
const THIN = '-'.repeat(72);

function formatWhen(iso: string | null): { date: string; time: string } {
  if (!iso) return { date: 'not recorded', time: 'not recorded' };
  const when = new Date(iso);
  return {
    date: when.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }),
    time: when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
  };
}

function locationBlock(investigation: FrameInvestigation): string[] {
  const { geotag } = investigation;
  const { date, time } = formatWhen(geotag.capturedAt ?? investigation.capturedAt);

  if (!geotag.available) {
    return [
      'LOCATION',
      '  Place       : not recorded',
      `  Date        : ${date}`,
      `  Time        : ${time}`,
      '',
      '  Location was unavailable when this frame was investigated, so no coordinates are',
      '  attached. The visual findings below are unaffected; only the geographic reference is',
      '  missing. Coordinates are never inferred.',
    ];
  }
  return [
    'LOCATION',
    `  Place       : ${geotag.resolvedName ?? 'name unresolved'}`,
    `  Coordinates : ${geotag.latitude?.toFixed(6)}, ${geotag.longitude?.toFixed(6)}`,
    `  GPS accuracy: ${geotag.accuracyMeters != null ? `±${Math.round(geotag.accuracyMeters)} m` : 'not reported'}`,
    `  Source      : ${geotag.source ?? 'unknown'}`,
    `  Date        : ${date}`,
    `  Time        : ${time}`,
  ];
}

export function buildInvestigationReport(investigation: FrameInvestigation): string {
  const lines: string[] = [];
  const { date, time } = formatWhen(investigation.capturedAt);

  lines.push(RULE);
  lines.push('ECOSENTINEL AI - WATER POLLUTION INVESTIGATION REPORT');
  lines.push(RULE);
  lines.push(`Investigation ID : ${investigation.investigationId}`);
  lines.push(`Generated        : ${date} ${time}`);
  lines.push(`Detector         : ${investigation.model ?? 'not reported'}`);
  lines.push(
    `Frame            : ${
      investigation.imageWidth && investigation.imageHeight
        ? `${investigation.imageWidth} x ${investigation.imageHeight} px`
        : 'dimensions not reported'
    }`,
  );
  lines.push('');

  lines.push('SUMMARY');
  lines.push(`  ${investigation.summary}`);
  lines.push('');

  lines.push(...locationBlock(investigation));
  lines.push('');

  // Stating what kinds of evidence exist stops a reader assuming measurements were taken.
  lines.push('EVIDENCE AVAILABLE');
  lines.push(`  Visual detection   : ${investigation.dataAvailability.visual ? 'yes' : 'no'}`);
  lines.push(`  Water measurements : ${investigation.dataAvailability.waterMeasurements ? 'yes' : 'no'}`);
  if (investigation.dataAvailability.detail) lines.push(`  ${investigation.dataAvailability.detail}`);
  lines.push('');

  lines.push(THIN);
  lines.push('WHERE - DETECTED OBJECTS');
  lines.push(THIN);
  if (investigation.detections.length === 0) {
    lines.push(`  ${investigation.detectionMessage ?? 'No objects were detected in this frame.'}`);
  } else {
    for (const detection of investigation.detections) {
      lines.push(
        `  ${detection.detectionId}  ${detection.className}  ${Math.round(detection.confidence * 100)}% confidence`,
      );
      lines.push(`      Position in frame : ${detection.imageRegion ?? 'unknown (frame size not reported)'}`);
      lines.push(`      Bounding box (px) : [${detection.bbox.map((v) => Math.round(v)).join(', ')}]`);
    }
    lines.push('');
    lines.push('  Positions describe where an object sits within the image, not its location on');
    lines.push('  the ground.');
  }
  lines.push('');

  lines.push(THIN);
  lines.push('WHY THIS IS A CONCERN');
  lines.push(THIN);
  if (investigation.reasons.length === 0) {
    lines.push('  No evidence-supported reasons were produced for this frame.');
  } else {
    lines.push(`  ${investigation.reasons.length} evidence-supported reason(s). Not padded to a target count.`);
    lines.push('');
    for (const reason of investigation.reasons) {
      lines.push(`  ${reason.reasonId} [${reason.type}]`);
      lines.push(`      ${reason.text}`);
      lines.push(`      Evidence: ${reason.evidenceIds.join(', ') || 'none'}`);
      if (reason.source) lines.push(`      Source  : ${reason.source}`);
      if (reason.confidence != null) lines.push(`      Confidence: ${Math.round(reason.confidence * 100)}%`);
    }
  }
  lines.push('');

  lines.push(THIN);
  lines.push('HOW THIS COULD GET WORSE');
  lines.push(THIN);
  if (investigation.escalationRisks.length === 0) {
    lines.push('  No escalation projections: no pollution-relevant objects were detected.');
  } else {
    // Labelled as projections so nothing here reads as a prediction of what will happen.
    lines.push('  Conditional projections, not predictions. A single image cannot establish what');
    lines.push('  will happen next; these describe plausible developments if nothing is done.');
    lines.push('');
    for (const risk of investigation.escalationRisks) {
      lines.push(`  ${risk.riskId} (${risk.horizon.replace('_', ' ')})`);
      lines.push(`      ${risk.text}`);
      lines.push(`      Evidence: ${risk.evidenceIds.join(', ') || 'none'}`);
    }
  }
  lines.push('');

  lines.push(THIN);
  lines.push('WHAT SHOULD BE DONE');
  lines.push(THIN);
  if (investigation.actions.length === 0) {
    lines.push('  No actions recommended: nothing pollution-relevant was detected to act on.');
  } else {
    for (const action of investigation.actions) {
      lines.push(`  ${action.actionId} [${action.priority.toUpperCase()}] ${action.action}`);
      lines.push(`      Why            : ${action.rationale}`);
      lines.push(`      Expected effect: ${action.expectedEffect}`);
      lines.push(`      Timeframe      : ${action.timeframe}`);
      lines.push(`      Evidence       : ${action.evidenceIds.join(', ') || 'none'}`);
    }
  }
  lines.push('');

  lines.push(THIN);
  lines.push('ESTIMATED PLANNING TIMELINE');
  lines.push(THIN);
  lines.push(`  Immediate   : ${investigation.timeline.immediate}`);
  lines.push(`  Short term  : ${investigation.timeline.shortTerm}`);
  lines.push(`  Medium term : ${investigation.timeline.mediumTerm}`);
  lines.push(`  Long term   : ${investigation.timeline.longTerm}`);
  lines.push('');
  lines.push(`  ${investigation.timeline.caveat}`);
  if (investigation.timeline.trendNote) lines.push(`  ${investigation.timeline.trendNote}`);
  lines.push('');

  lines.push(RULE);
  lines.push('LIMITS OF THIS REPORT');
  lines.push(RULE);
  // The reader is most likely to over-read a report that looks authoritative, so the limits are
  // stated at full width rather than as a footnote.
  lines.push('  This investigation is based on visual object detection in a single image.');
  lines.push('  An image can show visible pollution. It cannot establish chemical or');
  lines.push('  microbiological contamination, pollutant concentrations, toxicity, the source of');
  lines.push('  any pollution, or a long-term trend. Object classes are reported exactly as the');
  lines.push('  detector returned them and are never remapped.');
  if (!investigation.dataAvailability.waterMeasurements) {
    lines.push('');
    lines.push('  No water-quality measurements accompany this frame.');
  }
  lines.push('');

  return lines.join('\n');
}

export function investigationReportFilename(investigation: FrameInvestigation): string {
  const stamp = (investigation.capturedAt ?? new Date().toISOString()).slice(0, 19).replace(/[:T]/g, '-');
  return `ecosentinel-investigation-${investigation.investigationId}-${stamp}.txt`;
}
