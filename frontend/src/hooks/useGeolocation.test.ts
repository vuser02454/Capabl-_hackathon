/**
 * The safety-report location hook.
 *
 * Two contracts are worth protecting here. First, no permission prompt may fire on mount — a page
 * that asks the moment it loads trains people to deny, and the denial then costs us the fixes that
 * would have been given. Second, a denial is a supported branch, not a failure: the hook has to
 * report it distinctly so the report form can offer manual map selection instead of dead-ending.
 *
 * Nothing here touches a real geolocation device.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useGeolocation } from './useGeolocation';

const PERMISSION_DENIED = 1;
const POSITION_UNAVAILABLE = 2;
const TIMEOUT = 3;

function position(latitude = 12.9716, longitude = 77.5946, accuracy = 18) {
  return { coords: { latitude, longitude, accuracy } } as GeolocationPosition;
}

function stub(outcome: { position?: GeolocationPosition; error?: { code: number } }) {
  const getCurrentPosition = vi.fn((onSuccess: PositionCallback, onError?: PositionErrorCallback) => {
    if (outcome.error) {
      onError?.({ ...outcome.error, PERMISSION_DENIED, POSITION_UNAVAILABLE, TIMEOUT } as GeolocationPositionError);
    } else {
      onSuccess(outcome.position ?? position());
    }
  });
  Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition }, configurable: true, writable: true });
  return getCurrentPosition;
}

/** Two scripted attempts: the high-accuracy one, then the low-accuracy fallback. */
function stubSequence(...outcomes: Array<{ position?: GeolocationPosition; error?: { code: number } }>) {
  let call = 0;
  const optionsSeen: PositionOptions[] = [];
  const getCurrentPosition = vi.fn((
    onSuccess: PositionCallback, onError?: PositionErrorCallback, options?: PositionOptions,
  ) => {
    if (options) optionsSeen.push(options);
    const outcome = outcomes[Math.min(call, outcomes.length - 1)];
    call += 1;
    if (outcome.error) {
      onError?.({ ...outcome.error, PERMISSION_DENIED, POSITION_UNAVAILABLE, TIMEOUT } as GeolocationPositionError);
    } else {
      onSuccess(outcome.position ?? position());
    }
  });
  Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition }, configurable: true, writable: true });
  return { getCurrentPosition, optionsSeen };
}

afterEach(() => {
  Object.defineProperty(navigator, 'geolocation', { value: undefined, configurable: true, writable: true });
  vi.restoreAllMocks();
});

describe('useGeolocation', () => {
  it('does not prompt for permission on mount', () => {
    const getCurrentPosition = stub({ position: position() });
    const { result } = renderHook(() => useGeolocation());
    expect(getCurrentPosition).not.toHaveBeenCalled();
    expect(result.current.status).toBe('idle');
    expect(result.current.fix).toBeNull();
  });

  it('prompts only on an explicit locate() and keeps the reported accuracy', async () => {
    const getCurrentPosition = stub({ position: position(12.34, 56.78, 9) });
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.locate());

    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.status).toBe('ready'));
    // Accuracy is surfaced verbatim so the worker can judge whether the fix is worth confirming.
    expect(result.current.fix).toMatchObject({ latitude: 12.34, longitude: 56.78, accuracy: 9 });
    // Provenance travels with the fix so it is never inferred later.
    expect(result.current.fix?.source).toBe('browser_gps');
    expect(result.current.fix?.capturedAt).toBeTruthy();
  });

  it('treats a denial as its own branch and points at manual selection', async () => {
    stub({ error: { code: PERMISSION_DENIED } });
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.locate());

    await waitFor(() => expect(result.current.status).toBe('denied'));
    expect(result.current.status).not.toBe('error');
    expect(result.current.fix).toBeNull();
    expect(result.current.message).toMatch(/select it on the map/i);
  });

  it('distinguishes a technical failure from a denial', async () => {
    // Both attempts fail the same way, so the fallback is exhausted too.
    stub({ error: { code: POSITION_UNAVAILABLE } });
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.locate());

    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    expect(result.current.status).not.toBe('denied');
    expect(result.current.message).toMatch(/select it on the map/i);
  });

  it('reports an unavailable API without throwing, so the form still submits', () => {
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.locate());

    expect(result.current.status).toBe('unavailable');
    expect(result.current.fix).toBeNull();
  });

  it('accepts a manually picked coordinate as a fix', () => {
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.setManualFix({ latitude: 1.5, longitude: 2.5, accuracy: 0 }));

    expect(result.current.fix).toMatchObject({ latitude: 1.5, longitude: 2.5, accuracy: 0 });
  });

  it('clear() returns the hook to its unprompted state', async () => {
    stub({ position: position() });
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.locate());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    act(() => result.current.clear());

    expect(result.current.status).toBe('idle');
    expect(result.current.fix).toBeNull();
    expect(result.current.message).toBeNull();
  });
});

