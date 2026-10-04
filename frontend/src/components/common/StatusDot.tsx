import React from 'react';

interface StatusDotProps {
  status: 'online' | 'busy' | 'offline' | 'warning';
  pulse?: boolean;
  className?: string;
}

const colorMap = {
  online: 'bg-emerald-400',
  busy: 'bg-cyan-400',
  offline: 'bg-slate-500',
  warning: 'bg-amber-400',
};

export const StatusDot: React.FC<StatusDotProps> = ({
  status,
  pulse = false,
  className = '',
}) => {
  return (
    <span className={`relative flex h-2 w-2 ${className}`}>
      {pulse && (
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${colorMap[status]}`}
        />
      )}
      <span className={`relative inline-flex rounded-full h-2 w-2 ${colorMap[status]}`} />
    </span>
  );
};
