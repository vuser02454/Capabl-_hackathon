import { motion } from 'framer-motion';
import { ArrowDown } from 'lucide-react';
import { useId } from 'react';
import { cn } from '../../lib/format';

export function VerticalConnector({ active = true, className }: { active?: boolean; className?: string }) {
  return (
    <div aria-hidden className={cn('relative mx-auto h-8 w-px bg-linear-to-b from-black/[0.08] to-black/[0.18]', className)}>
      {active && <span className="flow-dot" />}
    </div>
  );
}

/** Three branches converging into (or fanning out from) a single node. */
export function BranchConnector({ direction = 'in', active = true, running = false, className }: { direction?: 'in' | 'out'; active?: boolean; running?: boolean; className?: string }) {
  const gradientId = `branch-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const paths =
    direction === 'in'
      ? ['M100 0 C100 32, 300 16, 300 48', 'M300 0 L300 48', 'M500 0 C500 32, 300 16, 300 48']
      : ['M300 0 C300 32, 100 16, 100 48', 'M300 0 L300 48', 'M300 0 C300 32, 500 16, 500 48'];

  return (
    <div aria-hidden className={cn('relative mx-auto h-12 w-full max-w-2xl', className)}>
      <svg viewBox="0 0 600 48" preserveAspectRatio="none" className="absolute inset-0 hidden size-full sm:block">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#0d9488" stopOpacity="0.2" />
            <stop offset="1" stopColor="#0d9488" stopOpacity="0.8" />
          </linearGradient>
        </defs>
        {paths.map((d) => (
          <g key={d}>
            <path d={d} fill="none" stroke="rgb(15 23 42 / 0.08)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
            {active && (
              <motion.path
                d={d}
                fill="none"
                stroke={`url(#${gradientId})`}
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
                strokeDasharray="5 7"
                animate={{ strokeDashoffset: running ? [0, -48] : 0 }}
                transition={running ? { repeat: Infinity, duration: 0.9, ease: 'linear' } : { duration: 0 }}
              />
            )}
          </g>
        ))}
      </svg>
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-black/[0.1] sm:hidden" />
      <ArrowDown className={cn('absolute -bottom-1.5 left-1/2 size-4 -translate-x-1/2', active ? 'text-brand/80' : 'text-fg-subtle')} />
    </div>
  );
}
