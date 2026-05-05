import { describe, expect, it } from 'vitest';

import {
  parseScansFilters,
  serializeScansFilters,
} from '@/lib/api/scans/use-scans-filters';

describe('parseScansFilters', () => {
  it('returns empty filters for an empty query string', () => {
    expect(parseScansFilters(new URLSearchParams())).toEqual({ status: [] });
  });

  it('parses a comma-joined status list', () => {
    const params = new URLSearchParams('status=running,completed');
    expect(parseScansFilters(params)).toEqual({
      status: ['running', 'completed'],
    });
  });

  it('drops unknown / duplicate / blank tokens (stale links degrade to no filter)', () => {
    const params = new URLSearchParams(
      'status=running,bogus,running,,COMPLETED,completed',
    );
    expect(parseScansFilters(params)).toEqual({
      // 'COMPLETED' is uppercase and not in the allowed set → dropped.
      // 'completed' deduped against itself.
      status: ['running', 'completed'],
    });
  });
});

describe('serializeScansFilters', () => {
  it('drops empty status so the URL stays clean', () => {
    expect(serializeScansFilters({ status: [] })).toBe('');
  });

  it('round-trips with parseScansFilters', () => {
    const filters = {
      status: ['pending' as const, 'cancelled' as const],
    };
    const qs = serializeScansFilters(filters);
    expect(parseScansFilters(new URLSearchParams(qs))).toEqual(filters);
  });
});
