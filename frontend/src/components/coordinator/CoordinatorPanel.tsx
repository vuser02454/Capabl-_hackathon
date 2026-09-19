import { motion } from 'framer-motion';
import { CircleCheck, LoaderCircle, Network, Plus, Quote, Sparkles, CircleX, TriangleAlert } from 'lucide-react';
import { Fragment } from 'react';
import { useAnalysis } from '../../context/AnalysisContext';
import { cn, pct } from '../../lib/format';
import { RISK_STYLES } from '../../lib/risk';
import type { CoordinatorResult, SpecialistAgentId, SpecialistResult } from '../../types/agents';
import { AGENT_META, SPECIALISTS } from '../agents/agentMeta';
import { BranchConnector } from '../architecture/Connectors';
import { DashboardCard } from '../ui/DashboardCard';
import { LoadingState } from '../ui/LoadingState';
import { Chip, ProgressBar } from '../ui/primitives';
import { RiskBadge } from '../ui/RiskBadge';
import { RiskGauge } from '../ui/RiskGauge';

export function ContributionBar({ coordinator, className }: { coordinator: CoordinatorResult; className?: string }) {
  const segments = SPECIALISTS.map((id) => coordinator.contributions.find((c) => c.agent === id)).filter(
    (segment): segment is NonNullable<typeof segment> => Boolean(segment),
  );
  const adjustment = coordinator.crossSignalAdjustment;

  return (
    <div className={className}>
      <div className="flex items-center justify-between">
        <p className="eyebrow">Risk aggregation</p>
        <span className="text-[11px] text-fg-subtle tabular">{pct(coordinator.overallScore)}% overall</span>
      </div>
      <div className="mt-2 flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full bg-black/[0.05]">
        {segments.map((segment) => (
          <motion.div
            key={segment.agent}
            className="h-full"
            style={{ background: AGENT_META[segment.agent].color }}
            initial={{ width: 0 }}
            animate={{ width: `${segment.contribution * 100}%` }}
            transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
            title={`${AGENT_META[segment.agent].short}: ${Math.round(segment.contribution * 100)} pts`}
          />
        ))}
        {adjustment > 0 && (
          <motion.div
            className="h-full"
            style={{ background: 'repeating-linear-gradient(45deg, #2563eb 0 3px, #2563eb55 3px 6px)' }}
            initial={{ width: 0 }}
            animate={{ width: `${adjustment * 100}%` }}
            transition={{ duration: 0.9, delay: 0.2 }}
            title={`Cross-signal adjustment: +${Math.round(adjustment * 100)} pts`}
          />
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-subtle">
        {segments.map((segment) => (
          <span key={segment.agent} className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-sm" style={{ background: AGENT_META[segment.agent].color }} />
            {AGENT_META[segment.agent].short}
            <span className="text-fg-muted tabular">
              {Math.round(segment.weight * 100)}% × {pct(segment.riskScore)}
            </span>
          </span>
        ))}
        {adjustment > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-sm" style={{ background: 'repeating-linear-gradient(45deg, #2563eb 0 2px, #2563eb55 2px 4px)' }} />
            Cross-signal <span className="text-fg-muted tabular">+{Math.round(adjustment * 100)}</span>
          </span>
        )}
      </div>
    </div>
  );
}

function InputTile({ id, result, pending, failed }: { id: SpecialistAgentId; result: SpecialistResult | null; pending: boolean; failed: boolean }) {
  const meta = AGENT_META[id];
  const Icon = meta.icon;
  const status = failed ? 'failed' : pending ? 'pending' : result ? 'received' : 'empty';

  return (
    <motion.div
      layout
      className={cn(
        'relative rounded-xl border p-3 transition-colors duration-300',
        status === 'received' ? 'border-black/[0.09] bg-black/[0.03]' : 'border-dashed border-black/[0.1]',
        status === 'failed' && 'border-risk-high/30 bg-risk-high/[0.04]',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[10.5px] font-semibold tracking-[0.12em] uppercase" style={{ color: meta.color }}>
          <Icon className="size-3.5" />
          {meta.short}
        </span>
        {status === 'received' && <CircleCheck className="size-3.5 text-risk-low" />}
        {status === 'pending' && <LoaderCircle className="size-3.5 animate-spin text-fg-subtle" />}
        {status === 'failed' && <CircleX className="size-3.5 text-risk-high" />}
      </div>
      {status === 'received' && result ? (
        <>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
            <RiskBadge level={result.riskLevel} />
            <span className="text-xs whitespace-nowrap text-fg-subtle">
              Risk: <span className="text-sm font-semibold text-fg tabular">{pct(result.riskScore)}%</span>
            </span>
          </div>
          <ProgressBar value={result.riskScore} color={RISK_STYLES[result.riskLevel].color} height={3} className="mt-2.5" />
        </>
      ) : (
        <p className="mt-2 text-[11px] text-fg-subtle">{status === 'pending' ? 'Awaiting report…' : status === 'failed' ? 'No report — agent failed' : 'No report yet'}</p>
      )}
    </motion.div>
  );
}

export function CoordinatorPanel({ className, showDetails = true }: { className?: string; showDetails?: boolean }) {
  const { display, pending, failures, state } = useAnalysis();
  const coordinator = display.coordinator;
  const reasoning = state.steps.coordinator.status === 'running';
  const waiting = pending.coordinator && !reasoning;
  const baseScore = coordinator ? coordinator.contributions.reduce((sum, c) => sum + c.contribution, 0) : 0;

  return (
    <DashboardCard
      title="Coordinator Agent"
      subtitle="Cross-signal environmental reasoning"
      icon={Network}
      iconColor="#2563eb"
      accent="#2563eb"
      className={className}
      actions={coordinator && !pending.coordinator ? <Chip color="#2563eb">Confidence {pct(coordinator.confidence)}%</Chip> : undefined}
    >
      <div className="grid grid-cols-1 items-stretch gap-2 sm:grid-cols-[1fr_auto_1fr_auto_1fr]">
        {SPECIALISTS.map((id, index) => (
          <Fragment key={id}>
            {index > 0 && (
              <div className="flex items-center justify-center text-fg-subtle" aria-hidden>
                <Plus className="size-4" />
              </div>
            )}
            <InputTile id={id} result={display[id]} pending={pending[id]} failed={Boolean(failures[id])} />
          </Fragment>
        ))}
      </div>

      <BranchConnector direction="in" active={reasoning || (!!coordinator && !waiting)} running={reasoning} className="my-1" />

      <div className="relative mx-auto mt-2 max-w-lg rounded-2xl border border-brand/20 bg-linear-to-b from-brand/[0.08] to-brand/[0.01] p-4 sm:p-5">
        {reasoning || (waiting && !coordinator) ? (
          <div className="flex items-center gap-4">
            <div className="relative grid size-[100px] shrink-0 place-items-center rounded-full border border-dashed border-brand/30">
              <span className="absolute inset-3 animate-pulse-ring rounded-full bg-brand/10" />
              <Network className="size-6 text-brand" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="eyebrow !text-brand">Coordinator</p>
              <p className="mt-1 text-sm text-fg">{reasoning ? 'Performing cross-signal reasoning…' : 'Waiting for specialist reports…'}</p>
              <LoadingState variant="skeleton" lines={2} className="mt-3" />
            </div>
          </div>
        ) : coordinator ? (
          <div className={cn('flex flex-col items-center gap-4 sm:flex-row', waiting && 'opacity-40')}>
            <RiskGauge score={coordinator.overallScore} level={coordinator.overallRiskLevel} size={100} stroke={8} label="overall" />
            <div className="text-center sm:text-left">
              <p className="eyebrow !text-brand">Coordinator · Overall risk</p>
              <p className={cn('mt-1 text-3xl font-semibold tracking-tight', RISK_STYLES[coordinator.overallRiskLevel].text)}>{coordinator.overallRiskLevel}</p>
              <p className="mt-1 text-xs text-fg-subtle">
                Weighted {pct(baseScore)}%
                {coordinator.crossSignalAdjustment > 0 && <> + {Math.round(coordinator.crossSignalAdjustment * 100)} cross-signal</>} · {coordinator.inputsReceived.length}/3 reports
              </p>
            </div>
          </div>
        ) : (
          <p className="py-6 text-center text-xs text-fg-subtle">Awaiting specialist reports</p>
        )}
      </div>

      {showDetails && coordinator && (
        <div className={cn('mt-5 grid gap-5 transition-opacity duration-300 lg:grid-cols-2', pending.coordinator && 'opacity-35')}>
          <div>
            <p className="eyebrow mb-2">Reasoning</p>
            <blockquote className="relative rounded-xl border border-black/[0.06] bg-black/[0.02] p-4 pr-9 text-[13px] leading-relaxed text-fg">
              <Quote className="absolute top-3 right-3 size-4 text-brand/30" />
              {coordinator.reasoning}
            </blockquote>
            {coordinator.crossSignalInsights.length > 0 && (
              <ul className="mt-3 space-y-2">
                {coordinator.crossSignalInsights.map((insight) => (
                  <li key={insight} className="flex gap-2 text-xs leading-relaxed text-fg-muted">
                    <Sparkles className="mt-0.5 size-3.5 shrink-0 text-brand" />
                    {insight}
                  </li>
                ))}
              </ul>
            )}
            {!!coordinator.dataLimitations?.length && (
              <div className="mt-3">
                <p className="eyebrow mb-1.5">Data limitations</p>
                <ul className="space-y-1.5">
                  {coordinator.dataLimitations.map((limitation) => (
                    <li key={limitation} className="flex gap-2 text-xs leading-relaxed text-fg-subtle">
                      <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-risk-moderate" />
                      {limitation}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div>
            <p className="eyebrow mb-2">Key contributing factors</p>
            <ul className="space-y-2">
              {coordinator.contributingFactors.map((factor, index) => (
                <motion.li
                  key={factor.label}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.08 }}
                  className="flex items-start gap-3 rounded-xl border border-black/[0.05] bg-black/[0.02] px-3 py-2.5"
                >
                  <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: AGENT_META[factor.agent].color }} />
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-fg">{factor.label}</p>
                    <p className="text-[11px] text-fg-subtle">
                      {factor.detail} · {AGENT_META[factor.agent].short}
                    </p>
                  </div>
                </motion.li>
              ))}
              {coordinator.contributingFactors.length === 0 && <li className="text-xs text-fg-subtle">No elevated risk factors detected.</li>}
            </ul>
            <ContributionBar coordinator={coordinator} className="mt-4" />
          </div>
        </div>
      )}
    </DashboardCard>
  );
}
