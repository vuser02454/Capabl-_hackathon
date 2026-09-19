/**
 * Reference-dataset match result for the Water Agent.
 *
 * Presents an APPEARANCE match, and is written so it cannot be read as a measurement. The
 * matcher's own reliability caveat is rendered with every result — including "no match", because
 * failing to match contaminated references is not evidence that water is clean.
 */
import { Images, TriangleAlert } from 'lucide-react';
import { AGENT_META } from './agentMeta';
import { DashboardCard } from '../ui/DashboardCard';
import { Chip, ProgressBar } from '../ui/primitives';
import { cn, pct } from '../../lib/format';
import { RISK_STYLES } from '../../lib/risk';
import type { WaterDatasetMatch } from '../../types/agents';

const STATUS_COPY: Record<string, string> = {
  not_run: 'No image matched yet. Take or choose a water photo to compare it against the reference dataset.',
  indexing: 'The reference index is still being built on the backend.',
  index_missing: 'No reference dataset is available on the backend.',
  unavailable: 'Reference matching was unavailable for this image.',
};

export function DatasetMatchPanel({ match }: { match: WaterDatasetMatch }) {
  const color = AGENT_META.water.color;
  const level = match.contaminationLevel ? RISK_STYLES[match.contaminationLevel] : null;
  const matched = match.status === 'ok';

  return (
    <DashboardCard
      title="Reference dataset match"
      subtitle="How closely this photo resembles labelled reference frames — appearance only, not a measurement"
      icon={Images}
      iconColor={color}
      actions={
        match.datasetSize ? <Chip color={color}>{match.datasetSize.toLocaleString()} reference frames</Chip> : undefined
      }
    >
      {match.status === 'indexing' ? (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-3">
          <p className="text-[12.5px] text-fg-muted">{match.message ?? STATUS_COPY.indexing}</p>
          <ProgressBar className="mt-2" value={match.progress ?? 0} color={color} />
        </div>
      ) : !matched && match.status !== 'no_match' ? (
        <p className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-3 text-[12.5px] text-fg-muted">
          {match.message ?? STATUS_COPY[match.status] ?? 'Reference matching did not run.'}
        </p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
              <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">Resembles</p>
              <p className={cn('mt-1 text-lg font-semibold', level ? level.text : 'text-fg')}>
                {matched ? (match.matchedLabel ?? match.matchedClass) : 'No match'}
              </p>
              <p className="text-[10.5px] text-fg-subtle">
                {matched ? `class "${match.matchedClass}"` : `below the ${match.matchThreshold?.toFixed(2)} threshold`}
              </p>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
              <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">Similarity</p>
              <p className="tabular mt-1 text-lg font-semibold text-fg">
                {match.similarity != null ? `${pct(match.similarity)}%` : '—'}
              </p>
              <p className="text-[10.5px] text-fg-subtle">closest reference frame</p>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
              <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">Neighbour vote</p>
              <p className="tabular mt-1 text-lg font-semibold text-fg">
                {match.voteShare != null ? `${pct(match.voteShare)}%` : '—'}
              </p>
              <p className="text-[10.5px] text-fg-subtle">of the nearest frames agree</p>
            </div>
          </div>

          {match.nearDuplicate && match.duplicateOf && (
            <p className="mt-3 flex items-start gap-1.5 rounded-xl border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-[11.5px] text-risk-moderate">
              <TriangleAlert className="mt-px size-3.5 shrink-0" />
              <span>
                Near-duplicate of reference frame <span className="font-mono">{match.duplicateOf}</span> — this is a
                replayed dataset sample, not a new observation.
              </span>
            </p>
          )}

          {match.neighbours.length > 0 && (
            <ul className="mt-3 space-y-1.5 border-t border-white/[0.06] pt-3">
              {match.neighbours.map((neighbour) => (
                <li key={neighbour.file} className="flex items-baseline justify-between gap-3">
                  <span className="truncate font-mono text-[11px] text-fg-muted">{neighbour.file}</span>
                  <span className="flex shrink-0 items-baseline gap-2">
                    <span className="text-[11px] text-fg-subtle">{neighbour.label}</span>
                    <span className="tabular text-[12.5px] font-semibold text-fg">{pct(neighbour.similarity)}%</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {match.caveat && (
        <p className="mt-3 border-t border-white/[0.06] pt-3 text-[10.5px] leading-relaxed text-fg-subtle">
          <span className="font-medium text-fg-muted">How reliable is this? </span>
          {match.caveat}
        </p>
      )}
    </DashboardCard>
  );
}
