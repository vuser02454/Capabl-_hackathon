import { motion } from 'framer-motion';
import { CircleCheck, Layers } from 'lucide-react';
import { useState } from 'react';
import { useToast } from '../../context/ToastContext';
import type { Recommendation } from '../../types/agents';
import { AGENT_META } from '../agents/agentMeta';
import { Button } from '../ui/Button';
import { Chip } from '../ui/primitives';

const URGENCY_COLORS: Record<Recommendation['urgency'], string> = {
  Immediate: '#f26b6b',
  'Within 24h': '#f5b544',
  Routine: '#60a5fa',
};

export function RecommendationCard({ recommendation, index, interactive = true }: { recommendation: Recommendation; index: number; interactive?: boolean }) {
  const [status, setStatus] = useState<'idle' | 'working' | 'done'>('idle');
  const { notify } = useToast();
  const meta = recommendation.agent === 'all' ? null : AGENT_META[recommendation.agent];
  const urgencyColor = URGENCY_COLORS[recommendation.urgency];

  const act = () => {
    setStatus('working');
    window.setTimeout(() => {
      setStatus('done');
      notify({ tone: 'success', title: `Task created · ${recommendation.actionLabel}`, description: recommendation.title });
    }, 700);
  };

  return (
    <motion.li
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.07, duration: 0.35 }}
      className="flex flex-col gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 transition hover:border-white/[0.12] hover:bg-white/[0.035] sm:flex-row sm:items-center"
    >
      <div className="flex min-w-0 flex-1 items-start gap-3.5">
        <span
          className="grid size-10 shrink-0 place-items-center rounded-xl border text-sm font-semibold"
          style={{ color: urgencyColor, borderColor: `${urgencyColor}40`, background: `${urgencyColor}12` }}
        >
          P{recommendation.priority}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="eyebrow">Priority {recommendation.priority}</span>
            <span className="inline-flex items-center gap-1 text-[10.5px] font-medium text-fg-muted">
              <span className="size-1.5 rounded-full" style={{ background: urgencyColor }} />
              {recommendation.urgency}
            </span>
          </div>
          <h4 className="mt-0.5 text-sm font-semibold text-fg">{recommendation.title}</h4>
          <p className="mt-1 text-xs leading-relaxed text-fg-muted">{recommendation.explanation}</p>
          <div className="mt-2">
            <Chip
              color={meta?.color ?? '#2dd4bf'}
              icon={meta ? <meta.icon className="size-3" style={{ color: meta.color }} /> : <Layers className="size-3 text-brand" />}
            >
              {meta ? meta.name : 'All agents'}
            </Chip>
          </div>
        </div>
      </div>
      {interactive && (
        <Button
          size="sm"
          variant={status === 'done' ? 'ghost' : recommendation.priority === 1 ? 'primary' : 'secondary'}
          icon={status === 'done' ? CircleCheck : undefined}
          loading={status === 'working'}
          disabled={status === 'done'}
          onClick={act}
          className="self-start sm:self-center"
        >
          {status === 'done' ? 'Assigned' : recommendation.actionLabel}
        </Button>
      )}
    </motion.li>
  );
}
