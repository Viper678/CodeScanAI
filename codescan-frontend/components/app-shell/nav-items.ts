import type { LucideIcon } from 'lucide-react';
import { FolderUp, ScanLine } from 'lucide-react';

export type AppNavItem = {
  href: '/scans' | '/uploads';
  icon: LucideIcon;
  label: 'Scans' | 'Uploads';
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
];
