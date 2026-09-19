/**
 * The environmental decision, and the reasoning behind it.
 *
 * The panel's job is to make the chain visible rather than hand down a verdict:
 *
 *     evidence -> problem -> priority -> decision
 *
 * so a reader can follow why this concern was chosen over the others, and can see the evidence
 * that contradicts it as readily as the evidence that supports it. Everything rendered here is
 * computed deterministically by the backend (backend/core/decision.py); the optional LLM prose
 * is shown separately and clearly labelled, because it explains the decision rather than making it.
 */
import { AnimatePresence, motion } from 'framer-motion';
import {
  Activity,
  AlertTriangle,
  ChevronDown,
  FlaskConical,
  Info,
  ScanSearch,
  Scale,
  Sparkles,
} from 'lucide-react';
import { useState } from 'react';
import { cn } from '../../lib/format';
import type {
  EnvironmentalDecision,
  EnvironmentalProblem,
  OverallDirection,
} from '../../types/agents';
import { DashboardCard } from '../ui/DashboardCard';
import { Chip } from '../ui/primitives';

const RISK_COLOR: Record<string, string> = {
  LOW: 'text-risk-low',
  MODERATE: 'text-risk-moderate',
  HIGH: 'text-risk-high',
};

/** Deliberately explicit: "insufficient history" is a real answer, not a missing value. */
const DIRECTION_LABEL: Record<OverallDirection, string> = {
  improving: 'Improving',
  deteriorating: 'Deteriorating',
  mixed: 'Mixed signals',
  stable: 'Stable',
  insufficient_history: 'No trend — insufficient history',
};

/** What the system is willing to claim about cause. */
const CAUSAL_LABEL: Record<string, string> = {
  observed: 'Directly observed',
  supported_hypothesis: 'Hypothesis — cause not established',
  unconfirmed: 'Unconfirmed',
};

type Tab = 'why' | 'evidence' | 'plan';

function ProblemRow({ problem, primary }: { problem: EnvironmentalProblem; primary?: boolean }) {
  return (
    <div className={cn('rounded-lg border px-3 py-2', primary ? 'border-brand/30 bg-brand/[0.06]' : 'border-black/[0.06] bg-black/[0.02]')}>
      <div className="flex items-baseline justify-between gap-3">
        <span className={cn('text-sm', primary ? 'font-medium text-fg' : 'text-fg-muted')}>{problem.title}</span>
        <span className={cn('shrink-0 text-[11px] font-medium', RISK_COLOR[problem.severity])}>{problem.severity}</span>
      </div>
      <p className="mt-1 text-[11px] text-fg-subtle">{problem.description}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-fg-subtle tabular">
        <span>Confidence {Math.round(problem.confidence * 100)}%</span>
        <span>Priority {problem.priority.toFixed(3)}</span>
        <span>{problem.evidenceIds.length} evidence item{problem.evidenceIds.length === 1 ? '' : 's'}</span>
        <span className={problem.causalStatus === 'observed' ? '' : 'text-risk-moderate'}>
          {CAUSAL_LABEL[problem.causalStatus]}
        </span>
      </div>
    </div>
  );
}

