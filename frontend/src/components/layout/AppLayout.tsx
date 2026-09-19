import { AnimatePresence, motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useNavigation } from '../../context/NavigationContext';
import { ChatPanel } from '../chat/ChatPanel';
import { ErrorBoundary } from '../ui/ErrorBoundary';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function AppLayout({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  // The assistant is available on every page: a question about the analysis should not require
  // navigating away from what prompted it.
  const [chatOpen, setChatOpen] = useState(false);
  const { route } = useNavigation();

  useEffect(() => {
    setMenuOpen(false);
  }, [route]);

  return (
    <div className="relative min-h-screen">
      <div className="app-backdrop" aria-hidden />
      <Sidebar open={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="relative z-10 lg:pl-64">
        <TopBar onMenu={() => setMenuOpen(true)} />
        <main className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <AnimatePresence mode="wait">
            <motion.div
              key={route}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
            >
              <ErrorBoundary resetKey={route}>{children}</ErrorBoundary>
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      {/* Assistant launcher. Hidden while the panel is open so the two never overlap. */}
      {!chatOpen && (
        <button
          type="button"
          onClick={() => setChatOpen(true)}
          aria-label="Open EcoSentinel assistant"
          className="fixed right-5 bottom-5 z-40 flex items-center gap-2 rounded-full border border-white/[0.1] bg-brand px-4 py-3 text-ink-950 shadow-lg shadow-black/30 transition hover:brightness-110"
        >
          <Sparkles className="size-4" />
          <span className="text-[12.5px] font-semibold">Ask EcoSentinel</span>
        </button>
      )}

      <AnimatePresence>
        {chatOpen && <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />}
      </AnimatePresence>
    </div>
  );
}
