'use client';

import React from 'react';
import Link from 'next/link';

export default function RiskReportsPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/risk/dashboard" className="hover:text-blue-600">Risk & Intelligence</Link> 
            <span className="text-slate-300">›</span> Reports
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Reports</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Generate insights, track trends and share reports across risk, market, ESG and compliance.</p>
        </div>
        <div className="flex items-center gap-3">
          <button className="bg-blue-600 text-white px-5 py-2.5 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            + Generate Report
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 border-b border-slate-200 pb-4">
         <div className="flex-1 max-w-[200px]">
            <label className="text-[10px] font-bold text-slate-500 block mb-1">Report Type</label>
            <select className="w-full border border-slate-200 bg-white rounded-lg px-3 py-2 text-sm font-bold text-[#0B2550] outline-none">
               <option>All Reports</option>
            </select>
         </div>
         <div className="flex-1 max-w-[250px]">
            <label className="text-[10px] font-bold text-slate-500 block mb-1">Date Range</label>
            <div className="w-full border border-slate-200 bg-white rounded-lg px-3 py-2 text-sm font-bold text-[#0B2550] flex items-center gap-2">
               📅 Aug 1, 2025 - Aug 31, 2025
            </div>
         </div>
         <div className="flex-1 max-w-[200px]">
            <label className="text-[10px] font-bold text-slate-500 block mb-1">Region</label>
            <select className="w-full border border-slate-200 bg-white rounded-lg px-3 py-2 text-sm font-bold text-[#0B2550] outline-none">
               <option>All Regions</option>
            </select>
         </div>
         <div className="flex-1 max-w-[200px]">
            <label className="text-[10px] font-bold text-slate-500 block mb-1">Supplier Tier</label>
            <select className="w-full border border-slate-200 bg-white rounded-lg px-3 py-2 text-sm font-bold text-[#0B2550] outline-none">
               <option>All Tiers</option>
            </select>
         </div>
         <div className="pt-5">
            <button className="border border-slate-200 text-slate-700 bg-white px-4 py-2 rounded-lg font-bold text-sm shadow-sm hover:bg-slate-50 flex items-center gap-2">
               <span>⧨</span> More Filters
            </button>
         </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-blue-50/50 rounded-xl border border-blue-100 p-4 shadow-sm flex items-center gap-4 relative overflow-hidden">
           <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-2xl shrink-0">📄</div>
           <div className="flex-1">
              <div className="text-sm font-bold text-slate-600 mb-1">Reports Generated</div>
              <div className="flex items-end gap-3">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight leading-none">24</span>
                 <div className="flex flex-col">
                    <span className="text-[10px] font-bold text-green-500">↑ 33%</span>
                    <span className="text-[9px] font-bold text-slate-400">vs last month</span>
                 </div>
              </div>
           </div>
        </div>

        <div className="bg-emerald-50/50 rounded-xl border border-emerald-100 p-4 shadow-sm flex items-center gap-4 relative overflow-hidden">
           <div className="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-2xl shrink-0">✅</div>
           <div className="flex-1">
              <div className="text-sm font-bold text-slate-600 mb-1">On-Time Reports</div>
              <div className="flex items-end gap-3">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight leading-none">96%</span>
                 <div className="flex flex-col">
                    <span className="text-[10px] font-bold text-green-500">↑ 4%</span>
                    <span className="text-[9px] font-bold text-slate-400">vs last month</span>
                 </div>
              </div>
           </div>
        </div>

        <div className="bg-red-50/50 rounded-xl border border-red-100 p-4 shadow-sm flex items-center gap-4 relative overflow-hidden">
           <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center text-red-600 text-2xl shrink-0">⚠️</div>
           <div className="flex-1">
              <div className="text-sm font-bold text-slate-600 mb-1">Critical Findings</div>
              <div className="flex items-end gap-3">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight leading-none">8</span>
                 <div className="flex flex-col">
                    <span className="text-[10px] font-bold text-red-500">↑ 2</span>
                    <span className="text-[9px] font-bold text-slate-400">vs last month</span>
                 </div>
              </div>
           </div>
        </div>

        <div className="bg-purple-50/50 rounded-xl border border-purple-100 p-4 shadow-sm flex items-center gap-4 relative overflow-hidden">
           <div className="w-12 h-12 rounded-full bg-purple-100 flex items-center justify-center text-purple-600 text-2xl shrink-0">👥</div>
           <div className="flex-1">
              <div className="text-sm font-bold text-slate-600 mb-1">Suppliers Covered</div>
              <div className="flex items-end gap-3">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight leading-none">165</span>
                 <div className="flex flex-col">
                    <span className="text-[10px] font-bold text-green-500">↑ 12%</span>
                    <span className="text-[9px] font-bold text-slate-400">vs last month</span>
                 </div>
              </div>
           </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-8 border-b border-slate-200 px-2 pt-2">
         {['Overview', 'Risk Reports', 'ESG Reports', 'Compliance Reports', 'Market Intelligence', 'Custom Reports'].map((tab, i) => (
            <button key={i} className={`pb-3 text-sm font-bold border-b-2 transition-colors ${i === 0 ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'}`}>
               {tab}
            </button>
         ))}
      </div>

      <div className="grid grid-cols-3 gap-4">
         {/* Reports Generated */}
         <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">📊</span> Reports Generated (Last 6 Months)</h3>
            
            <div className="flex items-center justify-center gap-3 text-[9px] font-bold text-slate-600 mb-4">
               <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Risk Reports</span>
               <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> ESG Reports</span>
               <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Compliance Reports</span>
               <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-purple-500"></span> Market Intelligence</span>
            </div>
            
            <div className="h-40 flex items-end justify-between relative px-2 mb-2">
               <div className="absolute inset-0 border-b border-l border-slate-200"></div>
               <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-5">
                  <span>50</span><span>40</span><span>30</span><span>20</span><span>10</span><span>0</span>
               </div>
               
               {/* Bars */}
               <div className="relative w-full h-full flex justify-between items-end pb-0 z-10 px-4">
                  {[
                     { m: 'Mar', h1: 10, h2: 7, h3: 5, h4: 4 },
                     { m: 'Apr', h1: 12, h2: 8, h3: 5, h4: 4 },
                     { m: 'May', h1: 11, h2: 7, h3: 6, h4: 4 },
                     { m: 'Jun', h1: 14, h2: 10, h3: 7, h4: 5 },
                     { m: 'Jul', h1: 15, h2: 12, h3: 8, h4: 6 },
                     { m: 'Aug', h1: 16, h2: 14, h3: 10, h4: 8 },
                  ].map((d, i) => (
                     <div key={i} className="flex flex-col justify-end items-center h-full w-8">
                        <div className="w-6 bg-purple-500 rounded-t-sm" style={{height: `${(d.h4/50)*100}%`}}></div>
                        <div className="w-6 bg-amber-500" style={{height: `${(d.h3/50)*100}%`}}></div>
                        <div className="w-6 bg-emerald-500" style={{height: `${(d.h2/50)*100}%`}}></div>
                        <div className="w-6 bg-blue-500" style={{height: `${(d.h1/50)*100}%`}}></div>
                        <span className="absolute -bottom-5 text-[10px] font-bold text-slate-500">{d.m}</span>
                     </div>
                  ))}
               </div>
            </div>
         </div>

         {/* Report Distribution */}
         <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">📄</span> Report Distribution</h3>
            
            <div className="flex items-center justify-center h-44 gap-8">
               <div className="relative w-36 h-36 shrink-0">
                  <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                     <path className="text-blue-500" strokeWidth="7" strokeDasharray="37, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                     <path className="text-emerald-500" strokeWidth="7" strokeDasharray="25, 100" strokeDashoffset="-37" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                     <path className="text-amber-500" strokeWidth="7" strokeDasharray="17, 100" strokeDashoffset="-62" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                     <path className="text-red-500" strokeWidth="7" strokeDasharray="13, 100" strokeDashoffset="-79" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                     <path className="text-purple-500" strokeWidth="7" strokeDasharray="8, 100" strokeDashoffset="-92" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                     <span className="text-3xl font-black text-[#0B2550] leading-none">24</span>
                     <span className="text-[10px] font-bold text-slate-500 mt-1">Total Reports</span>
                  </div>
               </div>
               
               <div className="space-y-3 w-full">
                  <div className="flex items-center justify-between">
                     <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-blue-500"></span><span className="text-[11px] font-bold text-slate-700">Risk Reports</span></div>
                     <span className="text-[11px] font-black text-[#0B2550]">37%</span>
                  </div>
                  <div className="flex items-center justify-between">
                     <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span><span className="text-[11px] font-bold text-slate-700">ESG Reports</span></div>
                     <span className="text-[11px] font-black text-[#0B2550]">25%</span>
                  </div>
                  <div className="flex items-center justify-between">
                     <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span><span className="text-[11px] font-bold text-slate-700">Compliance Reports</span></div>
                     <span className="text-[11px] font-black text-[#0B2550]">17%</span>
                  </div>
                  <div className="flex items-center justify-between">
                     <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-red-500"></span><span className="text-[11px] font-bold text-slate-700">Market Intelligence</span></div>
                     <span className="text-[11px] font-black text-[#0B2550]">13%</span>
                  </div>
                  <div className="flex items-center justify-between">
                     <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-purple-500"></span><span className="text-[11px] font-bold text-slate-700">Custom Reports</span></div>
                     <span className="text-[11px] font-black text-[#0B2550]">8%</span>
                  </div>
               </div>
            </div>
         </div>

         {/* Key Insights */}
         <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">💡</span> Key Insights from Reports</h3>
            
            <div className="space-y-4">
               <div className="flex gap-3">
                  <div className="text-red-500 mt-0.5 text-sm font-bold">↗</div>
                  <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Geopolitical risks in Asia Pacific increased by 18% this quarter.</p>
               </div>
               <div className="flex gap-3">
                  <div className="text-emerald-500 mt-0.5 text-sm font-bold">🍃</div>
                  <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">72% of suppliers are on track to meet ESG targets.</p>
               </div>
               <div className="flex gap-3">
                  <div className="text-blue-500 mt-0.5 text-sm font-bold">🛡️</div>
                  <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">3 suppliers flagged for compliance review due to regulatory changes.</p>
               </div>
               <div className="flex gap-3">
                  <div className="text-amber-500 mt-0.5 text-sm font-bold">📊</div>
                  <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Commodity price volatility expected to continue through Q4.</p>
               </div>
               <div className="flex gap-3">
                  <div className="text-purple-500 mt-0.5 text-sm font-bold">👥</div>
                  <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Supplier diversity improved by 12% compared to last quarter.</p>
               </div>
            </div>
         </div>
      </div>

      <div className="grid grid-cols-6 gap-4">
         {/* Top Reported Risk Categories */}
         <div className="col-span-2 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-6 text-sm"><span className="text-blue-600">📊</span> Top Reported Risk Categories</h3>
            
            <div className="space-y-4">
               {[
                 { label: 'Geopolitical Risk', val: 14, width: 90, color: 'bg-red-500' },
                 { label: 'Supply Disruption', val: 12, width: 80, color: 'bg-amber-500' },
                 { label: 'Compliance Risk', val: 10, width: 65, color: 'bg-amber-400' },
                 { label: 'ESG Risk', val: 8, width: 50, color: 'bg-emerald-500' },
                 { label: 'Financial Risk', val: 6, width: 35, color: 'bg-blue-500' },
                 { label: 'Cybersecurity', val: 5, width: 30, color: 'bg-purple-500' },
               ].map((item, i) => (
                 <div key={i} className="flex items-center justify-between gap-3">
                    <span className="text-[10px] font-bold text-[#0B2550] w-32 truncate">{item.label}</span>
                    <div className="flex-1 h-3 bg-slate-100 rounded-sm overflow-hidden">
                       <div className={`h-full ${item.color} rounded-sm`} style={{ width: `${item.width}%` }}></div>
                    </div>
                    <span className="text-[11px] font-black text-[#0B2550] w-6 text-right">{item.val}</span>
                 </div>
               ))}
            </div>
         </div>
         
         {/* Reports by Region */}
         <div className="col-span-2 bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
            <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-2 text-sm"><span className="text-blue-600">🌍</span> Reports by Region</h3>
            
            <div className="flex-1 relative bg-slate-50 rounded-lg overflow-hidden flex items-center justify-center border border-slate-100 mt-2 min-h-[220px]">
               <div className="absolute inset-0 opacity-50 bg-[url('https://upload.wikimedia.org/wikipedia/commons/e/ec/World_map_blank_without_borders.svg')] bg-contain bg-center bg-no-repeat"></div>
               {/* Map overlay abstraction */}
            </div>
            
            <div className="flex items-center justify-center gap-4 text-[9px] font-bold text-slate-500 mt-4">
               <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-red-500"></span> High Activity</span>
               <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span> Medium Activity</span>
               <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-amber-300"></span> Low Activity</span>
               <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-slate-300"></span> No Reports</span>
            </div>
         </div>

         {/* Recent Reports Table */}
         <div className="col-span-2 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4">
               <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📄</span> Recent Reports</h3>
               <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
            </div>
            
            <div className="overflow-x-auto">
               <table className="w-full text-left border-collapse">
                  <thead>
                     <tr className="border-b border-slate-100">
                        <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Report Name</th>
                        <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Type</th>
                        <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Date</th>
                        <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Status</th>
                        <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Action</th>
                     </tr>
                  </thead>
                  <tbody className="text-[10px] font-semibold text-slate-700">
                     {[
                        { name: 'Q2 Supplier Risk Report', type: 'Risk', date: 'Aug 25, 2025' },
                        { name: 'ESG Compliance Summary', type: 'ESG', date: 'Aug 22, 2025' },
                        { name: 'APAC Market Intelligence', type: 'Market', date: 'Aug 20, 2025' },
                        { name: 'Regulatory Impact Analysis', type: 'Compliance', date: 'Aug 18, 2025' },
                        { name: 'Commodity Price Outlook', type: 'Market', date: 'Aug 15, 2025' },
                     ].map((r, i) => (
                        <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                           <td className="py-2.5 text-[#0B2550] font-bold max-w-[120px] truncate pr-2">{r.name}</td>
                           <td className="py-2.5 text-slate-500">{r.type}</td>
                           <td className="py-2.5 text-slate-500">{r.date}</td>
                           <td className="py-2.5"><span className="text-emerald-600 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded font-bold">Completed</span></td>
                           <td className="py-2.5 text-right"><button className="px-2 py-1 bg-blue-50 text-blue-600 rounded font-bold hover:bg-blue-100 border border-blue-100">View</button></td>
                        </tr>
                     ))}
                  </tbody>
               </table>
            </div>
         </div>
      </div>

      {/* Footer Banner */}
      <div className="bg-blue-50/50 rounded-xl border border-blue-100 p-5 shadow-sm flex items-center justify-between">
         <div className="flex items-center gap-4">
            <div className="w-12 h-12 bg-blue-600 rounded-full flex items-center justify-center text-white text-2xl shadow-md">📊</div>
            <div>
               <h3 className="font-bold text-[#0B2550] text-sm">Create Custom Reports</h3>
               <p className="text-xs text-slate-500 mt-1">Build tailored reports with the data that matters to you. Schedule automated delivery and share with stakeholders.</p>
            </div>
         </div>
         <button className="bg-white border border-slate-200 text-blue-600 px-5 py-2.5 rounded-lg font-bold text-sm shadow-sm hover:bg-slate-50 transition-colors flex items-center gap-2">
            Create Custom Report →
         </button>
      </div>

    </div>
  );
}
