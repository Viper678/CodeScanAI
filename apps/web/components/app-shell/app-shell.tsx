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
            'flex min-h-screen w-16 shrink-0 flex-col border-r border-border/80 bg-card/70 backdrop-blur lg:transition-[width]',
            collapsed ? 'lg:w-16' : 'lg:w-72',
          )}
        >
          <div
            className={cn(
              'flex items-center border-b border-border/80 px-2',
              collapsed
                ? 'h-24 flex-col justify-center gap-3 lg:h-24'
                : 'h-16 justify-center lg:justify-between lg:px-3',
            )}
          >
            <Link
              href="/scans"
              className={cn(
                'flex items-center gap-3 rounded-md py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                collapsed ? 'justify-center px-0' : 'px-2',
              )}
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
                'rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                collapsed ? 'inline-flex' : 'hidden lg:inline-flex',
              )}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <PanelLeft className="size-4" />
            </button>
          </div>

          <nav aria-label="Primary navigation" className="flex-1 px-2 py-6">
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
                      title={collapsed ? label : undefined}
                      className={cn(
                        'flex min-h-11 items-center gap-3 rounded-r-xl border-l-2 border-transparent text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                        isActive &&
                          'border-indigo-500 bg-zinc-100 text-foreground dark:bg-zinc-800',
                        collapsed
                          ? 'justify-center px-0 lg:justify-center'
                          : 'justify-center px-0 lg:justify-start lg:px-3',
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

          <div className="border-t border-border/80 p-2">
            <Link
              href="/scans/new"
              aria-label="Create a new scan"
              title={collapsed ? 'New scan' : undefined}
              className={cn(
                buttonVariants({ variant: 'default', size: 'lg' }),
                'bg-primary text-primary-foreground hover:bg-primary/90',
                collapsed
                  ? 'h-10 w-10 justify-center px-0'
                  : 'w-full justify-center lg:justify-start',
              )}
            >
              <Plus className="size-4" />
              <span className={cn('hidden lg:block', collapsed && 'lg:hidden')}>
                New
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
