import React from 'react';

interface MetricCardProps {
  title: string;
  value: string | number;
  trend?: number;
  trendLabel?: string;
  icon?: React.ReactNode;
  iconBgColor?: string;
  iconTextColor?: string;
}

export function MetricCard({
  title,
  value,
  trend,
  trendLabel = "vs last month",
  icon,
  iconBgColor = "bg-blue-500/10",
  iconTextColor = "text-brand-ink"
}: MetricCardProps) {
  const isPositive = trend && trend > 0;
  const isNegative = trend && trend < 0;
  
  return (
    <div className="group relative flex flex-col justify-between h-full overflow-hidden rounded-2xl border border-line-strong/80 ring-1 ring-inset ring-black/[0.04] dark:ring-white/[0.06] bg-surface p-5 shadow-card transition-all duration-200 hover:-translate-y-1 hover:border-brand/60 hover:ring-brand/30 hover:shadow-raised">
      <div className="flex justify-between items-start mb-3">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center border border-line/60 shadow-xs transition-transform duration-200 group-hover:scale-105 ${iconBgColor} ${iconTextColor}`}>
          {icon || <span className="font-bold text-base">#</span>}
        </div>
        <div className="rounded-full p-1 text-ink-3 opacity-60 transition group-hover:opacity-100 group-hover:text-brand-ink">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg>
        </div>
      </div>
      <div>
        <h3 className="text-ink-3 text-xs font-semibold uppercase tracking-wider mb-1.5 transition-colors group-hover:text-brand-ink">{title}</h3>
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-3xl font-extrabold tracking-tight tabular-nums text-ink">{value}</span>
          {trend !== undefined && (
            <div className="flex flex-col items-end">
              <span className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 font-mono text-xs font-bold border ${
                isPositive
                  ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20'
                  : isNegative
                  ? 'bg-red-500/10 text-red-700 dark:text-red-400 border-red-500/20'
                  : 'bg-surface-3 text-ink-3 border-line'
              }`}>
                {isPositive ? '↑' : isNegative ? '↓' : ''} {Math.abs(trend)}%
              </span>
              <span className="mt-0.5 text-[10px] text-ink-3">{trendLabel}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