export function DecisionPanel({ decision, className }: { decision: EnvironmentalDecision | null; className?: string }) {
  const [tab, setTab] = useState<Tab>('why');
  const [open, setOpen] = useState(false);

  if (!decision) return null;

  const { primaryProblem: primary } = decision;

  return (
    <DashboardCard className={className} bodyClassName="p-4 sm:p-5">
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="eyebrow">Environmental decision</p>
            <h3 className="mt-1 text-lg font-medium text-fg">
              {primary ? primary.title : 'No primary concern identified'}
            </h3>
          </div>
          {decision.dataStatus === 'demo' && <Chip color="#8b93a7">Demo data</Chip>}
        </div>

        {/* Not enough evidence is a legitimate outcome, stated plainly rather than dressed up. */}
        {!decision.sufficientEvidence && (
          <p className="flex items-start gap-2 rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-xs text-risk-moderate">
            <AlertTriangle className="mt-px size-3.5 shrink-0" />
            <span>
              The available evidence is not sufficient to identify a primary concern. The investigation
              plan below lists what would resolve it.
            </span>
          </p>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <p className="eyebrow">Risk level</p>
            <p className={cn('mt-0.5 text-sm font-medium', RISK_COLOR[decision.riskLevel])}>
              {decision.riskLevel} · {Math.round(decision.riskScore * 100)}%
            </p>
          </div>
          <div>
            <p className="eyebrow">Confidence</p>
            <p className="mt-0.5 text-sm text-fg tabular">{Math.round(decision.confidence * 100)}%</p>
          </div>
          <div>
            <p className="eyebrow">Direction</p>
            <p className="mt-0.5 text-sm text-fg">{DIRECTION_LABEL[decision.overallDirection]}</p>
          </div>
          <div>
            <p className="eyebrow">Evidence</p>
            <p className="mt-0.5 text-sm text-fg tabular">{decision.evidence.length} items</p>
          </div>
        </div>

        <p className="text-xs leading-relaxed text-fg-muted">{decision.explanation}</p>

        {primary && <ProblemRow problem={primary} primary />}
        {decision.secondaryProblems.length > 0 && (
          <div className="space-y-2">
            <p className="eyebrow">Secondary concerns</p>
            {decision.secondaryProblems.map((problem) => (
              <ProblemRow key={problem.problemId} problem={problem} />
            ))}
          </div>
        )}

        {/* Contradictions get the same prominence as support — a mixed picture stays mixed. */}
        {decision.conflicts.length > 0 && (
          <div className="space-y-1.5">
            <p className="eyebrow flex items-center gap-1.5">
              <Scale className="size-3" /> Contradictory evidence
            </p>
            {decision.conflicts.map((conflict) => (
              <p key={conflict.conflictId} className="text-[11px] text-risk-moderate">{conflict.detail}</p>
            ))}
          </div>
        )}

        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className="flex w-full items-center justify-between rounded-lg border border-black/[0.08] bg-black/[0.03] px-3 py-2 text-xs text-fg-muted transition hover:bg-black/[0.06]"
        >
          <span className="flex items-center gap-2">
            <ScanSearch className="size-3.5" /> Why this decision?
          </span>
          <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
        </button>

        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="space-y-3 pt-1">
                <div className="flex gap-1 rounded-lg border border-black/[0.06] bg-black/[0.02] p-1">
                  {([
                    ['why', 'Decision trace', Activity],
                    ['evidence', 'Evidence', FlaskConical],
                    ['plan', 'Investigation', ScanSearch],
                  ] as const).map(([key, label, Icon]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setTab(key)}
                      className={cn(
                        'flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] transition',
                        tab === key ? 'bg-black/[0.07] text-fg' : 'text-fg-subtle hover:text-fg-muted',
                      )}
                    >
                      <Icon className="size-3" />
                      {label}
                    </button>
                  ))}
                </div>

                {tab === 'why' && (
                  <ol className="space-y-2">
                    {decision.decisionTrace.map((step) => (
                      <li key={step.step} className="flex gap-2.5 text-[11px]">
                        <span className="mt-px grid size-4 shrink-0 place-items-center rounded-full border border-black/10 text-[9px] text-fg-subtle tabular">
                          {step.step}
                        </span>
                        <span className="min-w-0">
                          <span className="mr-1.5 text-[9.5px] tracking-wide text-fg-subtle uppercase">{step.stage}</span>
                          <span className="text-fg-muted">{step.detail}</span>
                        </span>
                      </li>
                    ))}
                  </ol>
                )}

                {tab === 'evidence' && (
                  <ul className="space-y-1.5">
                    {decision.evidence.map((item) => {
                      const supports = decision.supportingEvidence.includes(item.evidenceId);
                      return (
                        <li key={item.evidenceId} className="flex items-baseline gap-2 text-[11px]">
                          <span
                            className={cn(
                              'w-16 shrink-0 text-[9.5px] tracking-wide uppercase',
                              supports ? 'text-brand' : 'text-fg-subtle',
                            )}
                          >
                            {item.domain}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="text-fg">{item.label}</span>
                            <span className="text-fg-subtle"> — {item.detail}</span>
                            <span className="block text-[10px] text-fg-subtle">
                              {item.source}
                              {item.isMock && ' · demo'}
                              {item.domain === 'geographic' && ' · context only, not a measurement'}
                            </span>
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}

                {tab === 'plan' && (
                  <ul className="space-y-2">
                    {decision.investigationPlan.length === 0 && (
                      <li className="text-[11px] text-fg-subtle">No further investigation is required.</li>
                    )}
                    {decision.investigationPlan.map((action) => (
                      <li key={action.actionId} className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2">
                        <p className="text-xs text-fg">{action.title}</p>
                        <p className="mt-0.5 text-[10.5px] text-fg-subtle">Missing: {action.missingData}</p>
                        <p className="mt-0.5 text-[10.5px] text-fg-subtle">Why: {action.rationale}</p>
                        <p className="mt-0.5 text-[10.5px] text-fg-muted">Source: {action.provider}</p>
                      </li>
                    ))}
                  </ul>
                )}

                {decision.crossSignalFindings.length > 0 && (
                  <div className="space-y-1.5 border-t border-black/[0.06] pt-2.5">
                    <p className="eyebrow">Cross-signal findings</p>
                    {decision.crossSignalFindings.map((finding) => (
                      <p key={finding.findingId} className="text-[11px] text-fg-subtle">{finding.detail}</p>
                    ))}
                  </div>
                )}

                {decision.dataGaps.length > 0 && (
                  <div className="space-y-1 border-t border-black/[0.06] pt-2.5">
                    <p className="eyebrow">Data gaps</p>
                    {decision.dataGaps.map((gap) => (
                      <p key={gap} className="flex items-start gap-1.5 text-[11px] text-fg-subtle">
                        <Info className="mt-px size-3 shrink-0" />
                        <span>{gap}</span>
                      </p>
                    ))}
                  </div>
                )}

                {/* Shown apart from the decision, because it explains rather than decides. */}
                {decision.llmExplanation && (
                  <div className="space-y-1 border-t border-black/[0.06] pt-2.5">
                    <p className="eyebrow flex items-center gap-1.5">
                      <Sparkles className="size-3" /> Plain-language summary
                    </p>
                    <p className="text-[11px] leading-relaxed text-fg-muted">{decision.llmExplanation}</p>
                    <p className="text-[10px] text-fg-subtle">
                      Written by a language model from the decision above. It did not influence the risk
                      score, confidence, priorities or evidence.
                    </p>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </DashboardCard>
  );
}
