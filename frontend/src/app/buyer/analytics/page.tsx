'use client';

import React, { useState } from 'react';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer,
  LineChart, Line, AreaChart, Area, PieChart, Pie, Cell
} from 'recharts';
import { TrendingUp, TrendingDown, DollarSign, Target, Briefcase, Activity } from 'lucide-react';

// --- MOCK REAL-TIME DATA ---
const monthlySpendData = [
  { month: 'Jan', direct: 450000, indirect: 120000, services: 85000 },
  { month: 'Feb', direct: 480000, indirect: 115000, services: 90000 },
  { month: 'Mar', direct: 520000, indirect: 125000, services: 88000 },
  { month: 'Apr', direct: 490000, indirect: 130000, services: 92000 },
  { month: 'May', direct: 550000, indirect: 140000, services: 105000 },
  { month: 'Jun', direct: 610000, indirect: 135000, services: 110000 },
  { month: 'Jul', direct: 590000, indirect: 145000, services: 115000 },
];

const categorySpend = [
  { name: 'Raw Materials', value: 2450000, color: '#0B2550' },
  { name: 'IT Hardware', value: 850000, color: '#1a4b9c' },
  { name: 'Logistics', value: 620000, color: '#3b82f6' },
  { name: 'Facilities', value: 410000, color: '#93c5fd' },
  { name: 'Marketing', value: 290000, color: '#dbeafe' },
];

const supplierPerformance = [
  { name: 'Apex Tooling', spend: 850000, onTime: 98, defect: 0.2 },
  { name: 'Global Metals', spend: 620000, onTime: 92, defect: 1.5 },
  { name: 'TechCorp Logistics', spend: 410000, onTime: 99, defect: 0.1 },
  { name: 'OfficeSolutions', spend: 250000, onTime: 85, defect: 3.2 },
];

