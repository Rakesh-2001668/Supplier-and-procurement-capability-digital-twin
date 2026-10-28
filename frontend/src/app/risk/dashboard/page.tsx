'use client';

import React from 'react';
import Link from 'next/link';

export default function RiskDashboardPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[#0B2550] tracking-tight">Risk Dashboard</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Real-time visibility into supply chain risks, powered by AI-driven intelligence.</p>
        </div>
        <div className="flex items-center gap-3">
          <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 shadow-sm outline-none focus:border-blue-500">
            <option>Last 30 Days</option>
            <option>Last Quarter</option>
            <option>Last Year</option>
          </select>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            📄 Generate Report
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-4">
        {/* High Risk */}
        <div className="bg-white rounded-xl border border-red-100 p-4 shadow-sm relative overflow-hidden">
           <div className="absolute top-0 right-0 p-4 opacity-10 text-3xl">⚠️</div>
           <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-red-100 flex items-center justify-center text-red-600">🛡️</div>
              <span className="text-sm font-bold text-slate-600">High Risk Suppliers</span>
           </div>
           <div className="flex items-end gap-3 mt-1">
              <span className="text-3xl font-black text-[#0B2550] tracking-tight">5</span>
              <span className="text-xs font-bold text-red-500 bg-red-50 px-1.5 py-0.5 rounded flex items-center mb-1">↑ 2</span>
           </div>
           <div className="text-[10px] font-semibold text-slate-400 mt-1 uppercase tracking-wider">vs last month</div>
        </div>

        {/* Medium Risk */}
        <div className="bg-white rounded-xl border border-amber-100 p-4 shadow-sm relative overflow-hidden">
           <div className="absolute top-0 right-0 p-4 opacity-10 text-3xl">⚠️</div>
           <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center text-amber-600">⚠️</div>
              <span className="text-sm font-bold text-slate-600">Medium Risk Suppliers</span>
           </div>
           <div className="flex items-end gap-3 mt-1">
              <span className="text-3xl font-black text-[#0B2550] tracking-tight">18</span>
              <span className="text-xs font-bold text-green-600 bg-green-50 px-1.5 py-0.5 rounded flex items-center mb-1">↓ 6</span>
           </div>
           <div className="text-[10px] font-semibold text-slate-400 mt-1 uppercase tracking-wider">vs last month</div>
        </div>

        {/* Low Risk */}
        <div className="bg-white rounded-xl border border-green-100 p-4 shadow-sm relative overflow-hidden">
           <div className="absolute top-0 right-0 p-4 opacity-10 text-3xl">✅</div>
           <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-green-100 flex items-center justify-center text-green-600">✅</div>
              <span className="text-sm font-bold text-slate-600">Low Risk Suppliers</span>
           </div>
           <div className="flex items-end gap-3 mt-1">
              <span className="text-3xl font-black text-[#0B2550] tracking-tight">142</span>
              <span className="text-xs font-bold text-green-600 bg-green-50 px-1.5 py-0.5 rounded flex items-center mb-1">↑ 12</span>
           </div>
           <div className="text-[10px] font-semibold text-slate-400 mt-1 uppercase tracking-wider">vs last month</div>
        </div>

        {/* Geopolitical Risk */}
        <div className="bg-white rounded-xl border border-blue-100 p-4 shadow-sm relative overflow-hidden">
           <div className="absolute top-0 right-0 p-4 opacity-10 text-3xl">🌍</div>
           <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600">🌍</div>
              <span className="text-sm font-bold text-slate-600">Geopolitical Risk</span>
           </div>
           <div className="mt-1">
              <span className="text-xl font-black text-amber-500 tracking-tight block">Moderate</span>
              <span className="text-xs font-bold text-slate-500 block mt-1">Global index: 56 / 100</span>
           </div>
        </div>

        {/* Compliance Score */}
        <div className="bg-white rounded-xl border border-emerald-100 p-4 shadow-sm relative overflow-hidden">
           <div className="absolute top-0 right-0 p-4 opacity-10 text-3xl">🍃</div>
           <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600">🍃</div>
              <span className="text-sm font-bold text-slate-600">Compliance Score</span>
           </div>
           <div className="flex items-end gap-3 mt-1">
              <span className="text-3xl font-black text-[#0B2550] tracking-tight">92%</span>
              <span className="text-xs font-bold text-green-600 bg-green-50 px-1.5 py-0.5 rounded flex items-center mb-1">↑ 4%</span>
           </div>
           <div className="text-[10px] font-semibold text-slate-400 mt-1 uppercase tracking-wider">vs last quarter</div>
        </div>
      </div>

      {/* Main Charts Row */}
      <div className="grid grid-cols-3 gap-4">
        {/* Risk Trend */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">📈</span> Risk Trend</h3>
              <select className="text-xs font-bold text-slate-500 border-none outline-none bg-transparent cursor-pointer">
                 <option>Last 6 Months</option>
              </select>
           </div>
           
           <div className="flex items-center justify-center gap-4 text-xs font-bold text-slate-600 mb-6">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> High Risk</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Medium Risk</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Low Risk</span>
           </div>
           
           <div className="h-48 flex items-end justify-between relative px-2">
              {/* Mocking the line chart visually */}
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-5">
                 <span>100</span><span>80</span><span>60</span><span>40</span><span>20</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[10px] font-bold text-slate-400 -mb-5 px-2">
                 <span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span>
              </div>
              
              {/* Lines placeholders (using svgs or styled divs would be best, here using simple CSS trick for representation) */}
              <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
                 <path d="M0,40 L60,45 L120,50 L180,55 L240,58 L300,60" fill="none" stroke="#3b82f6" strokeWidth="2" />
                 <path d="M0,100 L60,105 L120,110 L180,105 L240,110 L300,115" fill="none" stroke="#f59e0b" strokeWidth="2" />
                 <path d="M0,150 L60,155 L120,145 L180,150 L240,155 L300,160" fill="none" stroke="#ef4444" strokeWidth="2" />
                 {/* dots */}
                 <circle cx="0" cy="40" r="3" fill="#3b82f6" /><circle cx="60" cy="45" r="3" fill="#3b82f6" />
                 <circle cx="120" cy="50" r="3" fill="#3b82f6" /><circle cx="180" cy="55" r="3" fill="#3b82f6" />
                 <circle cx="240" cy="58" r="3" fill="#3b82f6" /><circle cx="300" cy="60" r="3" fill="#3b82f6" />
              </svg>
           </div>
        </div>

        {/* Risk Distribution */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4"><span className="text-blue-600">📊</span> Risk Distribution</h3>
           
           <div className="flex items-center justify-center h-48 gap-8 mt-2">
              <div className="relative w-32 h-32">
                 <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                    <path className="text-slate-100" strokeWidth="6" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-blue-500" strokeWidth="6" strokeDasharray="86, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-amber-500" strokeWidth="6" strokeDasharray="11, 100" strokeDashoffset="-86" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-red-500" strokeWidth="6" strokeDasharray="3, 100" strokeDashoffset="-97" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                 </svg>
                 <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="text-2xl font-black text-[#0B2550] leading-none">165</span>
                    <span className="text-[10px] font-bold text-slate-500">Suppliers</span>
                 </div>
              </div>
              
              <div className="space-y-4">
                 <div className="flex items-center gap-3">
                    <span className="w-3 h-3 rounded-full bg-red-500"></span>
                    <span className="text-xs font-bold text-slate-700 w-20">High Risk</span>
                    <span className="text-xs font-black text-[#0B2550]">5 (3%)</span>
                 </div>
                 <div className="flex items-center gap-3">
                    <span className="w-3 h-3 rounded-full bg-amber-500"></span>
                    <span className="text-xs font-bold text-slate-700 w-20">Medium Risk</span>
                    <span className="text-xs font-black text-[#0B2550]">18 (11%)</span>
                 </div>
                 <div className="flex items-center gap-3">
                    <span className="w-3 h-3 rounded-full bg-blue-500"></span>
                    <span className="text-xs font-bold text-slate-700 w-20">Low Risk</span>
                    <span className="text-xs font-black text-[#0B2550]">142 (86%)</span>
                 </div>
              </div>
           </div>
        </div>

        {/* Risk by Region */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">🌍</span> Risk by Region</h3>
              <select className="text-xs font-bold text-slate-500 border-none outline-none bg-transparent cursor-pointer">
                 <option>All Regions</option>
              </select>
           </div>
           
           <div className="h-48 relative bg-slate-50 rounded-lg overflow-hidden flex items-center justify-center group">
              <div className="absolute inset-0 opacity-40 bg-[url('https://upload.wikimedia.org/wikipedia/commons/e/ec/World_map_blank_without_borders.svg')] bg-contain bg-center bg-no-repeat"></div>
              
              {/* Map Pins */}
              <div className="absolute top-[40%] left-[75%]">
                 <div className="w-3 h-3 rounded-full bg-red-500 shadow-[0_0_0_4px_rgba(239,68,68,0.2)]"></div>
                 <div className="absolute top-0 left-4 bg-white shadow-lg border border-slate-100 rounded p-2 z-10 w-32 hidden group-hover:block">
                    <div className="text-xs font-bold text-[#0B2550]">China</div>
                    <div className="text-[10px] text-red-500 font-bold mb-1">Risk Level: High</div>
                    <Link href="/risk/geopolitical" className="text-[10px] text-blue-600 hover:underline">View Details →</Link>
                 </div>
              </div>
              <div className="absolute top-[35%] left-[50%]">
                 <div className="w-3 h-3 rounded-full bg-amber-500 shadow-[0_0_0_4px_rgba(245,158,11,0.2)]"></div>
              </div>
              <div className="absolute top-[50%] left-[25%]">
                 <div className="w-3 h-3 rounded-full bg-amber-500 shadow-[0_0_0_4px_rgba(245,158,11,0.2)]"></div>
              </div>
              <div className="absolute top-[25%] left-[20%]">
                 <div className="w-3 h-3 rounded-full bg-blue-500 shadow-[0_0_0_4px_rgba(59,130,246,0.2)]"></div>
              </div>
              
              {/* Legend */}
              <div className="absolute bottom-2 left-0 w-full flex justify-center gap-4 text-[9px] font-bold text-slate-500">
                 <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> High Risk</span>
                 <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Medium Risk</span>
                 <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Low Risk</span>
              </div>
           </div>
        </div>
      </div>

      {/* Secondary Charts Row */}
      <div className="grid grid-cols-3 gap-4">
        {/* Top Risk Factors */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-red-500">⚠️</span> Top Risk Factors</h3>
              <button className="text-blue-600 text-lg">→</button>
           </div>
           
           <div className="space-y-4">
              {[
                { label: 'Financial Instability', val: 32, color: 'bg-red-500' },
                { label: 'Geopolitical Exposure', val: 24, color: 'bg-amber-500' },
                { label: 'Supply Disruption', val: 18, color: 'bg-amber-400' },
                { label: 'Compliance Issues', val: 12, color: 'bg-blue-400' },
                { label: 'ESG Concerns', val: 8, color: 'bg-emerald-500' },
                { label: 'Cybersecurity Risk', val: 6, color: 'bg-purple-500' },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between gap-4">
                   <span className="text-xs font-bold text-slate-700 w-32 truncate">{item.label}</span>
                   <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
                      <div className={`h-full ${item.color} rounded-full`} style={{ width: `${item.val}%` }}></div>
                   </div>
                   <span className="text-xs font-black text-[#0B2550] w-8 text-right">{item.val}%</span>
                </div>
              ))}
           </div>
        </div>

        {/* Recent Risk Alerts */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-red-500">🔔</span> Recent Risk Alerts</h3>
              <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Date</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Supplier</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Alert Type</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Severity</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Status</th>
                    </tr>
                 </thead>
                 <tbody className="text-xs font-semibold text-slate-700">
                    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                       <td className="py-2.5 text-slate-500">Aug 25, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">Shenzhen Tech</td>
                       <td className="py-2.5 text-slate-600">Payment Delay</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-red-50 text-red-600 px-2 py-0.5 rounded text-[10px] font-bold border border-red-100"><span className="w-1.5 h-1.5 rounded-full bg-red-600"></span> High</span></td>
                       <td className="py-2.5 text-center"><span className="text-red-500 font-bold text-[10px]">Open</span></td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                       <td className="py-2.5 text-slate-500">Aug 24, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">Global Metals</td>
                       <td className="py-2.5 text-slate-600">Port Disruption</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-amber-50 text-amber-600 px-2 py-0.5 rounded text-[10px] font-bold border border-amber-100"><span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium</span></td>
                       <td className="py-2.5 text-center"><span className="text-red-500 font-bold text-[10px]">Open</span></td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                       <td className="py-2.5 text-slate-500">Aug 23, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">EuroPack</td>
                       <td className="py-2.5 text-slate-600">Compliance Update</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-amber-50 text-amber-600 px-2 py-0.5 rounded text-[10px] font-bold border border-amber-100"><span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium</span></td>
                       <td className="py-2.5 text-center"><span className="text-blue-500 font-bold text-[10px]">In Review</span></td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                       <td className="py-2.5 text-slate-500">Aug 22, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">Delta Electronics</td>
                       <td className="py-2.5 text-slate-600">Credit Rating Downgrade</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-red-50 text-red-600 px-2 py-0.5 rounded text-[10px] font-bold border border-red-100"><span className="w-1.5 h-1.5 rounded-full bg-red-600"></span> High</span></td>
                       <td className="py-2.5 text-center"><span className="text-red-500 font-bold text-[10px]">Open</span></td>
                    </tr>
                    <tr className="hover:bg-slate-50 transition-colors">
                       <td className="py-2.5 text-slate-500">Aug 20, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">TransLogistics</td>
                       <td className="py-2.5 text-slate-600">Political Unrest</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-amber-50 text-amber-600 px-2 py-0.5 rounded text-[10px] font-bold border border-amber-100"><span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium</span></td>
                       <td className="py-2.5 text-center"><span className="text-emerald-500 font-bold text-[10px]">Resolved</span></td>
                    </tr>
                 </tbody>
              </table>
           </div>
        </div>

        {/* AI Insights */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">🤖</span> AI Insights</h3>
              <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="flex-1 space-y-4">
              <div className="flex gap-3">
                 <div className="text-red-500 mt-0.5">📈</div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed">Increased port congestion in SE Asia may impact lead times (2-4 weeks).</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-amber-500 mt-0.5">📉</div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed">Commodity prices for aluminum expected to rise by 8% in Q3.</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-emerald-500 mt-0.5">📄</div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed">New ESG regulation coming into effect in EU from Jan 2026.</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-emerald-500 mt-0.5">📊</div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed">Supplier financial health improving in electronics sector.</p>
              </div>
           </div>
        </div>
      </div>

      {/* Bottom Table */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
         <div className="flex items-center justify-between mb-4">
            <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-red-500">🛡️</span> High Risk Suppliers</h3>
            <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
         </div>
         
         <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
               <thead>
                  <tr className="border-b border-slate-100">
                     <th className="py-3 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Supplier Name</th>
                     <th className="py-3 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Location</th>
                     <th className="py-3 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Risk Score</th>
                     <th className="py-3 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Key Risk Factors</th>
                     <th className="py-3 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Last Assessed</th>
                     <th className="py-3 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right pr-4">Action</th>
                  </tr>
               </thead>
               <tbody className="text-sm font-semibold text-slate-700">
                  <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors group">
                     <td className="py-3 text-[#0B2550] font-bold">Shenzhen Tech Components</td>
                     <td className="py-3 text-slate-500">China</td>
                     <td className="py-3"><span className="text-red-600 font-bold flex items-center gap-1">❌ 78 <span className="text-slate-400 font-medium text-xs">/ 100</span></span></td>
                     <td className="py-3 text-slate-600">Financial, Geopolitical</td>
                     <td className="py-3 text-slate-500">Aug 25, 2025</td>
                     <td className="py-3 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-xs font-bold hover:bg-blue-100 transition-colors mr-2">View</Link>
                        <button className="text-slate-400 hover:text-[#0B2550]">...</button>
                     </td>
                  </tr>
                  <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors group">
                     <td className="py-3 text-[#0B2550] font-bold">Global Metals Inc.</td>
                     <td className="py-3 text-slate-500">USA</td>
                     <td className="py-3"><span className="text-red-600 font-bold flex items-center gap-1">❌ 72 <span className="text-slate-400 font-medium text-xs">/ 100</span></span></td>
                     <td className="py-3 text-slate-600">Supply Disruption</td>
                     <td className="py-3 text-slate-500">Aug 22, 2025</td>
                     <td className="py-3 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-xs font-bold hover:bg-blue-100 transition-colors mr-2">View</Link>
                        <button className="text-slate-400 hover:text-[#0B2550]">...</button>
                     </td>
                  </tr>
                  <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors group">
                     <td className="py-3 text-[#0B2550] font-bold">EuroPack Solutions</td>
                     <td className="py-3 text-slate-500">Germany</td>
                     <td className="py-3"><span className="text-red-600 font-bold flex items-center gap-1">❌ 68 <span className="text-slate-400 font-medium text-xs">/ 100</span></span></td>
                     <td className="py-3 text-slate-600">Compliance, ESG</td>
                     <td className="py-3 text-slate-500">Aug 20, 2025</td>
                     <td className="py-3 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-xs font-bold hover:bg-blue-100 transition-colors mr-2">View</Link>
                        <button className="text-slate-400 hover:text-[#0B2550]">...</button>
                     </td>
                  </tr>
                  <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors group">
                     <td className="py-3 text-[#0B2550] font-bold">Delta Electronics</td>
                     <td className="py-3 text-slate-500">Taiwan</td>
                     <td className="py-3"><span className="text-red-600 font-bold flex items-center gap-1">❌ 65 <span className="text-slate-400 font-medium text-xs">/ 100</span></span></td>
                     <td className="py-3 text-slate-600">Financial</td>
                     <td className="py-3 text-slate-500">Aug 18, 2025</td>
                     <td className="py-3 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-xs font-bold hover:bg-blue-100 transition-colors mr-2">View</Link>
                        <button className="text-slate-400 hover:text-[#0B2550]">...</button>
                     </td>
                  </tr>
                  <tr className="hover:bg-slate-50 transition-colors group">
                     <td className="py-3 text-[#0B2550] font-bold">TransLogistics Ltd.</td>
                     <td className="py-3 text-slate-500">Singapore</td>
                     <td className="py-3"><span className="text-red-600 font-bold flex items-center gap-1">❌ 62 <span className="text-slate-400 font-medium text-xs">/ 100</span></span></td>
                     <td className="py-3 text-slate-600">Geopolitical</td>
                     <td className="py-3 text-slate-500">Aug 17, 2025</td>
                     <td className="py-3 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-xs font-bold hover:bg-blue-100 transition-colors mr-2">View</Link>
                        <button className="text-slate-400 hover:text-[#0B2550]">...</button>
                     </td>
                  </tr>
               </tbody>
            </table>
         </div>
      </div>
      
    </div>
  );
}
