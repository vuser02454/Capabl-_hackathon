import { AnimatePresence, motion } from 'framer-motion';
import { cn } from '../../lib/format';
import { seeded } from '../../lib/rng';
import type { Detection, WasteCategory, WasteCounts } from '../../types/agents';
import { WASTE_CATEGORY_COLORS } from './agentMeta';

const DEBRIS = (() => {
  const rng = seeded('scene-debris');
  const tones = ['#56606a', '#6a5f4f', '#48564d', '#7a7f84', '#5a4c40', '#3f5059'];
  return Array.from({ length: 34 }, () => ({
    x: 4 + rng() * 152,
    y: 52 + rng() * 44,
    w: 1.2 + rng() * 3.4,
    h: 0.7 + rng() * 1.8,
    r: rng() * 180,
    fill: tones[Math.floor(rng() * tones.length)],
  }));
})();

/** Stylised night-vision riverbank frame used when no image has been uploaded. */
function SceneBackdrop() {
  return (
    <svg viewBox="0 0 160 100" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 size-full" aria-hidden>
      <defs>
        <linearGradient id="eco-scene-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1b2833" />
          <stop offset="1" stopColor="#101920" />
        </linearGradient>
        <linearGradient id="eco-scene-water" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#14262f" />
          <stop offset="1" stopColor="#0c161b" />
        </linearGradient>
        <linearGradient id="eco-scene-ground" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1e211d" />
          <stop offset="1" stopColor="#0d0f0d" />
        </linearGradient>
        <radialGradient id="eco-scene-vignette" cx="0.5" cy="0.5" r="0.78">
          <stop offset="0.5" stopColor="#000" stopOpacity="0" />
          <stop offset="1" stopColor="#000" stopOpacity="0.65" />
        </radialGradient>
        <filter id="eco-scene-grain">
          <feTurbulence type="fractalNoise" baseFrequency="1.3" numOctaves="2" seed="7" />
          <feColorMatrix values="0 0 0 0 0.6  0 0 0 0 0.75  0 0 0 0 0.72  0 0 0 0.1 0" />
        </filter>
        <filter id="eco-scene-soft">
          <feGaussianBlur stdDeviation="0.35" />
        </filter>
      </defs>
      <rect width="160" height="100" fill="url(#eco-scene-sky)" />
      <path d="M0 31 Q8 23 16 28 T32 25 T50 29 T68 22 T88 27 T108 21 T130 27 T148 23 T160 26 V40 H0Z" fill="#0c1419" />
      <rect y="36" width="160" height="5" fill="#111c22" />
      <rect y="40" width="160" height="21" fill="url(#eco-scene-water)" />
      <g stroke="#2c4853" strokeWidth="0.3" opacity="0.55">
        <path d="M8 44 H40" />
        <path d="M58 47.5 H104" />
        <path d="M118 43 H152" />
        <path d="M18 53 H66" />
        <path d="M94 56 H142" />
      </g>
      <path d="M0 59 Q28 54 60 57.5 T122 55 T160 58.5 V100 H0Z" fill="url(#eco-scene-ground)" />
      <g filter="url(#eco-scene-soft)" opacity="0.7">
        {DEBRIS.map((item, index) => (
          <rect
            key={index}
            x={item.x}
            y={item.y}
            width={item.w}
            height={item.h}
            rx={0.5}
            fill={item.fill}
            transform={`rotate(${item.r} ${item.x + item.w / 2} ${item.y + item.h / 2})`}
          />
        ))}
      </g>
      <rect width="160" height="100" filter="url(#eco-scene-grain)" />
      <rect width="160" height="100" fill="url(#eco-scene-vignette)" />
    </svg>
  );
}

function Corners() {
  const base = 'absolute size-4 border-brand/60';
  return (
    <div aria-hidden className="pointer-events-none absolute inset-2">
      <span className={cn(base, 'top-0 left-0 rounded-tl-md border-t-2 border-l-2')} />
      <span className={cn(base, 'top-0 right-0 rounded-tr-md border-t-2 border-r-2')} />
      <span className={cn(base, 'bottom-0 left-0 rounded-bl-md border-b-2 border-l-2')} />
      <span className={cn(base, 'right-0 bottom-0 rounded-br-md border-r-2 border-b-2')} />
    </div>
  );
}

interface DetectionViewerProps {
  detections: Detection[];
  imageUrl?: string | null;
  sourceLabel: string;
  model: string;
  scanning?: boolean;
  maxLabels?: number;
  className?: string;
}

