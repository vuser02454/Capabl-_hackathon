/**
 * Role chooser for the landing page.
 *
 * Deliberately one small glass panel layered over the existing composition — no new background, no
 * new animation, no change to the scroll story already running underneath. The landing page's own
 * motion is untouched; this only adds two buttons and a border.
 */
import { HardHat, ShieldCheck } from 'lucide-react';
import { useNavigation } from '../../context/NavigationContext';
import { useRole } from '../../context/RoleContext';

export function RoleSelect() {
  const { setRole } = useRole();
  const { navigate } = useNavigation();

  const choose = (role: 'worker' | 'admin') => {
    setRole(role);
    navigate(role === 'worker' ? 'worker-report' : 'admin-dashboard');
  };

  return (
    <div className="pointer-events-auto w-[248px] rounded-2xl border border-white/15 bg-white/[0.07] p-4 backdrop-blur-md">
      <p className="text-center text-[11px] font-medium tracking-wider text-white/70 uppercase">
        Continue as
      </p>
      <div className="mt-3 space-y-2">
        <button
          type="button"
          onClick={() => choose('worker')}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/20 bg-white/[0.08] px-3 py-2.5 text-[13px] font-medium text-white transition hover:border-white/35 hover:bg-white/[0.14]"
        >
          <HardHat className="size-4" aria-hidden />
          Worker
        </button>
        <button
          type="button"
          onClick={() => choose('admin')}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/20 bg-white/[0.08] px-3 py-2.5 text-[13px] font-medium text-white transition hover:border-white/35 hover:bg-white/[0.14]"
        >
          <ShieldCheck className="size-4" aria-hidden />
          Safety Admin
        </button>
      </div>
    </div>
  );
}
