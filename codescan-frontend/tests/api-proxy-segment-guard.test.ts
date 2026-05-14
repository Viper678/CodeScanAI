/**
 * Regression: catch-all API proxy rejects path-traversal segments.
 *
 * The runtime proxy at codescan-frontend/app/api/v1/[...path]/route.ts forwards
 * /api/v1/<path> to the api service. Codex flagged that encoded ``..``
 * segments (e.g. ``%2e%2e`` or ``%252e%252e``) would normalize out of the
 * /api/v1 prefix via ``new URL()``'s path resolution — exposing internal
 * api routes like ``/readyz`` / ``/healthz``. The route handler now
 * validates each segment via ``isUnsafeSegment`` BEFORE constructing the
 * upstream URL. This test pins down the rule: any segment that recursively
 * decodes to ``.`` / ``..`` / empty must be rejected, regardless of
 * how many layers of percent encoding wrap it.
 */

import { describe, expect, it } from 'vitest';

import { isUnsafeSegment } from '@/lib/api/proxy-segment-guard';

describe('isUnsafeSegment', () => {
  it('rejects plain traversal segments', () => {
    expect(isUnsafeSegment('..')).toBe(true);
    expect(isUnsafeSegment('.')).toBe(true);
  });

  it('rejects empty segments (double-slash smuggling)', () => {
    expect(isUnsafeSegment('')).toBe(true);
  });

  it('rejects single-encoded traversal segments', () => {
    expect(isUnsafeSegment('%2e%2e')).toBe(true);
    expect(isUnsafeSegment('%2E%2E')).toBe(true);
    expect(isUnsafeSegment('%2e.')).toBe(true);
    expect(isUnsafeSegment('.%2E')).toBe(true);
    expect(isUnsafeSegment('%2e')).toBe(true);
  });

  it('rejects double-encoded traversal segments', () => {
    expect(isUnsafeSegment('%252e%252e')).toBe(true);
    expect(isUnsafeSegment('%252E%252E')).toBe(true);
  });

  it('rejects malformed percent encoding', () => {
    expect(isUnsafeSegment('%2')).toBe(true);
    expect(isUnsafeSegment('%zz')).toBe(true);
    expect(isUnsafeSegment('%')).toBe(true);
  });

  it('accepts normal path segments', () => {
    expect(isUnsafeSegment('scans')).toBe(false);
    expect(isUnsafeSegment('uploads')).toBe(false);
    expect(isUnsafeSegment('abc-123')).toBe(false);
    expect(isUnsafeSegment('019f6fd1-7c5b-7a3a-a4b3-2c7a13e6d4b9')).toBe(false);
    expect(isUnsafeSegment('hello.py')).toBe(false);
  });

  it('accepts segments that contain dots but are not entirely dots', () => {
    expect(isUnsafeSegment('main.py')).toBe(false);
    expect(isUnsafeSegment('..foo')).toBe(false);
    expect(isUnsafeSegment('foo..')).toBe(false);
    expect(isUnsafeSegment('.dotfile')).toBe(false);
  });
});
