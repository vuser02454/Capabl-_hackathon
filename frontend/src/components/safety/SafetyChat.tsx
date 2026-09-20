/**
 * The grounded safety assistant.
 *
 * Every answer comes from this project's database through fixed read-only queries on the server.
 * The panel shows which of those queries ran and what they returned, because an assistant that
 * says "3 workers were rerouted" is only useful if the three can be checked — and because an
 * ungrounded answer should look different from a grounded one rather than reading the same.
 *
 * It cannot act. Publishing, dismissing, resolving and contacting are Safety Admin actions in the
 * review interface; the server refuses those requests before any query runs, and the refusal is
 * rendered distinctly so it is not mistaken for a failure.
 */
import { AlertCircle, Loader2, MessageSquare, Send, ShieldCheck } from 'lucide-react';
import { useRef, useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import type { SafetyChatResponse } from '../../types/safety';
import { Button } from '../ui/Button';

interface Turn {
  question: string;
  response: SafetyChatResponse | null;
  error: string | null;
}

const ADMIN_EXAMPLES = [
  'What safety patterns are emerging?',
  'Which departments have the most reports?',
  'What published alerts are affecting routing?',
  'Which workers were rerouted by alert #1?',
];

const WORKER_EXAMPLES = [
  'Show my recent safety reports.',
  'Why was my route changed?',
  'What alerts are near me?',
];

export function SafetyChat({
  role,
  employeeId,
  context,
  onOpenRoute,
}: {
  role: 'admin' | 'worker';
  employeeId?: string;
  /** What the user is looking at, so "who passed through this" resolves without an id. */
  context?: Record<string, unknown>;
  /** Opens a route event elsewhere in the app when the answer cites one. */
  onOpenRoute?: (routeEventId: number) => void;
}) {
  const { api } = useSettings();
  const [question, setQuestion] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const ask = async (text: string) => {
    const asked = text.trim();
    if (!asked || busy) return;
    setBusy(true);
    setQuestion('');
    setTurns((previous) => [...previous, { question: asked, response: null, error: null }]);
    try {
      const response = await api.safetyChat({ question: asked, role, employeeId, context });
      setTurns((previous) => previous.map((turn, index) =>
        index === previous.length - 1 ? { ...turn, response } : turn));
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'The assistant is unavailable.';
      setTurns((previous) => previous.map((turn, index) =>
        index === previous.length - 1 ? { ...turn, error: message } : turn));
    } finally {
      setBusy(false);
      endRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  };

  /** Route event ids the answer's evidence actually contains, for the follow-up buttons. */
  const routeIds = (response: SafetyChatResponse): number[] => {
    const found = new Set<number>();
    for (const item of response.evidence) {
      const rows = (item.result as { workers?: Array<{ id?: number }>; id?: number });
      if (typeof rows.id === 'number' && item.tool === 'get_route_event') found.add(rows.id);
      for (const worker of rows.workers ?? []) {
        if (typeof worker.id === 'number') found.add(worker.id);
      }
    }
    return [...found].slice(0, 6);
  };

  const examples = role === 'admin' ? ADMIN_EXAMPLES : WORKER_EXAMPLES;

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {turns.length === 0 && (
          <div>
            <p className="text-[12.5px] text-fg-muted">
              Ask about reports, patterns, hotspots, published alerts or recorded routes. Answers
              come from this project's records — not from general knowledge.
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {examples.map((example) => (
                <button key={example} type="button" onClick={() => void ask(example)}
                        className="rounded-full border border-black/[0.08] bg-black/[0.02] px-2.5 py-1 text-[11px] text-fg-muted transition hover:border-brand/30 hover:text-fg">
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, index) => (
          <div key={index} className="space-y-1.5">
            <p className="ml-auto w-fit max-w-[85%] rounded-xl rounded-br-sm bg-brand/10 px-3 py-1.5 text-[12.5px] text-fg">
              {turn.question}
            </p>

            {turn.response === null && turn.error === null && (
              <p className="flex items-center gap-1.5 text-[11.5px] text-fg-subtle">
                <Loader2 className="size-3 animate-spin" /> Looking through the records…
              </p>
            )}

            {turn.error && (
              <p className="rounded-xl border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-[12px] text-risk-high">
                {turn.error}
              </p>
            )}

            {turn.response && (
              <div className={`rounded-xl px-3 py-2 ${
                turn.response.refused
                  ? 'border border-risk-moderate/25 bg-risk-moderate/[0.07]'
                  : 'border border-black/[0.06] bg-black/[0.02]'}`}>
                <p className="text-[12.5px] leading-relaxed text-fg">{turn.response.answer}</p>

                {turn.response.refused && (
                  <p className="mt-1 flex items-center gap-1.5 text-[10.5px] text-risk-moderate">
                    <ShieldCheck className="size-3" /> The assistant explains; it does not act.
                  </p>
                )}

                {!turn.response.grounded && !turn.response.refused && turn.response.hint && (
                  <p className="mt-1 flex items-start gap-1.5 text-[10.5px] text-fg-subtle">
                    <AlertCircle className="mt-0.5 size-3 shrink-0" /> {turn.response.hint}
                  </p>
                )}

                {turn.response.grounded && (
                  <>
                    {/* The queries that produced the answer, named. An answer whose evidence a
                        reader can inspect is a different thing from one they must trust. */}
                    <p className="mt-1.5 font-mono text-[10px] text-fg-subtle">
                      Evidence: {turn.response.tools.join(', ')}
                    </p>
                    {onOpenRoute && routeIds(turn.response).length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {routeIds(turn.response).map((id) => (
                          <Button key={id} size="sm" variant="ghost"
                                  onClick={() => onOpenRoute(id)}>
                            View route RE-{id}
                          </Button>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="mt-2 flex gap-2 border-t border-black/[0.06] pt-2">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') void ask(question); }}
          placeholder="Ask about the safety data…"
          aria-label="Ask the safety assistant"
          disabled={busy}
          className="min-w-0 flex-1 rounded-lg border border-black/[0.08] bg-black/[0.02] px-3 py-2 text-xs text-fg outline-none transition placeholder:text-fg-subtle focus:border-brand/40 disabled:opacity-60"
        />
        <Button size="sm" variant="primary" icon={busy ? Loader2 : Send} loading={busy}
                onClick={() => void ask(question)}>
          Ask
        </Button>
      </div>
      <p className="mt-1.5 flex items-start gap-1.5 text-[10px] leading-relaxed text-fg-subtle">
        <MessageSquare className="mt-0.5 size-3 shrink-0" />
        Answers are drawn from stored records through fixed read-only queries. The assistant
        explains safety decisions; it never makes or changes them.
      </p>
    </div>
  );
}
