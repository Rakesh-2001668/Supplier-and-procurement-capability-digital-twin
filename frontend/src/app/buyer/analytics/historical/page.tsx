'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, ScatterChart, Scatter, ZAxis, Legend } from 'recharts';
import { History, BarChart3, AlertOctagon, TrendingUp, Grid3X3 } from 'lucide-react';

export default function HistoricalAnalytics() {
  const { data: analytics, isLoading } = useQuery({
    queryKey: ['historical-analytics'],
    queryFn: async () => {
      const res = await fetch('http://localhost:8080/api/v1/analytics/historical');
      return res.json();
    }
  });

  if (isLoading) return <div className="p-8 text-gray-500">Compiling Historical Datasets...</div>;

  // Helper to color heatmap cells based on risk score (0-100)
  const getHeatmapColor = (value: number) => {
    if (value < 30) return 'bg-green-100 text-green-800'; // Low Risk
    if (value < 60) return 'bg-yellow-100 text-yellow-800'; // Medium Risk
    if (value < 80) return 'bg-orange-200 text-orange-900'; // High Risk
    return 'bg-red-500 text-white font-bold shadow-inner'; // Critical Risk
  };

  const highPerformers = analytics?.scatter.filter((d: any) => d.category === 'High Performer') || [];
  const riskAreas = analytics?.scatter.filter((d: any) => d.category === 'Risk Area') || [];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
            <History size={32} className="text-blue-600" />
            Deep Historical Analytics
          </h1>
          <p className="text-gray-500 mt-1">Advanced multi-dimensional visualizations for long-term supply chain performance.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Heatmap Visualization */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col">
          <div className="flex justify-between items-center mb-6">
            <h3 className="font-bold text-gray-800 flex items-center gap-2"><Grid3X3 className="text-purple-500"/> Supplier Risk Heatmap (6 Months)</h3>
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-1 rounded">Intensity = Operational Risk</span>
          </div>
          
          <div className="flex-1 overflow-x-auto">
            <table className="w-full text-sm text-left border-collapse">
              <thead>
                <tr>
                  <th className="p-3 font-bold text-gray-600 border-b-2 border-gray-100">Supplier</th>
                  {analytics?.months_columns.map((m: string) => (
                    <th key={m} className="p-3 font-bold text-gray-600 border-b-2 border-gray-100 text-center">{m}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {analytics?.heatmap.map((row: any, idx: number) => (
                  <tr key={idx} className="border-b border-gray-50">
                    <td className="p-3 font-bold text-[#0B2550] whitespace-nowrap">{row.supplier}</td>
                    {analytics?.months_columns.map((m: string) => (
                      <td key={m} className="p-2">
                        <div className={`w-full h-10 flex items-center justify-center rounded-md transition-colors duration-300 ${getHeatmapColor(row[m])}`}>
                          {row[m]}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Scatter Plot - Correlation Analysis */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[400px]">
          <div className="flex justify-between items-center mb-6">
            <h3 className="font-bold text-gray-800 flex items-center gap-2"><AlertOctagon className="text-red-500"/> Defect Rate vs. Lead Time</h3>
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-1 rounded">PO Level Granularity</span>
          </div>
          <div className="flex-1">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis type="number" dataKey="lead_time_days" name="Lead Time (Days)" unit="d" tick={{fill: '#6b7280'}} />
                <YAxis type="number" dataKey="defect_rate_pct" name="Defect Rate" unit="%" tick={{fill: '#6b7280'}} />
                <ZAxis type="number" range={[60, 60]} />
                <RechartsTooltip cursor={{ strokeDasharray: '3 3' }} />
                <Legend />
                <Scatter name="High Performers" data={highPerformers} fill="#10b981" opacity={0.6} />
                <Scatter name="Risk Areas" data={riskAreas} fill="#ef4444" opacity={0.8} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Long-term 12 month Trend Line */}
        <div className="lg:col-span-2 bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[400px]">
          <div className="flex justify-between items-center mb-6">
             <h3 className="font-bold text-gray-800 flex items-center gap-2"><TrendingUp className="text-blue-500"/> 12-Month Quality & Delivery Consistency</h3>
          </div>
          <div className="flex-1">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={analytics?.trends} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="month" tick={{fill: '#6b7280'}} axisLine={false} tickLine={false} />
                <YAxis domain={[80, 100]} tick={{fill: '#6b7280'}} axisLine={false} tickLine={false} />
                <RechartsTooltip />
                <Legend verticalAlign="top" height={36}/>
                <Line type="monotone" dataKey="on_time_delivery" name="On-Time Delivery (%)" stroke="#3b82f6" strokeWidth={3} dot={{r: 4}} activeDot={{r: 8}} />
                <Line type="monotone" dataKey="quality_yield" name="Quality Yield (%)" stroke="#8b5cf6" strokeWidth={3} dot={{r: 4}} activeDot={{r: 8}} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

      </div>
    </div>
  );
}
