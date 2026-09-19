/**
 * The living environment — one persistent place, seen from one fixed viewpoint.
 *
 * Composition follows the reference still's structure: a one-point perspective with the river
 * running to a vanishing point, masses receding on both banks, layered ridges filling the gap,
 * and dark rock framing the foreground. The hues are EcoSentinel's own and carry a full
 * day→night arc.
 *
 * Two independent systems drive it:
 *
 *   scroll-driven  sun, moon, stars, sky, factory emergence, smoke density, litter counts,
 *                  water clarity, camera push — all reversible, nothing latched
 *   always looping cloud drift, river flow, wind, rising smoke, debris travelling downstream
 *
 * The loops never reverse: scrub the story backwards and the river still runs downstream.
 * Colours arrive as CSS custom properties, so the whole morph costs no React renders.
 */
import { motion, useTransform, type MotionValue } from 'framer-motion';
import type { ScrollStory } from './useScrollStory';
import { useLayerOffset, type Parallax } from './useSceneInteraction';

export const SCENE = { w: 1440, h: 900 };
export const NARROW_VIEWBOX = '330 40 780 860';

/** Horizon, and the vanishing point the river and banks recede toward. */
const HORIZON = 560;
const VP = { x: 720, y: 548 };

/**
 * The river: narrow at the vanishing point, opening toward the camera, and bowed so the banks
 * meander. Straight edges plus full-width highlights read as a road with lane markings, which
 * is exactly what this must not look like.
 */
const RIVER_PATH =
  'M706 548 C690 640 638 700 594 780 C564 838 550 870 538 900 L902 900 \n   C884 862 858 806 828 748 C794 682 754 618 734 548 Z';

export const NARROW_BOX = { x: 330, y: 40, w: 780, h: 860 };
export const WIDE_BOX = { x: 0, y: 0, w: SCENE.w, h: SCENE.h };

/**
 * Where each signal lives in the scene, and where the three converge. Hotspots, signal paths
 * and the coordinator node all read these so they line up with the artwork and each other.
 */
export const ZONE_ANCHORS = {
  wide: {
    air: { x: 1042, y: 300 },
    water: { x: 720, y: 726 },
    waste: { x: 402, y: 742 },
    coordinator: { x: 720, y: 396 },
  },
  narrow: {
    air: { x: 858, y: 250 },
    water: { x: 720, y: 700 },
    waste: { x: 612, y: 772 },
    coordinator: { x: 720, y: 400 },
  },
} as const;

/** Deterministic pseudo-random so the scene is identical on every render and reload. */
function seeded(seed: number) {
  let value = seed;
  return () => {
    value = (value * 1664525 + 1013904223) % 4294967296;
    return value / 4294967296;
  };
}

const STARS = (() => {
  const r = seeded(19);
  return Array.from({ length: 54 }, () => ({
    x: r() * 1440,
    y: r() * 470,
    rad: 0.6 + r() * 1.3,
    o: 0.3 + r() * 0.7,
    dur: 3 + r() * 4,
  }));
})();

/** Trees flank both banks and recede toward the vanishing point. */
const TREES = (() => {
  const r = seeded(7);
  return Array.from({ length: 54 }, () => {
    const side = r() < 0.5 ? -1 : 1;
    const depth = r();
    // Distance from the channel is tied to depth, plus a little jitter — the riverbank widens
    // toward the camera, so trees must widen with it rather than wander into the water.
    const spread = 74 + depth * 620 + r() * 70;
    return {
      x: VP.x + side * spread,
      y: HORIZON + 6 + depth * 300,
      scale: 0.25 + depth * 1.5,
      lean: r() * 2 - 1,
    };
  });
})();

interface CloudSpec { x: number; y: number; rx: number; ry: number; o: number }

const CLOUD_BANDS: Array<{ duration: number; y: number; clouds: CloudSpec[] }> = [
  {
    duration: 150,
    y: 0,
    clouds: [
      { x: 200, y: 168, rx: 186, ry: 46, o: 0.9 },
      { x: 330, y: 200, rx: 128, ry: 34, o: 0.7 },
      { x: 820, y: 132, rx: 202, ry: 50, o: 0.8 },
      { x: 1210, y: 178, rx: 160, ry: 40, o: 0.68 },
    ],
  },
  {
    duration: 215,
    y: 58,
    clouds: [
      { x: 80, y: 268, rx: 150, ry: 30, o: 0.5 },
      { x: 600, y: 292, rx: 196, ry: 34, o: 0.44 },
      { x: 1080, y: 258, rx: 156, ry: 28, o: 0.52 },
    ],
  },
];

