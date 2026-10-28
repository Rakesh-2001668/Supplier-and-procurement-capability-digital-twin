import React from 'react';

interface RadarProps {
  dimensions: string[];
  data: number[];
  benchmark: number[];
}

export function RadarChart({ dimensions, data, benchmark }: RadarProps) {
  const N = dimensions.length;
  const R = 120;
  const cx = 210;
  const cy = 168;

  const getPoints = (vals: number[]) => {
    let pts = '';
    for (let i = 0; i < N; i++) {
      const a = -Math.PI / 2 + i * 2 * Math.PI / N;
      const r = R * (vals[i] / 100);
      pts += `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)} `;
    }
    return pts;
  };

  return (
    <svg width="420" height="330" viewBox="0 0 420 330" className="mx-auto block">
      {/* Grid Rings */}
      {[1, 2, 3, 4].map(ring => {
        let pts = '';
        for (let i = 0; i < N; i++) {
          const a = -Math.PI / 2 + i * 2 * Math.PI / N;
          const r = R * (ring / 4);
          pts += `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)} `;
        }
        return <polygon key={ring} points={pts} fill="none" stroke="#E2E8F0" strokeWidth="1" />
      })}
      
      {/* Spoke Lines & Labels */}
      {dimensions.map((dim, i) => {
        const a = -Math.PI / 2 + i * 2 * Math.PI / N;
        const x2 = cx + R * Math.cos(a);
        const y2 = cy + R * Math.sin(a);
        const labelX = cx + (R + 30) * Math.cos(a);
        const labelY = cy + (R + 30) * Math.sin(a) + 4;
        return (
          <g key={dim}>
            <line x1={cx} y1={cy} x2={x2} y2={y2} stroke="#E2E8F0" />
            <text x={labelX} y={labelY} fill="#64748B" fontSize="11px" textAnchor="middle" fontWeight="500">{dim}</text>
          </g>
        );
      })}

      {/* Benchmark Polygon */}
      <polygon points={getPoints(benchmark)} fill="rgba(100, 116, 139, 0.1)" stroke="#94A3B8" strokeWidth="2" strokeDasharray="4 4" />
      
      {/* Supplier Polygon */}
      <polygon points={getPoints(data)} fill="rgba(37, 99, 235, 0.15)" stroke="#2563EB" strokeWidth="2" />
    </svg>
  );
}
