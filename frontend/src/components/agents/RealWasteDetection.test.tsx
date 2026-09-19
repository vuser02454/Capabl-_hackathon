/**
 * The localisation gate's UI contract.
 *
 * The backend can refuse a box before any crop is classified — a region that is a person, or a box
 * so large it is a region rather than an object. Such a box is evidence about the detector, not a
 * waste object. The regression this guards against is rendering one as a finding: a `plastic_bags`
 * label drawn over a person reads as a detection, which is precisely what the gate exists to stop.
 *
 * Nothing here touches the network or a real model. `fetch` is stubbed with the same shape the API
 * client already expects, so the component is driven through the real `ApiClient` and the real
 * `WasteSegregationResult` contract rather than a parallel mock of it.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../../context/SettingsContext';
import type { WasteSegregationDetection, WasteSegregationResult } from '../../types/agents';
import { RealWasteDetection } from './RealWasteDetection';

/** Accepted: a real waste object that survived the gate and was classified. */
const ACCEPTED: WasteSegregationDetection = {
  id: 'det-accepted',
  bbox: [320, 80, 400, 200],
  detectedObject: 'metal_cans',
  detectionConfidence: 0.94,
  classification: 'metal_cans',
  classificationConfidence: 0.88,
  segregation: 'non_biodegradable',
  status: 'confirmed',
  display: 'Metal can',
  localisationRejected: null,
  message: null,
};

/**
 * Refused: the original failure. The detector drew a box over a person and called it
 * `plastic_bags`; the gate vetoed it before classification, so no material is asserted.
 */
const REFUSED: WasteSegregationDetection = {
  id: 'det-refused',
  bbox: [0, 357, 155, 639],
  detectedObject: 'plastic_bags',
  detectionConfidence: 0.81,
  classification: null,
  classificationConfidence: null,
  segregation: 'uncertain',
  status: 'unavailable',
  localisationRejected: 'non_waste_object',
  message:
    "This region is a 'person' (80% confidence from the general-purpose detector, IoU 1.00), " +
    'which cannot be waste, so no material is asserted.',
};

const RESPONSE: WasteSegregationResult = {
  status: 'ok',
  model: 'waste_detector',
  classifierAvailable: true,
  imageWidth: 640,
  imageHeight: 640,
  detections: [ACCEPTED, REFUSED],
  summary: {
    totalObjects: 1,
    biodegradable: 0,
    nonBiodegradable: 1,
    uncertain: 0,
    duplicateBoxesMerged: 0,
    nonWasteObjects: 0,
    localisationsRejected: 1,
  },
  message: null,
};

/** jsdom has no object URLs, and the component makes one to preview the uploaded photo. */
function stubObjectUrls() {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:photo', revokeObjectURL: () => {} }));
}

function stubFetch(payload: WasteSegregationResult) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify(payload)),
    } as Response),
  );
}

/** Render, hand the component a photo, and wait for the analysed result to appear. */
async function analysePhoto(payload: WasteSegregationResult = RESPONSE) {
  stubObjectUrls();
  stubFetch(payload);
  const { container } = render(
    <SettingsProvider>
      <RealWasteDetection />
    </SettingsProvider>,
  );

  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error('the file input the component uploads through is missing');
  const file = new File(['not-a-real-jpeg'], 'photo.jpg', { type: 'image/jpeg' });
  Object.defineProperty(input, 'files', { value: [file] });
  fireEvent.change(input);

  await waitFor(() => expect(screen.getByAltText('Analysed photo')).toBeTruthy());
  return container;
}

/** The boxes actually drawn over the photograph. */
const overlayBoxes = () =>
  Array.from(screen.getByAltText('Analysed photo').parentElement?.querySelectorAll('button') ?? []);

/** The findings list — accepted detections only. */
const findingRows = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('button[class*="w-full rounded-lg border"]'));

/** The "Refused before classification" container. */
const refusedBlock = () => screen.getByText(/Refused before classification/).closest('div');

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('a box the localisation gate refused', () => {
  it('is shown under its own heading, with the reason it was refused', async () => {
    await analysePhoto();

    const block = refusedBlock();
    expect(block).toBeTruthy();
    expect(block?.textContent).toContain('Refused before classification · 1');
    // The reason, and the measurement behind it — a rejection that cannot be checked is not much
    // better than a wrong label.
    expect(block?.textContent).toContain('region is not waste');
    expect(block?.textContent).toContain("This region is a 'person'");
    expect(block?.textContent).toContain('plastic_bags');
    // Stated plainly, so a refusal cannot be mistaken for a finding.
    expect(block?.textContent).toContain('no material is asserted');
  });

  it('is never drawn over the photo', async () => {
    await analysePhoto();

    const boxes = overlayBoxes();
    expect(boxes).toHaveLength(1);
    expect(boxes[0].textContent).toContain('metal_cans');
    // The regression: "#1 plastic_bags" sitting on a person.
    expect(boxes.some((box) => box.textContent?.includes('plastic_bags'))).toBe(false);
  });

  it('is never listed among the findings', async () => {
    const container = await analysePhoto();

    const rows = findingRows(container);
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('metal_cans');
    expect(rows.some((row) => row.textContent?.includes('plastic_bags'))).toBe(false);
  });

  it('is counted as refused rather than as waste', async () => {
    const container = await analysePhoto();

    expect(container.textContent).toContain('Refused:');
    // One object survived the gate; the refused box must not inflate the total.
    expect(container.textContent).toContain('Objects: 1');
  });

  it('keeps the light-theme surface the merge introduced', async () => {
    await analysePhoto();

    const className = refusedBlock()?.className ?? '';
    expect(className).toContain('border-black/[0.06]');
    expect(className).toContain('bg-black/[0.02]');
    // A dark-theme remnant here would read as a hole in the light dashboard.
    expect(className).not.toContain('white/');
  });
});

describe('an accepted detection', () => {
  it('still renders as a finding, with both stages and its segregation', async () => {
    const container = await analysePhoto();

    const row = findingRows(container)[0];
    expect(row.textContent).toContain('metal_cans');
    expect(row.textContent).toContain('detection 94%');
    expect(row.textContent).toContain('Metal can');
    expect(row.textContent).toContain('classification 88%');
    expect(row.textContent).toContain('Non-biodegradable');
  });

  it('is unaffected when nothing was refused', async () => {
    const container = await analysePhoto({
      ...RESPONSE,
      detections: [ACCEPTED],
      summary: { ...RESPONSE.summary, localisationsRejected: 0 },
    });

    expect(findingRows(container)).toHaveLength(1);
    expect(overlayBoxes()).toHaveLength(1);
    expect(screen.queryByText(/Refused before classification/)).toBeNull();
  });
});

describe('an image where every box was refused', () => {
  it('says so, rather than reporting that nothing was found', async () => {
    const container = await analysePhoto({
      ...RESPONSE,
      detections: [REFUSED],
      summary: { ...RESPONSE.summary, totalObjects: 0, nonBiodegradable: 0, localisationsRejected: 1 },
    });

    // "Nothing found" and "everything found was refused" are different answers, and only one of
    // them is about the photo.
    expect(container.textContent).toContain('No waste object survived localisation checks');
    expect(container.textContent).not.toContain('The detector found no objects it recognises');
    expect(overlayBoxes()).toHaveLength(0);
    expect(findingRows(container)).toHaveLength(0);
  });
});
