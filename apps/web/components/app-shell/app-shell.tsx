'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { PanelLeft, Plus } from 'lucide-react';

import { APP_NAV_ITEMS } from '@/components/app-shell/nav-items';
import { ThemeToggleMenu } from '@/components/app-shell/theme-toggle-menu';
import { buttonVariants } from '@/components/ui/button';
import { useShellStore } from '@/lib/stores/use-shell-store';
import { cn } from '@/lib/utils';

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: Readonly<AppShellProps>) {
  const pathname = usePathname();
  const collapsed = useShellStore((state) => state.collapsed);
  const toggleCollapsed = useShellStore((state) => state.toggleCollapsed);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="flex min-h-screen">
        <aside
          className={cn(
            'flex min-h-screen w-20 shrink-0 flex-col border-r border-border/80 bg-card/70 backdrop-blur lg:transition-[width]',
            collapsed ? 'lg:w-20' : 'lg:w-72',
          )}
        >
          <div className="flex h-16 items-center justify-center border-b border-border/80 px-3 lg:justify-between">
            <Link
              href="/scans"
              className="flex items-center gap-3 rounded-md px-2 py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <span className="flex size-9 items-center justify-center rounded-xl bg-primary/15 text-sm font-semibold text-primary">
                CS
              </span>
              <div className={cn('hidden lg:block', collapsed && 'lg:hidden')}>
                <p className="text-sm font-semibold">CodeScan</p>
                <p className="text-xs text-muted-foreground">
                  Frontend baseline
                </p>
              </div>
            </Link>
            <button
              type="button"
              onClick={toggleCollapsed}
              className={cn(
                'hidden rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background lg:inline-flex',
                collapsed && 'lg:mx-auto',
              )}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <PanelLeft className="size-4" />
            </button>
          </div>

          <nav aria-label="Primary navigation" className="flex-1 px-3 py-6">
            <ul className="space-y-2">
              {APP_NAV_ITEMS.map(({ href, icon: Icon, label }) => {
                const isActive =
                  pathname === href ||
                  (href === '/scans' && pathname.startsWith('/scans'));

                return (
                  <li key={href}>
                    <Link
                      href={href}
                      aria-label={label}
                      className={cn(
                        'flex min-h-11 items-center gap-3 rounded-r-xl border-l-2 border-transparent px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                        isActive &&
                          'border-indigo-500 bg-zinc-100 text-foreground dark:bg-zinc-800',
                        collapsed
                          ? 'justify-center lg:justify-center'
                          : 'justify-center lg:justify-start',
                      )}
                    >
                      <Icon className="size-4 shrink-0" />
                      <span
                        className={cn(
                          'hidden lg:block',
                          collapsed && 'lg:hidden',
                        )}
                      >
                        {label}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div className="border-t border-border/80 p-3">
            <Link
              href="/scans/new"
              aria-label="Create a new scan"
              className={cn(
                buttonVariants({ variant: 'default', size: 'lg' }),
                'w-full justify-center bg-primary text-primary-foreground hover:bg-primary/90',
                collapsed ? 'lg:px-0' : 'lg:justify-start',
              )}
            >
              <Plus className="size-4" />
              <span className={cn('hidden lg:block', collapsed && 'lg:hidden')}>
                + New
              </span>
            </Link>
          </div>
        </aside>

        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          <header className="flex h-16 items-center justify-between border-b border-border/80 bg-background/90 px-4 backdrop-blur lg:px-8">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                Code intelligence
              </p>
              <h1 className="text-sm font-semibold">Static shell preview</h1>
            </div>
            <ThemeToggleMenu />
          </header>
          <main className="flex-1 px-4 py-6 lg:p-8">{children}</main>
        </div>
      </div>
    </div>
  );
}
