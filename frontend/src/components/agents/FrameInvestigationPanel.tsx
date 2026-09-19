/**
 * The explainable-AI report for one clicked frame: WHERE / WHY / WHAT NEXT.
 *
 * The chain this panel exists to make visible:
 *
 *     IMAGE → DETECTION → EVIDENCE → EXPLANATION
 *
 * Clicking a box highlights its reason; clicking a reason highlights its boxes. That link is the
 * difference between "the model found 3 objects" and "here is the object, here is why it matters,
 * and here is what follows from it".
 *
 * Everything rendered comes from the backend, which derives it from what the detector actually
 * returned. When no model is configured the panel says so plainly rather than showing an empty
 * frame that reads like "nothing was found" — those are very different claims.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Clock, Crosshair, Info, ListChecks, MapPin, Sparkles, TrendingDown } from 'lucide-react';
import { useState } from 'react';
import { cn } from '../../lib/format';
import type { FrameInvestigation, InvestigationReason, ReasonType } from '../../types/agents';
import { DashboardCard } from '../ui/DashboardCard';
import { Chip } from '../ui/primitives';

/** How strongly the evidence backs a claim — surfaced on every reason, never implied. */
const REASON_STYLE: Record<ReasonType, { label: string; className: string }> = {
  OBSERVED: { label: 'Observed', className: 'text-risk-low border-risk-low/30 bg-risk-low/[0.08]' },
  INFERRED: { label: 'Inferred', className: 'text-info border-info/30 bg-info/[0.08]' },
  HYPOTHESIS: { label: 'Hypothesis', className: 'text-risk-moderate border-risk-moderate/30 bg-risk-moderate/[0.08]' },
  UNKNOWN: { label: 'Data gap', className: 'text-fg-subtle border-white/10 bg-white/[0.03]' },
};

const PRIORITY_STYLE: Record<string, string> = {
  high: 'text-risk-high',
  medium: 'text-risk-moderate',
  low: 'text-fg-muted',
};

function SectionTitle({ eyebrow, title, icon: Icon }: { eyebrow: string; title: string; icon: typeof MapPin }) {
  return (
    <div className="flex items-center gap-2.5">
      <Icon className="size-4 shrink-0 text-brand" />
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h3 className="text-base font-medium text-fg">{title}</h3>
      </div>
    </div>
  );
}

