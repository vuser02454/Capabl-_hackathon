export function Logo({ size = 34 }: { size?: number }) {
  return (
    <span
      className="relative grid shrink-0 place-items-center rounded-xl border border-brand/25 bg-linear-to-br from-brand/25 via-brand/10 to-transparent text-brand"
      style={{ width: size, height: size, boxShadow: '0 0 24px -6px var(--color-brand-glow)' }}
      aria-hidden
    >
      <svg viewBox="0 0 24 24" fill="none" style={{ width: size * 0.58, height: size * 0.58 }}>
        <path d="M12 3.2c4.3 2.5 6.6 5.7 6.6 9.1a6.6 6.6 0 0 1-13.2 0c0-3.4 2.3-6.6 6.6-9.1Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
        <path d="M12 19.6v-7m0 0 2.9-2.9M12 12.6 9.6 10.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
      <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-brand" style={{ boxShadow: '0 0 8px var(--color-brand)' }} />
    </span>
  );
}
