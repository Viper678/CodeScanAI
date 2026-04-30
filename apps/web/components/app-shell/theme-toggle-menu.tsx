'use client';

import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

type ThemeOption = 'system' | 'light' | 'dark';

const THEME_OPTIONS: Array<{
  icon: typeof Monitor;
  label: string;
  value: ThemeOption;
}> = [
  {
    icon: Monitor,
    label: 'System',
    value: 'system',
  },
  {
    icon: Sun,
    label: 'Light',
    value: 'light',
  },
  {
    icon: Moon,
    label: 'Dark',
    value: 'dark',
  },
];

function AvatarButton({ mounted }: Readonly<{ mounted: boolean }>) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 rounded-full border border-border/80 bg-card px-1.5 py-1 text-left transition-colors',
        mounted && 'hover:bg-muted/70',
      )}
    >
      <Avatar size="sm">
        <AvatarFallback className="bg-primary/15 font-medium text-primary">
          CS
        </AvatarFallback>
      </Avatar>
      <div className="hidden min-w-0 lg:block">
        <p className="truncate text-sm font-medium">Workspace</p>
        <p className="truncate text-xs text-muted-foreground">Theme + shell</p>
      </div>
    </div>
  );
}

export function ThemeToggleMenu() {
  const { setTheme, theme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return <AvatarButton mounted={false} />;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger aria-label="Open user menu">
        <AvatarButton mounted />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <div className="px-2 py-1 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Appearance
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={theme ?? 'system'}
          onValueChange={(value) => setTheme(value)}
        >
          {THEME_OPTIONS.map(({ icon: Icon, label, value }) => (
            <DropdownMenuRadioItem key={value} value={value}>
              <Icon className="size-4" />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          Account actions arrive in T1.3
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
