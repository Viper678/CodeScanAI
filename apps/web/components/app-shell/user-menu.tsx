'use client';

import { LogOut, Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { useLogout, useSession } from '@/lib/api/auth/use-session';
import { LOGIN_PATH } from '@/lib/auth/redirect';
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
  { icon: Monitor, label: 'System', value: 'system' },
  { icon: Sun, label: 'Light', value: 'light' },
  { icon: Moon, label: 'Dark', value: 'dark' },
];

function initialsFromEmail(email: string | undefined): string {
  if (!email) return 'CS';
  const local = email.split('@')[0] ?? '';
  if (local.length === 0) return 'CS';
  return local.slice(0, 2).toUpperCase();
}

function AvatarButton({
  email,
  interactive,
}: Readonly<{ email: string | undefined; interactive: boolean }>) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 rounded-full border border-border/80 bg-card px-1.5 py-1 text-left transition-colors',
        interactive && 'hover:bg-muted/70',
      )}
    >
      <Avatar size="sm">
        <AvatarFallback className="bg-primary/15 font-medium text-primary">
          {initialsFromEmail(email)}
        </AvatarFallback>
      </Avatar>
      <div className="hidden min-w-0 lg:block">
        <p className="truncate text-sm font-medium">{email ?? 'Signed in'}</p>
        <p className="truncate text-xs text-muted-foreground">
          Account & theme
        </p>
      </div>
    </div>
  );
}

export function UserMenu() {
  const { setTheme, theme } = useTheme();
  const { user } = useSession();
  const logout = useLogout();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const onSignOut = async () => {
    try {
      await logout.mutateAsync();
    } finally {
      // useLogout already clears the session cache; navigate regardless of
      // whether the network call succeeded so the user actually leaves.
      router.replace(LOGIN_PATH);
    }
  };

  if (!mounted) {
    return <AvatarButton email={user?.email} interactive={false} />;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger aria-label="Open user menu">
        <AvatarButton email={user?.email} interactive />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        {user ? (
          <>
            <div className="px-2 py-1.5 text-xs text-muted-foreground">
              Signed in as
              <p className="truncate text-sm font-medium text-foreground">
                {user.email}
              </p>
            </div>
            <DropdownMenuSeparator />
          </>
        ) : null}
        <div className="px-2 py-1 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Appearance
        </div>
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
        <DropdownMenuItem
          variant="destructive"
          disabled={logout.isPending}
          onClick={onSignOut}
        >
          <LogOut className="size-4" />
          {logout.isPending ? 'Signing out…' : 'Sign out'}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
