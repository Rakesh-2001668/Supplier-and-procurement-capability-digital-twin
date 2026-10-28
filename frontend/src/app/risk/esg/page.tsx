'use client';

import React from 'react';
import Link from 'next/link';

export default function ESGRiskPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/risk/dashboard" className="hover:text-blue-600">Risk & Intelligence</Link> 
            <span className="text-slate-300">›</span> ESG & Compliance
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">ESG & Compliance</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Monitor environmental, social and governance performance across your supplier network.</p>
        </div>
        <div className="flex items-center gap-3">
          <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 shadow-sm outline-none focus:border-blue-500">
            <option>Last 12 Months</option>
            <option>Last Quarter</option>
          </select>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            📄 Generate ESG Report
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        {/* ESG Compliant Suppliers */}
        <div className="bg-white rounded-xl border border-green-100 p-4 shadow-sm relative overflow-hidden flex items-center justify-between">
           <div>
              <div className="text-sm font-bold text-slate-600 mb-1">ESG Compliant Suppliers</div>
              <div className="flex items-end gap-1">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight">142</span>
                 <span className="text-xl font-bold text-slate-400 mb-0.5">/ 165</span>
              </div>
              <div className="text-[10px] font-bold text-green-600 flex items-center gap-1 mt-2">↑ 86% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last quarter</span></div>
           </div>
           <div className="w-14 h-14 rounded-full bg-green-100 flex items-center justify-center text-green-600 text-3xl opacity-80">🍃</div>
        </div>

        {/* Suppliers with Issues */}
        <div className="bg-white rounded-xl border border-amber-100 p-4 shadow-sm relative overflow-hidden flex items-center justify-between">
           <div>
              <div className="text-sm font-bold text-slate-600 mb-1">Suppliers with Issues</div>
              <div className="flex items-end gap-1">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight">18</span>
              </div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-2">↑ 3 <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last quarter</span></div>
           </div>
           <div className="w-14 h-14 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 text-3xl opacity-80">⚠️</div>
        </div>

        {/* Policies Meeting Standard */}
        <div className="bg-white rounded-xl border border-blue-100 p-4 shadow-sm relative overflow-hidden flex items-center justify-between">
           <div>
              <div className="text-sm font-bold text-slate-600 mb-1">Policies Meeting Standard</div>
              <div className="flex items-end gap-1">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight">92%</span>
              </div>
              <div className="text-[10px] font-bold text-green-600 flex items-center gap-1 mt-2">↑ 4% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last quarter</span></div>
           </div>
           <div className="w-14 h-14 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-3xl opacity-80">📄</div>
        </div>

        {/* High ESG Risk Suppliers */}
        <div className="bg-white rounded-xl border border-purple-100 p-4 shadow-sm relative overflow-hidden flex items-center justify-between">
           <div>
              <div className="text-sm font-bold text-slate-600 mb-1">High ESG Risk Suppliers</div>
              <div className="flex items-end gap-1">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight">5</span>
              </div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-2">↑ 2 <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last quarter</span></div>
           </div>
           <div className="w-14 h-14 rounded-full bg-purple-100 flex items-center justify-center text-purple-600 text-3xl opacity-80">👥</div>
        </div>
      </div>

      {/* Main Charts Row */}
      <div className="grid grid-cols-3 gap-4">
        {/* ESG Performance Trend */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">📊</span> ESG Performance Trend</h3>
              <select className="text-[10px] font-bold text-slate-500 border border-slate-200 rounded px-2 py-1 outline-none bg-transparent cursor-pointer">
                 <option>Last 12 Months</option>
              </select>
           </div>
           
           <div className="flex-1 flex flex-col justify-end relative px-4 mt-2 mb-8">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-6">
                 <span>100</span><span>80</span><span>60</span><span>40</span><span>20</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[9px] font-bold text-slate-400 -mb-5 px-4">
                 <span>Jan</span><span>Feb</span><span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span><span>Sep</span><span>Oct</span><span>Nov</span><span>Dec</span>
              </div>
              
              <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
                 {/* Green (Environmental) */}
                 <path d="M0,40 L30,38 L60,38 L90,35 L120,32 L150,30 L180,28 L210,25 L240,22 L270,20 L300,18 L330,15" fill="none" stroke="#10b981" strokeWidth="2.5" />
                 {/* Blue (Social) */}
                 <path d="M0,70 L30,68 L60,65 L90,60 L120,58 L150,55 L180,50 L210,48 L240,45 L270,42 L300,40 L330,38" fill="none" stroke="#3b82f6" strokeWidth="2.5" />
                 {/* Amber (Governance) */}
                 <path d="M0,100 L30,98 L60,95 L90,92 L120,88 L150,85 L180,82 L210,80 L240,78 L270,75 L300,72 L330,70" fill="none" stroke="#f59e0b" strokeWidth="2.5" />
                 
                 {/* Adding dots at end points for effect */}
                 <circle cx="0" cy="40" r="3" fill="#10b981" /><circle cx="330" cy="15" r="3" fill="#10b981" />
                 <circle cx="0" cy="70" r="3" fill="#3b82f6" /><circle cx="330" cy="38" r="3" fill="#3b82f6" />
                 <circle cx="0" cy="100" r="3" fill="#f59e0b" /><circle cx="330" cy="70" r="3" fill="#f59e0b" />
              </svg>
           </div>
           
           <div className="flex items-center justify-center gap-6 text-[10px] font-bold text-slate-600 mt-2">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> Environmental</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Social</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Governance</span>
           </div>
        </div>

        {/* ESG Score Distribution */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4"><span className="text-blue-600">📊</span> ESG Score Distribution</h3>
           
           <div className="flex items-center justify-center h-48 gap-8 mt-2">
              <div className="relative w-36 h-36">
                 <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                    <path className="text-emerald-500" strokeWidth="7" strokeDasharray="24, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-blue-500" strokeWidth="7" strokeDasharray="42, 100" strokeDashoffset="-24" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-amber-500" strokeWidth="7" strokeDasharray="21, 100" strokeDashoffset="-66" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-red-500" strokeWidth="7" strokeDasharray="12, 100" strokeDashoffset="-87" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                 </svg>
                 <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="text-2xl font-black text-[#0B2550] leading-none">165</span>
                    <span className="text-[10px] font-bold text-slate-500 mt-1">Suppliers</span>
                 </div>
              </div>
              
              <div className="space-y-3">
                 <div className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
                    <span className="text-[10px] font-bold text-slate-500 w-24">Excellent (80-100)</span>
                    <span className="text-[11px] font-black text-[#0B2550]">40 (24%)</span>
                 </div>
                 <div className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-blue-500"></span>
                    <span className="text-[10px] font-bold text-slate-500 w-24">Good (60-79)</span>
                    <span className="text-[11px] font-black text-[#0B2550]">70 (42%)</span>
                 </div>
                 <div className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span>
                    <span className="text-[10px] font-bold text-slate-500 w-24">Moderate (40-59)</span>
                    <span className="text-[11px] font-black text-[#0B2550]">35 (21%)</span>
                 </div>
                 <div className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-red-500"></span>
                    <span className="text-[10px] font-bold text-slate-500 w-24">Poor (0-39)</span>
                    <span className="text-[11px] font-black text-[#0B2550]">20 (12%)</span>
                 </div>
              </div>
           </div>
        </div>

        {/* Compliance Status */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4"><span className="text-blue-600">🛡️</span> Compliance Status</h3>
           
           <div className="space-y-2.5">
              {[
                { label: 'Environmental Regulations', val: 88, color: 'bg-emerald-500' },
                { label: 'Labour & Human Rights', val: 84, color: 'bg-emerald-500' },
                { label: 'Health & Safety', val: 90, color: 'bg-emerald-500' },
                { label: 'Anti-Corruption', val: 78, color: 'bg-amber-500' },
                { label: 'Data Privacy', val: 92, color: 'bg-emerald-500' },
                { label: 'Diversity & Inclusion', val: 76, color: 'bg-amber-500' },
                { label: 'Responsible Sourcing', val: 81, color: 'bg-emerald-500' },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between gap-3">
                   <span className="text-[10px] font-bold text-slate-600 w-36 truncate">{item.label}</span>
                   <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
                      <div className={`h-full ${item.color} rounded-full`} style={{ width: `${item.val}%` }}></div>
                   </div>
                   <span className="text-[10px] font-black text-[#0B2550] w-8 text-right">{item.val}%</span>
                </div>
              ))}
           </div>
        </div>
      </div>

      {/* Secondary Row */}
      <div className="grid grid-cols-4 gap-4">
        {/* Recent ESG Alerts */}
        <div className="col-span-2 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-red-500">🔔</span> Recent ESG Alerts</h3>
              <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Date</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Supplier</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Issue</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Severity</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Status</th>
                    </tr>
                 </thead>
                 <tbody className="text-[11px] font-semibold text-slate-700">
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2.5 text-slate-500">Aug 25, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">Global Metals Inc.</td>
                       <td className="py-2.5 text-[#0B2550] w-40 truncate">High carbon emissions</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-red-50 text-red-600 px-2 py-0.5 rounded text-[9px] font-bold border border-red-100"><span className="w-1.5 h-1.5 rounded-full bg-red-600"></span> High</span></td>
                       <td className="py-2.5 text-center"><span className="text-red-500 font-bold border border-red-100 px-2 py-0.5 rounded text-[9px]">Open</span></td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2.5 text-slate-500">Aug 22, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">EuroPack Solutions</td>
                       <td className="py-2.5 text-[#0B2550] w-40 truncate">Labour compliance audit pending</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-amber-50 text-amber-600 px-2 py-0.5 rounded text-[9px] font-bold border border-amber-100"><span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium</span></td>
                       <td className="py-2.5 text-center"><span className="text-red-500 font-bold border border-red-100 px-2 py-0.5 rounded text-[9px]">Open</span></td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2.5 text-slate-500">Aug 18, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">TransLogistics</td>
                       <td className="py-2.5 text-[#0B2550] w-40 truncate">Waste management non-compliance</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-amber-50 text-amber-600 px-2 py-0.5 rounded text-[9px] font-bold border border-amber-100"><span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium</span></td>
                       <td className="py-2.5 text-center"><span className="text-blue-500 font-bold border border-blue-100 px-2 py-0.5 rounded text-[9px] bg-blue-50">In Review</span></td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2.5 text-slate-500">Aug 12, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">Shenzhen Tech</td>
                       <td className="py-2.5 text-[#0B2550] w-40 truncate">Conflict minerals disclosure missing</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-red-50 text-red-600 px-2 py-0.5 rounded text-[9px] font-bold border border-red-100"><span className="w-1.5 h-1.5 rounded-full bg-red-600"></span> High</span></td>
                       <td className="py-2.5 text-center"><span className="text-red-500 font-bold border border-red-100 px-2 py-0.5 rounded text-[9px]">Open</span></td>
                    </tr>
                    <tr className="hover:bg-slate-50">
                       <td className="py-2.5 text-slate-500">Aug 10, 2025</td>
                       <td className="py-2.5 text-[#0B2550] font-bold">Delta Electronics</td>
                       <td className="py-2.5 text-[#0B2550] w-40 truncate">Diversity reporting incomplete</td>
                       <td className="py-2.5 text-center"><span className="inline-flex items-center gap-1 bg-emerald-50 text-emerald-600 px-2 py-0.5 rounded text-[9px] font-bold border border-emerald-100"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Low</span></td>
                       <td className="py-2.5 text-center"><span className="text-emerald-500 font-bold border border-emerald-100 px-2 py-0.5 rounded text-[9px] bg-emerald-50">Resolved</span></td>
                    </tr>
                 </tbody>
              </table>
           </div>
        </div>

        {/* Top ESG Risks */}
        <div className="col-span-1 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">📊</span> Top ESG Risks by Category</h3>
              <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="flex items-center justify-between text-[9px] font-extrabold text-slate-400 uppercase tracking-wider mb-2">
              <span>Category</span>
              <span>Number of Suppliers</span>
           </div>
           
           <div className="space-y-3.5 mt-4">
              {[
                { label: 'Carbon Emissions', val: 28, width: 85, color: 'bg-red-500' },
                { label: 'Labour Practices', val: 22, width: 65, color: 'bg-amber-500' },
                { label: 'Waste Management', val: 18, width: 55, color: 'bg-amber-500' },
                { label: 'Ethics & Anti-Corruption', val: 14, width: 45, color: 'bg-amber-400' },
                { label: 'Water Usage', val: 12, width: 40, color: 'bg-amber-400' },
                { label: 'Diversity & Inclusion', val: 10, width: 35, color: 'bg-emerald-500' },
                { label: 'Supply Chain Transparency', val: 8, width: 25, color: 'bg-emerald-500' },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between gap-3">
                   <span className="text-[10px] font-bold text-slate-700 w-36 truncate">{item.label}</span>
                   <div className="flex-1 h-3 bg-slate-100 rounded-sm overflow-hidden">
                      <div className={`h-full ${item.color} rounded-sm`} style={{ width: `${item.width}%` }}></div>
                   </div>
                   <span className="text-[11px] font-black text-[#0B2550] w-6 text-right">{item.val}</span>
                </div>
              ))}
           </div>
        </div>

        {/* AI Insights */}
        <div className="col-span-1 bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">💡</span> ESG Insights</h3>
           </div>
           
           <div className="flex-1 space-y-4">
              <div className="flex gap-3 items-start">
                 <div className="text-emerald-500 mt-0.5 font-bold">🍃</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">72% of suppliers have set carbon reduction targets.</p>
              </div>
              <div className="flex gap-3 items-start">
                 <div className="text-blue-500 mt-0.5 font-bold">👥</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Increase in social compliance audits by 15% this quarter.</p>
              </div>
              <div className="flex gap-3 items-start">
                 <div className="text-green-500 mt-0.5 font-bold">📄</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">New EU regulations on sustainable sourcing coming Jan 2026.</p>
              </div>
              <div className="flex gap-3 items-start">
                 <div className="text-blue-600 mt-0.5 font-bold">📊</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Suppliers with ESG issues show 2.3x higher operational risk.</p>
              </div>
           </div>
           
           <button className="w-full py-2 border border-slate-200 rounded-lg text-blue-600 font-bold text-xs mt-4 hover:bg-slate-50 transition-colors">
              View Detailed Analysis →
           </button>
        </div>
      </div>

      {/* Bottom Table */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
         <div className="flex items-center justify-between mb-4">
            <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-amber-500">🏆</span> ESG Top Performers</h3>
            <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
         </div>
         
         <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
               <thead>
                  <tr className="border-b border-slate-100">
                     <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Supplier Name</th>
                     <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Country</th>
                     <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">ESG Score</th>
                     <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Environmental</th>
                     <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Social</th>
                     <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Governance</th>
                     <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Certifications</th>
                     <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Last Assessed</th>
                     <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right pr-4">Action</th>
                  </tr>
               </thead>
               <tbody className="text-[11px] font-semibold text-slate-700">
                  <tr className="border-b border-slate-50 hover:bg-slate-50">
                     <td className="py-2.5 text-[#0B2550] font-bold text-xs">GreenTech Materials</td>
                     <td className="py-2.5 text-slate-500">Germany</td>
                     <td className="py-2.5 text-center"><span className="text-emerald-500 font-black text-sm">92</span></td>
                     <td className="py-2.5 text-center text-slate-600">95</td>
                     <td className="py-2.5 text-center text-slate-600">90</td>
                     <td className="py-2.5 text-center text-slate-600">91</td>
                     <td className="py-2.5 text-slate-600">ISO 14001, SA8000</td>
                     <td className="py-2.5 text-slate-500">Aug 20, 2025</td>
                     <td className="py-2.5 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1 bg-blue-50 text-blue-600 rounded-lg text-[10px] font-bold hover:bg-blue-100 mr-2">View</Link>
                        <button className="text-slate-400 hover:text-[#0B2550]">...</button>
                     </td>
                  </tr>
                  <tr className="border-b border-slate-50 hover:bg-slate-50">
                     <td className="py-2.5 text-[#0B2550] font-bold text-xs">Nordic Components</td>
                     <td className="py-2.5 text-slate-500">Sweden</td>
                     <td className="py-2.5 text-center"><span className="text-emerald-500 font-black text-sm">88</span></td>
                     <td className="py-2.5 text-center text-slate-600">90</td>
                     <td className="py-2.5 text-center text-slate-600">85</td>
                     <td className="py-2.5 text-center text-slate-600">89</td>
                     <td className="py-2.5 text-slate-600">ISO 14001, ISO 45001</td>
                     <td className="py-2.5 text-slate-500">Aug 18, 2025</td>
                     <td className="py-2.5 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1 bg-blue-50 text-blue-600 rounded-lg text-[10px] font-bold hover:bg-blue-100 mr-2">View</Link>
                        <button className="text-slate-400 hover:text-[#0B2550]">...</button>
                     </td>
                  </tr>
                  <tr className="border-b border-slate-50 hover:bg-slate-50">
                     <td className="py-2.5 text-[#0B2550] font-bold text-xs">Sunrise Electronics</td>
                     <td className="py-2.5 text-slate-500">Taiwan</td>
                     <td className="py-2.5 text-center"><span className="text-emerald-500 font-black text-sm">85</span></td>
                     <td className="py-2.5 text-center text-slate-600">87</td>
                     <td className="py-2.5 text-center text-slate-600">82</td>
                     <td className="py-2.5 text-center text-slate-600">86</td>
                     <td className="py-2.5 text-slate-600">RBA, ISO 14001</td>
                     <td className="py-2.5 text-slate-500">Aug 15, 2025</td>
                     <td className="py-2.5 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1 bg-blue-50 text-blue-600 rounded-lg text-[10px] font-bold hover:bg-blue-100 mr-2">View</Link>
                        <button className="text-slate-400 hover:text-[#0B2550]">...</button>
                     </td>
                  </tr>
                  <tr className="border-b border-slate-50 hover:bg-slate-50">
                     <td className="py-2.5 text-[#0B2550] font-bold text-xs">EcoPack Solutions</td>
                     <td className="py-2.5 text-slate-500">Netherlands</td>
                     <td className="py-2.5 text-center"><span className="text-emerald-500 font-black text-sm">83</span></td>
                     <td className="py-2.5 text-center text-slate-600">85</td>
                     <td className="py-2.5 text-center text-slate-600">80</td>
                     <td className="py-2.5 text-center text-slate-600">84</td>
                     <td className="py-2.5 text-slate-600">FSC, ISO 14001</td>
                     <td className="py-2.5 text-slate-500">Aug 12, 2025</td>
                     <td className="py-2.5 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1 bg-blue-50 text-blue-600 rounded-lg text-[10px] font-bold hover:bg-blue-100 mr-2">View</Link>
                        <button className="text-slate-400 hover:text-[#0B2550]">...</button>
                     </td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                     <td className="py-2.5 text-[#0B2550] font-bold text-xs">Sustainable Logistics</td>
                     <td className="py-2.5 text-slate-500">Canada</td>
                     <td className="py-2.5 text-center"><span className="text-emerald-500 font-black text-sm">82</span></td>
                     <td className="py-2.5 text-center text-slate-600">80</td>
                     <td className="py-2.5 text-center text-slate-600">84</td>
                     <td className="py-2.5 text-center text-slate-600">82</td>
                     <td className="py-2.5 text-slate-600">ISO 14001, TCFD</td>
                     <td className="py-2.5 text-slate-500">Aug 10, 2025</td>
                     <td className="py-2.5 text-right pr-4">
                        <Link href="/risk/supplier-risk" className="inline-flex items-center justify-center px-3 py-1 bg-blue-50 text-blue-600 rounded-lg text-[10px] font-bold hover:bg-blue-100 mr-2">View</Link>
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
