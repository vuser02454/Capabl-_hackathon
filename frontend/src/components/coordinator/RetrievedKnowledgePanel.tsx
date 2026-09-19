/**
 * Evidence & Retrieved Knowledge — what the retriever found, and what it was asked.
 *
 * The query is shown, not just the results. It is built deterministically from the evidence
 * rather than written by a language model, and showing it is what lets a reader check that the
 * system searched for what it actually measured.
 *
 * Every passage is rendered with its chunk id and source file, both of which resolve to a real
 * section of a real file in the repository. Nothing here is a summary of a source: it is the
 * retrieved text. A citation that cannot be opened is worse than none, because it makes an
 * unverified claim look checked.
 *
 * An empty result is rendered as an explicit statement, never as a blank panel — "the corpus does
 * not cover this" is a useful answer and must not read as a failure to load.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { BookOpen, ChevronDown, FileText, Search } from 'lucide-react';
import { useState } from 'react';
import { cn } from '../../lib/format';
import type { KnowledgeRetrieval } from '../../types/agents';
import { DashboardCard } from '../ui/DashboardCard';
import { Chip } from '../ui/primitives';

const STATUS_COPY: Record<string, string> = {
  not_run: 'Knowledge retrieval did not run for this analysis.',
  unavailable: 'The knowledge corpus could not be loaded.',
};

/** Relevance is shown as a bar and a number — a weak match should read as weak. */
function Relevance({ score }: { score: number }) {
  const percent = Math.round(Math.min(1, Math.max(0, score)) * 100);
  return (
    <span className="flex items-center gap-1.5" title={`Cosine similarity ${score.toFixed(3)}`}>
      <span className="h-1 w-10 overflow-hidden rounded-full bg-black/[0.08]">
        <span
          className="block h-full rounded-full bg-amber-300/70"
          style={{ width: `${Math.max(6, percent)}%` }}
        />
      </span>
      <span className="tabular text-[10px] text-fg-subtle">{score.toFixed(2)}</span>
    </span>
  );
}

export function RetrievedKnowledgePanel({ knowledge }: { knowledge: KnowledgeRetrieval }) {
  const [open, setOpen] = useState<string | null>(knowledge.results?.[0]?.chunkId ?? null);

  const results = knowledge.results ?? [];
  const unavailable = knowledge.status !== 'ok';

  return (
    <DashboardCard
      title="Evidence & Retrieved Knowledge"
      subtitle="Passages retrieved to ground the explanation — context, never evidence"
      icon={BookOpen}
      iconColor="#fbbf24"
      actions={
        knowledge.status === 'ok' ? (
          <Chip color="#fbbf24">
            {knowledge.chunksIndexed} chunks · {knowledge.documentsIndexed} docs
          </Chip>
        ) : null
      }
    >
      {unavailable ? (
        <p className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-3 text-[12.5px] text-fg-muted">
          {knowledge.message ?? STATUS_COPY[knowledge.status] ?? 'Retrieval did not run.'}
        </p>
      ) : (
        <div className="space-y-3">
          {/* The query, shown because it is derived from evidence rather than authored. */}
          <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-[10px] font-medium tracking-wider text-fg-subtle uppercase">
              <Search className="size-3" /> Query
            </p>
            <p className="mt-1 font-mono text-[11.5px] leading-relaxed break-words text-fg-muted">
              {knowledge.query || '—'}
            </p>
            <p className="mt-1.5 text-[10px] text-fg-subtle">
              Built from this analysis's evidence, not written by a language model.
            </p>
          </div>

          {results.length === 0 ? (
            <p className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-3 text-[12.5px] text-fg-muted">
              {knowledge.message ??
                'No passage cleared the relevance floor. The knowledge base does not cover this question.'}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {results.map((item, index) => {
                const expanded = open === item.chunkId;
                return (
                  <motion.li
                    key={item.chunkId}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.05 }}
                  >
                    <button
                      type="button"
                      onClick={() => setOpen(expanded ? null : item.chunkId)}
                      className={cn(
                        'w-full rounded-xl border px-3 py-2.5 text-left transition',
                        expanded
                          ? 'border-amber-300/25 bg-amber-300/[0.05]'
                          : 'border-black/[0.06] bg-black/[0.02] hover:bg-black/[0.05]',
                      )}
                    >
                      <div className="flex items-start gap-2">
                        <FileText className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[12.5px] font-medium text-fg">
                            {item.documentTitle}
                            <span className="text-fg-subtle"> — {item.section}</span>
                          </p>
                          <p className="mt-0.5 truncate font-mono text-[10px] text-fg-subtle">
                            {item.chunkId}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <Relevance score={item.score} />
                          <ChevronDown
                            className={cn(
                              'size-3.5 text-fg-subtle transition-transform',
                              expanded && 'rotate-180',
                            )}
                          />
                        </div>
                      </div>

                      <AnimatePresence initial={false}>
                        {expanded && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.18 }}
                            className="overflow-hidden"
                          >
                            <div className="mt-2.5 border-t border-black/[0.06] pt-2.5">
                              {/* The retrieved text itself, not a paraphrase of it. */}
                              <p className="text-[11.5px] leading-relaxed whitespace-pre-line text-fg-muted">
                                {item.content}
                              </p>
                              <dl className="mt-2.5 grid gap-1 text-[10.5px] text-fg-subtle">
                                {item.sourceFile && (
                                  <div className="flex gap-1.5">
                                    <dt className="shrink-0">Source:</dt>
                                    <dd className="font-mono break-all">{item.sourceFile}</dd>
                                  </div>
                                )}
                                {item.usedBy && (
                                  <div className="flex gap-1.5">
                                    <dt className="shrink-0">Used by:</dt>
                                    <dd>{item.usedBy}</dd>
                                  </div>
                                )}
                              </dl>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </button>
                  </motion.li>
                );
              })}
            </ul>
          )}

          <p className="text-[10.5px] leading-relaxed text-fg-subtle">
            Retrieved by {knowledge.embedding} similarity over EcoSentinel's own documented
            standards and measured results
            {knowledge.minScore != null && <> · relevance floor {knowledge.minScore}</>}. These
            passages explain what the measurements mean — they carry no severity and cannot change
            the risk score.
          </p>
        </div>
      )}
    </DashboardCard>
  );
}
