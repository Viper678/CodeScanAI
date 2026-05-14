import { describe, expect, it } from 'vitest';

import { normalizeKeywordItems, scanConfigSchema } from '@/lib/schemas/scan';

const BASE_VALID = {
  keywords: { case_sensitive: false, items: [], regex: false },
  name: 'My scan',
  scan_types: ['security' as const],
};

describe('scanConfigSchema', () => {
  it('rejects an empty scan_types list', () => {
    const result = scanConfigSchema.safeParse({
      ...BASE_VALID,
      scan_types: [],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.path).toEqual(['scan_types']);
    }
  });

  it('rejects keywords scan with empty items', () => {
    const result = scanConfigSchema.safeParse({
      ...BASE_VALID,
      keywords: { case_sensitive: false, items: [], regex: false },
      scan_types: ['keywords' as const],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.path).toEqual(['keywords', 'items']);
    }
  });

  it('rejects keywords scan with whitespace-only items (after trimming)', () => {
    const result = scanConfigSchema.safeParse({
      ...BASE_VALID,
      keywords: {
        case_sensitive: false,
        items: ['   ', '\t', ''],
        regex: false,
      },
      scan_types: ['keywords' as const],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.path).toEqual(['keywords', 'items']);
    }
  });

  it('accepts a single security scan with no keywords config provided', () => {
    const result = scanConfigSchema.safeParse({
      ...BASE_VALID,
      scan_types: ['security' as const],
    });
    expect(result.success).toBe(true);
  });

  it('accepts a valid keyword scan in plain (non-regex) mode', () => {
    const result = scanConfigSchema.safeParse({
      ...BASE_VALID,
      keywords: {
        case_sensitive: false,
        items: ['TODO', 'FIXME'],
        regex: false,
      },
      scan_types: ['keywords' as const],
    });
    expect(result.success).toBe(true);
  });

  it('rejects regex mode with an invalid pattern (per-pattern message)', () => {
    const result = scanConfigSchema.safeParse({
      ...BASE_VALID,
      keywords: {
        case_sensitive: false,
        items: ['valid', '[unclosed'],
        regex: true,
      },
      scan_types: ['keywords' as const],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      const badIssue = result.error.issues.find(
        (issue) =>
          issue.path[0] === 'keywords' &&
          issue.path[1] === 'items' &&
          typeof issue.path[2] === 'number',
      );
      expect(badIssue).toBeDefined();
      expect(badIssue?.path).toEqual(['keywords', 'items', 1]);
      expect(badIssue?.message).toBeTypeOf('string');
      expect(badIssue?.message.length).toBeGreaterThan(0);
    }
  });

  it('accepts a valid full form with multiple scan types', () => {
    const result = scanConfigSchema.safeParse({
      keywords: {
        case_sensitive: true,
        items: ['^password\\s*=', 'TODO'],
        regex: true,
      },
      name: 'Repo audit',
      scan_types: ['security' as const, 'bugs' as const, 'keywords' as const],
    });
    expect(result.success).toBe(true);
  });
});

describe('normalizeKeywordItems', () => {
  it('trims, drops empties, and dedupes (preserving first-seen order)', () => {
    expect(
      normalizeKeywordItems(['  TODO  ', 'FIXME', '', '\tFIXME', 'todo']),
    ).toEqual(['TODO', 'FIXME', 'todo']);
  });

  it('returns an empty list when all entries are whitespace', () => {
    expect(normalizeKeywordItems(['', '   ', '\n'])).toEqual([]);
  });
});
