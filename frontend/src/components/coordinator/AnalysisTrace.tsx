/**
 * Analysis Trace — which stages ran, in what order, and what each produced.
 *
 * THIS IS NOT CHAIN-OF-THOUGHT. It shows pipeline execution events, every one of which is
 * already a fact in the response payload: an agent run and its status, a count of evidence
 * items, a number of retrieved passages, a risk figure. No prompt, no model reasoning and no
 * intermediate deliberation is exposed, because none of that is in the data this renders.
 *
 * The distinction matters for more than privacy. Execution events are verifiable — a viewer can
 * check that four agents ran and ten evidence items exist — whereas narrated "reasoning" is
 * unfalsifiable by construction. Showing the former builds the trust that showing the latter
 * only performs.
 */
import { motion } from 'framer-motion';
import { AlertTriangle, Check, ListTree, Minus } from 'lucide-react';
import { cn } from '../../lib/format';
import type { AgentRun, EnvironmentalDecision } from '../../types/agents';
import { DashboardCard } from '../ui/DashboardCard';

type StepStatus = 'ok' | 'degraded' | 'skipped';

interface TraceStep {
  label: string;
  status: StepStatus;
  detail: string;
  durationMs?: number | null;
}

const ICON: Record<StepStatus, typeof Check> = {
  ok: Check,
  degraded: AlertTriangle,
  skipped: Minus,
};

const TONE: Record<StepStatus, string> = {
  ok: 'text-risk-low',
  degraded: 'text-risk-moderate',
  skipped: 'text-fg-subtle',
};

const AGENT_LABEL: Record<string, string> = {
  air: 'Air Agent',
  water: 'Water Agent',
  waste: 'Waste Agent',
  coordinator: 'Coordinator',
};

export function AnalysisTrace({
  decision,
  runs,
}: {
  decision: EnvironmentalDecision;
  runs: AgentRun[];
}) {
  const evidence = decision.evidence ?? [];
  const knowledge = decision.knowledge;

  const steps: TraceStep[] = [];

  // --- specialists, from the runs the graph actually recorded -------------------------------
  for (const run of runs) {
    const label = AGENT_LABEL[run.agent] ?? run.agent;
    if (run.agent === 'coordinator') continue;
    const domainEvidence = evidence.filter((item) => item.domain === run.agent);
    steps.push({
      label,
      status: run.status === 'complete' ? 'ok' : 'degraded',
      detail:
        run.status === 'complete'
          ? `${domainEvidence.length} evidence item${domainEvidence.length === 1 ? '' : 's'}`
          : (run.error ?? `${run.status}`),
      durationMs: run.durationMs,
    });
  }

  // --- water vision, reported only when it contributed detections ---------------------------
  const litter = evidence.filter((item) => item.evidenceId.startsWith('IMG-DET')).length;
  if (litter > 0) {
    steps.push({
      label: 'Evidence filter',
      status: 'ok',
      detail: `${litter} visible-litter detection${litter === 1 ? '' : 's'} admitted as evidence`,
    });
  }

  // --- context ------------------------------------------------------------------------------
  const context = evidence.filter((item) => item.domain === 'geographic').length;
  steps.push({
    label: 'Geographic context',
    status: context ? 'ok' : 'skipped',
    detail: context ? `${context} mapped feature group(s) · severity 0` : 'no mapped features',
  });

  // --- retrieval ----------------------------------------------------------------------------
  const retrieved = knowledge?.results?.length ?? 0;
  steps.push({
    label: 'Knowledge retrieval',
    status: knowledge?.status === 'ok' ? (retrieved ? 'ok' : 'skipped') : 'degraded',
    detail:
      knowledge?.status === 'ok'
        ? retrieved
          ? `${retrieved} passage${retrieved === 1 ? '' : 's'} retrieved`
          : 'no passage cleared the relevance floor'
        : (knowledge?.message ?? 'retrieval unavailable'),
  });

  // --- reasoning ----------------------------------------------------------------------------
  steps.push({
    label: 'Evidence validation',
    status: evidence.length ? 'ok' : 'degraded',
    detail: `${evidence.length} item${evidence.length === 1 ? '' : 's'} normalised`,
  });

  const conflicts = decision.conflicts?.length ?? 0;
  steps.push({
    label: 'Conflict analysis',
    status: 'ok',
    detail: conflicts ? `${conflicts} conflict${conflicts === 1 ? '' : 's'} surfaced` : 'no conflicts found',
  });

  steps.push({
    label: 'Sufficiency check',
    status: decision.sufficientEvidence ? 'ok' : 'degraded',
    detail: decision.sufficientEvidence ? 'evidence sufficient to decide' : 'evidence inconclusive',
  });

  steps.push({
    label: 'Risk engine',
    status: 'ok',
    detail: `${Math.round(decision.riskScore * 100)} / 100 · ${decision.riskLevel} · computed deterministically`,
  });

  const actions = decision.investigationPlan?.length ?? 0;
  steps.push({
    label: 'Investigation planner',
    status: actions ? 'ok' : 'skipped',
    detail: actions ? `${actions} recommended action${actions === 1 ? '' : 's'}` : 'no further collection required',
  });

  steps.push({
    label: 'Explanation',
    status: 'ok',
    detail: decision.llmEnhanced
      ? `narrated by ${decision.explanationProvider ?? 'the configured provider'}`
      : 'deterministic template (no provider configured)',
  });

  return (
    <DashboardCard
      title="Analysis Trace"
      subtitle="Pipeline stages that ran, and what each produced"
      icon={ListTree}
      iconColor="#94a3b8"
    >
      <ol className="space-y-1">
        {steps.map((step, index) => {
          const Icon = ICON[step.status];
          return (
            <motion.li
              key={`${step.label}-${index}`}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.035, duration: 0.25 }}
              className="flex items-baseline gap-2.5 rounded-lg px-1.5 py-1"
            >
              <Icon className={cn('size-3.5 shrink-0 translate-y-0.5', TONE[step.status])} />
              <span className="shrink-0 text-[12.5px] font-medium text-fg">{step.label}</span>
              <span className="min-w-0 flex-1 truncate text-[11.5px] text-fg-subtle">
                {step.detail}
              </span>
              {step.durationMs != null && (
                <span className="tabular shrink-0 text-[10px] text-fg-subtle">
                  {step.durationMs} ms
                </span>
              )}
            </motion.li>
          );
        })}
      </ol>
      <p className="mt-3 border-t border-white/[0.06] pt-2.5 text-[10.5px] leading-relaxed text-fg-subtle">
        Execution events only. No prompt or model reasoning is shown — every line above is a fact
        already present in the analysis payload.
      </p>
    </DashboardCard>
  );
}
