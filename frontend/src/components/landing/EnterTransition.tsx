/**
 * Cinematic hand-off from the environment into an agent.
 *
 * Clicking a zone does not change the URL straight away — the camera travels into that part
 * of the environment first (atmosphere for air, a fluid ripple for water, a detection sweep
 * for waste), then the route changes. Under reduced motion this collapses to a short fade.
 */
import { motion } from 'framer-motion';
import { useEffect } from 'react';
import type { Detection } from '../../types/agents';
import { SIGNAL_COLORS } from './scrollStory';
import type { EnterTarget } from './types';

const TARGETS: Record<EnterTarget, { label: string; caption: string; color: string }> = {
  air: { label: 'Air Agent', caption: 'Entering atmosphere', color: SIGNAL_COLORS.air },
  water: { label: 'Water Agent', caption: 'Following the water', color: SIGNAL_COLORS.water },
  waste: { label: 'Waste Agent', caption: 'Scanning for objects', color: SIGNAL_COLORS.waste },
  dashboard: { label: 'EcoSentinel', caption: 'Activating agents', color: SIGNAL_COLORS.coordinator },
};

const PARTICLES = Array.from({ length: 18 }, (_, index) => ({
  x: (index * 37) % 100,
  delay: (index % 6) * 0.06,
  size: 2 + (index % 3),
}));

const ACTIVATION = ['Air Agent', 'Water Agent', 'Waste Agent', 'Coordinator'];

export function EnterTransition({
  target,
  detections,
  reduced,
  onComplete,
}: {
  target: EnterTarget;
  /** Real waste detections, used for the scan frame. Empty = sweep only, no boxes drawn. */
  detections: Detection[];
  reduced: boolean;
  onComplete: () => void;
}) {
  const meta = TARGETS[target];
  const duration = reduced ? 260 : 1250;

  useEffect(() => {
    const timer = window.setTimeout(onComplete, duration);
    return () => window.clearTimeout(timer);
  }, [duration, onComplete]);

  return (
    <motion.div
      className="fixed inset-0 z-90 overflow-hidden"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
      role="status"
      aria-live="polite"
    >
      <div className="absolute inset-0 bg-ink-950/82 backdrop-blur-md" />

      {/* Camera push toward the selected zone */}
      <motion.div
        className="absolute inset-0"
        initial={{ scale: 1, opacity: 0.9 }}
        animate={reduced ? { opacity: 1 } : { scale: 2.6, opacity: 0 }}
        transition={{ duration: duration / 1000, ease: [0.5, 0, 0.75, 0] }}
        style={{
          background: `radial-gradient(38rem 26rem at 50% 50%, ${meta.color}2e, transparent 68%)`,
        }}
      />

      {target === 'water' && !reduced && (
        <>
          {[0, 1, 2].map((index) => (
            <motion.div
              key={index}
              className="absolute top-1/2 left-1/2 rounded-full border"
              style={{ borderColor: `${meta.color}55` }}
              initial={{ width: 80, height: 80, x: '-50%', y: '-50%', opacity: 0.7 }}
              animate={{ width: 1600, height: 1600, opacity: 0 }}
              transition={{ duration: 1.1, delay: index * 0.22, ease: 'easeOut' }}
            />
          ))}
          <motion.div
            className="absolute inset-x-0 bottom-0"
            style={{ background: `linear-gradient(0deg, ${meta.color}44, transparent)` }}
            initial={{ height: 0 }}
            animate={{ height: '100%' }}
            transition={{ duration: 1.1, ease: [0.4, 0, 0.2, 1] }}
          />
        </>
      )}

      {target === 'air' && !reduced && (
        <div className="absolute inset-0">
          {PARTICLES.map((particle, index) => (
            <motion.span
              key={index}
              className="absolute rounded-full"
              style={{
                left: `${particle.x}%`,
                width: particle.size,
                height: particle.size,
                background: meta.color,
                boxShadow: `0 0 10px ${meta.color}`,
              }}
              initial={{ top: '105%', opacity: 0 }}
              animate={{ top: '-10%', opacity: [0, 0.8, 0] }}
              transition={{ duration: 1.2, delay: particle.delay, ease: 'easeOut' }}
            />
          ))}
        </div>
      )}

      {target === 'waste' && !reduced && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="relative aspect-video w-[min(70vw,720px)] overflow-hidden rounded-xl border border-white/10">
            <motion.div
              className="absolute inset-x-0 h-0.5"
              style={{ background: meta.color, boxShadow: `0 0 18px ${meta.color}` }}
              initial={{ top: '0%' }}
              animate={{ top: '100%' }}
              transition={{ duration: 1.1, ease: 'easeInOut' }}
            />
            {/* Boxes are drawn only from detections the Waste Agent actually returned. */}
            {detections.slice(0, 6).map((detection, index) => (
              <motion.div
                key={detection.id}
                className="absolute border"
                style={{
                  left: `${detection.bbox[0] * 100}%`,
                  top: `${detection.bbox[1] * 100}%`,
                  width: `${detection.bbox[2] * 100}%`,
                  height: `${detection.bbox[3] * 100}%`,
                  borderColor: meta.color,
                }}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.2, delay: 0.25 + index * 0.08 }}
              >
                <span
                  className="absolute -top-4 left-0 font-mono text-[9px] whitespace-nowrap"
                  style={{ color: meta.color }}
                >
                  {detection.label.toUpperCase()} {detection.confidence.toFixed(2)}
                </span>
              </motion.div>
            ))}
          </div>
        </div>
      )}

      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center">
        <motion.p
          className="eyebrow"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          {meta.caption}
        </motion.p>
        <motion.p
          className="text-2xl font-semibold tracking-tight sm:text-3xl"
          style={{ color: meta.color }}
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.35, delay: 0.14 }}
        >
          {meta.label}
        </motion.p>

        {target === 'dashboard' && (
          <div className="mt-2 flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
            {ACTIVATION.map((name, index) => (
              <motion.span
                key={name}
                className="font-mono text-[10px] tracking-wider text-fg-muted"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.2, delay: 0.25 + index * 0.16 }}
              >
                {name} ·<span className="text-brand"> online</span>
              </motion.span>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