export function DetectionViewer({ detections, imageUrl, sourceLabel, model, scanning = false, maxLabels = 6, className }: DetectionViewerProps) {
  const labelled = new Set(
    [...detections]
      .sort((a, b) => b.confidence - a.confidence)
      .slice(0, maxLabels)
      .map((detection) => detection.id),
  );
  const renderKey = `${imageUrl ?? sourceLabel}-${detections.length}`;

  return (
    <div className={cn('relative aspect-[16/10] w-full overflow-hidden rounded-xl border border-black/[0.07] bg-ink-900', className)}>
      {imageUrl ? <img src={imageUrl} alt="Uploaded environmental image under analysis" className="absolute inset-0 size-full object-cover" /> : <SceneBackdrop />}
      <div className="absolute inset-0 bg-linear-to-t from-ink-950/60 via-transparent to-ink-950/35" />

      <AnimatePresence>
        {!scanning &&
          detections.map((detection, index) => {
            const [x, y, width, height] = detection.bbox;
            const color = WASTE_CATEGORY_COLORS[detection.category];
            return (
              <motion.div
                key={`${renderKey}-${detection.id}`}
                initial={{ opacity: 0, scale: 1.25 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                transition={{ delay: index * 0.03, duration: 0.3 }}
                className="absolute rounded-[3px]"
                style={{
                  left: `${x * 100}%`,
                  top: `${y * 100}%`,
                  width: `${width * 100}%`,
                  height: `${height * 100}%`,
                  border: `1.5px solid ${color}`,
                  boxShadow: `0 0 0 1px rgb(0 0 0 / 0.35), inset 0 0 10px ${color}26`,
                }}
                title={`${detection.label} · ${Math.round(detection.confidence * 100)}%`}
              >
                {labelled.has(detection.id) && (
                  <span
                    className="absolute -top-[14px] -left-[1.5px] rounded-t-[3px] px-1 py-px font-mono text-[8.5px] leading-[12px] font-semibold whitespace-nowrap text-ink-950"
                    style={{ background: color }}
                  >
                    {detection.label} {detection.confidence.toFixed(2)}
                  </span>
                )}
              </motion.div>
            );
          })}
      </AnimatePresence>

      {scanning && (
        <>
          <div className="absolute inset-x-0 h-20 -translate-y-1/2 animate-scan bg-linear-to-b from-transparent via-brand/25 to-transparent" />
          <div className="absolute inset-0 grid place-items-center">
            <span className="rounded-full border border-brand/30 bg-ink-950/75 px-3 py-1 font-mono text-[11px] text-brand backdrop-blur">Running object detection…</span>
          </div>
        </>
      )}

      <div className="absolute top-3 left-3 flex items-center gap-1.5 rounded-md bg-ink-950/75 px-1.5 py-1 font-mono text-[10px] text-fg-muted backdrop-blur">
        <span className="size-1.5 animate-pulse rounded-full bg-risk-high" />
        {imageUrl ? 'UPLOAD' : `${sourceLabel} · LIVE`}
      </div>
      <div className="absolute top-3 right-3 max-w-[60%] truncate rounded-md bg-ink-950/75 px-1.5 py-1 font-mono text-[10px] text-fg-muted backdrop-blur">
        {model} · {scanning ? '…' : detections.length} obj
      </div>
      <Corners />
    </div>
  );
}

const CATEGORIES: WasteCategory[] = ['plastic', 'paper', 'other'];

export function CategoryBreakdown({ counts, className }: { counts: WasteCounts; className?: string }) {
  const total = counts.plastic + counts.paper + counts.other;
  return (
    <div className={className}>
      <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full bg-black/[0.05]">
        {CATEGORIES.filter((category) => counts[category] > 0).map((category) => (
          <motion.div
            key={category}
            className="h-full"
            style={{ background: WASTE_CATEGORY_COLORS[category] }}
            initial={{ width: 0 }}
            animate={{ width: `${(counts[category] / Math.max(total, 1)) * 100}%` }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          />
        ))}
      </div>
      <div className="mt-2.5 grid grid-cols-3 gap-2">
        {CATEGORIES.map((category) => (
          <div key={category}>
            <div className="flex items-center gap-1.5 text-[11px] text-fg-subtle capitalize">
              <span className="size-2 rounded-sm" style={{ background: WASTE_CATEGORY_COLORS[category] }} />
              {category}
            </div>
            <p className="mt-0.5 text-base font-semibold text-fg tabular">
              {counts[category]}
              <span className="ml-1 text-[11px] font-normal text-fg-subtle">{total ? Math.round((counts[category] / total) * 100) : 0}%</span>
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
