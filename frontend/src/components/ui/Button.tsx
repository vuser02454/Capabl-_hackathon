import { LoaderCircle, type LucideIcon } from 'lucide-react';
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/format';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: LucideIcon;
  iconRight?: LucideIcon;
  loading?: boolean;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-linear-to-b from-brand to-brand-strong text-ink-950 font-semibold shadow-[0_0_0_1px_rgb(45_212_191/0.45),0_10px_28px_-10px_rgb(45_212_191/0.6)] hover:brightness-110',
  secondary: 'border border-black/10 bg-black/[0.04] text-fg hover:border-black/15 hover:bg-black/[0.08]',
  ghost: 'text-fg-muted hover:bg-black/[0.05] hover:text-fg',
  danger: 'border border-risk-high/30 bg-risk-high/10 text-risk-high hover:bg-risk-high/15',
};

const SIZES: Record<Size, string> = {
  sm: 'h-8 gap-1.5 rounded-lg px-3 text-xs',
  md: 'h-9 gap-2 rounded-xl px-3.5 text-sm',
  lg: 'h-11 gap-2 rounded-xl px-5 text-sm',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon: Icon, iconRight: IconRight, loading = false, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  const iconSize = size === 'sm' ? 'size-3.5' : 'size-4';
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cn(
        'inline-flex shrink-0 items-center justify-center whitespace-nowrap font-medium transition-all duration-200 select-none',
        'focus-visible:ring-2 focus-visible:ring-brand/60 focus-visible:outline-none active:scale-[0.98]',
        'disabled:pointer-events-none disabled:opacity-50',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <LoaderCircle className={cn(iconSize, 'animate-spin')} /> : Icon ? <Icon className={iconSize} /> : null}
      {children}
      {IconRight && !loading && <IconRight className={iconSize} />}
    </button>
  );
});
