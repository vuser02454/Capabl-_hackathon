/**
 * Derives the whole environmental timeline from one scroll progress value.
 *
 * Everything here is a `MotionValue`, so scrubbing the story never re-renders React — values
 * are written straight to the DOM. Colours are published as CSS custom properties on the scene
 * wrapper, which SVG gradients read via `style={{ stopColor: 'var(--sky-high)' }}`; that keeps
 * a full day→night morph off the React render path too.
 */
import { useScroll, useSpring, useTransform, type MotionValue } from 'framer-motion';
import { useMemo, type RefObject } from 'react';
import {
  CANOPY,
  CANOPY_LIT,
  CITY,
  FACTORY,
  GROUND,
  LIGHT,
  RIDGE_FAR,
  RIDGE_MID,
  RIDGE_NEAR,
  ROCK,
  SKY_HIGH,
  SKY_LOW,
  SKY_MID,
  SKY_STOPS,
  SUN,
  WATER_DEEP,
  WATER_LIT,
} from './scrollStory';

export interface ScrollStory {
  progress: MotionValue<number>;
  /** Unsmoothed scroll fraction — 1:1 with the scrollbar, no spring lag. The frame sequence
   *  tracks this directly so the background never feels like it is catching up to the scroll. */
  rawProgress: MotionValue<number>;

  /** Cause → effect chain. Each drives the visible event, not a generic overlay. */
  /** Distant industry resolving out of the haze. */
  factories: MotionValue<number>;
  /** Windows and yard lamps coming on as daylight drops. */
  cityLights: MotionValue<number>;
  /** How hard the chimneys are working — plume opacity and size, not its motion. */
  smoke: MotionValue<number>;
  /** Airborne particulate, downstream of the smoke. */
  pollution: MotionValue<number>;
  /** How much litter is riding the current. */
  riverWaste: MotionValue<number>;
  /** Water clarity lost, downstream of the river litter. */
  turbidity: MotionValue<number>;
  /** Litter accumulating on the bank. */
  landWaste: MotionValue<number>;
  /** The three signals resolving into a network. */
  signals: MotionValue<number>;

  /** Celestial positions, in scene viewBox units. */
  sunX: MotionValue<number>;
  sunY: MotionValue<number>;
  sunOpacity: MotionValue<number>;
  moonX: MotionValue<number>;
  moonY: MotionValue<number>;
  moonOpacity: MotionValue<number>;
  starOpacity: MotionValue<number>;
  hazeOpacity: MotionValue<number>;

  /** Cinematic camera: a slow push toward the vanishing point. */
  cameraScale: MotionValue<number>;
  cameraY: MotionValue<number>;

  colorVars: Record<string, MotionValue<string>>;
}

