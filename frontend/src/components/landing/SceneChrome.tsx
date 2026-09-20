/**
 * Fixed chrome over the scene: navigation, the scroll/phase indicator and system telemetry.
 * All of it routes through the application's existing navigation rather than its own links.
 */
import { motion, useTransform } from 'framer-motion';
import { cn } from '../../lib/format';
import { Logo } from '../layout/Logo';
import { PHASES } from './scrollStory';
import type { ScrollStory } from './useScrollStory';

export function FixedNavigation({ onDashboard, onHowItWorks }: { onDashboard: () => void; onHowItWorks: () => void }) {
  return (
    <header className="pointer-events-none absolute inset-x-0 top-0 z-40 flex items-center justify-between gap-4 px-4 py-4 sm:px-8">
      <div className="pointer-events-auto flex items-center gap-2.5">
        <Logo size={30} />
        <span className="text-sm font-semibold tracking-tight" style={{ textShadow: '0 1px 8px rgb(0 0 0 / 0.6)' }}>
          EcoSentinel <span className="text-white/55">AI</span>
        </span>
      </div>
      <nav className="pointer-events-auto flex items-center gap-1.5">
        <button
          type="button"
          onClick={onHowItWorks}
          className="hidden rounded-lg px-3 py-1.5 text-xs font-semibold text-white/70 transition-colors hover:text-white focus-visible:ring-2 focus-visible:ring-white/70 focus-visible:outline-none sm:block"
        >
          How it works
        </button>
        <button
          type="button"
          onClick={onDashboard}
          className="rounded-lg border border-white/20 bg-black/25 px-3 py-1.5 text-xs font-semibold text-white backdrop-blur-sm transition-colors hover:bg-black/45 focus-visible:ring-2 focus-visible:ring-white/70 focus-visible:outline-none"
        >
          Dashboard
        </button>
      </nav>
    </header>
  );
}

/**
 * Phase rail. Doubles as a map of the story — the visitor can see how far through the
 * environmental timeline they are, and which signal is currently being told.
 */
export function ScrollProgressIndicator({ story, narrow }: { story: ScrollStory; narrow: boolean }) {
  const scale = useTransform(story.progress, [0, 1], [0, 1]);

  if (narrow) {
    return (
      <div className="pointer-events-none absolute inset-x-0 top-0 z-40 h-0.5 bg-white/10">
        <motion.div className="h-full origin-left bg-brand" style={{ scaleX: scale }} />
      </div>
    );
  }

  return (
    <div className="pointer-events-none absolute top-1/2 right-6 z-40 hidden -translate-y-1/2 lg:block">
      <div className="relative h-56 w-px bg-white/15">
        <motion.div className="absolute inset-x-0 top-0 h-full origin-top bg-brand" style={{ scaleY: scale }} />
        {PHASES.map((phase) => (
          <PhaseTick key={phase.id} phase={phase} story={story} />
        ))}
      </div>
    </div>
  );
}

function PhaseTick({ phase, story }: { phase: (typeof PHASES)[number]; story: ScrollStory }) {
  const active = useTransform(
    story.progress,
    [phase.start - 0.02, phase.start + 0.02, phase.end - 0.02, phase.end + 0.02],
    [0.35, 1, 1, 0.35],
    { clamp: true },
  );
  const mid = (phase.start + phase.end) / 2;

  return (
    <motion.span
      className="absolute right-0 flex translate-x-1/2 items-center"
      style={{ top: `${mid * 100}%`, opacity: active }}
    >
      <span className="size-1.5 rounded-full bg-brand" />
      <span className="absolute right-4 font-mono text-[8.5px] tracking-[0.16em] whitespace-nowrap text-white/70 uppercase">
        {phase.id}
      </span>
    </motion.span>
  );
}

export function TelemetryStrip({
  location,
  mode,
  coordinatorOnline,
  running,
  hidden,
}: {
  location: string;
  mode: 'demo' | 'live';
  coordinatorOnline: boolean;
  running: boolean;
  hidden: boolean;
}) {
  // Labels only. The values, their conditions and the dynamic location are unchanged.
  const items: Array<[string, string]> = [
    ['Safety intelligence', running ? 'Scanning' : 'Live'],
    ['Safety agents', 'Active'],
    ['Safety analyst', coordinatorOnline ? 'Online' : 'Awaiting'],
    ['Incident data', mode === 'demo' ? 'Demo' : 'Live'],
    ['Location', location],
  ];

  return (
    <div
      className={cn(
        'pointer-events-none absolute inset-x-0 bottom-0 z-30 hidden border-t border-white/10 bg-black/30 backdrop-blur-md transition-opacity duration-300 sm:block',
        hidden && 'opacity-0',
      )}
    >
      <dl className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-x-6 gap-y-1 px-8 py-2.5">
        {items.map(([label, value]) => (
          <div key={label} className="flex items-baseline gap-2">
            <dt className="font-mono text-[9px] tracking-[0.16em] text-white/45 uppercase">{label}</dt>
            <dd className="font-mono text-[10.5px] font-semibold tracking-wider text-white/80 uppercase">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
