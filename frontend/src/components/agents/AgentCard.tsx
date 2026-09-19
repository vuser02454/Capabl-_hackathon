import { Clock3 } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn, pct } from '../../lib/format';
import { RISK_STYLES } from '../../lib/risk';
import type { SpecialistAgentId, SpecialistResult } from '../../types/agents';
import { DashboardCard } from '../ui/DashboardCard';
import { ErrorState } from '../ui/ErrorState';
import { LoadingState } from '../ui/LoadingState';
import { ProgressBar } from '../ui/primitives';
import { RiskBadge } from '../ui/RiskBadge';
import { AGENT_META } from './agentMeta';

interface AgentCardProps {
  agent: SpecialistAgentId;
  result: SpecialistResult | null;
  pending: boolean;
  failure: string | null;
  subtitle: ReactNode;
  badges?: ReactNode;
  footerNote?: ReactNode;
  actions?: ReactNode;
  delay?: number;
  children?: ReactNode;
}

/** Shared shell for the three specialist agent cards. */
export function AgentCard({ agent, result, pending, failure, subtitle, badges, footerNote, actions, delay, children }: AgentCardProps) {
  const meta = AGENT_META[agent];
  const Icon = meta.icon;

  return (
    <DashboardCard className="h-full" bodyClassName="flex flex-col p-0" accent={meta.color} delay={delay} interactive>
      <div className="flex items-start justify-between gap-3 p-5 pb-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl" style={{ background: `${meta.color}14`, color: meta.color, border: `1px solid ${meta.color}2e` }}>
            <Icon className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-[10px] font-semibold tracking-[0.1em] uppercase" style={{ color: meta.color }}>
              {meta.name}
            </p>
            <p className="truncate text-sm font-medium text-fg">{subtitle}</p>
          </div>
        </div>
        {pending ? <LoadingState label="Running" /> : result ? <RiskBadge level={result.riskLevel} className="shrink-0" /> : null}
      </div>

      {badges && <div className="mb-3 flex flex-wrap gap-1.5 px-5">{badges}</div>}

      <div className="relative flex-1 px-5">
        {failure ? (
          <ErrorState compact title={`${meta.short} unavailable`} message={failure} />
        ) : !result ? (
          <LoadingState variant="skeleton" lines={5} className="py-2" />
        ) : (
          <div className={cn('transition-opacity duration-300', pending && 'opacity-35')}>
            <div className="mb-4 flex items-center gap-3">
              <span className="w-[72px] shrink-0 text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">Risk score</span>
              <ProgressBar value={result.riskScore} color={RISK_STYLES[result.riskLevel].color} height={5} markers={[0.4, 0.7]} />
              <span className="w-10 shrink-0 text-right text-sm font-semibold text-fg tabular">{pct(result.riskScore)}%</span>
            </div>
            {children}
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between gap-2 border-t border-white/[0.05] px-5 py-3">
        <span className="flex min-w-0 items-center gap-1.5 truncate text-[11px] text-fg-subtle">
          <Clock3 className="size-3 shrink-0" />
          <span className="truncate">{footerNote ?? '—'}</span>
        </span>
        <div className="flex shrink-0 gap-2">{actions}</div>
      </div>
    </DashboardCard>
  );
}
