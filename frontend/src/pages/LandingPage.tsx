/**
 * The landing experience.
 *
 * A single environmental scene is pinned to the viewport while a tall scroll track runs behind
 * it, so scrolling scrubs the environment's condition like a video: healthy daylight → air
 * degradation → water quality → waste accumulation → multi-signal correlation → coordinator at
 * night. Every one of those is interpolated from one progress value, so scrolling back up
 * reverses the whole story. Meanwhile clouds drift, the river flows and the trees move on
 * their own loops, independent of scroll.
 *
 * Data is never invented: the hotspot readouts and the coordinator panel show the results the
 * existing analysis pipeline produced, or say they are awaiting analysis. Navigation reuses
 * the application's existing routes and handlers.
 */
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { useCallback, useMemo, useRef, useState } from 'react';
import { EnterTransition } from '../components/landing/EnterTransition';
import { EnvironmentalHotspots } from '../components/landing/EnvironmentalHotspots';
import { EnvironmentalParticles } from '../components/landing/EnvironmentalParticles';
import { EnvironmentalScene } from '../components/landing/EnvironmentalScene';
import { buildHotspots } from '../components/landing/environmentState';
import { FinalCta } from '../components/landing/FinalCta';
import { MultiSignalCoordinator } from '../components/landing/MultiSignalCoordinator';
import { NarrativeText } from '../components/landing/NarrativeText';
import { FixedNavigation, ScrollProgressIndicator, TelemetryStrip } from '../components/landing/SceneChrome';
import type { EnterTarget, Zone } from '../components/landing/types';
import { useMediaQuery, useParallax, useZoneShortcuts } from '../components/landing/useSceneInteraction';
import { useScrollStory } from '../components/landing/useScrollStory';
import { useAnalysis } from '../context/AnalysisContext';
import { useNavigation } from '../context/NavigationContext';
import { useSettings } from '../context/SettingsContext';

export function LandingPage() {
  const analysis = useAnalysis();
  const { navigate } = useNavigation();
  const { settings } = useSettings();
  const reduced = useReducedMotion() ?? false;

  /** Interaction model (no hover) and composition (column framing) are separate concerns. */
  const touch = useMediaQuery('(pointer: coarse)');
  const narrow = useMediaQuery('(max-width: 767px)');

  const trackRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);
  const story = useScrollStory(trackRef);
  const parallax = useParallax(!touch);

  const [active, setActive] = useState<Zone | null>(null);
  const [entering, setEntering] = useState<EnterTarget | null>(null);

  const { display, state } = analysis;
  const hotspots = useMemo(() => buildHotspots({ display }), [display]);

  /** Entering an agent plays a short transition, then hands off to the existing route. */
  const enter = useCallback((target: EnterTarget) => {
    setActive(null);
    setEntering(target);
  }, []);

  const completeEnter = useCallback(() => {
    if (entering) navigate(entering);
    setEntering(null);
  }, [entering, navigate]);

  const shortcuts = useMemo(
    () => ({
      a: () => enter('air'),
      w: () => enter('water'),
      s: () => enter('waste'),
      d: () => enter('dashboard'),
      escape: () => setActive(null),
    }),
    [enter],
  );
  useZoneShortcuts(shortcuts, !entering);

  const startAnalysis = useCallback(() => {
    void analysis.runAnalysis();
    enter('dashboard');
  }, [analysis, enter]);

  return (
    <div className="relative bg-ink-950">
      {/* The scroll track's height sets how long the story takes to play. */}
      <div ref={trackRef} className="relative h-[680vh]">
        <div
          ref={sceneRef}
          className="sticky top-0 h-[100svh] overflow-hidden"
          onPointerMove={parallax.onPointerMove}
          onPointerLeave={() => parallax.onPointerLeave()}
        >
          {/* Scroll-driven colours are published here as CSS custom properties. */}
          <motion.div className="absolute inset-0" style={story.colorVars}>
            <EnvironmentalScene story={story} parallax={parallax} reduced={reduced} narrow={narrow} />
          </motion.div>

          <EnvironmentalParticles story={story} reduced={reduced} />
          <MultiSignalCoordinator story={story} narrow={narrow} />
          <NarrativeText story={story} narrow={narrow} />

          <EnvironmentalHotspots
            sceneRef={sceneRef}
            hotspots={hotspots}
            story={story}
            narrow={narrow}
            touch={touch}
            active={active}
            onActivate={setActive}
            onEnter={enter}
          />

          <FixedNavigation onDashboard={() => enter('dashboard')} onHowItWorks={() => navigate('how-it-works')} />
          <ScrollProgressIndicator story={story} narrow={narrow} />
          <TelemetryStrip
            location={state.result?.location ?? state.selectedLocation}
            mode={settings.demoMode ? 'demo' : 'live'}
            coordinatorOnline={Boolean(display.coordinator)}
            running={state.phase === 'running'}
            hidden={Boolean(active && touch)}
          />

          <p className="pointer-events-none absolute bottom-10 left-1/2 z-30 -translate-x-1/2 font-mono text-[9px] whitespace-nowrap text-white/50 uppercase tracking-[0.16em] sm:bottom-14 sm:text-[9.5px]">
            {touch ? 'Scroll to play · tap a zone' : 'Scroll to play · A · W · S to enter an agent'}
          </p>
        </div>
      </div>

      <FinalCta onStart={startAnalysis} onDashboard={() => enter('dashboard')} />

      <AnimatePresence>
        {entering && (
          <EnterTransition
            target={entering}
            detections={display.waste?.detections ?? []}
            reduced={reduced}
            onComplete={completeEnter}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
