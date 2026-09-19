import { animate } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';

interface AnimatedNumberProps {
  value: number;
  decimals?: number;
  duration?: number;
  className?: string;
}

/** Counts smoothly from the previous value to the new one. */
export function AnimatedNumber({ value, decimals = 0, duration = 0.9, className }: AnimatedNumberProps) {
  const previous = useRef(0);
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const controls = animate(previous.current, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (latest) => setDisplay(latest),
    });
    previous.current = value;
    return () => controls.stop();
  }, [value, duration]);

  return <span className={className}>{display.toFixed(decimals)}</span>;
}
