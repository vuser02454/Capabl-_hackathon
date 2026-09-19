/**
 * The environmental timeline.
 *
 * Scroll position is the single source of truth for the *story*: sun and moon, sky colour,
 * factory emergence, smoke, river debris, land waste, and the narrative all read from one 0→1
 * progress value. Nothing latches, so the whole sequence scrubs backwards exactly as it runs
 * forwards.
 *
 * The world's own life — drifting clouds, river flow, wind, rising smoke, debris travelling
 * downstream — is deliberately NOT on this timeline. Those are independent loops that keep
 * running when the visitor stops scrolling, and keep running in their normal direction even
 * while the story is being scrubbed backwards.
 */

export type PhaseId = 'healthy' | 'air' | 'water' | 'waste' | 'signals' | 'coordinator';

export interface Phase {
  id: PhaseId;
  start: number;
  end: number;
  title: string;
  support: string;
}

export const PHASES: Phase[] = [
  {
    id: 'healthy',
    start: 0,
    end: 0.15,
    title: 'The environment is always moving.',
    support: 'Every environment leaves signals.',
  },
  {
    id: 'air',
    start: 0.15,
    end: 0.35,
    title: 'Air tells the first story.',
    support: 'Particles accumulate before pollution becomes obvious.',
  },
  {
    id: 'water',
    start: 0.35,
    end: 0.55,
    title: 'Water remembers.',
    support: 'What enters the environment eventually becomes a signal.',
  },
  {
    id: 'waste',
    start: 0.55,
    end: 0.75,
    title: 'What we leave behind becomes a signal.',
    support: 'Visible waste becomes structured environmental intelligence.',
  },
  {
    id: 'signals',
    start: 0.75,
    end: 0.9,
    title: "The environment doesn't speak in isolation.",
    support: 'Individual signals become intelligence when they connect.',
  },
  {
    id: 'coordinator',
    start: 0.9,
    end: 1,
    title: 'Together, the signals tell a story.',
    support: 'Air, water and waste, reasoned over as one assessment.',
  },
];

/**
 * Signal identities for the landing experience. The dashboard keeps its own `AGENT_META`
 * palette; these are the semantic colours the story uses for cause and effect.
 */
export const SIGNAL_COLORS = {
  air: '#f0a742',
  water: '#4fc3e8',
  waste: '#a98bff',
  coordinator: '#2dd4bf',
} as const;

/**
 * Fade window for one phase's narrative. The outgoing headline finishes before the incoming
 * one starts — two headlines sharing a spot at half opacity reads as a smear, not a crossfade.
 * The first phase is already up at rest; the last stays put at the end.
 */
export function bandStops(phase: Phase, fade = 0.045): [number[], number[]] {
  const { start, end } = phase;
  return [
    [start, start + fade, end - fade, end],
    [start <= 0 ? 1 : 0, 1, 1, end >= 1 ? 1 : 0],
  ];
}

/**
 * Keyframe positions for the time-of-day ramp: midday, afternoon, golden hour, sunset, dusk,
 * night. Every colour array below is sampled at exactly these stops.
 */
export const SKY_STOPS = [0, 0.22, 0.42, 0.58, 0.76, 1];

/**
 * Palette.
 *
 * Structure and gradient treatment take after the reference still — every surface carries a
 * vertical gradient and a warm rim from a low sun — but the hues are EcoSentinel's own, and
 * they have to carry a full day→night arc rather than a single sunset.
 */
export const SKY_HIGH = ['#2d6f9e', '#33699a', '#3d5f8e', '#43406f', '#241d40', '#070912'];
export const SKY_MID = ['#77b4d2', '#89aec6', '#a68fae', '#a6608b', '#4b2f56', '#101427'];
export const SKY_LOW = ['#cfe7ef', '#e0ddda', '#f0c39b', '#f09a6d', '#8d4f62', '#1d2138'];

/** Warm key light on every lit edge — the reference's signature rim. */
export const LIGHT = ['#fdfaf0', '#fff3d8', '#ffd7a0', '#ff9e63', '#a5637a', '#38425e'];
export const SUN = ['#fffdf2', '#fff6d2', '#ffd98e', '#ff8f4d', '#e0603f', '#8a3d3d'];

export const RIDGE_FAR = ['#7e9fb8', '#86a0b4', '#9a94ad', '#96708f', '#42355c', '#141a2e'];
export const RIDGE_MID = ['#5c7f9b', '#628098', '#736f92', '#6e4f73', '#2e2547', '#0d1324'];
export const RIDGE_NEAR = ['#3c5f78', '#41617a', '#4e5273', '#4c365a', '#1f1937', '#080c1a'];

export const CANOPY = ['#1f5c37', '#245331', '#2f4632', '#33283c', '#181a30', '#070b16'];
export const CANOPY_LIT = ['#4d9c5c', '#4d8e4e', '#546d44', '#5a3f50', '#27263f', '#0c111f'];

export const WATER_LIT = ['#a6e2f2', '#a8d2e0', '#b9b3c8', '#bd8794', '#544a74', '#17223d'];
export const WATER_DEEP = ['#1f7ba0', '#2a6f88', '#3a5b78', '#433a5a', '#1a2040', '#070e1f'];

export const GROUND = ['#2b6440', '#2e5a39', '#3a4b37', '#3b2c40', '#1c1b33', '#080c18'];
export const ROCK = ['#4a5a68', '#4d5665', '#574c62', '#4f3550', '#231e38', '#0a0e1b'];

/** Distant city and industry: unlit masses by day, warm windows after dark. */
export const CITY = ['#8fa8bd', '#93a3b6', '#9b8fa8', '#7a5876', '#2b2447', '#101528'];
export const FACTORY = ['#7d94a8', '#8290a2', '#8a7f97', '#6b4d68', '#251f3e', '#0d1222'];
