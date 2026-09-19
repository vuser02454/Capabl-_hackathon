/**
 * Evidence Fusion — the architecture, drawn from the analysis that actually ran.
 *
 * Every lane, count and score here comes from the decision payload. A lane that did not report
 * is drawn dimmed and labelled, rather than omitted: "the waste agent had nothing to say" and
 * "there is no waste agent" are different statements, and a diagram that cannot tell them apart
 * is decoration rather than instrumentation.
 *
 * Knowledge is deliberately drawn on a separate, dashed lane that joins AFTER the risk engine.
 * Retrieved passages ground the explanation; they are not evidence, carry no severity and cannot
 * move the score. Drawing them as another input would misstate the one property this
 * architecture exists to guarantee.
 */
import { motion } from 'framer-motion';
import { Boxes, BookOpen, Droplets, Gauge, Trash2, Wind } from 'lucide-react';
import { cn } from '../../lib/format';
import type { EnvironmentalDecision, RiskLevel } from '../../types/agents';
import { DashboardCard } from '../ui/DashboardCard';

const RISK_TEXT: Record<RiskLevel, string> = {
  LOW: 'text-risk-low',
  MODERATE: 'text-risk-moderate',
  HIGH: 'text-risk-high',
};

const RISK_STROKE: Record<RiskLevel, string> = {
  LOW: 'var(--color-risk-low, #34d399)',
  MODERATE: 'var(--color-risk-moderate, #fbbf24)',
  HIGH: 'var(--color-risk-high, #f87171)',
};

interface Lane {
  id: string;
  label: string;
  icon: typeof Wind;
  color: string;
  count: number;
  detail: string;
  reported: boolean;
}

export function EvidenceFusion({ decision }: { decision: EnvironmentalDecision }) {
  const evidence = decision.evidence ?? [];
  const knowledge = decision.knowledge;

  const forDomain = (domain: string) => evidence.filter((item) => item.domain === domain);
  const describe = (items: typeof evidence) => {
    if (!items.length) return 'no evidence';
    const elevated = items.filter((item) => item.severity >= 0.4).length;
    return elevated ? `${items.length} items · ${elevated} elevated` : `${items.length} items`;
  };

  const lanes: Lane[] = [
    { id: 'air', label: 'Air', icon: Wind, color: '#60a5fa' },
    { id: 'water', label: 'Water', icon: Droplets, color: '#38bdf8' },
    { id: 'waste', label: 'Waste', icon: Trash2, color: '#2dd4bf' },
    { id: 'geographic', label: 'Context', icon: Boxes, color: '#a78bfa' },
  ].map((lane) => {
    const items = forDomain(lane.id);
    return {
      ...lane,
      count: items.length,
      detail: lane.id === 'geographic' && items.length ? `${items.length} mapped · severity 0` : describe(items),
      reported: items.length > 0,
    };
  });

  const knowledgeCount = knowledge?.results?.length ?? 0;
  const riskPercent = Math.round(decision.riskScore * 100);

  return (
    <DashboardCard
      title="Evidence Fusion"
      subtitle="Every signal that reached the decision, and what each contributed"
      icon={Gauge}
      iconColor="#818cf8"
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,0.9fr)] lg:items-center">
        {/* ---------------------------------------------------------------- inputs */}
        <ul className="space-y-2">
          {lanes.map((lane, index) => {
            const Icon = lane.icon;
            return (
              <motion.li
                key={lane.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.06, duration: 0.3 }}
                className={cn(
                  'flex items-center gap-3 rounded-xl border px-3 py-2.5 transition',
                  lane.reported
                    ? 'border-white/[0.08] bg-white/[0.03]'
                    : 'border-white/[0.04] bg-white/[0.01] opacity-55',
                )}
              >
                <span
                  className="grid size-8 shrink-0 place-items-center rounded-lg"
                  style={{ background: `${lane.color}1a`, color: lane.color }}
                >
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[12.5px] font-medium text-fg">{lane.label}</span>
                  <span className="block truncate text-[10.5px] text-fg-subtle">{lane.detail}</span>
                </span>
                <span className="tabular text-sm font-semibold text-fg-muted">{lane.count}</span>
              </motion.li>
            );
          })}
        </ul>

        {/* ---------------------------------------------------------------- connectors */}
        <svg
          viewBox="0 0 120 200"
          className="hidden h-[200px] w-[120px] lg:block"
          aria-hidden="true"
          preserveAspectRatio="none"
        >
          {lanes.map((lane, index) => {
            const y = 26 + index * 44;
            return (
              <motion.path
                key={lane.id}
                d={`M0 ${y} C 55 ${y}, 55 100, 118 100`}
                fill="none"
                stroke={lane.color}
                strokeWidth={lane.reported ? 1.6 : 1}
                strokeOpacity={lane.reported ? 0.75 : 0.22}
                strokeDasharray={lane.reported ? undefined : '3 4'}
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.7, delay: 0.15 + index * 0.08, ease: 'easeOut' }}
              />
            );
          })}
        </svg>

        {/* ---------------------------------------------------------------- output */}
        <div className="space-y-3">
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.45, duration: 0.35 }}
            className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3.5"
          >
            <p className="text-[10px] font-medium tracking-wider text-fg-subtle uppercase">
              Deterministic risk engine
            </p>
            <p className={cn('tabular mt-1 text-3xl font-semibold', RISK_TEXT[decision.riskLevel])}>
              {riskPercent}
              <span className="text-base text-fg-subtle"> / 100</span>
            </p>
            <p className={cn('text-xs font-medium', RISK_TEXT[decision.riskLevel])}>
              {decision.riskLevel}
              {!decision.sufficientEvidence && (
                <span className="text-fg-subtle"> · evidence inconclusive</span>
              )}
            </p>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
              <motion.div
                className="h-full rounded-full"
                style={{ background: RISK_STROKE[decision.riskLevel] }}
                initial={{ width: 0 }}
                animate={{ width: `${riskPercent}%` }}
                transition={{ duration: 0.6, delay: 0.5 }}
              />
            </div>
            <p className="mt-2 text-[10.5px] leading-relaxed text-fg-subtle">
              Computed in Python from the evidence above. No language model contributes to this
              number.
            </p>
          </motion.div>

          {/* Knowledge joins AFTER the score, on its own lane, because it explains rather than
              weighs. */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.6 }}
            className="flex items-start gap-3 rounded-xl border border-dashed border-white/[0.09] bg-white/[0.01] px-3 py-2.5"
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-amber-400/10 text-amber-300">
              <BookOpen className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block text-[12.5px] font-medium text-fg">
                Retrieved knowledge
                <span className="tabular ml-1.5 text-fg-muted">{knowledgeCount}</span>
              </span>
              <span className="block text-[10.5px] leading-relaxed text-fg-subtle">
                Grounds the explanation. Carries no severity and cannot change the score.
              </span>
            </span>
          </motion.div>
        </div>
      </div>
    </DashboardCard>
  );
}