// --- the two-stage acquisition ------------------------------------------------------------------
//
// The bug this guards against: a single high-accuracy request with `maximumAge: 0` forces a cold
// hardware fix, which indoors and on desktops (no GPS radio) simply times out. The fix is to
// accept a recent cached fix and, on timeout, retry once without the high-accuracy requirement.

describe('the high-accuracy attempt', () => {
  it('accepts a recent cached fix rather than forcing a cold acquisition', () => {
    const { optionsSeen } = stubSequence({ position: position() });
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.locate());

    expect(optionsSeen[0].enableHighAccuracy).toBe(true);
    expect(optionsSeen[0].timeout).toBe(15_000);
    // The previous value of 0 refused every cached position and was the cause of the timeouts.
    expect(optionsSeen[0].maximumAge).toBe(30_000);
  });
});

describe('the low-accuracy fallback', () => {
  it('retries without high accuracy when the first attempt times out', async () => {
    const { getCurrentPosition, optionsSeen } = stubSequence(
      { error: { code: TIMEOUT } },
      { position: position(12.5, 77.5, 850) },
    );
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.locate());

    expect(getCurrentPosition).toHaveBeenCalledTimes(2);
    expect(optionsSeen[1].enableHighAccuracy).toBe(false);
    expect(optionsSeen[1].timeout).toBe(10_000);
    expect(optionsSeen[1].maximumAge).toBe(60_000);

    await waitFor(() => expect(result.current.status).toBe('ready'));
    // A coarse fix is still a fix; the accuracy is surfaced so it is never mistaken for a precise one.
    expect(result.current.fix?.accuracy).toBe(850);
    expect(result.current.fix?.source).toBe('browser_gps');
  });

  it('retries a position-unavailable failure too', () => {
    const { getCurrentPosition } = stubSequence(
      { error: { code: POSITION_UNAVAILABLE } },
      { position: position() },
    );
    const { result } = renderHook(() => useGeolocation());
    act(() => result.current.locate());
    expect(getCurrentPosition).toHaveBeenCalledTimes(2);
  });

  it('does NOT retry a denied permission', () => {
    const { getCurrentPosition } = stubSequence({ error: { code: PERMISSION_DENIED } });
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.locate());

    // Asking again would prompt the worker twice for an answer that will not change.
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe('denied');
  });

  it('gives one clear message when both attempts fail', async () => {
    stubSequence({ error: { code: TIMEOUT } }, { error: { code: TIMEOUT } });
    const { result } = renderHook(() => useGeolocation());

    act(() => result.current.locate());

    await waitFor(() => expect(result.current.status).toBe('timeout'));
    // Worded for the cause: a timeout may succeed on retry, so it says so rather than
    // reporting the same thing as a device with no positioning hardware.
    expect(result.current.message).toMatch(/gps location timed out/i);
    expect(result.current.message).toMatch(/search for a location or select it on the map/i);
    expect(result.current.fix).toBeNull();   // nothing is fabricated on failure
  });
});
