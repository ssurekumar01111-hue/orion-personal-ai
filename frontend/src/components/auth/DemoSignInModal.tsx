import React, { useState } from 'react';
import { Shield, KeyRound, AlertCircle, Eye, EyeOff } from 'lucide-react';
import { setDemoKey } from '../../api/client';
import { getProviders } from '../../api/system';
import { Button } from '../common/Button';

interface DemoSignInModalProps {
  isOpen: boolean;
  onSuccess: () => void;
  initialError?: string | null;
}

export const DemoSignInModal: React.FC<DemoSignInModalProps> = ({
  isOpen,
  onSuccess,
  initialError = null,
}) => {
  const [keyInput, setKeyInput] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(initialError);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = keyInput.trim();
    if (!trimmed) {
      setError('Please enter a demo key.');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Store candidate demo key
      setDemoKey(trimmed);

      // Verify credentials with backend
      await getProviders();

      // Authentication succeeded
      onSuccess();
    } catch {
      // Clear rejected demo key
      setDemoKey(null);
      setError('Invalid demo key. Please verify credentials and try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4"
      data-testid="demo-sign-in-modal"
    >
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-orion-950 p-6 shadow-2xl shadow-cyan-950/20 space-y-5">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            <Shield className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-100 tracking-tight">
              Orion Demo Access
            </h2>
            <p className="text-xs text-slate-400">
              Enter the demo key to access your Orion AI operating layer.
            </p>
          </div>
        </div>

        {/* Security Scope Notice */}
        <div className="rounded-xl border border-slate-800 bg-orion-900/60 p-3.5 text-xs text-slate-400 leading-relaxed space-y-1.5">
          <div className="flex items-center gap-1.5 text-cyan-400 font-semibold font-mono text-[11px] uppercase">
            <KeyRound className="w-3.5 h-3.5" />
            <span>Shared Demo Secret</span>
          </div>
          <p>
            Local demonstration authentication. This demo key provides access to Orion API capabilities. It does not provide individual user identities or fine-grained multi-user authorization.
          </p>
        </div>

        {/* Error Notification */}
        {error && (
          <div
            className="flex items-start gap-2.5 p-3 rounded-xl bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300"
            data-testid="demo-sign-in-error"
          >
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="demo-key"
              className="block text-xs font-mono font-medium text-slate-300 uppercase tracking-wider"
            >
              Demo Key
            </label>
            <div className="relative">
              <input
                id="demo-key"
                type={showKey ? 'text' : 'password'}
                value={keyInput}
                onChange={(e) => {
                  setKeyInput(e.target.value);
                  if (error) setError(null);
                }}
                placeholder="Enter demo key..."
                autoFocus
                disabled={isLoading}
                data-testid="demo-key-input"
                className="w-full rounded-xl bg-orion-900 border border-slate-750 px-3.5 py-2.5 pr-10 text-sm text-slate-100 placeholder-slate-500 font-mono focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500 disabled:opacity-50"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-200 transition-colors"
                title={showKey ? 'Hide key' : 'Show key'}
              >
                {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <Button
            type="submit"
            variant="primary"
            className="w-full justify-center font-mono py-2.5"
            isLoading={isLoading}
            disabled={isLoading || !keyInput.trim()}
            data-testid="demo-sign-in-button"
          >
            Sign In to Demo
          </Button>
        </form>
      </div>
    </div>
  );
};
