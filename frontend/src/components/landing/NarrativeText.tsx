/**
 * The narrative layer.
 *
 * Each phase's copy is a pure function of scroll position: it fades in as its phase opens and
 * out as the next one arrives. Nothing is triggered on entering the viewport, so scrolling
 * back up crossfades the text in reverse with no special handling.
 */
import { motion, useTransform } from 'framer-motion';
import { bandStops, PHASES, type Phase } from './scrollStory';
import type { ScrollStory } from './useScrollStory';

function PhaseCopy({ phase, story, narrow }: { phase: Phase; story: ScrollStory; narrow: boolean }) {
  const [input, output] = bandStops(phase);
  const opacity = useTransform(story.progress, input, output, { clamp: true });
  // A small counter-drift as the copy arrives and leaves, so the crossfade has direction.
  const y = useTransform(story.progress, input, [16, 0, 0, -16], { clamp: true });

  return (
    <motion.div
      style={{ opacity, y }}
      className="pointer-events-none absolute inset-x-0 top-0"
    >
      <h2
        className={
          narrow
            ? 'text-[clamp(1.5rem,7vw,2.1rem)] leading-[1.1] font-semibold tracking-tight text-balance'
            : 'text-[clamp(1.9rem,3.6vw,3.2rem)] leading-[1.05] font-semibold tracking-tight text-balance'
        }
        style={{ textShadow: '0 2px 20px rgb(0 0 0 / 0.55)' }}
      >
        {phase.title}
      </h2>
      <p
        className="mt-3 max-w-md text-[13.5px] leading-relaxed text-white/72"
        style={{ textShadow: '0 1px 12px rgb(0 0 0 / 0.6)' }}
      >
        {phase.support}
      </p>
    </motion.div>
  );
}

export function NarrativeText({ story, narrow }: { story: ScrollStory; narrow: boolean }) {
  return (
    <div
      className={
        narrow
          ? 'pointer-events-none absolute inset-x-0 top-[32%] z-20 px-5'
          : 'pointer-events-none absolute top-[30%] left-0 z-20 w-[44%] max-w-xl px-8 lg:px-14'
      }
    >
      {/* The phases are stacked and crossfaded in place, so the block never reflows. */}
      <div className="relative h-52">
        {PHASES.map((phase) => (
          <PhaseCopy key={phase.id} phase={phase} story={story} narrow={narrow} />
        ))}
      </div>
    </div>
  );
}
