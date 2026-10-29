import React from 'react';
import { ProviderType } from '../../types/api';
import { StatusDot } from '../common/StatusDot';
import {
  Cpu,
  LogOut,
  PanelLeft,
  PanelRight,
} from 'lucide-react';

interface HeaderProps {
  provider: ProviderType;
  onProviderChange: (provider: ProviderType) => void;
  availableProviders: ProviderType[];
  isOnline: boolean;
  activeSessionTitle?: string;
  onToggleLeftSidebar: () => void;
  onToggleRightSidebar: () => void;
  onSignOut?: () => void;
  isAuthenticated?: boolean;
  className?: string;
}

export const Header: React.FC<HeaderProps> = ({
  provider,
  onProviderChange,
  availableProviders = ['nebius', 'hermes'],
  isOnline = true,
  activeSessionTitle = 'Current Session',
  onToggleLeftSidebar,
  onToggleRightSidebar,
  onSignOut,
  isAuthenticated = false,
  className = '',
}) => {
  return (
    <header
      className={`h-14 border-b border-slate-800 bg-orion-950/80 backdrop-blur-md px-4 flex items-center justify-between gap-4 z-20 ${className}`}
      data-testid="header"
    >
      {/* Left: Mobile Nav Toggle & Session Title */}
      <div className="flex items-center gap-3 min-w-0">
        <button
          type="button"
          onClick={onToggleLeftSidebar}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800/80 transition-colors lg:hidden"
          title="Toggle Navigation"
        >
          <PanelLeft className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-2 truncate">
          <span className="text-xs font-semibold text-slate-200 truncate max-w-xs sm:max-w-sm">
            {activeSessionTitle}
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-750">
            v1.0
          </span>
        </div>
      </div>

      {/* Right: Provider Selector & System Status & Context Toggle */}
      <div className="flex items-center gap-3">
        {/* Provider Selector */}
        <div className="flex items-center gap-1.5 bg-orion-900 border border-slate-800 rounded-lg p-1">
          <Cpu className="w-3.5 h-3.5 text-cyan-400 ml-1.5 hidden sm:block" />
          <span className="text-[10px] font-mono uppercase text-slate-400 hidden sm:inline">
            Provider:
          </span>
          <select
            value={provider}
            onChange={(e) => onProviderChange(e.target.value as ProviderType)}
            className="bg-transparent text-xs font-mono text-cyan-300 font-medium focus:outline-none cursor-pointer pr-1"
            data-testid="provider-select"
          >
            {availableProviders.map((p) => (
              <option key={p} value={p} className="bg-orion-900 text-slate-200 font-mono">
                {p}
              </option>
            ))}
          </select>
        </div>

        {/* System Online Status */}
        <div
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-orion-900 border border-slate-800 text-xs font-mono"
          title={isOnline ? 'Orion Backend Online' : 'Orion Backend Offline'}
        >
          <StatusDot status={isOnline ? 'online' : 'offline'} pulse={isOnline} />
          <span className="text-[11px] text-slate-300 hidden md:inline">
            {isOnline ? 'ONLINE' : 'OFFLINE'}
          </span>
        </div>

        {/* Demo Sign Out Button */}
        {isAuthenticated && onSignOut && (
          <button
            type="button"
            onClick={onSignOut}
            className="p-1.5 rounded-lg text-slate-400 hover:text-rose-300 hover:bg-slate-800/80 transition-colors"
            title="Lock Demo / Sign Out"
            data-testid="sign-out-button"
          >
            <LogOut className="w-4 h-4" />
          </button>
        )}

        {/* Right context sidebar toggle on mobile */}
        <button
          type="button"
          onClick={onToggleRightSidebar}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800/80 transition-colors xl:hidden"
          title="Toggle Context Panel"
        >
          <PanelRight className="w-5 h-5" />
        </button>
      </div>
    </header>
  );
};
