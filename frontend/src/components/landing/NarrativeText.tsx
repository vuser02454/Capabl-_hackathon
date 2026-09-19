/**
 * The narrative layer.
 *
 * Each phase's copy is a pure function of scroll position: it fades in as its phase opens and
 * out as the next one arrives. Nothing is triggered on entering the viewport, so scrolling
 * back up crossfades the text in reverse with no special handling.
 *
 * Centred, bold, plain white — a simple caption over the scene rather than a styled panel.
 */
import { motion, useTransform } from 'framer-motion';
import { bandStops, PHASES, type Phase } from './scrollStory';
import type { ScrollStory } from './useScrollStory';

function PhaseCopy({ phase, story, narrow }: { phase: Phase; story: ScrollStory; narrow: boolean }) {
  const [input, output] = bandStops(phase);
  const opacity = useTransform(story.progress, input, output, { clamp: true });
  // A small counter-drift as the copy arrives and leaves, so the crossfade has direction.
  const y = useTransform(story.progress, input, [20, 0, 0, -20], { clamp: true });

  return (
    <motion.div
      style={{ opacity, y }}
      className="pointer-events-none absolute inset-x-0 top-0 flex flex-col items-center text-center"
    >
      <h2
        className={
          narrow
            ? 'text-[clamp(1.6rem,7vw,2.2rem)] leading-[1.15] font-bold tracking-tight text-balance'
            : 'text-[clamp(2rem,3.6vw,3.2rem)] leading-[1.15] font-bold tracking-tight text-balance'
        }
        style={{ textShadow: '0 2px 24px rgb(0 0 0 / 0.6)' }}
      >
        {phase.title}
      </h2>
      <p
        className="mt-3 max-w-md text-[14px] leading-relaxed text-white/80"
        style={{ textShadow: '0 1px 14px rgb(0 0 0 / 0.7)' }}
      >
        {phase.support}
      </p>
    </motion.div>
  );
}

export function NarrativeText({ story, narrow }: { story: ScrollStory; narrow: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center px-6">
      {/* The phases are stacked and crossfaded in place, so the block never reflows. */}
      <div className="relative h-56 w-full max-w-xl">
        {PHASES.map((phase) => (
          <PhaseCopy key={phase.id} phase={phase} story={story} narrow={narrow} />
        ))}
      </div>
    </div>
  );
}
