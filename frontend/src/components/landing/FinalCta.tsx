/** Closing call to action — the hand-off into the dashboard and a live analysis run. */
import { motion } from 'framer-motion';
import { ArrowRight, Play } from 'lucide-react';
import { SIGNAL_COLORS } from './scrollStory';

const CHAIN = [
  { label: 'Air Agent', color: SIGNAL_COLORS.air },
  { label: 'Water Agent', color: SIGNAL_COLORS.water },
  { label: 'Waste Agent', color: SIGNAL_COLORS.waste },
  { label: 'Coordinator', color: SIGNAL_COLORS.coordinator },
];

export function FinalCta({ onStart, onDashboard }: { onStart: () => void; onDashboard: () => void }) {
  return (
    <section className="relative overflow-hidden bg-ink-950 px-4 py-28 sm:px-8 sm:py-36">
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-[60%]"
        style={{ background: 'radial-gradient(44rem 24rem at 50% 0%, rgb(45 212 191 / 0.12), transparent 70%)' }}
        aria-hidden
      />

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: '-80px' }}
        transition={{ duration: 0.65, ease: [0.16, 1, 0.3, 1] }}
        className="relative mx-auto max-w-2xl text-center"
      >
        <h2 className="text-[clamp(1.9rem,5vw,3.2rem)] leading-[1.08] font-semibold tracking-tight text-balance">
          The environment is always speaking.
          <br />
          <span className="text-brand">EcoSentinel listens.</span>
        </h2>

        <p className="mx-auto mt-5 max-w-md text-[13.5px] leading-relaxed text-fg-muted">
          Turn environmental signals into actionable intelligence.
        </p>

        <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            onClick={onStart}
            className="inline-flex h-12 items-center gap-2.5 rounded-xl bg-linear-to-b from-brand to-brand-strong px-6 text-sm font-semibold text-ink-950 shadow-[0_0_0_1px_rgb(45_212_191/0.45),0_14px_36px_-12px_rgb(45_212_191/0.7)] transition-[filter] hover:brightness-110 focus-visible:ring-2 focus-visible:ring-brand/60 focus-visible:outline-none"
          >
            <Play className="size-4" />
            Start environmental analysis
          </button>
          <button
            type="button"
            onClick={onDashboard}
            className="inline-flex h-12 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-6 text-sm font-semibold text-fg transition-colors hover:bg-white/[0.09] focus-visible:ring-2 focus-visible:ring-brand/60 focus-visible:outline-none"
          >
            Open dashboard
            <ArrowRight className="size-4" />
          </button>
        </div>

        <ul className="mt-10 flex flex-wrap items-center justify-center gap-x-3 gap-y-2">
          {CHAIN.map((agent, index) => (
            <li key={agent.label} className="flex items-center gap-3">
              <span className="flex items-center gap-1.5 font-mono text-[10.5px] tracking-wider text-fg-subtle uppercase">
                <span className="size-1.5 rounded-full" style={{ background: agent.color }} />
                {agent.label}
              </span>
              {index < CHAIN.length - 1 && <span className="text-fg-subtle/40">·</span>}
            </li>
          ))}
        </ul>
      </motion.div>
    </section>
  );
}
