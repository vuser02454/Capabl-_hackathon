/**
 * The three environmental objects, clickable throughout the whole journey.
 *
 * Interaction is deliberately independent of the scroll story: a hotspot never becomes
 * inert, never moves out from under the cursor mid-click, and always routes through the
 * application's existing navigation. Scroll only changes how strongly each zone is
 * emphasised — its own phase brings it forward.
 */
import { AnimatePresence, motion, useTransform } from 'framer-motion';
import { cn } from '../../lib/format';
import { HotspotCard } from './HotspotCard';
import { NARROW_BOX, WIDE_BOX, ZONE_ANCHORS } from './EnvironmentalScene';
import type { HotspotData } from './environmentState';
import { PHASES, SIGNAL_COLORS } from './scrollStory';
import type { Zone } from './types';
import type { ScrollStory } from './useScrollStory';
import { useSceneProjection } from './useSceneInteraction';
import type { RefObject } from 'react';

/** Each zone's phase, used to bring it forward while its part of the story is on screen. */
const PHASE_FOR: Record<Zone, { start: number; end: number }> = {
  air: PHASES[1],
  water: PHASES[2],
  waste: PHASES[3],
};

function Hotspot({
  zone,
  data,
  story,
  point,
  ready,
  active,
  touch,
  onActivate,
  onEnter,
}: {
  zone: Zone;
  data: HotspotData;
  story: ScrollStory;
  point: { left: number; top: number };
  ready: boolean;
  active: boolean;
  touch: boolean;
  onActivate: (zone: Zone | null) => void;
  onEnter: (zone: Zone) => void;
}) {
  const phase = PHASE_FOR[zone];
  // Emphasis peaks across the zone's own phase, then settles back — never to invisible.
  const emphasis = useTransform(
    story.progress,
    [phase.start - 0.08, phase.start + 0.05, phase.end - 0.02, phase.end + 0.08],
    [0.55, 1, 1, 0.62],
    { clamp: true },
  );
  const color = SIGNAL_COLORS[zone];

  return (
    <div
      className="absolute z-20"
      style={{ left: point.left, top: point.top, transform: 'translate(-50%, -50%)', opacity: ready ? 1 : 0 }}
    >
      <motion.button
        type="button"
        aria-label={`${data.title} — ${data.tag}. ${data.hasData ? `Risk ${data.riskLevel}` : 'Awaiting analysis'}`}
        aria-expanded={active}
        onPointerEnter={(event) => event.pointerType === 'mouse' && onActivate(zone)}
        onPointerLeave={(event) => event.pointerType === 'mouse' && onActivate(null)}
        // Only keyboard focus opens the card; a touch tap must not, or the first tap would
        // both preview and navigate.
        onFocus={(event) => event.currentTarget.matches(':focus-visible') && onActivate(zone)}
        onClick={() => (touch && !active ? onActivate(zone) : onEnter(zone))}
        style={{ ['--zone' as string]: color, opacity: emphasis }}
        className="group relative grid min-h-11 min-w-11 cursor-pointer place-items-center rounded-full focus-visible:ring-2 focus-visible:ring-white/80 focus-visible:outline-none"
      >
        <span className={cn('sensor-ring', active && 'sensor-ring-active')} aria-hidden />
        <span className="sensor-core" aria-hidden />
        <span
          className={cn(
            'absolute top-[calc(50%+18px)] font-mono text-[9.5px] font-semibold tracking-[0.18em] whitespace-nowrap uppercase transition-opacity duration-300',
            active ? 'opacity-100' : 'opacity-0 group-hover:opacity-80',
          )}
          style={{ color, textShadow: '0 1px 6px rgb(0 0 0 / 0.8)' }}
        >
          {data.tag}
        </span>
      </motion.button>

      <AnimatePresence>
        {active && !touch && (
          <HotspotCard
            key={zone}
            data={data}
            onEnter={() => onEnter(zone)}
            className={cn(
              'absolute z-30',
              zone === 'air' && 'top-8 left-8',
              zone === 'water' && 'bottom-8 left-8',
              zone === 'waste' && 'right-8 bottom-8',
            )}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

export function EnvironmentalHotspots({
  sceneRef,
  hotspots,
  story,
  narrow,
  touch,
  active,
  onActivate,
  onEnter,
}: {
  sceneRef: RefObject<HTMLElement | null>;
  hotspots: Record<Zone, HotspotData>;
  story: ScrollStory;
  narrow: boolean;
  touch: boolean;
  active: Zone | null;
  onActivate: (zone: Zone | null) => void;
  onEnter: (zone: Zone) => void;
}) {
  const projection = useSceneProjection(sceneRef, narrow ? NARROW_BOX : WIDE_BOX);
  const anchors = narrow ? ZONE_ANCHORS.narrow : ZONE_ANCHORS.wide;
  const zones: Zone[] = ['air', 'water', 'waste'];

  return (
    <>
      {zones.map((zone) => (
        <Hotspot
          key={zone}
          zone={zone}
          data={hotspots[zone]}
          story={story}
          point={projection.project(anchors[zone].x, anchors[zone].y)}
          ready={projection.ready}
          active={active === zone}
          touch={touch}
          onActivate={onActivate}
          onEnter={onEnter}
        />
      ))}

      {/* Touch readout sheet */}
      <AnimatePresence>
        {active && touch && (
          <motion.div
            className="absolute inset-x-0 bottom-0 z-40 flex justify-center px-4 pb-6"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 24 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          >
            <HotspotCard data={hotspots[active]} onEnter={() => onEnter(active)} className="w-full max-w-sm" compact />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
