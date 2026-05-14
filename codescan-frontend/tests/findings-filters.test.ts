import { describe, expect, it } from 'vitest';

import {
  parseFindingsFilters,
  serializeFindingsFilters,
} from '@/lib/api/findings/use-findings-filters';

describe('parseFindingsFilters', () => {
  it('returns empty filters for an empty query string', () => {
    expect(parseFindingsFilters(new URLSearchParams())).toEqual({
      file_id: null,
      scan_type: [],
      severity: [],
    });
  });

  it('parses comma-joined severity and scan_type lists', () => {
    const params = new URLSearchParams(
      'severity=critical,high&scan_type=security,bugs&file_id=file-123',
    );
    expect(parseFindingsFilters(params)).toEqual({
      file_id: 'file-123',
      scan_type: ['security', 'bugs'],
      severity: ['critical', 'high'],
    });
  });

  it('drops unknown / duplicate / blank tokens', () => {
    const params = new URLSearchParams(
      'severity=high,bogus,high,,critical&scan_type=keywords,wat',
    );
    expect(parseFindingsFilters(params)).toEqual({
      file_id: null,
      scan_type: ['keywords'],
      severity: ['high', 'critical'],
    });
  });
});

describe('serializeFindingsFilters', () => {
  it('drops empty arrays so the URL stays clean', () => {
    expect(
      serializeFindingsFilters({
        file_id: null,
        scan_type: [],
        severity: [],
      }),
    ).toBe('');
  });

  it('round-trips with parseFindingsFilters', () => {
    const filters = {
      file_id: 'file-9',
      scan_type: ['security' as const, 'keywords' as const],
      severity: ['low' as const, 'medium' as const],
    };
    const qs = serializeFindingsFilters(filters);
    expect(parseFindingsFilters(new URLSearchParams(qs))).toEqual(filters);
  });
});
