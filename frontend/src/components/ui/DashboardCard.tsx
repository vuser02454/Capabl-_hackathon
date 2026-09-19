import { motion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../../lib/format';

interface DashboardCardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  icon?: LucideIcon;
  iconColor?: string;
  actions?: ReactNode;
  accent?: string;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  interactive?: boolean;
  delay?: number;
}

export function DashboardCard({
  title,
  subtitle,
  icon: Icon,
  iconColor,
  actions,
  accent,
  children,
  className,
  bodyClassName,
  interactive = false,
  delay = 0,
}: DashboardCardProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: [0.16, 1, 0.3, 1] }}
      className={cn('glass flex min-w-0 flex-col overflow-hidden', interactive && 'glass-interactive', className)}
    >
      {accent && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-6 top-0 h-px"
          style={{ background: `linear-gradient(90deg, transparent, ${accent}88, transparent)` }}
        />
      )}
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 px-5 pt-4">
          <div className="flex min-w-0 items-center gap-3">
            {Icon && (
              <span
                className="grid size-9 shrink-0 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.03]"
                style={iconColor ? { color: iconColor, background: `${iconColor}12`, borderColor: `${iconColor}26` } : undefined}
              >
                <Icon className="size-[18px]" />
              </span>
            )}
            <div className="min-w-0">
              {title && <h3 className="truncate text-sm font-semibold tracking-tight text-fg">{title}</h3>}
              {subtitle && <p className="mt-0.5 truncate text-xs text-fg-subtle">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn('flex-1 p-5', title ? 'pt-4' : undefined, bodyClassName)}>{children}</div>
    </motion.section>
  );
}
