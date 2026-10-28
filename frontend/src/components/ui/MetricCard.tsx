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

export function MetricCard({ title, value, trend, trendLabel = "vs last month", icon, iconBgColor = "bg-blue-50", iconTextColor = "text-blue-600" }: MetricCardProps) {
  const isPositive = trend && trend > 0;
  const isNegative = trend && trend < 0;
  
  return (
    <div className="bg-white border border-[var(--border-light)] rounded-xl p-5 shadow-sm flex flex-col justify-between h-full">
      <div className="flex justify-between items-start mb-4">
        <div className={`w-10 h-10 rounded-full flex items-center justify-center ${iconBgColor} ${iconTextColor}`}>
          {icon || <span className="font-bold text-lg">#</span>}
        </div>
        <button className="text-gray-400 hover:text-gray-600">
           <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg>
        </button>
      </div>
      <div>
        <h3 className="text-[var(--text-secondary)] text-sm font-medium mb-1">{title}</h3>
        <div className="flex items-end justify-between">
            <span className="text-3xl font-bold text-[var(--text-primary)]">{value}</span>
            {trend !== undefined && (
                <div className="flex flex-col items-end">
                    <span className={`text-sm font-semibold flex items-center ${isPositive ? 'text-green-600' : isNegative ? 'text-red-600' : 'text-gray-500'}`}>
                        {isPositive ? '↑' : isNegative ? '↓' : ''} {Math.abs(trend)}%
                    </span>
                    <span className="text-[10px] text-[var(--text-secondary)]">{trendLabel}</span>
                </div>
            )}
        </div>
      </div>
    </div>
  );
}
