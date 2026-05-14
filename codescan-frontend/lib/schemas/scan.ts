import { z } from 'zod';

import type { ScanType } from '@/lib/api/scans/types';

/**
 * Try compiling a regex pattern via `new RegExp`. Returns `null` on success or
 * a human-readable error message string on failure. Used for client-side
 * "validate" UX in the keywords editor and for schema-level validation when
 * `regex=true`.
 *
 * Note: JavaScript's RegExp dialect is NOT identical to Python's `re`, so the
 * server is the ground truth at POST time. This is typing-time UX only.
 *
 * TODO(T3.x): replace with a server round-trip to `/scans/validate-keywords`
 * once that endpoint exists, so we surface real Python `re` errors.
 */
export function tryCompileRegex(
  pattern: string,
  caseSensitive: boolean,
): string | null {
  try {
    new RegExp(pattern, caseSensitive ? '' : 'i');
    return null;
  } catch (error) {
    if (error instanceof Error) return error.message;
    return 'Invalid regular expression.';
  }
}

/** Trim, drop empties, and dedupe (preserving first-seen order). */
export function normalizeKeywordItems(raw: ReadonlyArray<string>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of raw) {
    const trimmed = item.trim();
    if (trimmed.length === 0) continue;
    if (seen.has(trimmed)) continue;
    seen.add(trimmed);
    out.push(trimmed);
  }
  return out;
}

const SCAN_TYPE_VALUES = [
  'security',
  'bugs',
  'keywords',
] as const satisfies ReadonlyArray<ScanType>;

const keywordsConfigSchema = z.object({
  case_sensitive: z.boolean(),
  /**
   * Items as the user typed them. Validation normalizes (trim/dedupe) the
   * list before checking emptiness; the form holds the raw list so we can
   * render what the user typed verbatim.
   */
  items: z.array(z.string()),
  regex: z.boolean(),
});

/**
 * Schema for Step 3 (Scan configuration). Used as a zodResolver on
 * react-hook-form, so the input/output shapes are intentionally identical
 * (no `.transform()`).
 *
 * Cross-field rules:
 * - `scan_types` must be non-empty.
 * - if `keywords` ∈ `scan_types`, `keywords.items` must be non-empty after
 *   trim+dedupe.
 * - if `keywords.regex` is on, every (normalized) pattern must compile via
 *   `new RegExp` — per-pattern errors land on `keywords.items.<index>`.
 */
export const scanConfigSchema = z
  .object({
    keywords: keywordsConfigSchema,
    /** Optional; blank ↦ server gets `null`. */
    name: z.string().max(255).optional(),
    scan_types: z.array(z.enum(SCAN_TYPE_VALUES)),
  })
  .superRefine((value, ctx) => {
    if (value.scan_types.length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Pick at least one scan type.',
        path: ['scan_types'],
      });
    }

    if (value.scan_types.includes('keywords')) {
      const normalized = normalizeKeywordItems(value.keywords.items);
      if (normalized.length === 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'Add at least one keyword.',
          path: ['keywords', 'items'],
        });
        return;
      }

      if (value.keywords.regex) {
        normalized.forEach((pattern, index) => {
          const err = tryCompileRegex(pattern, value.keywords.case_sensitive);
          if (err !== null) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              message: err,
              path: ['keywords', 'items', index],
            });
          }
        });
      }
    }
  });

/** The form's value shape (and what `onSubmit` hands back to the page). */
export type ScanConfigValues = z.infer<typeof scanConfigSchema>;

/** Defaults seeded into react-hook-form. The page overrides `name`. */
export const DEFAULT_SCAN_CONFIG: ScanConfigValues = {
  keywords: { case_sensitive: false, items: [], regex: false },
  name: '',
  scan_types: ['security'],
};
