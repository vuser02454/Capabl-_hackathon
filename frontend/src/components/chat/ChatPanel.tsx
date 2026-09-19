/**
 * EcoSentinel chat — an interface into the analysis, not a general chatbot.
 *
 * Three things are rendered that an ordinary chat UI would not show, and each is deliberate:
 *
 * 1. **Tool executions.** Which tools ran, why, and a one-line result. This is what makes an
 *    answer checkable — a number in the prose can be traced to the tool that produced it. No
 *    prompt or routing rationale is shown: that is not verifiable by a reader, whereas "this
 *    tool ran and returned this" is.
 *
 * 2. **Citations.** Real corpus chunks with their chunk id and source file, expandable to the
 *    retrieved text itself. A citation that cannot be opened is worse than none.
 *
 * 3. **The route taken.** `analysis` answers come from the held decision; `functional` answers
 *    come from a tool; `general` answers come from the conversational model and have no access
 *    to the user's data. Collapsing those into one voice would let a general answer about
 *    eutrophication read like a finding about this river.
 *
 * With no analysis loaded the panel says so and still answers general questions, because that is
 * what the backend does — the UI does not pretend to a capability the server lacks.
 */
import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  Loader2,
  MessageSquare,
  RotateCcw,
  Send,
  Sparkles,
  Trash2,
  Wrench,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useSettings } from '../../context/SettingsContext';
import { cn } from '../../lib/format';
import { isAbortError, toAppError } from '../../services/errors';
import type { ChatCitation, ChatResponse, ChatToolExecution } from '../../types/environment';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  intent?: ChatResponse['intent'];
  source?: string;
  tools?: ChatToolExecution[];
  citations?: ChatCitation[];
  evidenceIds?: string[];
  failed?: boolean;
}

const SUGGESTIONS = [
  'What caused the current risk?',
  'Show water evidence',
  'What should I verify next?',
  'Show retrieved sources',
  'What is eutrophication?',
];

const INTENT_LABEL: Record<string, { label: string; tone: string }> = {
  analysis: { label: 'Grounded in this analysis', tone: 'text-brand' },
  functional: { label: 'Tool result', tone: 'text-risk-low' },
  general: { label: 'General knowledge — not your data', tone: 'text-fg-subtle' },
  unavailable: { label: 'Unavailable', tone: 'text-risk-moderate' },
};

function ToolRow({ execution }: { execution: ChatToolExecution }) {
  const ok = execution.status === 'ok';
  return (
    <li className="flex items-baseline gap-2 text-[11px]">
      {ok ? (
        <Check className="size-3 shrink-0 translate-y-0.5 text-risk-low" />
      ) : (
        <X className="size-3 shrink-0 translate-y-0.5 text-risk-high" />
      )}
      <span className="font-mono text-fg-muted">{execution.tool}</span>
      <span className="min-w-0 flex-1 truncate text-fg-subtle">
        {ok ? execution.summary || execution.purpose : execution.error}
      </span>
      {execution.durationMs > 0 && (
        <span className="tabular shrink-0 text-[10px] text-fg-subtle">{execution.durationMs} ms</span>
      )}
    </li>
  );
}

function Citation({ citation }: { citation: ChatCitation }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full rounded-lg border border-black/[0.06] bg-black/[0.02] px-2.5 py-1.5 text-left transition hover:bg-black/[0.05]"
      >
        <div className="flex items-center gap-1.5">
          <BookOpen className="size-3 shrink-0 text-amber-300/80" />
          <span className="min-w-0 flex-1 truncate text-[11px] text-fg-muted">
            {citation.documentTitle} — {citation.section}
          </span>
          <span className="tabular shrink-0 text-[10px] text-fg-subtle">
            {citation.score.toFixed(2)}
          </span>
          <ChevronDown className={cn('size-3 shrink-0 text-fg-subtle transition', open && 'rotate-180')} />
        </div>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.16 }}
              className="overflow-hidden"
            >
              <p className="mt-1.5 border-t border-black/[0.06] pt-1.5 font-mono text-[9.5px] text-fg-subtle">
                {citation.chunkId}
              </p>
              <p className="mt-1 text-[11px] leading-relaxed whitespace-pre-line text-fg-muted">
                {citation.content}
              </p>
              {citation.sourceFile && (
                <p className="mt-1 font-mono text-[9.5px] break-all text-fg-subtle">
                  Source: {citation.sourceFile}
                </p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </button>
    </li>
  );
}

