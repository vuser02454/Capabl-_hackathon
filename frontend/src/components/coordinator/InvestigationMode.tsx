/**
 * Investigation Mode — observed / not established / verify next, as a working checklist.
 *
 * The four questions are the ones an operator actually has: what did we see, what is still open,
 * what would settle it, and what happens now. All four are answered from the decision payload —
 * `evidence`, `conflicts`, `dataGaps` and `investigationPlan` — so nothing here is authored for
 * the UI.
 *
 * NOT ESTABLISHED is populated deliberately rather than left to inference. A panel that lists
 * only findings invites the reader to treat the absence of a claim as the absence of a risk; the
 * whole point of this system is that those are different. The checklist state is local and
 * ephemeral: it helps someone work through the actions in front of them and is never presented
 * as a record of completed fieldwork.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { ClipboardCheck, CircleHelp, Eye, ListChecks, Play, ShieldQuestion } from 'lucide-react';
import { useMemo, useState } from 'react';
import { cn } from '../../lib/format';
import type { EnvironmentalDecision } from '../../types/agents';
import { Button } from '../ui/Button';
import { DashboardCard } from '../ui/DashboardCard';

export function InvestigationMode({ decision }: { decision: EnvironmentalDecision }) {
  const [started, setStarted] = useState(false);
  const [done, setDone] = useState<Set<string>>(new Set());

  const observed = useMemo(
    () =>
      (decision.evidence ?? [])
        .filter((item) => item.severity >= 0.4 && item.domain !== 'geographic')
        .slice(0, 5),
    [decision.evidence],
  );

  // Built from what the evidence CANNOT support, not from what it does.
  const notEstablished = useMemo(() => {
    const items: string[] = [];
    const hasVision = (decision.evidence ?? []).some((e) => e.evidenceId.startsWith('IMG-DET'));
    if (hasVision) {
      items.push(
        'Chemical contamination — an image establishes a surface condition, never a chemistry.',
      );
    }
    for (const conflict of decision.conflicts ?? []) items.push(conflict.detail);
    if (!decision.sufficientEvidence) {
      items.push('A primary concern — the available evidence is inconclusive.');
    }
    if (decision.overallDirection === 'insufficient_history') {
      items.push('Any trend — there is no baseline to compare these readings against.');
    }
    return items.slice(0, 4);
  }, [decision]);

  const actions = decision.investigationPlan ?? [];
  const gaps = decision.dataGaps ?? [];

  const toggle = (id: string) =>
    setDone((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <DashboardCard
      title={decision.sufficientEvidence ? 'Investigation' : 'Investigation required'}
      subtitle="What was observed, what is not established, and what would settle it"
      icon={ShieldQuestion}
      iconColor={decision.sufficientEvidence ? '#38bdf8' : '#fbbf24'}
      actions={
        actions.length > 0 && !started ? (
          <Button size="sm" variant="primary" icon={Play} onClick={() => setStarted(true)}>
            Start investigation
          </Button>
        ) : null
      }
    >
      <div className="space-y-3.5">
        {/* ------------------------------------------------------------- 1. observed */}
        <section>
          <h4 className="flex items-center gap-1.5 text-[10px] font-medium tracking-wider text-fg-subtle uppercase">
            <Eye className="size-3" /> Observed
          </h4>
          {observed.length ? (
            <ul className="mt-1.5 space-y-1">
              {observed.map((item) => (
                <li key={item.evidenceId} className="flex gap-2 text-[12px] text-fg-muted">
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-risk-moderate" />
                  <span>
                    <span className="text-fg">{item.label}</span>
                    <span className="text-fg-subtle"> — {item.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 text-[12px] text-fg-subtle">
              No elevated evidence in this analysis. That is not the same as nothing being wrong.
            </p>
          )}
        </section>

        {/* ------------------------------------------------------------- 2. not established */}
        {notEstablished.length > 0 && (
          <section className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
            <h4 className="flex items-center gap-1.5 text-[10px] font-medium tracking-wider text-fg-subtle uppercase">
              <CircleHelp className="size-3" /> Not established
            </h4>
            <ul className="mt-1.5 space-y-1">
              {notEstablished.map((item) => (
                <li key={item} className="flex gap-2 text-[12px] text-fg-muted">
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-fg-subtle" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* ------------------------------------------------------------- 3. verify next */}
        <section>
          <h4 className="flex items-center gap-1.5 text-[10px] font-medium tracking-wider text-fg-subtle uppercase">
            <ListChecks className="size-3" /> Verify next
          </h4>
          {actions.length ? (
            <ul className="mt-1.5 space-y-1">
              {actions.map((action) => {
                const id = action.actionId ?? action.title;
                const checked = done.has(id);
                return (
                  <li key={id}>
                    <label
                      className={cn(
                        'flex cursor-pointer items-start gap-2.5 rounded-lg border px-2.5 py-2 transition',
                        checked
                          ? 'border-risk-low/25 bg-risk-low/[0.05]'
                          : 'border-black/[0.06] bg-black/[0.02] hover:bg-black/[0.05]',
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={!started}
                        onChange={() => toggle(id)}
                        className="mt-0.5 size-3.5 shrink-0 accent-brand disabled:opacity-40"
                      />
                      <span className="min-w-0">
                        <span
                          className={cn(
                            'block text-[12px] font-medium',
                            checked ? 'text-fg-subtle line-through' : 'text-fg',
                          )}
                        >
                          {action.title}
                        </span>
                        <span className="block text-[11px] text-fg-subtle">{action.rationale}</span>
                        {action.provider && (
                          <span className="mt-0.5 block text-[10px] text-fg-subtle">
                            Source: {action.provider}
                          </span>
                        )}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-1.5 text-[12px] text-fg-subtle">
              No further collection is recommended — the reporting domains answered.
            </p>
          )}

          <AnimatePresence>
            {started && actions.length > 0 && (
              <motion.p
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="mt-2 flex items-center gap-1.5 text-[11px] text-fg-subtle"
              >
                <ClipboardCheck className="size-3" />
                {done.size} of {actions.length} marked. This checklist is local to your browser and
                is not a record of completed fieldwork.
              </motion.p>
            )}
          </AnimatePresence>
        </section>

        {/* ------------------------------------------------------------- 4. gaps */}
        {gaps.length > 0 && (
          <section className="border-t border-black/[0.06] pt-2.5">
            <h4 className="text-[10px] font-medium tracking-wider text-fg-subtle uppercase">
              Data gaps
            </h4>
            <ul className="mt-1.5 space-y-0.5">
              {gaps.map((gap) => (
                <li key={gap} className="text-[11.5px] text-fg-subtle">
                  {gap}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </DashboardCard>
  );
}
