/**
 * The living environment — a photographed valley, scrubbed frame-by-frame with scroll.
 *
 * A 50-frame sequence (`public/landing-frames/frame-001.jpg` … `frame-050.jpg`) covers the same
 * sunrise → midday → sunset → night arc the story timeline describes: clean morning haze,
 * smoke thickening over the distant plant by afternoon, litter and turbidity implied by golden
 * hour, full night by the end. `story.progress` (0→1) selects the frame; nothing else about the
 * story changes shape, so every other component — hotspots, signal paths, projection — keeps
 * working against the same coordinate space unmodified.
 *
 * The frame is drawn to a canvas with a manual "cover" fit — the same scale/offset arithmetic
 * `useSceneProjection` uses for `xMidYMid slice` — so hotspot anchors defined against `SCENE`
 * still land in the same visually sensible places (sky, river, bank) regardless of viewport
 * aspect ratio.
 */
import { motion, useMotionValueEvent } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import type { ScrollStory } from './useScrollStory';
import { useLayerOffset, type Parallax } from './useSceneInteraction';

export const SCENE = { w: 1440, h: 900 };
export const NARROW_VIEWBOX = '330 40 780 860';

export const NARROW_BOX = { x: 330, y: 40, w: 780, h: 860 };
export const WIDE_BOX = { x: 0, y: 0, w: SCENE.w, h: SCENE.h };

/**
 * Where each signal lives in the scene, and where the three converge. Hotspots, signal paths
 * and the coordinator node all read these so they line up with each other (and roughly with
 * the photograph: sky for air, river for water, bank for waste).
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

const FRAME_COUNT = 50;
const frameSrc = (i: number) => `/landing-frames/frame-${String(i + 1).padStart(3, '0')}.jpg`;

type DecodedFrame = ImageBitmap | HTMLImageElement;
const frameW = (f: DecodedFrame) => ('naturalWidth' in f ? f.naturalWidth : f.width);
const frameH = (f: DecodedFrame) => ('naturalWidth' in f ? f.naturalHeight : f.height);

/** Decode off the main thread where supported, so scrubbing never blocks on JPEG decode. */
async function loadFrame(i: number): Promise<DecodedFrame> {
  const img = new Image();
  img.decoding = 'async';
  img.src = frameSrc(i);
  await img.decode();
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(img);
    } catch {
      return img;
    }
  }
  return img;
}

interface SceneProps {
  story: ScrollStory;
  parallax: Parallax;
  reduced: boolean;
  narrow: boolean;
}

export function EnvironmentalScene({ story, parallax, reduced }: SceneProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const framesRef = useRef<(DecodedFrame | null)[]>(new Array(FRAME_COUNT).fill(null));
  const frameIndexRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const dirtyRef = useRef(true);
  const [ready, setReady] = useState(false);

  const offset = useLayerOffset(parallax, 18);

  function draw() {
    const canvas = canvasRef.current;
    const frame = framesRef.current[frameIndexRef.current];
    if (!canvas || !frame) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssW = canvas.clientWidth;
    const cssH = canvas.clientHeight;
    if (cssW === 0 || cssH === 0) return;
    const pxW = Math.round(cssW * dpr);
    const pxH = Math.round(cssH * dpr);
    if (canvas.width !== pxW || canvas.height !== pxH) {
      canvas.width = pxW;
      canvas.height = pxH;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Manual "cover" fit — identical scale/offset math to `useSceneProjection`'s slice mode.
    const fw = frameW(frame);
    const fh = frameH(frame);
    const scale = Math.max(cssW / fw, cssH / fh);
    const w = fw * scale;
    const h = fh * scale;
    const x = (cssW - w) / 2;
    const y = (cssH - h) / 2;
    ctx.clearRect(0, 0, cssW, cssH);
    ctx.drawImage(frame, x, y, w, h);
  }

  /** Coalesces bursts of scroll/resize events into one paint per animation frame. */
  function scheduleDraw() {
    dirtyRef.current = true;
    if (rafRef.current != null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      if (dirtyRef.current) {
        dirtyRef.current = false;
        draw();
      }
    });
  }

  useEffect(() => {
    let cancelled = false;
    let loaded = 0;

    for (let i = 0; i < FRAME_COUNT; i += 1) {
      loadFrame(i).then((frame) => {
        if (cancelled) return;
        framesRef.current[i] = frame;
        loaded += 1;
        if (i === frameIndexRef.current) scheduleDraw();
        if (loaded === FRAME_COUNT) setReady(true);
      });
    }

    return () => {
      cancelled = true;
      for (const frame of framesRef.current) {
        if (frame && 'close' in frame) frame.close();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The frame sequence tracks raw scroll, not the spring — a background that eases in behind
  // the pointer reads as sluggish; a video-style scrub has to feel welded to the scrollbar.
  useMotionValueEvent(story.rawProgress, 'change', (value) => {
    const index = Math.min(FRAME_COUNT - 1, Math.max(0, Math.round(value * (FRAME_COUNT - 1))));
    if (index !== frameIndexRef.current) {
      frameIndexRef.current = index;
      scheduleDraw();
    }
  });

  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;
    const observer = new ResizeObserver(() => scheduleDraw());
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={wrapRef} className="absolute inset-0 h-full w-full overflow-hidden bg-ink-950">
      <motion.div
        className="absolute inset-0 h-full w-full"
        style={
          reduced
            ? { scale: story.cameraScale }
            : { scale: story.cameraScale, x: offset.x, y: offset.y }
        }
      >
        <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden />
      </motion.div>

      {!ready && <div className="absolute inset-0 bg-ink-950" aria-hidden />}

      {/* Legibility scrims, in place of the old SVG's <rect fill="url(#scrim)"> layers. */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'linear-gradient(to bottom, rgba(4,7,10,0.17) 0%, rgba(4,7,10,0) 26%, rgba(4,7,10,0.5) 100%)',
        }}
        aria-hidden
      />
      <div
        className="pointer-events-none absolute inset-0 hidden md:block"
        style={{ background: 'linear-gradient(to right, rgba(4,7,10,0.52) 0%, rgba(4,7,10,0) 55%)' }}
        aria-hidden
      />
    </div>
  );
}