export function useScrollStory(targetRef: RefObject<HTMLElement | null>): ScrollStory {
  const { scrollYProgress } = useScroll({ target: targetRef, offset: ['start start', 'end end'] });

  // A light spring smooths wheel/trackpad jitter without adding lag or breaking reversibility.
  const progress = useSpring(scrollYProgress, { stiffness: 180, damping: 38, mass: 0.35 });

  // Written out rather than generated in a loop, so every `useTransform` call is unconditional
  // and the hook order can never shift between renders.

  // ── The causal chain: industry → smoke → air ──────────────────
  const factories = useTransform(progress, [0.34, 0.6], [0, 1], { clamp: true });
  const cityLights = useTransform(progress, [0.4, 0.66], [0, 1], { clamp: true });
  const smoke = useTransform(progress, [0.46, 0.78], [0, 1], { clamp: true });
  // Particulate lags the smoke that causes it.
  const pollution = useTransform(progress, [0.52, 0.86], [0, 1], { clamp: true });

  // ── Dumping → river litter → water quality ───────────────────
  const riverWaste = useTransform(progress, [0.44, 0.74], [0, 1], { clamp: true });
  // Turbidity lags the litter entering the water.
  const turbidity = useTransform(progress, [0.5, 0.82], [0, 1], { clamp: true });

  // ── Dumping → land waste ─────────────────────────────────────
  const landWaste = useTransform(progress, [0.55, 0.82], [0, 1], { clamp: true });

  const signals = useTransform(progress, [0.74, 0.88], [0, 1], { clamp: true });

  // The sun tracks a shallow arc and sets behind the ridge (horizon ≈ y 560).
  const sunX = useTransform(progress, [0, 1], [250, 1210]);
  const sunY = useTransform(progress, [0, 0.42, 0.58, 0.76, 1], [128, 250, 470, 610, 700]);
  const sunOpacity = useTransform(progress, [0, 0.6, 0.74, 0.84], [1, 1, 0.5, 0]);

  // The moon rises on the opposite side as the sun goes down.
  const moonX = useTransform(progress, [0.5, 1], [1120, 430]);
  const moonY = useTransform(progress, [0.5, 1], [660, 160]);
  const moonOpacity = useTransform(progress, [0.55, 0.78, 1], [0, 0.7, 1]);
  const starOpacity = useTransform(progress, [0.6, 0.94], [0, 1], { clamp: true });

  const hazeOpacity = useTransform(pollution, [0, 1], [0.05, 0.6]);

  // Camera: a slow, shallow push toward the vanishing point. Small on purpose — the reference's
  // move is a drift, not a zoom, and anything larger gets dizzying over a long scroll.
  const cameraScale = useTransform(progress, [0, 1], [1, 1.14]);
  const cameraY = useTransform(progress, [0, 1], [0, -26]);

  const skyHigh = useTransform(progress, SKY_STOPS, SKY_HIGH);
  const skyMid = useTransform(progress, SKY_STOPS, SKY_MID);
  const skyLow = useTransform(progress, SKY_STOPS, SKY_LOW);
  const light = useTransform(progress, SKY_STOPS, LIGHT);
  const sun = useTransform(progress, SKY_STOPS, SUN);
  const ridgeFar = useTransform(progress, SKY_STOPS, RIDGE_FAR);
  const ridgeMid = useTransform(progress, SKY_STOPS, RIDGE_MID);
  const ridgeNear = useTransform(progress, SKY_STOPS, RIDGE_NEAR);
  const canopy = useTransform(progress, SKY_STOPS, CANOPY);
  const canopyLit = useTransform(progress, SKY_STOPS, CANOPY_LIT);
  const waterLit = useTransform(progress, SKY_STOPS, WATER_LIT);
  const waterDeep = useTransform(progress, SKY_STOPS, WATER_DEEP);
  const ground = useTransform(progress, SKY_STOPS, GROUND);
  const rock = useTransform(progress, SKY_STOPS, ROCK);
  const city = useTransform(progress, SKY_STOPS, CITY);
  const factory = useTransform(progress, SKY_STOPS, FACTORY);
  // Plumes read pale against a bright sky and dirty against a dark one.
  const smokeTint = useTransform(progress, [0, 0.5, 1], ['#e8eef2', '#d8c3ae', '#6d6470']);
  // Warm underlight on the plume base, only once the yard lights are actually on.
  const ember = useTransform(cityLights, [0, 1], ['#caa98a', '#ff9d3c']);

  const colorVars = useMemo(
    () => ({
      '--sky-high': skyHigh,
      '--sky-mid': skyMid,
      '--sky-low': skyLow,
      '--light': light,
      '--sun': sun,
      '--ridge-far': ridgeFar,
      '--ridge-mid': ridgeMid,
      '--ridge-near': ridgeNear,
      '--canopy': canopy,
      '--canopy-lit': canopyLit,
      '--water-lit': waterLit,
      '--water-deep': waterDeep,
      '--ground': ground,
      '--rock': rock,
      '--city': city,
      '--factory': factory,
      '--smoke': smokeTint,
      '--ember': ember,
    }),
    [skyHigh, skyMid, skyLow, light, sun, ridgeFar, ridgeMid, ridgeNear, canopy, canopyLit,
     waterLit, waterDeep, ground, rock, city, factory, smokeTint, ember],
  );

  return {
    progress,
    rawProgress: scrollYProgress,
    factories,
    cityLights,
    smoke,
    pollution,
    riverWaste,
    turbidity,
    landWaste,
    signals,
    sunX,
    sunY,
    sunOpacity,
    moonX,
    moonY,
    moonOpacity,
    starOpacity,
    hazeOpacity,
    cameraScale,
    cameraY,
    colorVars,
  };
}
