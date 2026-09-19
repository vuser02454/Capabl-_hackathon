/**
 * Waste detection source used by the Waste Detection Agent.
 *
 * The mock detector is deterministic (same image -> same detections) and matches
 * backend/services/waste_detection_service.py. A YOLO model runs server-side.
 */
import type { LocationProfile } from '../../data/locations';
import { roundHalfUp } from '../../lib/risk';
import { seeded } from '../../lib/rng';
import type { Detection, WasteCategory } from '../../types/agents';
import { AppError } from '../errors';

/**
 * Keep in step with ECOSENTINEL_MAX_UPLOAD_MB (backend/config.py, default 25). The backend is the
 * real gate; this check only saves the user a pointless upload before the server rejects it.
 */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

const LABELS: Record<WasteCategory, string[]> = {
  plastic: ['PET bottle', 'Plastic bag', 'Food wrapper', 'Plastic cup', 'Styrofoam'],
  paper: ['Cardboard', 'Paper cup', 'Newspaper'],
  other: ['Metal can', 'Glass bottle', 'Textile', 'Rubber'],
};

export interface ImageInput {
  name: string;
  size: number;
}

export interface DetectionOutput {
  sourceId: string;
  sourceName: string;
  inputType: 'camera' | 'upload';
  model: string;
  detections: Detection[];
  isMock: boolean;
}

export interface WasteDetectionSource {
  readonly name: string;
  readonly model: string;
  detectCameraFrame(location: LocationProfile): Promise<DetectionOutput>;
  detectImage(image: ImageInput, location: LocationProfile): Promise<DetectionOutput>;
}

export function validateImageFile(file: File | null | undefined): File {
  if (!file) throw new AppError('INVALID_IMAGE', 'No image was selected.');
  if (!file.type.startsWith('image/')) {
    throw new AppError('INVALID_IMAGE', 'Unsupported file type. Upload a JPG, PNG or WebP image.');
  }
  if (file.size === 0) throw new AppError('INVALID_IMAGE', 'The selected image is empty.');
  if (file.size > MAX_UPLOAD_BYTES)
    throw new AppError('INVALID_IMAGE', `Image exceeds the ${MAX_UPLOAD_BYTES / 1024 / 1024} MB upload limit.`);
  return file;
}

export function generateDetections(seedKey: string, plastic: number, paper: number, other: number): Detection[] {
  const rng = seeded(seedKey);
  const categories: WasteCategory[] = [
    ...Array<WasteCategory>(plastic).fill('plastic'),
    ...Array<WasteCategory>(paper).fill('paper'),
    ...Array<WasteCategory>(other).fill('other'),
  ];
  return categories.map((category, index) => {
    const options = LABELS[category];
    const label = options[Math.floor(rng() * options.length)];
    const width = 0.05 + rng() * 0.09;
    const height = 0.05 + rng() * 0.1;
    const x = 0.03 + rng() * (0.94 - width);
    const y = 0.28 + rng() * (0.68 - height);
    const confidence = roundHalfUp(0.76 + rng() * 0.22, 2);
    return {
      id: `det-${String(index + 1).padStart(2, '0')}`,
      label,
      category,
      confidence,
      bbox: [x, y, width, height].map((value) => roundHalfUp(value, 4)) as Detection['bbox'],
    };
  });
}

export function simulatedUploadCounts(seedKey: string) {
  const rng = seeded(seedKey);
  const total = 6 + Math.floor(rng() * 20);
  const plastic = roundHalfUp(total * (0.4 + rng() * 0.25), 0);
  const paper = Math.floor((total - plastic) * (0.3 + rng() * 0.4));
  return { plastic, paper, other: total - plastic - paper };
}

export class MockWasteDetector implements WasteDetectionSource {
  readonly name = 'Simulated detector';
  readonly model = 'YOLOv8n-waste (simulated)';

  async detectCameraFrame(location: LocationProfile): Promise<DetectionOutput> {
    const { waste } = location;
    return {
      sourceId: waste.cameraId,
      sourceName: waste.cameraName,
      inputType: 'camera',
      model: this.model,
      detections: generateDetections(`camera:${location.id}`, waste.plastic, waste.paper, waste.other),
      isMock: true,
    };
  }

  async detectImage(image: ImageInput): Promise<DetectionOutput> {
    const seedKey = `upload:${image.name}:${image.size}`;
    const counts = simulatedUploadCounts(seedKey);
    return {
      sourceId: 'UPLOAD',
      sourceName: image.name,
      inputType: 'upload',
      model: this.model,
      detections: generateDetections(`${seedKey}:boxes`, counts.plastic, counts.paper, counts.other),
      isMock: true,
    };
  }
}
