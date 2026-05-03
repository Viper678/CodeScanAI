'use client';

import { useState } from 'react';
import { Check, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { normalizeKeywordItems, tryCompileRegex } from '@/lib/schemas/scan';
import { cn } from '@/lib/utils';

type KeywordsEditorProps = {
  value: {
    items: string[];
    case_sensitive: boolean;
    regex: boolean;
  };
  onChange: (next: KeywordsEditorProps['value']) => void;
  /** Optional schema-level error for the items field (e.g. "Add at least one"). */
  itemsError?: string;
};

/** One row of validation feedback per pattern. */
type ValidationRow = {
  pattern: string;
  ok: boolean;
  message: string | null;
};

/**
 * Editor for the "keywords" scan-type configuration.
 *
 * - Items are entered one-per-line in a textarea (whitespace trimmed,
 *   duplicates dropped at validation/POST time).
 * - "Case sensitive" and "Regex mode" toggles default to off.
 * - "Validate" compiles each pattern via JS `new RegExp` only when regex mode
 *   is enabled, surfacing per-pattern OK / error feedback. JS RegExp differs
 *   slightly from Python `re`; the server is the ground truth at POST time.
 *   TODO(T3.x): swap this for a `/scans/validate-keywords` round-trip once
 *   the endpoint exists, so we surface real Python `re` errors.
 */
export function KeywordsEditor({
  value,
  onChange,
  itemsError,
}: Readonly<KeywordsEditorProps>) {
  const [validation, setValidation] = useState<ValidationRow[] | null>(null);

  const itemsText = value.items.join('\n');

  function handleItemsTextChange(next: string) {
    onChange({ ...value, items: next.split(/\r?\n/) });
    // Any edit invalidates the previous validate run.
    if (validation !== null) setValidation(null);
  }

  function runValidation() {
    const normalized = normalizeKeywordItems(value.items);
    if (!value.regex) {
      // In plain mode every non-empty pattern is trivially OK.
      setValidation(
        normalized.map((pattern) => ({ message: null, ok: true, pattern })),
      );
      return;
    }
    setValidation(
      normalized.map((pattern) => {
        const err = tryCompileRegex(pattern, value.case_sensitive);
        return { message: err, ok: err === null, pattern };
      }),
    );
  }

  return (
    <div className="space-y-4 rounded-2xl border border-border/80 bg-card/60 p-4">
      <div className="space-y-2">
        <Label htmlFor="keyword-items">Keywords (one per line)</Label>
        <textarea
          id="keyword-items"
          value={itemsText}
          onChange={(event) => handleItemsTextChange(event.target.value)}
          rows={5}
          spellCheck={false}
          className={cn(
            'w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 py-2 font-mono text-xs leading-5 transition-colors outline-none',
            'placeholder:text-muted-foreground',
            'focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
            'aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20',
            'dark:bg-input/30',
          )}
          aria-invalid={itemsError ? 'true' : 'false'}
          aria-describedby={itemsError ? 'keyword-items-error' : undefined}
          placeholder={'TODO\nFIXME\npassword\n…'}
        />
        {itemsError ? (
          <p id="keyword-items-error" className="text-sm text-red-500">
            {itemsError}
          </p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <Label htmlFor="keyword-case-sensitive" className="cursor-pointer">
          <Checkbox
            id="keyword-case-sensitive"
            checked={value.case_sensitive}
            onCheckedChange={(next) =>
              onChange({ ...value, case_sensitive: next })
            }
          />
          <span>Case sensitive</span>
        </Label>
        <Label htmlFor="keyword-regex" className="cursor-pointer">
          <Checkbox
            id="keyword-regex"
            checked={value.regex}
            onCheckedChange={(next) => {
              onChange({ ...value, regex: next });
              // Toggling regex mode invalidates prior validation results.
              if (validation !== null) setValidation(null);
            }}
          />
          <span>Regex mode</span>
        </Label>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={runValidation}
        >
          Validate
        </Button>
      </div>

      {validation !== null ? (
        <div
          data-testid="keyword-validation-results"
          className="space-y-1.5 rounded-xl border border-border/60 bg-background/50 p-3"
        >
          {validation.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No keywords to validate.
            </p>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {validation.map((row, index) => (
                <li
                  // Patterns may collide post-trim; index keeps keys stable.
                  key={`${row.pattern}-${index}`}
                  className="flex items-start gap-2"
                  data-state={row.ok ? 'ok' : 'error'}
                >
                  {row.ok ? (
                    <Check
                      className="mt-0.5 size-3.5 shrink-0 text-emerald-500"
                      aria-hidden="true"
                    />
                  ) : (
                    <X
                      className="mt-0.5 size-3.5 shrink-0 text-red-500"
                      aria-hidden="true"
                    />
                  )}
                  <span className="break-all font-mono text-foreground">
                    {row.pattern}
                  </span>
                  {!row.ok && row.message ? (
                    <span className="text-red-500">— {row.message}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