export default function SpendAnalyticsDashboard() {
  const [timeframe, setTimeframe] = useState('YTD');

  // Helper for formatting currency
  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0
    }).format(value);
  };

  return (
    <div className="space-y-6">
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
            <Activity size={32} />
            Spend Analytics
          </h1>
          <p className="text-gray-500 mt-1">Real-time intelligence on enterprise procurement spend.</p>
        </div>
        <div className="flex bg-white rounded-lg p-1 border border-gray-200 shadow-sm">
          {['Q1', 'Q2', 'Q3', 'YTD', '1Y'].map(tf => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-4 py-1.5 text-sm font-bold rounded-md transition-colors ${timeframe === tf ? 'bg-[#0B2550] text-white' : 'text-gray-600 hover:bg-gray-100'}`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex items-center gap-4">
          <div className="bg-blue-100 p-4 rounded-lg text-blue-800"><DollarSign size={24} /></div>
          <div>
            <p className="text-sm font-bold text-gray-500 uppercase">Total Spend (YTD)</p>
            <h3 className="text-2xl font-black text-gray-800">$4.62M</h3>
            <p className="text-xs font-bold text-green-600 flex items-center gap-1 mt-1"><TrendingDown size={14}/> 2.4% vs Last Year</p>
          </div>
        </div>

        <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex items-center gap-4">
          <div className="bg-purple-100 p-4 rounded-lg text-purple-800"><Target size={24} /></div>
          <div>
            <p className="text-sm font-bold text-gray-500 uppercase">Cost Savings</p>
            <h3 className="text-2xl font-black text-gray-800">$340K</h3>
            <p className="text-xs font-bold text-green-600 flex items-center gap-1 mt-1"><TrendingUp size={14}/> 12% above target</p>
          </div>
        </div>

        <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex items-center gap-4">
          <div className="bg-amber-100 p-4 rounded-lg text-amber-800"><Briefcase size={24} /></div>
          <div>
            <p className="text-sm font-bold text-gray-500 uppercase">Active Suppliers</p>
            <h3 className="text-2xl font-black text-gray-800">124</h3>
            <p className="text-xs font-bold text-gray-500 mt-1">Across 12 categories</p>
          </div>
        </div>

        <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 flex flex-col justify-center">
            <p className="text-sm font-bold text-gray-500 uppercase mb-2">PO Automation Rate</p>
            <div className="flex items-center gap-3">
              <div className="flex-1 bg-gray-200 rounded-full h-3">
                <div className="bg-green-500 h-3 rounded-full" style={{ width: '82%' }}></div>
              </div>
              <span className="font-black text-lg text-gray-800">82%</span>
            </div>
        </div>
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Spend Trend over Time */}
        <div className="lg:col-span-2 bg-white p-6 rounded-xl shadow-sm border border-gray-100 h-96">
          <h3 className="font-bold text-gray-800 mb-6">Spend Trend by Category Type</h3>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={monthlySpendData} margin={{ top: 10, right: 30, left: 0, bottom: 20 }}>
              <defs>
                <linearGradient id="colorDirect" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#0B2550" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#0B2550" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorIndirect" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
              <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{fill: '#6b7280', fontSize: 12}} dy={10} />
              <YAxis tickFormatter={(val) => `$${val/1000}k`} axisLine={false} tickLine={false} tick={{fill: '#6b7280', fontSize: 12}} />
              <RechartsTooltip formatter={(val: any) => formatCurrency(Number(val) || 0)} />
              <Legend verticalAlign="top" height={36}/>
              <Area type="monotone" dataKey="direct" name="Direct Spend" stroke="#0B2550" fillOpacity={1} fill="url(#colorDirect)" />
              <Area type="monotone" dataKey="indirect" name="Indirect Spend" stroke="#3b82f6" fillOpacity={1} fill="url(#colorIndirect)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Spend by Category Pie */}
        <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100 h-96 flex flex-col">
          <h3 className="font-bold text-gray-800 mb-2">Spend Distribution</h3>
          <div className="flex-1 relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={categorySpend}
                  cx="50%"
                  cy="50%"
                  innerRadius={80}
                  outerRadius={110}
                  paddingAngle={2}
                  dataKey="value"
                >
                  {categorySpend.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <RechartsTooltip formatter={(val: any) => formatCurrency(Number(val) || 0)} />
              </PieChart>
            </ResponsiveContainer>
            {/* Center text for Donut */}
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-gray-500 font-bold text-xs">Top Category</span>
              <span className="text-[#0B2550] font-black">Raw Mats</span>
            </div>
          </div>
        </div>

      </div>

      {/* Top Suppliers Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="p-6 border-b border-gray-100 flex justify-between items-center">
          <h3 className="font-bold text-gray-800">Top Suppliers by Spend</h3>
          <button className="text-sm font-bold text-blue-600 hover:text-blue-800">View All</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wider">
                <th className="p-4 font-bold">Supplier Name</th>
                <th className="p-4 font-bold text-right">YTD Spend</th>
                <th className="p-4 font-bold text-center">On-Time Delivery</th>
                <th className="p-4 font-bold text-center">Defect Rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {supplierPerformance.map((sup, idx) => (
                <tr key={idx} className="hover:bg-gray-50 transition-colors">
                  <td className="p-4">
                    <div className="font-bold text-[#0B2550]">{sup.name}</div>
                  </td>
                  <td className="p-4 text-right font-mono font-bold text-gray-700">
                    {formatCurrency(sup.spend)}
                  </td>
                  <td className="p-4">
                    <div className="flex items-center justify-center gap-2">
                      <span className={`font-bold ${sup.onTime >= 95 ? 'text-green-600' : sup.onTime >= 90 ? 'text-amber-500' : 'text-red-500'}`}>
                        {sup.onTime}%
                      </span>
                    </div>
                  </td>
                  <td className="p-4">
                    <div className="flex items-center justify-center gap-2">
                      <span className={`font-bold ${sup.defect <= 1.0 ? 'text-green-600' : sup.defect <= 2.0 ? 'text-amber-500' : 'text-red-500'}`}>
                        {sup.defect}%
                      </span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}
