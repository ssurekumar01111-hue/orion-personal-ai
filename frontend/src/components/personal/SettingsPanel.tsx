import React from 'react';
import { Badge } from '../common/Badge';
import {
  ShieldCheck,
  Lock,
  Terminal,
  KeyRound,
} from 'lucide-react';

interface ToolMeta {
  name: string;
  description: string;
  permission: string;
}

interface SettingsPanelProps {
  tools: ToolMeta[];
  isOnline: boolean;
  className?: string;
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({
  tools,
  isOnline,
  className = '',
}) => {
  return (
    <div className={`p-6 max-w-5xl mx-auto space-y-6 ${className}`} data-testid="settings-panel">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-slate-100 tracking-tight">Security & Guardrails</h2>
          <p className="text-xs text-slate-400">
            System boundaries, confirmation enforcement, and registered tool permissions.
          </p>
        </div>
        <Badge variant={isOnline ? 'emerald' : 'rose'}>
          {isOnline ? 'Active Protection' : 'Offline'}
        </Badge>
      </div>

      {/* Security Policies Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-xl border border-slate-800 bg-orion-900/80 space-y-2">
          <div className="flex items-center gap-2 text-cyan-400">
            <Lock className="w-4 h-4" />
            <h3 className="text-xs font-semibold font-mono uppercase text-slate-200">
              Tool Permissions
            </h3>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            All mutating workspace operations (write_file, delete_file, run_command, personal mutations, skills) require explicit user approval.
          </p>
        </div>

        <div className="p-4 rounded-xl border border-slate-800 bg-orion-900/80 space-y-2">
          <div className="flex items-center gap-2 text-emerald-400">
            <ShieldCheck className="w-4 h-4" />
            <h3 className="text-xs font-semibold font-mono uppercase text-slate-200">
              Bounded Loop Limit
            </h3>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Autonomous multi-step planner loops are strictly bounded at a maximum of 5 iterations per request to prevent runaway loops.
          </p>
        </div>

        <div className="p-4 rounded-xl border border-slate-800 bg-orion-900/80 space-y-2">
          <div className="flex items-center gap-2 text-amber-400">
            <KeyRound className="w-4 h-4" />
            <h3 className="text-xs font-semibold font-mono uppercase text-slate-200">
              Zero Credential Leakage
            </h3>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            API keys, gateway tokens, and .env contents are automatically scrubbed from responses, audit logs, and tool arguments.
          </p>
        </div>
      </div>

      {/* Registered Tools List */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold font-mono uppercase text-slate-300">
            Registered Workspace & Agent Tools ({tools.length})
          </h3>
        </div>

        <div className="divide-y divide-slate-800/80 border border-slate-800 rounded-xl bg-orion-900/60 overflow-hidden">
          {tools.map((t) => (
            <div key={t.name} className="p-3.5 flex items-center justify-between gap-4 text-xs">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Terminal className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                  <span className="font-mono font-medium text-slate-200">{t.name}</span>
                </div>
                <p className="text-slate-400 text-[11px] pl-5">{t.description}</p>
              </div>

              <Badge
                variant={
                  t.permission === 'automatic'
                    ? 'emerald'
                    : t.permission === 'confirmation_required'
                    ? 'amber'
                    : 'rose'
                }
              >
                {t.permission}
              </Badge>
            </div>
          ))}

          {tools.length === 0 && (
            <div className="p-6 text-center text-slate-400 text-xs italic">
              Loading registered tools...
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
