/**
 * The signal network — phases 5 and 6, overlaid on the scene.
 *
 * Three paths run from the environmental zones the visitor has just watched degrade and
 * converge on a single point. That convergence is the whole argument: air, water and waste
 * stop being separate observations and become one thing.
 *
 * The coordinator's actual assessment — risk level, score, confidence — deliberately does NOT
 * appear here. Those are analysis results, and they live on the dashboard. The landing makes
 * the case; the dashboard shows the numbers.
 */
import { motion, useTransform } from 'framer-motion';
import { NARROW_VIEWBOX, SCENE, ZONE_ANCHORS } from './EnvironmentalScene';
import { SIGNAL_COLORS } from './scrollStory';
import type { Zone } from './types';
import type { ScrollStory } from './useScrollStory';

const ORDER: Array<{ id: Zone; color: string; delay: number }> = [
  { id: 'air', color: SIGNAL_COLORS.air, delay: 0 },
  { id: 'water', color: SIGNAL_COLORS.water, delay: 0.12 },
  { id: 'waste', color: SIGNAL_COLORS.waste, delay: 0.24 },
];

function SignalPath({
  source,
  from,
  to,
  story,
}: {
  source: (typeof ORDER)[number];
  from: { x: number; y: number };
  to: { x: number; y: number };
  story: ScrollStory;
}) {
  // Each path draws itself over its own slice of the phase, so the three arrive in sequence.
  const length = useTransform(story.signals, [source.delay, source.delay + 0.5], [0, 1], { clamp: true });
  const opacity = useTransform(story.signals, [source.delay, source.delay + 0.2], [0, 0.8], { clamp: true });
  const d = `M${from.x} ${from.y} Q ${(from.x + to.x) / 2} ${from.y}, ${to.x} ${to.y}`;

  return (
    <>
      <motion.path d={d} fill="none" stroke={source.color} strokeWidth={2} style={{ pathLength: length, opacity }} />
      <motion.circle r={4} fill={source.color} style={{ opacity }}>
        <animateMotion dur="2.6s" repeatCount="indefinite" path={d} begin={`${source.delay * 4}s`} />
      </motion.circle>
    </>
  );
}

export function MultiSignalCoordinator({ story, narrow }: { story: ScrollStory; narrow: boolean }) {
  const networkOpacity = useTransform(story.signals, [0, 0.2, 1], [0, 0.9, 1], { clamp: true });
  // The meeting point is a soft bloom rather than a labelled node — it marks that the signals
  // join without turning the scene into a dashboard widget.
  const bloomOpacity = useTransform(story.signals, [0.5, 0.9], [0, 0.85], { clamp: true });
  const bloomScale = useTransform(story.signals, [0.5, 0.9], [0.6, 1], { clamp: true });

  const anchors = narrow ? ZONE_ANCHORS.narrow : ZONE_ANCHORS.wide;
  const center = anchors.coordinator;

  return (
    <motion.svg
      className="pointer-events-none absolute inset-0 z-10 h-full w-full"
      viewBox={narrow ? NARROW_VIEWBOX : `0 0 ${SCENE.w} ${SCENE.h}`}
      preserveAspectRatio="xMidYMid slice"
      style={{ opacity: networkOpacity }}
      aria-hidden
    >
      <defs>
        <radialGradient id="signalBloom" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor={SIGNAL_COLORS.coordinator} stopOpacity="0.55" />
          <stop offset="55%" stopColor={SIGNAL_COLORS.coordinator} stopOpacity="0.16" />
          <stop offset="100%" stopColor={SIGNAL_COLORS.coordinator} stopOpacity="0" />
        </radialGradient>
      </defs>

      {ORDER.map((source) => (
        <SignalPath key={source.id} source={source} from={anchors[source.id]} to={center} story={story} />
      ))}

      <motion.g style={{ opacity: bloomOpacity, scale: bloomScale, transformOrigin: `${center.x}px ${center.y}px` }}>
        <circle cx={center.x} cy={center.y} r={132} fill="url(#signalBloom)" />
        <circle cx={center.x} cy={center.y} r={7} fill={SIGNAL_COLORS.coordinator} opacity={0.9} />
      </motion.g>
    </motion.svg>
  );
}
