/**
 * Airborne motes.
 *
 * Drift is a continuous CSS loop — it keeps running when the visitor stops scrolling — while
 * how *many* are visible and how dirty they look is scroll-driven, so the air phase reads as
 * accumulating particulate rather than decorative sparkle. Deliberately a handful of elements
 * rather than a particle system.
 */
import { motion, useTransform } from 'framer-motion';
import type { ScrollStory } from './useScrollStory';

const MOTES = Array.from({ length: 18 }, (_, index) => ({
  left: (index * 5.7 + 3) % 100,
  delay: (index * 1.9) % 18,
  duration: 15 + (index % 6) * 3.5,
  size: 1.5 + (index % 3),
}));

export function EnvironmentalParticles({ story, reduced }: { story: ScrollStory; reduced: boolean }) {
  // Always faintly present; markedly denser and dirtier once the air phase gets going.
  const opacity = useTransform(story.pollution, [0, 1], [0.18, 0.7]);
  const color = useTransform(story.pollution, [0, 1], ['#e8f4f0', '#c9b79a']);

  if (reduced) return null;

  return (
    <motion.div className="pointer-events-none absolute inset-0 z-10 overflow-hidden" style={{ opacity }} aria-hidden>
      {MOTES.map((mote, index) => (
        <motion.span
          key={index}
          className="scene-mote"
          style={{
            left: `${mote.left}%`,
            width: mote.size,
            height: mote.size,
            background: color,
            animationDelay: `${mote.delay}s`,
            animationDuration: `${mote.duration}s`,
          }}
        />
      ))}
    </motion.div>
  );
}
