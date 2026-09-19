import { AnimatePresence, motion } from 'framer-motion';
import { Activity, Check, CircleCheck, Clock3, GitMerge, X, type LucideIcon } from 'lucide-react';
import { Fragment } from 'react';
import { useAnalysis, type AgentStepState, type StepStatus } from '../../context/AnalysisContext';
import { cn } from '../../lib/format';
import { AGENT_ORDER } from '../../services/analysisEngine';
import type { AgentId } from '../../types/agents';
import { DashboardCard } from '../ui/DashboardCard';
import { ProgressBar } from '../ui/primitives';
import { RiskBadge } from '../ui/RiskBadge';
import { AGENT_META, SPECIALISTS } from './agentMeta';

function TypingDots({ color }: { color: string }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-hidden>
      {[0, 1, 2].map((index) => (
        <motion.span
          key={index}
          className="size-1 rounded-full"
          style={{ background: color }}
          animate={{ opacity: [0.25, 1, 0.25], y: [0, -2, 0] }}
          transition={{ duration: 0.9, repeat: Infinity, delay: index * 0.15 }}
        />
      ))}
    </span>
  );
}

function StepNode({ status, color, icon: Icon }: { status: StepStatus; color: string; icon: LucideIcon }) {
  const failed = status === 'failed';
  const timeout = status === 'timeout';
  const idle = status === 'idle' || status === 'queued';
  return (
    <span
      className="relative z-10 grid size-8 shrink-0 place-items-center rounded-full border bg-ink-900 transition-colors duration-300"
      style={{ borderColor: idle ? 'rgb(15 23 42 / 0.1)' : failed ? '#dc262680' : timeout ? '#d9770680' : status === 'complete' ? `${color}70` : color }}
    >
      {status === 'running' && (
        <>
          <span className="absolute inset-0 animate-pulse-ring rounded-full" style={{ background: `${color}40` }} />
          <svg className="absolute -inset-[3px] animate-spin" viewBox="0 0 38 38" aria-hidden>
            <circle cx="19" cy="19" r="17.5" fill="none" stroke={color} strokeWidth="2" strokeDasharray="28 90" strokeLinecap="round" />
          </svg>
        </>
      )}
      {status === 'complete' ? (
        <motion.span initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: 'spring', stiffness: 500, damping: 22 }}>
          <Check className="size-4" style={{ color }} strokeWidth={2.75} />
        </motion.span>
      ) : failed ? (
        <X className="size-4 text-risk-high" strokeWidth={2.5} />
      ) : timeout ? (
        <Clock3 className="size-4 text-risk-moderate" />
      ) : (
        <Icon className="size-3.5" style={{ color: status === 'running' ? color : '#838d97' }} />
      )}
    </span>
  );
}

function statusText(step: AgentStepState) {
  switch (step.status) {
    case 'running':
      return <span className="text-brand">Running…</span>;
    case 'queued':
      return <span className="text-fg-subtle">Queued</span>;
    case 'complete':
      return <span className="text-fg-subtle tabular">Completed{step.durationMs !== null && step.durationMs >= 50 ? ` · ${(step.durationMs / 1000).toFixed(1)}s` : ''}</span>;
    case 'failed':
      return <span className="text-risk-high">Failed</span>;
    case 'timeout':
      return <span className="text-risk-moderate">Timed out</span>;
    default:
      return <span className="text-fg-subtle">Idle</span>;
  }
}

