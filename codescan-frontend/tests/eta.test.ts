import { describe, expect, it } from 'vitest';

import { computeEta, formatEta } from '@/lib/scan-progress/eta';

describe('computeEta', () => {
  it('returns null when remaining is 0', () => {
    expect(
      computeEta({ latencies: [1000, 2000, 3000], remaining: 0 }),
    ).toBeNull();
  });

  it('returns null when remaining is negative', () => {
    expect(
      computeEta({ latencies: [1000, 2000, 3000], remaining: -5 }),
    ).toBeNull();
  });

  it('returns null below the 3-sample threshold', () => {
    expect(computeEta({ latencies: [], remaining: 10 })).toBeNull();
    expect(computeEta({ latencies: [1000], remaining: 10 })).toBeNull();
    expect(computeEta({ latencies: [1000, 2000], remaining: 10 })).toBeNull();
  });

  it('returns remaining * average when at threshold', () => {
    // avg = 2000, remaining = 5 → 10000
    expect(computeEta({ latencies: [1000, 2000, 3000], remaining: 5 })).toBe(
      10_000,
    );
  });

  it('only considers the last 10 latencies', () => {
    // First 5 huge values are dropped; last 10 average to 1000.
    const latencies = [
      9_999_999, 9_999_999, 9_999_999, 9_999_999, 9_999_999, 1000, 1000, 1000,
      1000, 1000, 1000, 1000, 1000, 1000, 1000,
    ];
    expect(computeEta({ latencies, remaining: 4 })).toBe(4_000);
  });

  it('rounds to the nearest millisecond', () => {
    // avg = (1000 + 2000 + 1500) / 3 = 1500. Remaining = 3 → 4500.
    expect(computeEta({ latencies: [1000, 2000, 1500], remaining: 3 })).toBe(
      4_500,
    );
  });
});

describe('formatEta', () => {
  it('renders sub-minute as Xs', () => {
    expect(formatEta(0)).toBe('0s');
    expect(formatEta(500)).toBe('1s'); // rounds
    expect(formatEta(45_000)).toBe('45s');
  });

  it('renders >= 60s as Xm Ys', () => {
    expect(formatEta(60_000)).toBe('1m 0s');
    expect(formatEta(125_000)).toBe('2m 5s');
  });

  it('clamps negative input to 0s', () => {
    expect(formatEta(-100)).toBe('0s');
  });
});
