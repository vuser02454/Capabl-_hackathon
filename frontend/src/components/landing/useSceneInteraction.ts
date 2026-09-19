import { useEffect, useMemo, useState } from 'react';
import { useMotionValue, useReducedMotion, useSpring, useTransform, type MotionValue } from 'framer-motion';

/** Matches a media query and stays in sync with viewport changes. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia(query).matches,
  );
  useEffect(() => {
    const list = window.matchMedia(query);
    const onChange = () => setMatches(list.matches);
    onChange();
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}

export interface Parallax {
  /** Normalised pointer position, -1..1 from the centre of the scene. */
  x: MotionValue<number>;
  y: MotionValue<number>;
  onPointerMove: (event: React.PointerEvent<HTMLElement>) => void;
  onPointerLeave: () => void;
  /** False when parallax is suppressed (reduced motion / touch), so layers render static. */
  active: boolean;
}

/**
 * Pointer parallax for the scene layers. Disabled under `prefers-reduced-motion`
 * and on coarse pointers, where the springs stay pinned at 0.
 */
export function useParallax(enabled: boolean): Parallax {
  const reduced = useReducedMotion();
  const active = enabled && !reduced;

  const rawX = useMotionValue(0);
  const rawY = useMotionValue(0);
  const x = useSpring(rawX, { stiffness: 60, damping: 22, mass: 0.6 });
  const y = useSpring(rawY, { stiffness: 60, damping: 22, mass: 0.6 });

  const onPointerMove = (event: React.PointerEvent<HTMLElement>) => {
    if (!active || event.pointerType !== 'mouse') return;
    const rect = event.currentTarget.getBoundingClientRect();
    rawX.set(((event.clientX - rect.left) / rect.width) * 2 - 1);
    rawY.set(((event.clientY - rect.top) / rect.height) * 2 - 1);
  };

  const onPointerLeave = () => {
    rawX.set(0);
    rawY.set(0);
  };

  // If parallax is switched off while the pointer is mid-scene (reduced motion enabled, or a
  // switch to a coarse pointer), recentre so the layers don't stay frozen at an offset.
  useEffect(() => {
    if (!active) {
      rawX.set(0);
      rawY.set(0);
    }
  }, [active, rawX, rawY]);

  return useMemo(() => ({ x, y, onPointerMove, onPointerLeave, active }), [x, y, active]);
}

/**
 * Depth offset for one scene layer. Called once per layer at the top level of the scene
 * component, so hook order stays fixed. Larger `distance` = closer to the camera.
 */
export function useLayerOffset(parallax: Parallax, distance: number) {
  // No `active` check here on purpose: when parallax is off the source values are pinned at 0,
  // so these already resolve to 0 — and reading `active` inside the closure would capture a
  // stale value if it ever flipped.
  const x = useTransform(parallax.x, (value) => value * -distance);
  const y = useTransform(parallax.y, (value) => value * -distance * 0.55);
  return { x, y };
}

/**
 * Keyboard shortcuts for entering the three zones and the dashboard, so the scene is
 * navigable without a pointer. Ignored while the visitor is typing in a field.
 */
export function useZoneShortcuts(handlers: Record<string, () => void>, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const handler = handlers[event.key.toLowerCase()];
      if (handler) {
        event.preventDefault();
        handler();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [handlers, enabled]);
}

/** A scene viewBox, matching the `minX minY width height` the SVG is rendered with. */
export interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Projects a point from the scene's viewBox into container pixels, mirroring what
 * `preserveAspectRatio="xMidYMid slice"` does to the SVG. This keeps the hotspots welded to
 * the cloud, the river and the waste pile at every aspect ratio, instead of drifting the way
 * fixed percentage offsets would once the scene is cropped.
 */
export function useSceneProjection(ref: React.RefObject<HTMLElement | null>, viewBox: ViewBox) {
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return useMemo(() => {
    const scale = size.width && size.height ? Math.max(size.width / viewBox.w, size.height / viewBox.h) : 0;
    const offsetX = (size.width - viewBox.w * scale) / 2;
    const offsetY = (size.height - viewBox.h * scale) / 2;
    return {
      ready: scale > 0,
      project: (x: number, y: number) => ({
        left: offsetX + (x - viewBox.x) * scale,
        top: offsetY + (y - viewBox.y) * scale,
      }),
    };
  }, [size, viewBox]);
}
