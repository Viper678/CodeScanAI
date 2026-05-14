import { describe, expect, it } from 'vitest';

import { formatBytes, formatShortDate } from '@/lib/format';

describe('formatBytes', () => {
  it('renders < 1 KB as bytes', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1)).toBe('1 B');
    expect(formatBytes(1023)).toBe('1023 B');
  });

  it('renders < 1 MB as kilobytes with one decimal', () => {
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(1024 * 1023)).toBe('1023.0 KB');
  });

  it('renders < 1 GB as megabytes with one decimal', () => {
    expect(formatBytes(1024 * 1024)).toBe('1.0 MB');
    expect(formatBytes(1.2 * 1024 * 1024)).toBe('1.2 MB');
  });

  it('renders >= 1 GB as gigabytes with two decimals', () => {
    expect(formatBytes(1024 * 1024 * 1024)).toBe('1.00 GB');
    expect(formatBytes(2.5 * 1024 * 1024 * 1024)).toBe('2.50 GB');
  });
});

describe('formatShortDate', () => {
  it('returns the empty string for null/undefined/invalid input', () => {
    expect(formatShortDate(null)).toBe('');
    expect(formatShortDate(undefined)).toBe('');
    expect(formatShortDate('not a date')).toBe('');
  });

  it('returns a non-empty string for a valid ISO timestamp', () => {
    const out = formatShortDate('2026-05-03T14:32:00Z');
    expect(out.length).toBeGreaterThan(0);
    // We don't assert exact format because Intl varies by locale, but it
    // should at least mention the year.
    expect(out).toMatch(/2026/);
  });
});
