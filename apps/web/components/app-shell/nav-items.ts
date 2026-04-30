import type { LucideIcon } from 'lucide-react';
import { FolderUp, ScanLine, Settings } from 'lucide-react';

export type AppNavItem = {
  href: '/scans' | '/uploads' | '/settings';
  icon: LucideIcon;
  label: 'Scans' | 'Uploads' | 'Settings';
};

export const APP_NAV_ITEMS: AppNavItem[] = [
  {
    href: '/scans',
    icon: ScanLine,
    label: 'Scans',
  },
  {
    href: '/uploads',
    icon: FolderUp,
    label: 'Uploads',
  },
  {
    href: '/settings',
    icon: Settings,
    label: 'Settings',
  },
];