function CloudBand({ band, reduced }: { band: (typeof CLOUD_BANDS)[number]; reduced: boolean }) {
  // Two copies exactly one scene-width apart: as the first leaves frame the second has already
  // taken its place, so the loop has no seam.
  return (
    <motion.g
      animate={reduced ? undefined : { x: [0, -SCENE.w] }}
      transition={reduced ? undefined : { duration: band.duration, repeat: Infinity, ease: 'linear' }}
    >
      {[0, SCENE.w].map((offset) => (
        <g key={offset} transform={`translate(${offset} ${band.y})`}>
          {band.clouds.map((c, i) => (
            <g key={i}>
              <ellipse cx={c.x} cy={c.y} rx={c.rx} ry={c.ry} fill="url(#cloudBody)" opacity={c.o} />
              <ellipse
                cx={c.x - c.rx * 0.36}
                cy={c.y + c.ry * 0.44}
                rx={c.rx * 0.58}
                ry={c.ry * 0.7}
                fill="url(#cloudBody)"
                opacity={c.o * 0.78}
              />
            </g>
          ))}
        </g>
      ))}
    </motion.g>
  );
}

function Tree({ x, y, scale, lean }: { x: number; y: number; scale: number; lean: number }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale}) rotate(${lean})`}>
      <rect x={-1.6} y={-15} width={3.2} height={17} style={{ fill: 'var(--canopy)' }} />
      <path d="M0 -58 L14 -15 L-14 -15 Z" style={{ fill: 'var(--canopy)' }} />
      <path d="M0 -47 L9 -19 L-9 -19 Z" style={{ fill: 'var(--canopy-lit)' }} opacity={0.5} />
    </g>
  );
}

/* ── Industry ─────────────────────────────────────────────────────
   Factories resolve out of the distance rather than popping in: they fade up and settle
   down into place, their windows warm as daylight drops, and only then do the stacks start
   working. Cause before effect. */

const PLANTS = [
  { x: 168, y: HORIZON, w: 210, h: 96, stacks: [40, 92], towers: [148], delay: 0 },
  { x: 1086, y: HORIZON, w: 232, h: 84, stacks: [56, 140, 186], towers: [8], delay: 0.18 },
  { x: 402, y: HORIZON, w: 132, h: 60, stacks: [34], towers: [], delay: 0.34 },
];

const WINDOWS = (() => {
  const r = seeded(91);
  return PLANTS.map((p) =>
    Array.from({ length: Math.round(p.w / 26) }, (_, i) => ({
      x: p.x + 10 + i * 24,
      y: p.y - p.h + 16 + Math.round(r() * 2) * 16,
      lit: r(),
    })),
  );
})();

/** One lit window. Its own component so the hook is never called from inside a loop body. */
function Window({ spec, cityLights }: { spec: { x: number; y: number; lit: number }; cityLights: MotionValue<number> }) {
  const opacity = useTransform(cityLights, [spec.lit * 0.55, spec.lit * 0.55 + 0.3], [0, 0.9], { clamp: true });
  return <motion.rect x={spec.x} y={spec.y} width={7} height={9} fill="#ffca6e" style={{ opacity }} />;
}

function Plant({
  plant,
  windows,
  factories,
  cityLights,
}: {
  plant: (typeof PLANTS)[number];
  windows: { x: number; y: number; lit: number }[];
  factories: MotionValue<number>;
  cityLights: MotionValue<number>;
}) {
  const opacity = useTransform(factories, [plant.delay, plant.delay + 0.45], [0, 1], { clamp: true });
  const rise = useTransform(factories, [plant.delay, plant.delay + 0.45], [16, 0], { clamp: true });
  const top = plant.y - plant.h;

  return (
    <motion.g style={{ opacity, y: rise }}>
      <rect x={plant.x} y={top} width={plant.w} height={plant.h} style={{ fill: 'var(--factory)' }} />
      <rect x={plant.x} y={top} width={plant.w} height={4} style={{ fill: 'var(--light)' }} opacity={0.25} />
      {plant.towers.map((tx, i) => (
        // Concave-waisted cooling tower — the silhouette that reads instantly as heavy industry.
        <path
          key={`t${i}`}
          d={`M${plant.x + tx} ${top} C${plant.x + tx + 7} ${top - 30} ${plant.x + tx + 9} ${top - 48} ${plant.x + tx + 8} ${top - 70}
             L${plant.x + tx + 44} ${top - 70} C${plant.x + tx + 43} ${top - 48} ${plant.x + tx + 45} ${top - 30} ${plant.x + tx + 52} ${top} Z`}
          style={{ fill: 'var(--factory)' }}
        />
      ))}
      {plant.stacks.map((sx, i) => (
        <g key={i}>
          <rect x={plant.x + sx} y={top - 62 - i * 10} width={13} height={62 + i * 10} style={{ fill: 'var(--factory)' }} />
          <rect x={plant.x + sx - 2} y={top - 64 - i * 10} width={17} height={5} style={{ fill: 'var(--factory)' }} />
        </g>
      ))}
      {windows.map((w, i) => (
        <Window key={i} spec={w} cityLights={cityLights} />
      ))}
    </motion.g>
  );
}

/** One chimney plume: puffs rise, widen, drift downwind and dissolve — always, on a loop. */
function Plume({ x, y, smoke, reduced }: { x: number; y: number; smoke: MotionValue<number>; reduced: boolean }) {
  const opacity = useTransform(smoke, [0, 1], [0, 0.55]);
  // Two passes: a short warm one catching the yard lights just above the stack, and a taller
  // cool one that drifts downwind and dissolves — the layering in the reference.
  const passes = [
    { fill: 'url(#emberPuff)', rise: 96, drift: 40, grow: 34, dur: 6.5, n: 4 },
    { fill: 'url(#smokePuff)', rise: 210, drift: 110, grow: 62, dur: 10, n: 6 },
  ];
  return (
    <motion.g style={{ opacity }}>
      {passes.map((pass, pi) =>
        Array.from({ length: pass.n }, (_, i) => (
          <motion.circle
            key={`${pi}-${i}`}
            cx={x}
            cy={y}
            r={10}
            fill={pass.fill}
            animate={
              reduced
                ? { opacity: 0.4, cy: y - pass.rise * 0.3 }
                : {
                    cy: [y, y - pass.rise],
                    cx: [x, x + pass.drift],
                    r: [9, pass.grow],
                    opacity: [0, 0.85, 0],
                  }
            }
            transition={
              reduced
                ? undefined
                : { duration: pass.dur, repeat: Infinity, delay: (i * pass.dur) / pass.n, ease: 'easeOut' }
            }
          />
        )),
      )}
    </motion.g>
  );
}

/* ── Waste ────────────────────────────────────────────────────────
   Litter on the bank appears piece by piece; debris in the river is always travelling
   downstream on its own loop, and only how MUCH of it there is follows the story. */

const LAND_ITEMS = (() => {
  const r = seeded(53);
  return Array.from({ length: 18 }, (_, i) => {
    const side = i % 2 === 0 ? -1 : 1;
    const depth = r();
    // Hugging the waterline rather than sprinkled across the whole field.
    const bank = 48 + depth * 300;
    return {
      x: VP.x + side * (bank + r() * 90),
      y: 660 + depth * 220,
      w: 7 + r() * 13,
      rot: r() * 80 - 40,
      at: i / 18,
      kind: (['bottle', 'bag', 'sheet'] as const)[i % 3],
      tone: ['#e2dccb', '#b9c7bd', '#d8c9a8', '#9fb8c9', '#cbb6d8'][i % 5],
    };
  });
})();

function LandPiece({ item, landWaste }: { item: (typeof LAND_ITEMS)[number]; landWaste: MotionValue<number> }) {
  const opacity = useTransform(landWaste, [item.at, item.at + 0.16], [0, 0.9], { clamp: true });
  const scale = useTransform(landWaste, [item.at, item.at + 0.16], [0.5, 1], { clamp: true });
  const common = {
    fill: item.tone,
    transform: `rotate(${item.rot} ${item.x} ${item.y})`,
    style: { opacity, scale, transformOrigin: `${item.x}px ${item.y}px` },
  };
  if (item.kind === 'bottle') {
    // Neck + body, so it reads as a bottle rather than a chip of something.
    return (
      <motion.g {...common}>
        <rect x={item.x} y={item.y} width={item.w} height={item.w * 0.44} rx={item.w * 0.2} />
        <rect x={item.x + item.w * 0.9} y={item.y + item.w * 0.12} width={item.w * 0.32} height={item.w * 0.2} rx={1} />
      </motion.g>
    );
  }
  if (item.kind === 'bag') {
    return (
      <motion.path
        d={`M${item.x} ${item.y} q${item.w * 0.3} ${-item.w * 0.5} ${item.w * 0.7} ${-item.w * 0.16}
            q${item.w * 0.4} ${item.w * 0.12} ${item.w * 0.3} ${item.w * 0.5}
            q${-item.w * 0.5} ${item.w * 0.2} ${-item.w} ${-item.w * 0.34} Z`}
        {...common}
      />
    );
  }
  return <motion.rect x={item.x} y={item.y} width={item.w} height={item.w * 0.22} rx={1} {...common} />;
}

/* ── River margins ────────────────────────────────────────────────
   In the references the litter is not evenly spread down the channel: it packs into a raft
   against the banks and thickens toward the camera, while the middle stays open water. The
   helpers below walk the actual bank curves so the mat hugs them exactly. */

type Pt = { x: number; y: number };

function cubic(p0: Pt, p1: Pt, p2: Pt, p3: Pt, t: number): Pt {
  const u = 1 - t;
  return {
    x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
    y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
  };
}

/** Point on a bank at `t` (0 = vanishing point, 1 = camera). `side` -1 = left, 1 = right. */
function bankPoint(t: number, side: -1 | 1): Pt {
  const seg = t < 0.5 ? 0 : 1;
  const lt = seg === 0 ? t * 2 : (t - 0.5) * 2;
  if (side === -1) {
    return seg === 0
      ? cubic({ x: 706, y: 548 }, { x: 690, y: 640 }, { x: 638, y: 700 }, { x: 594, y: 780 }, lt)
      : cubic({ x: 594, y: 780 }, { x: 564, y: 838 }, { x: 550, y: 870 }, { x: 538, y: 900 }, lt);
  }
  return seg === 0
    ? cubic({ x: 734, y: 548 }, { x: 754, y: 618 }, { x: 794, y: 682 }, { x: 828, y: 748 }, lt)
    : cubic({ x: 828, y: 748 }, { x: 858, y: 806 }, { x: 884, y: 862 }, { x: 902, y: 900 }, lt);
}

/** The raft of litter caught along each bank. */
const EDGE_WASTE = (() => {
  const r = seeded(211);
  return Array.from({ length: 168 }, () => {
    const side: -1 | 1 = r() < 0.5 ? -1 : 1;
    // Weighted toward the near-middle of the channel: that is where the water is widest AND
    // still on screen — the very front of the river falls below the frame.
    const t = 0.18 + Math.pow(r(), 0.6) * 0.66;
    const p = bankPoint(t, side);
    const inward = r() * r() * (16 + t * 96);
    const size = 3.5 + t * 17 + r() * 5;
    return {
      x: p.x - side * inward,
      y: p.y + (r() * 10 - 5),
      w: size,
      h: size * (0.4 + r() * 0.35),
      rot: r() * 180,
      at: r() * 0.85,
      bob: 1 + r() * 2,
      dur: 3 + r() * 3,
      tone: ['#f4f7f4', '#e6ecea', '#d6ded9', '#c3d2de', '#efe9d8', '#a9ced3'][Math.floor(r() * 6)],
    };
  });
})();

function EdgePiece({ item, riverWaste, reduced }: { item: (typeof EDGE_WASTE)[number]; riverWaste: MotionValue<number>; reduced: boolean }) {
  const opacity = useTransform(riverWaste, [item.at, item.at + 0.2], [0, 1], { clamp: true });
  return (
    <motion.rect
      x={item.x}
      y={item.y}
      width={item.w}
      height={item.h}
      rx={item.h * 0.45}
      fill={item.tone}
      transform={`rotate(${item.rot} ${item.x} ${item.y})`}
      style={{ opacity }}
      // Framer treats `y` on an SVG node as a transform, not the `y` attribute — so this must
      // be a small relative offset, not an absolute coordinate, or each piece is translated
      // its own y-position downward and leaves the frame entirely.
      animate={reduced ? undefined : { y: [0, item.bob, 0] }}
      transition={reduced ? undefined : { duration: item.dur, repeat: Infinity, ease: 'easeInOut' }}
    />
  );
}

/** Algal scum: swirls of surface film on water that has lost its quality. */
const ALGAE = (() => {
  const r = seeded(307);
  return Array.from({ length: 11 }, () => {
    const side: -1 | 1 = r() < 0.5 ? -1 : 1;
    const t = 0.25 + r() * 0.75;
    const p = bankPoint(t, side);
    return {
      x: p.x - side * (r() * (20 + t * 90)),
      y: p.y,
      rx: 13 + t * 38 + r() * 14,
      ry: 2.5 + t * 5,
      rot: r() * 40 - 20,
      at: r() * 0.6,
      drift: 4 + r() * 8,
      dur: 9 + r() * 8,
    };
  });
})();

function Algae({ item, turbidity, reduced }: { item: (typeof ALGAE)[number]; turbidity: MotionValue<number>; reduced: boolean }) {
  const opacity = useTransform(turbidity, [item.at, item.at + 0.35], [0, 0.2], { clamp: true });
  return (
    <motion.ellipse
      cx={item.x}
      cy={item.y}
      rx={item.rx}
      ry={item.ry}
      fill="#6b8a52"
      transform={`rotate(${item.rot} ${item.x} ${item.y})`}
      style={{ opacity }}
      animate={reduced ? undefined : { cx: [item.x, item.x + item.drift, item.x] }}
      transition={reduced ? undefined : { duration: item.dur, repeat: Infinity, ease: 'easeInOut' }}
    />
  );
}

const GLINTS = (() => {
  const r = seeded(67);
  return Array.from({ length: 9 }, (_, i) => ({
    lane: r() * 2 - 1,
    rx: 26 + r() * 30,
    dur: 6 + r() * 3.5,
    delay: (i / 9) * 7,
  }));
})();

const DEBRIS = (() => {
  const r = seeded(31);
  return Array.from({ length: 12 }, (_, i) => ({
    lane: r() * 2 - 1,
    w: 6 + r() * 10,
    at: i / 12,
    delay: r() * 9,
    dur: 9 + r() * 6,
    tone: ['#e6e0cf', '#cfd9d2', '#d9c8a6', '#b9cfe0'][i % 4],
  }));
})();

/**
 * A single piece of river debris. It travels the river's own axis from the vanishing point to
 * the camera on a continuous loop — it does not reverse when the story is scrubbed back; only
 * its visibility follows `riverWaste`.
 */
function Debris({ item, riverWaste, reduced }: { item: (typeof DEBRIS)[number]; riverWaste: MotionValue<number>; reduced: boolean }) {
  const opacity = useTransform(riverWaste, [item.at * 0.8, item.at * 0.8 + 0.25], [0, 0.95], { clamp: true });
  const startX = VP.x + item.lane * 12;
  const endX = VP.x + item.lane * 170;
  return (
    <motion.g style={{ opacity }}>
      <motion.rect
        x={-item.w / 2}
        y={-item.w * 0.25}
        width={item.w}
        height={item.w * 0.5}
        rx={2}
        fill={item.tone}
        animate={
          reduced
            ? { x: endX, y: 760, scale: 1 }
            : { x: [startX, endX], y: [HORIZON + 4, 910], scale: [0.25, 1.5], rotate: [0, item.lane * 40] }
        }
        transition={
          reduced ? undefined : { duration: item.dur, repeat: Infinity, delay: item.delay, ease: 'linear' }
        }
      />
    </motion.g>
  );
}

/** Fissures opening in the dried ground, straight from the degraded half of the references. */
const CRACKS = (() => {
  const r = seeded(101);
  return Array.from({ length: 22 }, () => {
    const side = r() < 0.5 ? -1 : 1;
    const depth = r();
    const x = VP.x + side * (150 + depth * 560);
    const y = 660 + depth * 230;
    const len = 26 + r() * 74;
    const a = r() * 1.6 - 0.8;
    return {
      d: `M${x} ${y} l${Math.cos(a) * len} ${Math.sin(a) * len * 0.4}
          m${-Math.cos(a) * len * 0.5} ${-Math.sin(a) * len * 0.2} l${r() * 30 - 15} ${12 + r() * 16}`,
      w: 0.8 + r() * 1.3,
    };
  });
})();

/** Birds: healthy-state life, drifting on their own loop. */
const BIRDS = (() => {
  const r = seeded(137);
  return Array.from({ length: 7 }, (_, i) => ({
    y: 180 + r() * 170,
    scale: 0.6 + r() * 0.8,
    dur: 46 + r() * 34,
    delay: i * 5.5,
  }));
})();

/**
 * Figures at the bank, implying where the waste comes from. Deliberately tiny and abstract —
 * a posture, not a person, and never a distressing scene.
 */
const FIGURES = [
  { x: VP.x - 300, y: 742, at: 0.15 },
  { x: VP.x + 268, y: 716, at: 0.45 },
  { x: VP.x - 176, y: 690, at: 0.72 },
];

function Figure({ figure, landWaste }: { figure: (typeof FIGURES)[number]; landWaste: MotionValue<number> }) {
  const opacity = useTransform(landWaste, [figure.at, figure.at + 0.18], [0, 0.72], { clamp: true });
  return (
    <motion.g style={{ opacity }}>
      <ellipse cx={figure.x} cy={figure.y - 15} rx={2.6} ry={3} style={{ fill: 'var(--rock)' }} />
      <path
        d={`M${figure.x - 3.4} ${figure.y} l3.4 -11 l3.4 11`}
        style={{ stroke: 'var(--rock)' }}
        strokeWidth={2.6}
        fill="none"
        strokeLinecap="round"
      />
    </motion.g>
  );
}

interface SceneProps {
  story: ScrollStory;
  parallax: Parallax;
  reduced: boolean;
  narrow: boolean;
}

export function EnvironmentalScene({ story, parallax, reduced, narrow }: SceneProps) {
  const skyL = useLayerOffset(parallax, 5);
  const cloudL = useLayerOffset(parallax, 14);
  const farL = useLayerOffset(parallax, 24);
  const midL = useLayerOffset(parallax, 40);
  const cityL = useLayerOffset(parallax, 56);
  const treeL = useLayerOffset(parallax, 74);
  const waterL = useLayerOffset(parallax, 92);
  const foreL = useLayerOffset(parallax, 128);

  const sunGlow = useTransform(story.sunOpacity, (v) => v * 0.55);
  const turbidityOpacity = useTransform(story.turbidity, [0, 1], [0, 0.3]);
  // The surface never stops glinting — clarity drops, movement does not.
  const glintOpacity = useTransform(story.turbidity, [0, 1], [0.34, 0.18]);
  const vegetationFade = useTransform(story.pollution, [0, 1], [0, 0.24]);
  const crackOpacity = useTransform(story.landWaste, [0, 1], [0, 0.5]);
  // Wildlife thins out as the air loads up — present in the healthy state, gone by night.
  const birdOpacity = useTransform(story.pollution, [0, 0.45], [0.9, 0], { clamp: true });

  return (
    <svg
      className="absolute inset-0 h-full w-full"
      viewBox={narrow ? NARROW_VIEWBOX : `0 0 ${SCENE.w} ${SCENE.h}`}
      preserveAspectRatio="xMidYMid slice"
      aria-hidden
    >
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" style={{ stopColor: 'var(--sky-high)' }} />
          <stop offset="56%" style={{ stopColor: 'var(--sky-mid)' }} />
          <stop offset="100%" style={{ stopColor: 'var(--sky-low)' }} />
        </linearGradient>
        <radialGradient id="sunDisc" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" style={{ stopColor: 'var(--sun)' }} stopOpacity="0.72" />
          <stop offset="46%" style={{ stopColor: 'var(--sun)' }} stopOpacity="0.22" />
          <stop offset="100%" style={{ stopColor: 'var(--sun)' }} stopOpacity="0" />
        </radialGradient>
        <radialGradient id="cloudBody" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" style={{ stopColor: 'var(--light)' }} stopOpacity="0.92" />
          <stop offset="62%" style={{ stopColor: 'var(--light)' }} stopOpacity="0.42" />
          <stop offset="100%" style={{ stopColor: 'var(--light)' }} stopOpacity="0" />
        </radialGradient>
        <radialGradient id="emberPuff" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" style={{ stopColor: 'var(--ember)' }} stopOpacity="0.5" />
          <stop offset="55%" style={{ stopColor: 'var(--ember)' }} stopOpacity="0.18" />
          <stop offset="100%" style={{ stopColor: 'var(--ember)' }} stopOpacity="0" />
        </radialGradient>

        <radialGradient id="smokePuff" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" style={{ stopColor: 'var(--smoke)' }} stopOpacity="0.5" />
          <stop offset="55%" style={{ stopColor: 'var(--smoke)' }} stopOpacity="0.2" />
          <stop offset="100%" style={{ stopColor: 'var(--smoke)' }} stopOpacity="0" />
        </radialGradient>

        <radialGradient id="hazeBank" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" style={{ stopColor: 'var(--smoke)' }} stopOpacity="0.55" />
          <stop offset="100%" style={{ stopColor: 'var(--smoke)' }} stopOpacity="0" />
        </radialGradient>
        <linearGradient id="water" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" style={{ stopColor: 'var(--water-lit)' }} />
          <stop offset="100%" style={{ stopColor: 'var(--water-deep)' }} />
        </linearGradient>
        <linearGradient id="scrim" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#04070a" stopOpacity="0.17" />
          <stop offset="26%" stopColor="#04070a" stopOpacity="0" />
          <stop offset="100%" stopColor="#04070a" stopOpacity="0.5" />
        </linearGradient>
        <linearGradient id="textScrim" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#04070a" stopOpacity="0.52" />
          <stop offset="100%" stopColor="#04070a" stopOpacity="0" />
        </linearGradient>
        <clipPath id="riverClip">
          <path d={RIVER_PATH} />
        </clipPath>
      </defs>

      {/* The camera push applies to the whole world, so the place stays one place. */}
      <motion.g style={{ scale: story.cameraScale, y: story.cameraY, transformOrigin: `${VP.x}px ${VP.y}px` }}>
        {/* ── Sky, stars, moon, sun ───────────────────────────── */}
        <motion.g style={skyL}>
          <rect x={-120} y={-120} width={1680} height={820} fill="url(#sky)" />
          <motion.g style={{ opacity: story.starOpacity }}>
            {STARS.map((s, i) => (
              <motion.circle
                key={i}
                cx={s.x}
                cy={s.y}
                r={s.rad}
                fill="#eaf2ff"
                animate={reduced ? undefined : { opacity: [s.o * 0.4, s.o, s.o * 0.4] }}
                transition={reduced ? undefined : { duration: s.dur, repeat: Infinity, ease: 'easeInOut' }}
                opacity={s.o}
              />
            ))}
          </motion.g>
          <motion.g style={{ x: story.moonX, y: story.moonY, opacity: story.moonOpacity }}>
            <circle r={132} fill="url(#sunDisc)" opacity={0.3} />
            <circle r={27} fill="#e4ecf6" />
            <circle cx={9} cy={-7} r={4.6} fill="#c6d2e2" opacity={0.7} />
            <circle cx={-6} cy={9} r={3.1} fill="#c6d2e2" opacity={0.55} />
          </motion.g>
          <motion.g style={{ x: story.sunX, y: story.sunY, opacity: story.sunOpacity }}>
            <motion.circle r={330} fill="url(#sunDisc)" style={{ opacity: sunGlow }} />
            <circle r={118} fill="url(#sunDisc)" />
            <circle r={44} style={{ fill: 'var(--sun)' }} />
            <circle r={26} fill="#fffdf6" opacity={0.9} />
          </motion.g>
        </motion.g>

        {/* ── Clouds (continuous drift) ───────────────────────── */}
        <motion.g style={cloudL}>
          {CLOUD_BANDS.map((band, i) => (
            <CloudBand key={i} band={band} reduced={reduced} />
          ))}
          <motion.g style={{ opacity: birdOpacity }}>
            {BIRDS.map((b, i) => (
              <motion.g
                key={i}
                animate={reduced ? undefined : { x: [-160, SCENE.w + 160] }}
                transition={reduced ? undefined : { duration: b.dur, repeat: Infinity, delay: b.delay, ease: 'linear' }}
              >
                <path
                  d={`M0 ${b.y} q6 -5 11 0 q5 -5 11 0`}
                  stroke="#2f3a44"
                  strokeWidth={1.6}
                  fill="none"
                  opacity={0.5}
                  transform={`scale(${b.scale})`}
                />
              </motion.g>
            ))}
          </motion.g>
        </motion.g>

        {/* ── Ridges: three receding layers ───────────────────── */}
        <motion.g style={farL}>
          <path
            d="M-120 566 L110 372 L250 452 L420 322 L560 448 L700 368 L860 452 L1010 336 L1160 448 L1320 384 L1560 470 L1560 600 L-120 600 Z"
            style={{ fill: 'var(--ridge-far)' }}
          />
        </motion.g>
        <motion.g style={midL}>
          <path
            d="M-120 586 L120 452 L300 532 L500 430 L700 530 L880 448 L1080 536 L1280 452 L1560 540 L1560 640 L-120 640 Z"
            style={{ fill: 'var(--ridge-mid)' }}
          />
        </motion.g>

        {/* ── City and industry ───────────────────────────────── */}
        <motion.g style={cityL}>
          <path
            d="M-120 600 L60 520 L260 560 L470 498 L700 556 L930 500 L1150 558 L1360 512 L1560 566 L1560 660 L-120 660 Z"
            style={{ fill: 'var(--ridge-near)' }}
          />
          {PLANTS.map((plant, i) => (
            <Plant key={i} plant={plant} windows={WINDOWS[i]} factories={story.factories} cityLights={story.cityLights} />
          ))}
          {/* Plumes sit above the stacks, drifting downwind on their own clock. */}
          {PLANTS.map((plant, pi) =>
            plant.stacks.map((sx, si) => (
              <Plume
                key={`${pi}-${si}`}
                x={plant.x + sx + 6}
                y={plant.y - plant.h - 64 - si * 10}
                smoke={story.smoke}
                reduced={reduced}
              />
            )),
          )}
        </motion.g>

        {/* Particulate haze — downstream of the smoke, cutting visibility */}
        <motion.g style={{ opacity: story.hazeOpacity }}>
          <ellipse cx={720} cy={470} rx={1020} ry={200} fill="url(#hazeBank)" />
          <ellipse cx={1080} cy={410} rx={540} ry={140} fill="url(#hazeBank)" opacity={0.7} />
          <ellipse cx={300} cy={440} rx={520} ry={130} fill="url(#hazeBank)" opacity={0.65} />
        </motion.g>

        {/* ── Ground and vegetation ───────────────────────────── */}
        <motion.g style={treeL}>
          <path
            d="M-120 566 C 200 552, 460 572, 706 556 C 950 572, 1220 552, 1560 566 L1560 960 L-120 960 Z"
            style={{ fill: 'var(--ground)' }}
          />
          <ellipse cx={720} cy={HORIZON} rx={980} ry={52} fill="url(#hazeBank)" opacity={0.45} />
          {/* Lit shingle along the waterline, so the bank separates from the field behind it. */}
          <path
            d="M706 548 C690 640 638 700 594 780 C564 838 550 870 538 900 L470 900 C500 858 520 800 556 726 C614 636 664 590 690 548 Z"
            style={{ fill: 'var(--light)' }}
            opacity={0.07}
          />
          <path
            d="M734 548 C754 618 794 682 828 748 C858 806 884 862 902 900 L972 900 C942 858 916 800 878 726 C818 636 770 590 750 548 Z"
            style={{ fill: 'var(--light)' }}
            opacity={0.07}
          />
          <motion.g
            animate={reduced ? undefined : { rotate: [0, 0.4, 0, -0.4, 0] }}
            transition={reduced ? undefined : { duration: 11, repeat: Infinity, ease: 'easeInOut' }}
            style={{ transformOrigin: `${VP.x}px 760px` }}
          >
            {TREES.map((t, i) => (
              <Tree key={i} {...t} />
            ))}
          </motion.g>
          <motion.rect x={-120} y={556} width={1680} height={404} fill="#5b5640" style={{ opacity: vegetationFade }} />
          {/* The ground dries and splits as the story advances. */}
          <motion.g style={{ opacity: crackOpacity }}>
            {CRACKS.map((c, i) => (
              <path key={i} d={c.d} stroke="#2a2015" strokeWidth={c.w} fill="none" strokeLinecap="round" opacity={0.75} />
            ))}
          </motion.g>
        </motion.g>

        {/* ── River: always flowing, clarity follows the story ── */}
        <motion.g style={waterL}>
          <path d={RIVER_PATH} fill="url(#water)" />
          <g clipPath="url(#riverClip)">
            {GLINTS.map((g, i) => (
              <motion.ellipse
                key={i}
                cx={VP.x + g.lane * 26}
                cy={600 + i * 44}
                rx={g.rx}
                ry={2.6}
                fill="#f2fdff"
                style={{ opacity: glintOpacity }}
                animate={
                  reduced
                    ? undefined
                    : { cy: [566, 910], cx: [VP.x + g.lane * 14, VP.x + g.lane * 150], scaleX: [0.18, 2.4] }
                }
                transition={
                  reduced ? undefined : { duration: g.dur, repeat: Infinity, delay: g.delay, ease: 'linear' }
                }
              />
            ))}
            <motion.rect x={400} y={540} width={640} height={380} fill="#5f5a3c" style={{ opacity: turbidityOpacity }} />
            {ALGAE.map((a, i) => (
              <Algae key={i} item={a} turbidity={story.turbidity} reduced={reduced} />
            ))}
            {EDGE_WASTE.map((w, i) => (
              <EdgePiece key={i} item={w} riverWaste={story.riverWaste} reduced={reduced} />
            ))}
            {DEBRIS.map((d, i) => (
              <Debris key={i} item={d} riverWaste={story.riverWaste} reduced={reduced} />
            ))}
          </g>
          <path d={RIVER_PATH} fill="none" stroke="#04070a" strokeOpacity={0.3} strokeWidth={2.5} />
        </motion.g>

        {/* ── Foreground: banks, litter, framing rock ─────────── */}
        <motion.g style={foreL}>
          {FIGURES.map((f, i) => (
            <Figure key={i} figure={f} landWaste={story.landWaste} />
          ))}
          {LAND_ITEMS.map((item, i) => (
            <LandPiece key={i} item={item} landWaste={story.landWaste} />
          ))}
          <path
            d="M-120 872 C 120 838, 330 878, 520 900 L-120 960 Z"
            style={{ fill: 'var(--rock)' }}
          />
          <path
            d="M1560 872 C 1320 838, 1110 878, 920 900 L1560 960 Z"
            style={{ fill: 'var(--rock)' }}
          />
        </motion.g>
      </motion.g>

      <rect x={-120} y={-120} width={1680} height={1140} fill="url(#scrim)" />
      {!narrow && <rect x={-120} y={-120} width={880} height={1140} fill="url(#textScrim)" />}
    </svg>
  );
}