function TimelineItem({ step, isLast }: { step: AgentStepState; isLast: boolean }) {
  const meta = AGENT_META[step.agent];
  const { status } = step;
  const failed = status === 'failed' || status === 'timeout';

  return (
    <li className="relative flex gap-3.5 pb-5 last:pb-0">
      {!isLast && (
        <span aria-hidden className="absolute top-9 bottom-1 left-[15.5px] w-px overflow-hidden bg-black/[0.07]">
          <motion.span
            className="absolute inset-x-0 top-0 block"
            style={{ background: `linear-gradient(${meta.color}, ${meta.color}30)` }}
            initial={false}
            animate={{ height: status === 'complete' ? '100%' : '0%' }}
            transition={{ duration: 0.6, ease: 'easeOut' }}
          />
          {status === 'running' && <span className="flow-dot" style={{ background: meta.color, boxShadow: `0 0 10px ${meta.color}` }} />}
        </span>
      )}
      <StepNode status={status} color={meta.color} icon={meta.icon} />
      <div className="min-w-0 flex-1 pt-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className={cn('text-sm font-medium', status === 'idle' || status === 'queued' ? 'text-fg-muted' : 'text-fg')}>{meta.name}</span>
          <span className="text-[11px]">{statusText(step)}</span>
          {status === 'complete' && step.riskLevel && (
            <span className="ml-auto">
              <RiskBadge level={step.riskLevel} />
            </span>
          )}
        </div>
        <ul className="mt-1.5 space-y-0.5">
          <AnimatePresence initial={false}>
            {step.logs.map((log, index) => (
              <motion.li
                key={`${index}-${log}`}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25 }}
                className="flex gap-2 font-mono text-[11.5px] leading-relaxed text-fg-muted"
              >
                <span className="text-fg-subtle select-none" style={status === 'running' && index === step.logs.length - 1 ? { color: meta.color } : undefined}>
                  ›
                </span>
                <span className="min-w-0 break-words">{log}</span>
              </motion.li>
            ))}
          </AnimatePresence>
          {status === 'running' && (
            <li className="flex items-center gap-2 pl-4 font-mono text-[11px] text-fg-subtle">
              <TypingDots color={meta.color} />
              {step.agent === 'coordinator' && step.logs.length > 0 ? 'reasoning' : step.logs.length ? 'processing' : 'waiting for data source'}
            </li>
          )}
          {failed && step.error && <li className="font-mono text-[11.5px] leading-relaxed text-risk-high">✕ {step.error}</li>}
          {status === 'idle' && <li className="text-[11.5px] text-fg-subtle">Waiting for an analysis request</li>}
        </ul>
      </div>
    </li>
  );
}

function HandOff({ steps }: { steps: Record<AgentId, AgentStepState> }) {
  const received = SPECIALISTS.filter((agent) => steps[agent].status === 'complete').length;
  const settled = SPECIALISTS.every((agent) => !['queued', 'running'].includes(steps[agent].status));
  const active = settled && steps.coordinator.status !== 'idle';
  return (
    <li aria-hidden className="relative -mt-1 mb-4 ml-11 flex items-center gap-2 text-[10.5px] text-fg-subtle">
      <GitMerge className="size-3.5 transition-colors" style={{ color: active ? '#2563eb' : undefined }} />
      <span className={cn('transition-colors', active && 'text-fg-muted')}>
        {received}/3 specialist reports handed off to Coordinator
      </span>
      <span className="h-px flex-1 bg-linear-to-r from-brand/30 to-transparent" />
    </li>
  );
}

export function AgentTimeline({ agents = AGENT_ORDER, className }: { agents?: AgentId[]; className?: string }) {
  const { state, progress } = useAnalysis();
  const { phase, steps, lastDurationMs } = state;
  const running = phase === 'running';

  const chip = running
    ? { label: 'Analyzing Environment…', className: 'border-brand/30 bg-brand/10 text-brand' }
    : phase === 'error'
      ? { label: 'Interrupted', className: 'border-risk-high/30 bg-risk-high/10 text-risk-high' }
      : phase === 'complete'
        ? { label: 'Complete', className: 'border-risk-low/25 bg-risk-low/10 text-risk-low' }
        : { label: 'Idle', className: 'border-black/10 bg-black/5 text-fg-subtle' };

  return (
    <DashboardCard
      title="Agent Activity"
      subtitle="Live execution of independent agents"
      icon={Activity}
      iconColor="#2563eb"
      className={className}
      actions={<span className={cn('rounded-full border px-2 py-0.5 text-[10.5px] font-medium', chip.className)}>{chip.label}</span>}
    >
      <div className="mb-4 h-0.5">{running && <ProgressBar value={progress} height={2} />}</div>
      <ol className="relative">
        {agents.map((agent, index) => (
          <Fragment key={agent}>
            {agent === 'coordinator' && agents.length > 1 && <HandOff steps={steps} />}
            <TimelineItem step={steps[agent]} isLast={index === agents.length - 1} />
          </Fragment>
        ))}
      </ol>
      <AnimatePresence>
        {phase === 'complete' && agents.includes('coordinator') && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mt-4 flex items-center gap-2 rounded-xl border border-risk-low/20 bg-risk-low/[0.06] px-3 py-2.5 text-xs font-medium text-risk-low"
          >
            <CircleCheck className="size-4" />
            Environmental analysis complete
            <span className="ml-auto font-normal text-fg-subtle tabular">
              {lastDurationMs !== null && lastDurationMs >= 300 ? `${(lastDurationMs / 1000).toFixed(1)}s total` : 'Instant refresh'}
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </DashboardCard>
  );
}
