export type AppErrorCode =
  | 'INVALID_LOCATION'
  | 'NO_MONITORING_DATA'
  | 'API_UNAVAILABLE'
  | 'API_TIMEOUT'
  | 'DATA_SOURCE_ERROR'
  | 'PROVIDER_NOT_CONFIGURED'
  | 'SENSOR_DATA_UNAVAILABLE'
  | 'INVALID_IMAGE'
  | 'AGENT_TIMEOUT'
  | 'ANALYSIS_FAILED'
  | 'VALIDATION_ERROR'
  | 'UNKNOWN';

const TITLES: Record<AppErrorCode, string> = {
  INVALID_LOCATION: 'Location not recognised',
  NO_MONITORING_DATA: 'No monitoring data',
  API_UNAVAILABLE: 'API unavailable',
  API_TIMEOUT: 'Request timed out',
  DATA_SOURCE_ERROR: 'Data source error',
  PROVIDER_NOT_CONFIGURED: 'Integration not configured',
  SENSOR_DATA_UNAVAILABLE: 'Sensor data unavailable',
  INVALID_IMAGE: 'Image could not be analyzed',
  AGENT_TIMEOUT: 'Agent timed out',
  ANALYSIS_FAILED: 'Analysis failed',
  VALIDATION_ERROR: 'Invalid request',
  UNKNOWN: 'Something went wrong',
};

export class AppError extends Error {
  readonly code: AppErrorCode;
  readonly title: string;

  constructor(code: AppErrorCode, message: string) {
    super(message);
    this.name = 'AppError';
    this.code = code;
    this.title = TITLES[code] ?? TITLES.UNKNOWN;
  }
}

export function toAppError(error: unknown): AppError {
  if (error instanceof AppError) return error;
  if (error instanceof DOMException && error.name === 'AbortError') {
    return new AppError('ANALYSIS_FAILED', 'The analysis was cancelled.');
  }
  const message = error instanceof Error ? error.message : 'An unexpected error occurred.';
  return new AppError('UNKNOWN', message);
}

export const isAbortError = (error: unknown) =>
  error instanceof DOMException && error.name === 'AbortError';

export const isKnownCode = (code: string): code is AppErrorCode => code in TITLES;
