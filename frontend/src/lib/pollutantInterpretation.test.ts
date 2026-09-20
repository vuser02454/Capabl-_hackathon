import { describe, expect, it } from 'vitest';
import { evaluateComparison, normalizePeriod, normalizeUnit } from './pollutantInterpretation';
import { getPollutantMetadata, HEALTH_DISCLAIMER } from '../data/pollutantMetadata';

describe('pollutantInterpretation', () => {
  it('normalizes units and periods correctly', () => {
    expect(normalizeUnit(' µg/m³ ')).toBe('ug/m3');
    expect(normalizePeriod('24h')).toBe('24-hour');
    expect(normalizePeriod('8-hr')).toBe('8-hour');
  });

  it('1. PM2.5 91 µg/m³ with 24-hour WHO reference of 15', () => {
    const res = evaluateComparison(91, 'µg/m³', '24-hour', 15, 'µg/m³', '24-hour', 0.91);
    expect(res.isCompatible).toBe(true);
    expect(res.status).toBe('compatible');
    expect(res.ratio).toBe(6.07);
    expect(res.difference).toBe(76);
    expect(res.percentageDifference).toBe(506.7);
    expect(res.interpretationLabel).toBe('CRITICAL');
    expect(res.interpretationDescription).not.toMatch(/100% safe/i);
  });

  it('2. PM10 165 µg/m³ with 24-hour WHO reference of 45', () => {
    const res = evaluateComparison(165, 'µg/m³', '24-hour', 45, 'µg/m³', '24-hour', 0.92);
    expect(res.isCompatible).toBe(true);
    expect(res.ratio).toBe(3.67);
    expect(res.difference).toBe(120);
    expect(res.percentageDifference).toBe(266.7);
    expect(res.interpretationLabel).toBe('CRITICAL');
  });

  it('3. NO2 42 µg/m³ with 24-hour WHO reference of 25', () => {
    const res = evaluateComparison(42, 'µg/m³', '24-hour', 25, 'µg/m³', '24-hour', 0.53);
    expect(res.isCompatible).toBe(true);
    expect(res.ratio).toBe(1.68);
    expect(res.difference).toBe(17);
    expect(res.percentageDifference).toBe(68.0);
    expect(res.interpretationLabel).toBe('ABOVE GUIDELINE REFERENCE');
  });

  it('4. O3 31 µg/m³ with 8-hour reference of 100 (compatible averaging period)', () => {
    const res = evaluateComparison(31, 'µg/m³', '8-hour', 100, 'µg/m³', '8-hour', 0.31);
    expect(res.isCompatible).toBe(true);
    expect(res.ratio).toBe(0.31);
    expect(res.difference).toBe(-69);
    expect(res.percentageDifference).toBe(-69.0);
    expect(res.interpretationLabel).toBe('WITHIN GUIDELINE REFERENCE');
    expect(res.interpretationDescription).toBe('Within the WHO guideline reference');
    expect(res.interpretationDescription).not.toMatch(/100% safe/i);
  });

  it('5. Unit mismatch prevents misleading calculation', () => {
    const res = evaluateComparison(4, 'mg/m³', '24-hour', 15, 'µg/m³', '24-hour');
    expect(res.isCompatible).toBe(false);
    expect(res.status).toBe('mismatch_units');
    expect(res.ratio).toBeNull();
    expect(res.note).toContain('Unit mismatch');
  });

  it('6. Averaging-period mismatch returns withholding notice', () => {
    const res = evaluateComparison(91, 'µg/m³', '1-hour', 15, 'µg/m³', '24-hour');
    expect(res.isCompatible).toBe(false);
    expect(res.status).toBe('mismatch_averaging_period');
    expect(res.ratio).toBeNull();
    expect(res.note).toBe('Comparable WHO reference unavailable for this averaging period.');
  });

  it('7. Missing guideline handled gracefully', () => {
    const res = evaluateComparison(50, 'µg/m³', '24-hour', null, 'µg/m³', '24-hour');
    expect(res.isCompatible).toBe(false);
    expect(res.status).toBe('missing_data');
    expect(res.ratio).toBeNull();
  });

  it('8. Missing measurement handled gracefully', () => {
    const res = evaluateComparison(null, 'µg/m³', '24-hour', 15, 'µg/m³', '24-hour');
    expect(res.isCompatible).toBe(false);
    expect(res.status).toBe('missing_data');
    expect(res.ratio).toBeNull();
  });

  it('9. O3 secondary-pollutant metadata is verified', () => {
    const o3 = getPollutantMetadata('o3');
    expect(o3).toBeDefined();
    expect(o3?.is_secondary_pollutant).toBe(true);
    expect(o3?.source_type).toBe('secondary');
    expect(o3?.precursor_pollutants).toEqual(expect.arrayContaining(['NOₓ (Nitrogen Oxides)', 'VOCs (Volatile Organic Compounds)']));
    expect(o3?.description).toContain('secondary pollutant');
  });

  it('10. Health disclaimer is present and non-prescriptive', () => {
    expect(HEALTH_DISCLAIMER).toContain('not a medical diagnosis');
    expect(HEALTH_DISCLAIMER).toContain('published air-quality guidance');
  });
});