export function FrameInvestigationPanel({
  investigation,
  imageUrl,
}: {
  investigation: FrameInvestigation;
  imageUrl: string | null;
}) {
  const [activeDetection, setActiveDetection] = useState<string | null>(null);
  const { detections, reasons, actions, timeline, geotag } = investigation;

  /** Reasons that cite a given detection — the link from image back to explanation. */
  const reasonsFor = (detectionId: string): InvestigationReason[] =>
    reasons.filter((reason) => reason.evidenceIds.includes(detectionId));

  const active = detections.find((d) => d.detectionId === activeDetection) ?? null;

  return (
    <div className="space-y-4">
      {/* --- Explainable AI header: make the mode unmistakable. --- */}
      <DashboardCard bodyClassName="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <Sparkles className="mt-0.5 size-4 shrink-0 text-brand" />
            <div>
              <p className="eyebrow !text-brand">✦ Explainable AI report</p>
              <p className="mt-0.5 text-sm text-fg">
                Evidence-backed explanation of the detected environmental problem
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[10.5px] text-fg-subtle">
            {investigation.model && <Chip color="#8b93a7">{investigation.model}</Chip>}
            <span className="font-mono">{investigation.investigationId}</span>
          </div>
        </div>

        <p className="mt-3 text-xs leading-relaxed text-fg-muted">{investigation.summary}</p>

        {/* The provider's reasoning about THIS frame. Shown apart from the deterministic summary
            above, and labelled, because it explains the finding rather than establishing it. */}
        {investigation.llmReasoning && (
          <div className="mt-3 rounded-lg border border-brand/20 bg-brand/[0.04] px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-[10px] tracking-wide text-brand uppercase">
              <Sparkles className="size-3" /> AI reasoning
              {investigation.explanationProvider && (
                <span className="ml-1 font-mono text-fg-subtle normal-case">
                  via {investigation.explanationProvider}
                </span>
              )}
            </p>
            <p className="mt-1.5 text-xs leading-relaxed whitespace-pre-line text-fg-muted">
              {investigation.llmReasoning}
            </p>
            <p className="mt-1.5 text-[10px] text-fg-subtle">
              Written from the detections and evidence above. It did not change any detection,
              count, box or score.
            </p>
          </div>
        )}

        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[11px] text-fg-subtle">
          {investigation.capturedAt && (
            <span className="flex items-center gap-1.5">
              <Clock className="size-3" />
              {new Date(investigation.capturedAt).toLocaleString()}
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <MapPin className="size-3" />
            {geotag.available ? (
              <>
                <span className="tabular">
                  {geotag.latitude?.toFixed(4)}, {geotag.longitude?.toFixed(4)}
                </span>
                {geotag.accuracyMeters != null && <span>· ±{Math.round(geotag.accuracyMeters)} m</span>}
                {geotag.resolvedName && <span className="max-w-xs truncate">· {geotag.resolvedName}</span>}
              </>
            ) : (
              <span>{geotag.message ?? 'Location unavailable — investigation continued without geotagging.'}</span>
            )}
          </span>
        </div>
      </DashboardCard>

      {/* --- WHERE --- */}
      <DashboardCard bodyClassName="p-4 sm:p-5">
        <SectionTitle eyebrow="Where" title="Where is the pollution?" icon={Crosshair} />

        {!investigation.detectionsAvailable && (
          <p className="mt-3 flex items-start gap-2 rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-xs text-risk-moderate">
            <AlertTriangle className="mt-px size-3.5 shrink-0" />
            {/* "The model did not run" and "the model found nothing" are different claims. */}
            <span>
              {investigation.detectionStatus === 'ok'
                ? 'No visible pollution objects were detected in this frame. This does not rule out contamination an image cannot show.'
                : `Visual detection did not run, so nothing can be said about visible pollution in this frame. ${investigation.detectionMessage ?? ''}`}
            </span>
          </p>
        )}

        {imageUrl && (
          <div className="relative mt-3 overflow-hidden rounded-xl border border-white/10">
            <img src={imageUrl} alt="Investigated frame" className="block w-full" />
            {/* Boxes are positioned from the detector's own normalised coordinates. */}
            {detections.map((detection, index) => {
              const [x1, y1, x2, y2] = detection.bboxRelative;
              if (detection.bboxRelative.length !== 4) return null;
              const selected = activeDetection === detection.detectionId;
              return (
                <button
                  key={detection.detectionId}
                  type="button"
                  onClick={() => setActiveDetection(selected ? null : detection.detectionId)}
                  className={cn(
                    'absolute rounded-md border-2 transition',
                    selected ? 'border-brand bg-brand/20' : 'border-brand/60 hover:border-brand hover:bg-brand/10',
                  )}
                  style={{
                    left: `${x1 * 100}%`,
                    top: `${y1 * 100}%`,
                    width: `${(x2 - x1) * 100}%`,
                    height: `${(y2 - y1) * 100}%`,
                  }}
                >
                  <span className="absolute -top-5 left-0 rounded bg-brand px-1 py-0.5 text-[9px] font-medium whitespace-nowrap text-ink-950">
                    #{index + 1} {detection.className.replace(/_/g, ' ')}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {detections.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {detections.map((detection, index) => {
              const selected = activeDetection === detection.detectionId;
              return (
                <li key={detection.detectionId}>
                  <button
                    type="button"
                    onClick={() => setActiveDetection(selected ? null : detection.detectionId)}
                    className={cn(
                      'flex w-full items-baseline gap-3 rounded-lg border px-3 py-2 text-left text-xs transition',
                      selected ? 'border-brand/40 bg-brand/[0.07]' : 'border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.05]',
                    )}
                  >
                    <span className="font-mono text-[10px] text-fg-subtle">#{index + 1}</span>
                    <span className="min-w-0 flex-1">
                      <span className="text-fg capitalize">{detection.className.replace(/_/g, ' ')}</span>
                      {detection.imageRegion && (
                        <span className="text-fg-subtle"> · {detection.imageRegion} of frame</span>
                      )}
                      <span className="block font-mono text-[10px] text-fg-subtle">{detection.detectionId}</span>
                    </span>
                    <span className="shrink-0 text-fg-muted tabular">{Math.round(detection.confidence * 100)}%</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <AnimatePresence>
          {active && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="mt-3 rounded-lg border border-brand/25 bg-brand/[0.05] px-3 py-2.5">
                <p className="text-xs text-fg">
                  {active.className.replace(/_/g, ' ')} · {Math.round(active.confidence * 100)}% confidence
                </p>
                <p className="mt-0.5 text-[11px] text-fg-subtle">
                  {active.imageRegion ? `${active.imageRegion} of the frame` : 'Frame position unavailable'} ·{' '}
                  <span className="font-mono">{active.detectionId}</span>
                </p>
                {reasonsFor(active.detectionId).map((reason) => (
                  <p key={reason.reasonId} className="mt-1.5 text-[11px] text-fg-muted">
                    <span className="font-mono text-fg-subtle">{reason.reasonId}</span> — {reason.text}
                  </p>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <p className="mt-3 text-[10.5px] text-fg-subtle">
          Positions describe where an object sits <em>within the frame</em>, not its location on the
          ground. Geographic position, when available, is shown separately above.
        </p>
      </DashboardCard>

      {/* --- WHY --- */}
      {reasons.length > 0 && (
        <DashboardCard bodyClassName="p-4 sm:p-5">
          <SectionTitle eyebrow="Why" title="Why is this a concern?" icon={Info} />
          <p className="mt-1 text-[11px] text-fg-subtle">
            {reasons.length} evidence-supported reason{reasons.length === 1 ? '' : 's'} — not padded to a
            target count.
          </p>

          <ol className="mt-3 space-y-2">
            {reasons.map((reason) => {
              const style = REASON_STYLE[reason.type];
              const linked = reason.evidenceIds.some((id) => id === activeDetection);
              return (
                <li
                  key={reason.reasonId}
                  className={cn(
                    'rounded-lg border px-3 py-2.5 transition',
                    linked ? 'border-brand/40 bg-brand/[0.06]' : 'border-white/[0.06] bg-white/[0.02]',
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 text-xs text-fg">{reason.text}</p>
                    <span className={cn('shrink-0 rounded border px-1.5 py-0.5 text-[9.5px]', style.className)}>
                      {style.label}
                    </span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-fg-subtle">
                    <span className="font-mono">{reason.reasonId}</span>
                    {reason.evidenceIds.map((id) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setActiveDetection(id.startsWith('IMG-DET') ? id : null)}
                        className={cn(
                          'font-mono underline decoration-dotted underline-offset-2',
                          id.startsWith('IMG-DET') ? 'text-brand hover:text-brand-strong' : 'text-fg-subtle',
                        )}
                      >
                        {id}
                      </button>
                    ))}
                    {reason.source && <span>· {reason.source}</span>}
                    {reason.confidence != null && <span>· {Math.round(reason.confidence * 100)}%</span>}
                  </div>
                </li>
              );
            })}
          </ol>
        </DashboardCard>
      )}

      {/* --- WHAT NEXT --- */}
      {actions.length > 0 && (
        <DashboardCard bodyClassName="p-4 sm:p-5">
          <SectionTitle eyebrow="What next" title="What should be done?" icon={ListChecks} />
          <ol className="mt-3 space-y-2">
            {actions.map((action) => (
              <li key={action.actionId} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 text-xs text-fg">{action.action}</p>
                  <span className={cn('shrink-0 text-[10px] uppercase', PRIORITY_STYLE[action.priority])}>
                    {action.priority}
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-fg-subtle">Why: {action.rationale}</p>
                <p className="mt-0.5 text-[11px] text-fg-subtle">Expected effect: {action.expectedEffect}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 text-[10.5px] text-fg-subtle">
                  <span className="text-fg-muted">{action.timeframe}</span>
                  {action.evidenceIds.map((id) => (
                    <span key={id} className="font-mono">{id}</span>
                  ))}
                </div>
              </li>
            ))}
          </ol>
        </DashboardCard>
      )}

      {/* --- How this could get worse --- */}
      {investigation.escalationRisks.length > 0 && (
        <DashboardCard bodyClassName="p-4 sm:p-5">
          <SectionTitle eyebrow="If nothing is done" title="How this could get worse" icon={TrendingDown} />
          {/* Labelled as projections, not predictions: a single image cannot establish what
              happens next, and presenting these as forecasts would be exactly that claim. */}
          <p className="mt-1 text-[11px] text-fg-subtle">
            Conditional projections, not predictions — plausible developments if the observed waste
            stays in place.
          </p>
          <ol className="mt-3 space-y-2">
            {investigation.escalationRisks.map((risk) => (
              <li key={risk.riskId} className="rounded-lg border border-risk-moderate/20 bg-risk-moderate/[0.04] px-3 py-2.5">
                <p className="text-xs text-fg">{risk.text}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 text-[10.5px] text-fg-subtle">
                  <span className="font-mono">{risk.riskId}</span>
                  <span>{risk.horizon.replace('_', ' ')}</span>
                  {risk.evidenceIds.map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setActiveDetection(id.startsWith('IMG-DET') ? id : null)}
                      className="font-mono text-brand underline decoration-dotted underline-offset-2"
                    >
                      {id}
                    </button>
                  ))}
                </div>
              </li>
            ))}
          </ol>
        </DashboardCard>
      )}

      {/* --- Timeline --- */}
      <DashboardCard bodyClassName="p-4 sm:p-5">
        <SectionTitle eyebrow="Timeline" title="Estimated recovery timeline" icon={Clock} />
        <div className="mt-3 grid gap-2 sm:grid-cols-4">
          {[
            ['Immediate', timeline.immediate],
            ['Short term', timeline.shortTerm],
            ['Medium term', timeline.mediumTerm],
            ['Long term', timeline.longTerm],
          ].map(([label, range]) => (
            <div key={label} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
              <p className="text-[10.5px] tracking-wide text-fg-subtle uppercase">{label}</p>
              <p className="mt-0.5 text-xs text-fg tabular">{range}</p>
            </div>
          ))}
        </div>
        {/* The caveat is not fine print — it is the reason these are bands and not dates. */}
        <p className="mt-3 text-[11px] text-fg-subtle">{timeline.caveat}</p>
        {timeline.trendNote && (
          <p className="mt-1.5 flex items-start gap-1.5 text-[11px] text-risk-moderate">
            <Info className="mt-px size-3 shrink-0" />
            <span>{timeline.trendNote}</span>
          </p>
        )}
      </DashboardCard>
    </div>
  );
}
