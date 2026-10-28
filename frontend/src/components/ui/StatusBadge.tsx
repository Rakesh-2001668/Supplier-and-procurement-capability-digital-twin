import React from 'react';

interface StatusBadgeProps {
  status: 'Verified' | 'Pending' | 'High Risk' | 'Medium Risk' | 'Low Risk' | 'Active' | 'Inactive' | string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  let bg = "bg-gray-100";
  let text = "text-gray-700";
  let icon = "";

  const s = status.toLowerCase();
  if (s.includes('verified') || s.includes('active') || s.includes('low')) {
    bg = "bg-green-50";
    text = "text-green-700";
    icon = "✓";
  } else if (s.includes('pending') || s.includes('medium')) {
    bg = "bg-yellow-50";
    text = "text-yellow-700";
    icon = "◷";
  } else if (s.includes('risk') || s.includes('inactive')) {
    bg = "bg-red-50";
    text = "text-red-700";
    icon = "!";
  }

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${bg} ${text} border border-[rgba(0,0,0,0.05)]`}>
      {icon && <span className="mr-1.5 font-bold">{icon}</span>}
      {status}
    </span>
  );
}
