import Link from 'next/link';
import type { LucideIcon } from 'lucide-react';

import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type EmptyStateProps = {
  action: {
    href: string;
    label: string;
  };
  description: string;
  icon: LucideIcon;
  title: string;
};

export function EmptyState({
  action,
  description,
  icon: Icon,
  title,
}: Readonly<EmptyStateProps>) {
  return (
    <section className="flex min-h-[55vh] items-center justify-center">
      <div className="mx-auto flex w-full max-w-xl flex-col items-center rounded-3xl border border-dashed border-border/80 bg-card/50 px-8 py-14 text-center shadow-sm">
        <div className="mb-5 flex size-16 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <Icon className="size-8" aria-hidden="true" />
        </div>
        <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
        <p className="mt-3 max-w-md text-sm leading-6 text-muted-foreground">
          {description}
        </p>
        <Link
          href={action.href}
          className={cn(
            buttonVariants({ size: 'lg' }),
            'mt-8 bg-primary text-primary-foreground hover:bg-primary/90',
          )}
        >
          {action.label}
        </Link>
      </div>
    </section>
  );
}
