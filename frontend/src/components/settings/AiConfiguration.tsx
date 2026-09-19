/**
 * AI configuration, presented as three distinct roles.
 *
 * Deliberately NOT a single "choose your AI: Gemini / Groq / OpenRouter" list. That framing
 * implies the three do the same job, and they do not: Gemini performs functional work whose
 * output becomes evidence the decision engine weighs, while OpenRouter and Groq receive an
 * already-final decision and put it into words. A user who swaps one for the other because the
 * UI suggested they were alternatives would silently change what the system is allowed to decide.
 *
 * Configuration lives in `backend/.env` and is read-only here. Keys never reach the browser —
 * this panel only asks the backend which roles are configured and whether they can answer.
 */
import { BadgeCheck, Brain, CircleAlert, MessageSquareText, ScanEye, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import type { AiRoleStatus, AiStatusResponse } from '../../types/environment';
import { DashboardCard } from '../ui/DashboardCard';

function RoleCard({
  title,
  purpose,
  role,
  options,
  envVar,
  icon: Icon,
}: {
  title: string;
  purpose: string;
  role: AiRoleStatus | null;
  options: string[];
  envVar: string;
  icon: typeof Brain;
}) {
  const configured = role?.configured ?? false;
  const available = role?.available ?? false;
  const provider = role?.provider ?? 'none';

  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
      <div className="flex items-start gap-2.5">
        <Icon className="mt-0.5 size-4 shrink-0 text-brand" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-fg">{title}</p>
          <p className="mt-0.5 text-[11px] text-fg-subtle">{purpose}</p>
        </div>
        {available ? (
          <span className="flex shrink-0 items-center gap-1 text-[10.5px] text-risk-low">
            <BadgeCheck className="size-3" /> Active
          </span>
        ) : (
          <span className="flex shrink-0 items-center gap-1 text-[10.5px] text-fg-subtle">
            <CircleAlert className="size-3" /> Inactive
          </span>
        )}
      </div>

      <div className="mt-3 space-y-1.5">
        {options.map((option) => {
          const selected = provider === option;
          return (
            <div
              key={option}
              className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${
                selected ? 'border-brand/30 bg-brand/[0.06] text-fg' : 'border-white/[0.05] text-fg-subtle'
              }`}
            >
              <span
                className={`size-2.5 shrink-0 rounded-full border ${
                  selected ? 'border-brand bg-brand' : 'border-white/20'
                }`}
              />
              <span className="flex-1 capitalize">{option === 'none' ? 'None (deterministic only)' : option}</span>
              {selected && role?.model && <span className="font-mono text-[10px] text-fg-subtle">{role.model}</span>}
            </div>
          );
        })}
      </div>

      {role?.detail && <p className="mt-2 text-[10.5px] text-fg-subtle">{role.detail}</p>}
      <p className="mt-2 font-mono text-[10px] text-fg-subtle">
        {envVar} in backend/.env
        {configured && !available && ' · configured but unavailable'}
      </p>
    </div>
  );
}

export function AiConfiguration() {
  const { api } = useSettings();
  const [status, setStatus] = useState<AiStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .aiStatus()
      .then((response) => !cancelled && setStatus(response))
      .catch(() => !cancelled && setError('Could not read AI configuration from the backend.'));
    return () => {
      cancelled = true;
    };
  }, [api]);

  return (
    <DashboardCard
      title="AI configuration"
      subtitle="Three roles, deliberately not interchangeable"
      icon={Brain}
      iconColor="#2dd4bf"
    >
      <div className="space-y-3">
        <div className="grid gap-3 lg:grid-cols-3">
          <RoleCard
            title="Functional AI"
            purpose="Performs AI work inside the pipeline. Its output is validated and enters as evidence, which the deterministic engine then weighs."
            role={status?.functionalAi ?? null}
            options={['none', 'gemini']}
            envVar="FUNCTIONAL_AI_PROVIDER"
            icon={Brain}
          />
          <RoleCard
            title="Visual detection"
            purpose="Locates objects in an image and returns real bounding boxes. Neither AI provider may substitute for it, and no detection is ever inferred by a language model."
            role={status?.vision ?? null}
            options={['off', 'local', 'roboflow']}
            envVar="ECOSENTINEL_WATER_VISION_PROVIDER"
            icon={ScanEye}
          />
          <RoleCard
            title="Explainable AI"
            purpose="Receives an already-final decision and puts it into words. It cannot change the risk score, confidence, priorities, evidence or the primary problem."
            role={status?.explainableAi ?? null}
            options={['none', 'openrouter', 'groq']}
            envVar="EXPLAINABILITY_AI_PROVIDER"
            icon={MessageSquareText}
          />
        </div>

        <p className="flex items-start gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px] text-fg-subtle">
          <ShieldCheck className="mt-px size-3.5 shrink-0 text-brand" />
          <span>
            Risk scores, problem priorities and evidence sufficiency are always computed
            deterministically. With both AI roles set to <span className="font-mono">none</span> the full
            pipeline still runs and every explanation falls back to deterministic text. Visual
            detection is a separate role again: YOLO locates objects, and no language model may
            infer a bounding box. API keys stay in{' '}
            <span className="font-mono">backend/.env</span> and are never sent to the browser.
          </span>
        </p>

        {error && <p className="text-[11px] text-risk-moderate">{error}</p>}
      </div>
    </DashboardCard>
  );
}
