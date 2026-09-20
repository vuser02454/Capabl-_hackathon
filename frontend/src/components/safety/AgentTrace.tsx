/**
 * The agent hand-off, made watchable.
 *
 * The claim "agentic architecture" is cheap; this is the evidence for it. Each step is a real node
 * in the LangGraph workflow that ran, in the order it ran, with the payload it passed on. The
 * Technical Details disclosure carries the actual hand-off object rather than a summary of it, so
 * the boundary between agents is inspectable rather than asserted.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { Check, ChevronRight, Circle, MinusCircle } from 'lucide-react';
import { useState } from 'react';
import { cn } from '../../lib/format';
import type { AgentTraceStep } from '../../types/safety';
import { DashboardCard } from '../ui/DashboardCard';

const STATUS_ICON = { ok: Check, skipped: MinusCircle, error: Circle } as const;
const STATUS_STYLE = {
  ok: 'border-risk-low/30 bg-risk-low/10 text-risk-low',
  skipped: 'border-black/10 bg-black/[0.04] text-fg-subtle',
  error: 'border-risk-high/30 bg-risk-high/10 text-risk-high',
} as const;

export function AgentTrace({ trace, className }: { trace: AgentTraceStep[]; className?: string }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!trace.length) return null;

  return (
    <DashboardCard
      title="Agent Execution"
      subtitle={`${trace.length} agents ran in sequence — each hand-off is shown below`}
      icon={ChevronRight}
      iconColor="#2563eb"
      className={className}
    >
      <ol className="space-y-2">
        {trace.map((step, index) => {
          const Icon = STATUS_ICON[step.status] ?? Circle;
          const expanded = open === `${index}`;
          const hasPayload = step.payload && Object.keys(step.payload).length > 0;
          return (
            <li key={`${step.agent}-${index}`}>
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    'mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border',
                    STATUS_STYLE[step.status] ?? STATUS_STYLE.error,
                  )}
                  aria-hidden
                >
                  <Icon className="size-3.5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-medium text-fg">{step.agent}</p>
                  <p className="text-xs text-fg-muted">{step.detail}</p>
                  {hasPayload && (
                    <button
                      type="button"
                      onClick={() => setOpen(expanded ? null : `${index}`)}
                      className="mt-1 text-[11px] text-fg-subtle underline-offset-2 transition hover:text-fg-muted hover:underline"
                    >
                      {expanded ? 'Hide' : 'Show'} technical details
                    </button>
                  )}
                  <AnimatePresence initial={false}>
                    {expanded && hasPayload && (
                      <motion.pre
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.18 }}
                        className="mt-2 overflow-x-auto rounded-lg border border-black/[0.06] bg-black/[0.02] p-3 font-mono text-[10.5px] leading-relaxed text-fg-muted"
                      >
                        {JSON.stringify(step.payload, null, 2)}
                      </motion.pre>
                    )}
                  </AnimatePresence>
                </div>
              </div>
              {index < trace.length - 1 && (
                <div aria-hidden className="ml-3 h-3 w-px bg-black/[0.08]" />
              )}
            </li>
          );
        })}
      </ol>
    </DashboardCard>
  );
}