export function ChatPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { api } = useSettings();
  const { state } = useAnalysis();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastQuestion = useRef<string>('');

  const analysisId = state.result?.analysisId ?? null;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, busy]);

  const send = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || busy) return;
      lastQuestion.current = trimmed;
      setInput('');
      setMessages((previous) => [
        ...previous,
        { id: `u-${Date.now()}`, role: 'user', text: trimmed },
      ]);
      setBusy(true);
      try {
        // An empty analysisId is still sent: the backend serves functional and general intents
        // without one, and only refuses questions about an analysis it does not hold.
        const response = await api.chat(analysisId ?? 'none', trimmed);
        setMessages((previous) => [
          ...previous,
          {
            id: `a-${Date.now()}`,
            role: 'assistant',
            text: response.answer,
            intent: response.intent,
            source: response.source,
            tools: response.toolExecutions,
            citations: response.citations,
            evidenceIds: response.evidenceIds,
          },
        ]);
      } catch (cause) {
        if (isAbortError(cause)) return;
        setMessages((previous) => [
          ...previous,
          {
            id: `e-${Date.now()}`,
            role: 'assistant',
            text: toAppError(cause).message,
            failed: true,
          },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [api, analysisId, busy],
  );

  if (!open) return null;

  return (
    <motion.aside
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: 0.22 }}
      className="fixed top-0 right-0 bottom-0 z-50 flex w-full max-w-[420px] flex-col border-l border-black/[0.08] bg-ink-950/95 backdrop-blur-xl"
      aria-label="EcoSentinel assistant"
    >
      {/* header */}
      <header className="flex items-center gap-2 border-b border-black/[0.08] px-4 py-3">
        <span className="grid size-8 place-items-center rounded-lg bg-brand/10 text-brand">
          <Sparkles className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-fg">EcoSentinel Assistant</p>
          <p className="truncate text-[10.5px] text-fg-subtle">
            {analysisId ? (
              <>
                Grounded in analysis{' '}
                <span className="font-mono">{analysisId.slice(0, 8)}</span>
              </>
            ) : (
              'No analysis loaded — general questions only'
            )}
          </p>
        </div>
        {messages.length > 0 && (
          <button
            type="button"
            onClick={() => setMessages([])}
            title="Clear conversation"
            className="rounded-lg p-1.5 text-fg-subtle transition hover:bg-black/[0.06] hover:text-fg"
          >
            <Trash2 className="size-3.5" />
          </button>
        )}
        <button
          type="button"
          onClick={onClose}
          title="Close"
          className="rounded-lg p-1.5 text-fg-subtle transition hover:bg-black/[0.06] hover:text-fg"
        >
          <X className="size-4" />
        </button>
      </header>

      {/* messages */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 && (
          <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-3">
            <p className="flex items-center gap-1.5 text-[12px] text-fg-muted">
              <MessageSquare className="size-3.5" /> Ask about this analysis, or anything
              environmental.
            </p>
            <p className="mt-1.5 text-[10.5px] leading-relaxed text-fg-subtle">
              Questions about your analysis are answered from its actual evidence. Tools run in
              Python and their results are shown. Nothing numeric is written by a language model.
            </p>
          </div>
        )}

        {messages.map((message) =>
          message.role === 'user' ? (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-brand/15 px-3 py-2 text-[12.5px] text-fg"
            >
              {message.text}
            </motion.div>
          ) : (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className={cn(
                'max-w-[92%] rounded-2xl rounded-bl-sm border px-3 py-2.5',
                message.failed
                  ? 'border-risk-high/25 bg-risk-high/[0.05]'
                  : 'border-black/[0.07] bg-black/[0.03]',
              )}
            >
              {message.failed ? (
                <>
                  <p className="flex items-start gap-1.5 text-[12px] text-risk-moderate">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                    <span>{message.text}</span>
                  </p>
                  <button
                    type="button"
                    onClick={() => void send(lastQuestion.current)}
                    className="mt-2 flex items-center gap-1 text-[11px] text-brand hover:underline"
                  >
                    <RotateCcw className="size-3" /> Retry
                  </button>
                </>
              ) : (
                <>
                  {/* Which route served this, so a general answer never reads as a finding. */}
                  {message.intent && (
                    <p
                      className={cn(
                        'mb-1.5 text-[9.5px] font-medium tracking-wider uppercase',
                        INTENT_LABEL[message.intent]?.tone ?? 'text-fg-subtle',
                      )}
                    >
                      {INTENT_LABEL[message.intent]?.label ?? message.intent}
                    </p>
                  )}

                  {message.tools && message.tools.length > 0 && (
                    <ul className="mb-2 space-y-0.5 rounded-lg border border-black/[0.05] bg-black/[0.02] px-2 py-1.5">
                      <li className="flex items-center gap-1.5 text-[9.5px] font-medium tracking-wider text-fg-subtle uppercase">
                        <Wrench className="size-2.5" /> Tools
                      </li>
                      {message.tools.map((tool) => (
                        <ToolRow key={`${tool.tool}-${tool.status}`} execution={tool} />
                      ))}
                    </ul>
                  )}

                  <p className="text-[12.5px] leading-relaxed whitespace-pre-line text-fg-muted">
                    {message.text}
                  </p>

                  {message.citations && message.citations.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      <li className="text-[9.5px] font-medium tracking-wider text-fg-subtle uppercase">
                        Sources
                      </li>
                      {message.citations.map((citation) => (
                        <Citation key={citation.chunkId} citation={citation} />
                      ))}
                    </ul>
                  )}

                  {message.evidenceIds && message.evidenceIds.length > 0 && (
                    <p className="mt-2 font-mono text-[9.5px] break-all text-fg-subtle">
                      Evidence: {message.evidenceIds.join(', ')}
                    </p>
                  )}
                </>
              )}
            </motion.div>
          ),
        )}

        {busy && (
          <p className="flex items-center gap-2 text-[11.5px] text-fg-subtle">
            <Loader2 className="size-3.5 animate-spin text-brand" /> Routing, running tools…
          </p>
        )}
      </div>

      {/* suggestions */}
      {messages.length === 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-2">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => void send(suggestion)}
              className="rounded-full border border-black/[0.08] bg-black/[0.02] px-2.5 py-1 text-[10.5px] text-fg-muted transition hover:bg-black/[0.06] hover:text-fg"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {/* composer */}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void send(input);
        }}
        className="flex items-end gap-2 border-t border-black/[0.08] px-4 py-3"
      >
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void send(input);
            }
          }}
          rows={1}
          placeholder="Ask about this analysis…"
          disabled={busy}
          className="max-h-28 min-h-[38px] flex-1 resize-none rounded-xl border border-black/[0.08] bg-black/[0.03] px-3 py-2 text-[12.5px] text-fg placeholder:text-fg-subtle focus:border-brand/40 focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="grid size-[38px] shrink-0 place-items-center rounded-xl bg-brand text-ink-950 transition disabled:opacity-35"
        >
          <Send className="size-4" />
        </button>
      </form>
    </motion.aside>
  );
}
