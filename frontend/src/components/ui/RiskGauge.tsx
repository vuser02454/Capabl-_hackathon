import { motion } from 'framer-motion';
import { useId } from 'react';
import { clamp, RISK_STYLES } from '../../lib/risk';
import type { RiskLevel } from '../../types/agents';
import { AnimatedNumber } from './AnimatedNumber';

interface RiskGaugeProps {
  score: number;
  level: RiskLevel;
  size?: number;
  stroke?: number;
  label?: string;
}

/** Circular risk indicator with threshold ticks at 40% (moderate) and 70% (high). */
export function RiskGauge({ score, level, size = 120, stroke = 9, label = 'Risk score' }: RiskGaugeProps) {
  const gradientId = `gauge-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const color = RISK_STYLES[level].color;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const center = size / 2;

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`${label}: ${Math.round(score * 100)}%, ${level}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.5} />
            <stop offset="100%" stopColor={color} />
          </linearGradient>
        </defs>
        <circle cx={center} cy={center} r={radius} fill="none" stroke="rgb(255 255 255 / 0.06)" strokeWidth={stroke} />
        <motion.circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - clamp(score)) }}
          transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1] }}
          style={{ filter: `drop-shadow(0 0 6px ${color}55)` }}
        />
        {[0.4, 0.7].map((threshold) => {
          const angle = threshold * 2 * Math.PI;
          const inner = radius - stroke / 2 - 2;
          const outer = radius + stroke / 2 + 2;
          return (
            <line
              key={threshold}
              x1={center + inner * Math.cos(angle)}
              y1={center + inner * Math.sin(angle)}
              x2={center + outer * Math.cos(angle)}
              y2={center + outer * Math.sin(angle)}
              stroke="#06080a"
              strokeWidth={2}
            />
          );
        })}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="leading-none font-semibold tracking-tight text-fg" style={{ fontSize: size * 0.25 }}>
          <AnimatedNumber value={Math.round(score * 100)} />
          <span className="text-fg-muted" style={{ fontSize: size * 0.12 }}>%</span>
        </span>
        {label && <span className="mt-1 text-[9.5px] font-medium tracking-[0.12em] text-fg-subtle uppercase">{label}</span>}
      </div>
    </div>
  );
}
