'use client';

import { Bug, KeyRound, ShieldCheck } from 'lucide-react';

import { Checkbox } from '@/components/ui/checkbox';
import type { ScanType } from '@/lib/api/scans/types';
import { cn } from '@/lib/utils';

type ScanTypesSectionProps = {
  value: ScanType[];
  onChange: (next: ScanType[]) => void;
  errorMessage?: string;
};

type CardSpec = {
  blurb: string;
  icon: typeof ShieldCheck;
  label: string;
  type: ScanType;
};

const CARDS: ReadonlyArray<CardSpec> = [
  {
    blurb:
      'OWASP-style: injections, hardcoded secrets, weak crypto, insecure deserialization, …',
    icon: ShieldCheck,
    label: 'Security scan',
    type: 'security',
  },
  {
    blurb:
      'Logic bugs, null derefs, off-by-one, race conditions, resource leaks, …',
    icon: Bug,
    label: 'Bug report scan',
    type: 'bugs',
  },
  {
    blurb:
      'Search for specific strings or regex patterns across the selected files.',
    icon: KeyRound,
    label: 'Keyword scan',
    type: 'keywords',
  },
];

/** Toggle every scan type on/off, preserving canonical ordering. */
function toggle(current: ScanType[], type: ScanType): ScanType[] {
  if (current.includes(type)) return current.filter((t) => t !== type);
  // Re-sort into canonical order so the POST body is stable.
  const next = [...current, type];
  const order: Record<ScanType, number> = {
    bugs: 1,
    keywords: 2,
    security: 0,
  };
  return next.sort((a, b) => order[a] - order[b]);
}

export function ScanTypesSection({
  value,
  onChange,
  errorMessage,
}: Readonly<ScanTypesSectionProps>) {
  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-3">
        {CARDS.map((card) => {
          const checked = value.includes(card.type);
          const Icon = card.icon;
          const inputId = `scan-type-${card.type}`;
          return (
            <label
              key={card.type}
              htmlFor={inputId}
              className={cn(
                'flex cursor-pointer items-start gap-3 rounded-2xl border bg-card/60 p-4 transition-colors',
                checked
                  ? 'border-primary/60 bg-primary/5 shadow-sm shadow-primary/10'
                  : 'border-border/80 hover:border-border',
              )}
            >
              <Checkbox
                id={inputId}
                checked={checked}
                onCheckedChange={() => onChange(toggle(value, card.type))}
                aria-describedby={`${inputId}-blurb`}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Icon
                    className={cn(
                      'size-4',
                      checked ? 'text-primary' : 'text-muted-foreground',
                    )}
                    aria-hidden="true"
                  />
                  <p className="text-sm font-medium text-foreground">
                    {card.label}
                  </p>
                </div>
                <p
                  id={`${inputId}-blurb`}
                  className="mt-1.5 text-xs leading-relaxed text-muted-foreground"
                >
                  {card.blurb}
                </p>
              </div>
            </label>
          );
        })}
      </div>
      {errorMessage ? (
        <p role="alert" className="text-sm text-red-500">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
