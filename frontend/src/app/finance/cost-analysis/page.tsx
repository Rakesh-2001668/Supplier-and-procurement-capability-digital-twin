'use client';

import React from 'react';
import Link from 'next/link';

export default function CostAnalysisPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/finance/dashboard" className="hover:text-blue-600">Finance & Payments</Link> 
            <span className="text-slate-300">›</span> Cost Analysis
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Cost Analysis</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Understand, analyze and optimize your spending across suppliers, categories, and business units.</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 flex items-center gap-2">
            📅 Aug 1, 2025 - Aug 31, 2025
          </div>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            📄 Export
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xl shrink-0">🪙</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Total Spend</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 2,48,500</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 12% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
           </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl shrink-0">📊</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Cost Savings</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 18,450</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 24% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
           </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl shrink-0">📄</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Avg. Cost per Invoice</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 7,765</div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ 6% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
           </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xl shrink-0">📈</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Spend Variance</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">-5.2%</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↓ Improved <span className="text-slate-400 font-semibold uppercase tracking-wider">vs budget</span></div>
           </div>
        </div>

        <div className="bg-white rounded-xl border border-green-50 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center text-green-600 text-xl shrink-0">🍃</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Cost Optimization Opportunity</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 32,000</div>
              <div className="text-[10px] font-bold text-slate-500 flex items-center gap-1 mt-1">Identified by AI</div>
           </div>
        </div>
      </div>

      {/* Main Charts Row 1 */}
      <div className="grid grid-cols-12 gap-4">
        {/* Spend Trend */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📈</span> Spend Trend</h3>
              <select className="text-[10px] font-bold text-slate-500 border border-slate-200 rounded px-2 py-1 outline-none bg-transparent cursor-pointer">
                 <option>Last 6 Months</option>
              </select>
           </div>
           
           <div className="flex items-center justify-center gap-6 text-[10px] font-bold text-slate-600 mb-6 mt-2">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Actual Spend</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500"></span> Budgeted Spend</span>
           </div>
           
           <div className="h-44 flex items-end justify-between relative px-2 mb-2">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              
              <div className="absolute inset-0 flex flex-col justify-between">
                 {[...Array(7)].map((_, i) => (
                    <div key={i} className="w-full border-t border-slate-100" style={{height: '1px'}}></div>
                 ))}
              </div>

              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-8">
                 <span>300K</span><span>250K</span><span>200K</span><span>150K</span><span>100K</span><span>50K</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[9px] font-bold text-slate-400 -mb-5 px-6">
                 <span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span>
              </div>
              
              <div className="relative w-full h-full flex justify-between items-end pb-0 px-4 z-10">
                 {[
                    { m: 'Mar', act: 40, bud: 55 },
                    { m: 'Apr', act: 48, bud: 60 },
                    { m: 'May', act: 52, bud: 65 },
                    { m: 'Jun', act: 58, bud: 70 },
                    { m: 'Jul', act: 65, bud: 75 },
                    { m: 'Aug', act: 75, bud: 80 },
                 ].map((d, i) => (
                    <div key={i} className="flex flex-col justify-end items-center h-full w-8">
                       <div className="w-6 bg-blue-500 rounded-t-sm" style={{height: `${d.act}%`}}></div>
                    </div>
                 ))}
              </div>
              
              {/* Green Line (Budgeted Spend) */}
              <svg className="absolute inset-0 h-full w-full z-20" preserveAspectRatio="none">
                 <path d="M25,80 L80,72 L135,64 L190,56 L245,48 L300,40" fill="none" stroke="#22c55e" strokeWidth="2.5" />
                 <circle cx="25" cy="80" r="3" fill="#22c55e" stroke="#fff" strokeWidth="1" />
                 <circle cx="80" cy="72" r="3" fill="#22c55e" stroke="#fff" strokeWidth="1" />
                 <circle cx="135" cy="64" r="3" fill="#22c55e" stroke="#fff" strokeWidth="1" />
                 <circle cx="190" cy="56" r="3" fill="#22c55e" stroke="#fff" strokeWidth="1" />
                 <circle cx="245" cy="48" r="3" fill="#22c55e" stroke="#fff" strokeWidth="1" />
                 <circle cx="300" cy="40" r="3" fill="#22c55e" stroke="#fff" strokeWidth="1" />
              </svg>
           </div>
        </div>

        {/* Spend by Category */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">📄</span> Spend by Category</h3>
           
           <div className="flex items-center justify-center gap-4 mt-2">
              <div className="relative w-40 h-40 shrink-0">
                 <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                    <path className="text-blue-500" strokeWidth="7" strokeDasharray="32, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-amber-500" strokeWidth="7" strokeDasharray="18, 100" strokeDashoffset="-32" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-green-500" strokeWidth="7" strokeDasharray="15, 100" strokeDashoffset="-50" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-purple-500" strokeWidth="7" strokeDasharray="12, 100" strokeDashoffset="-65" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-orange-500" strokeWidth="7" strokeDasharray="10, 100" strokeDashoffset="-77" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-yellow-400" strokeWidth="7" strokeDasharray="8, 100" strokeDashoffset="-87" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-slate-400" strokeWidth="7" strokeDasharray="5, 100" strokeDashoffset="-95" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                 </svg>
                 <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="text-xl font-black text-[#0B2550] leading-tight">$ 2,48,500</span>
                    <span className="text-[9px] font-bold text-slate-500">Total Spend</span>
                 </div>
              </div>
              
              <div className="space-y-2 flex-1">
                 {[
                    { label: 'Raw Materials', val: '32%', color: 'bg-blue-500' },
                    { label: 'Logistics', val: '18%', color: 'bg-amber-500' },
                    { label: 'Facilities', val: '15%', color: 'bg-green-500' },
                    { label: 'IT & Software', val: '12%', color: 'bg-purple-500' },
                    { label: 'Professional Services', val: '10%', color: 'bg-orange-500' },
                    { label: 'Travel & Expenses', val: '8%', color: 'bg-yellow-400' },
                    { label: 'Other', val: '5%', color: 'bg-slate-400' },
                 ].map((item, i) => (
                    <div key={i} className="flex items-center justify-between">
                       <div className="flex items-center gap-2"><span className={`w-2 h-2 rounded-full ${item.color}`}></span><span className="text-[10px] font-bold text-slate-700">{item.label}</span></div>
                       <span className="text-[10px] font-black text-[#0B2550]">{item.val}</span>
                    </div>
                 ))}
              </div>
           </div>
        </div>

        {/* Spend by Business Unit */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-6 text-sm"><span className="text-blue-600">🏢</span> Spend by Business Unit</h3>
           
           <div className="space-y-3.5 mt-2">
              {[
                 { label: 'Manufacturing', val: '$ 82,400', pct: '33%', width: 100, color: 'bg-blue-500' },
                 { label: 'R&D', val: '$ 48,200', pct: '19%', width: 57, color: 'bg-green-500' },
                 { label: 'Sales & Marketing', val: '$ 36,700', pct: '15%', width: 45, color: 'bg-yellow-400' },
                 { label: 'IT', val: '$ 28,600', pct: '12%', width: 36, color: 'bg-purple-500' },
                 { label: 'Operations', val: '$ 24,900', pct: '10%', width: 30, color: 'bg-red-500' },
                 { label: 'HR', val: '$ 14,800', pct: '6%', width: 18, color: 'bg-amber-500' },
                 { label: 'Other', val: '$ 12,900', pct: '5%', width: 15, color: 'bg-slate-400' },
              ].map((item, i) => (
                 <div key={i} className="flex items-center justify-between gap-3">
                    <span className="text-[10px] font-bold text-[#0B2550] w-24 truncate">{item.label}</span>
                    <span className="text-[10px] font-mono text-slate-500 w-16 text-right">{item.val}</span>
                    <div className="flex-1 h-3 bg-slate-100 rounded-sm overflow-hidden">
                       <div className={`h-full ${item.color} rounded-sm`} style={{ width: `${item.width}%` }}></div>
                    </div>
                    <span className="text-[11px] font-black text-[#0B2550] w-8 text-right">{item.pct}</span>
                 </div>
              ))}
           </div>
        </div>
      </div>

      {/* Main Charts Row 2 */}
      <div className="grid grid-cols-12 gap-4">
        {/* Top Suppliers by Spend */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">👥</span> Top Suppliers by Spend</h3>
              <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider w-6">#</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider">Supplier</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Spend (USD)</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-center">% of Total</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Change</th>
                    </tr>
                 </thead>
                 <tbody className="text-[10px] font-semibold text-slate-700">
                    {[
                       { no: '1', color: 'bg-blue-600', name: 'Global Metals Inc.', spend: '52,400', pct: '21%', chg: '↑ 8%', chgColor: 'text-green-500' },
                       { no: '2', color: 'bg-emerald-500', name: 'EuroPack Solutions', spend: '38,750', pct: '16%', chg: '↓ 5%', chgColor: 'text-red-500' },
                       { no: '3', color: 'bg-amber-500', name: 'TransLogistics', spend: '28,300', pct: '11%', chg: '↑ 12%', chgColor: 'text-green-500' },
                       { no: '4', color: 'bg-purple-500', name: 'Shenzhen Tech', spend: '24,600', pct: '10%', chg: '↑ 6%', chgColor: 'text-green-500' },
                       { no: '5', color: 'bg-red-500', name: 'AgriFoods Co.', spend: '18,950', pct: '8%', chg: '↓ 3%', chgColor: 'text-red-500' },
                    ].map((s, i) => (
                       <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                          <td className="py-2.5"><div className={`w-4 h-4 rounded-full ${s.color} text-white flex items-center justify-center text-[9px] font-bold`}>{s.no}</div></td>
                          <td className="py-2.5 text-[#0B2550] font-bold">{s.name}</td>
                          <td className="py-2.5 text-right font-mono text-[10px]">{s.spend}</td>
                          <td className="py-2.5 text-center font-black text-[#0B2550]">{s.pct}</td>
                          <td className={`py-2.5 text-right font-bold ${s.chgColor}`}>{s.chg}</td>
                       </tr>
                    ))}
                 </tbody>
              </table>
           </div>
        </div>

        {/* Spend by Cost Center */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">🏢</span> Spend by Cost Center</h3>
              <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider">Cost Center</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Spend (USD)</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-center">% of Total</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Variance</th>
                    </tr>
                 </thead>
                 <tbody className="text-[10px] font-semibold text-slate-700">
                    {[
                       { cc: 'CC-1001 Production', spend: '72,300', pct: '29%', var: '- 6%', varColor: 'text-red-500' },
                       { cc: 'CC-1002 Logistics', spend: '38,600', pct: '16%', var: '+ 4%', varColor: 'text-green-500' },
                       { cc: 'CC-1003 IT Infrastructure', spend: '28,600', pct: '12%', var: '- 8%', varColor: 'text-red-500' },
                       { cc: 'CC-1004 Facilities', spend: '26,400', pct: '11%', var: '+ 2%', varColor: 'text-green-500' },
                       { cc: 'CC-1005 Admin', spend: '18,200', pct: '7%', var: '- 10%', varColor: 'text-green-500' },
                    ].map((s, i) => (
                       <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                          <td className="py-2.5 text-[#0B2550] font-bold">{s.cc}</td>
                          <td className="py-2.5 text-right font-mono text-[10px]">{s.spend}</td>
                          <td className="py-2.5 text-center font-black text-[#0B2550]">{s.pct}</td>
                          <td className={`py-2.5 text-right font-bold ${s.varColor}`}>{s.var}</td>
                       </tr>
                    ))}
                 </tbody>
              </table>
           </div>
        </div>

        {/* Cost Breakdown */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-2 text-sm"><span className="text-blue-600">💎</span> Cost Breakdown</h3>
           
           <div className="flex border-b border-slate-200 mb-2">
              <button className="pb-2 text-[10px] font-bold border-b-2 border-blue-600 text-blue-600 flex-1">By Category</button>
              <button className="pb-2 text-[10px] font-bold border-b-2 border-transparent text-slate-500 flex-1 hover:text-slate-700">By Supplier</button>
              <button className="pb-2 text-[10px] font-bold border-b-2 border-transparent text-slate-500 flex-1 hover:text-slate-700">By Cost Center</button>
           </div>
           
           <div className="overflow-x-auto flex-1">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider">Category</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Amount (USD)</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-center">%</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Trend</th>
                    </tr>
                 </thead>
                 <tbody className="text-[10px] font-semibold text-slate-700">
                    {[
                       { cat: 'Raw Materials', amt: '79,600', pct: '32%', trend: '↑', color: 'text-green-500' },
                       { cat: 'Logistics', amt: '44,800', pct: '18%', trend: '↑', color: 'text-green-500' },
                       { cat: 'Facilities', amt: '37,500', pct: '15%', trend: '↓', color: 'text-red-500' },
                       { cat: 'IT & Software', amt: '29,800', pct: '12%', trend: '↑', color: 'text-green-500' },
                       { cat: 'Professional Services', amt: '24,100', pct: '10%', trend: '↓', color: 'text-red-500' },
                       { cat: 'Travel & Expenses', amt: '19,200', pct: '8%', trend: '↑', color: 'text-green-500' },
                       { cat: 'Other', amt: '12,500', pct: '5%', trend: '→', color: 'text-blue-500' },
                    ].map((s, i) => (
                       <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                          <td className="py-1.5 text-slate-600 font-medium">{s.cat}</td>
                          <td className="py-1.5 text-right font-mono text-[9px]">{s.amt}</td>
                          <td className="py-1.5 text-center font-bold text-[#0B2550]">{s.pct}</td>
                          <td className={`py-1.5 text-center font-bold ${s.color}`}>{s.trend}</td>
                       </tr>
                    ))}
                 </tbody>
              </table>
           </div>
        </div>
      </div>

      {/* Main Charts Row 3 */}
      <div className="grid grid-cols-12 gap-4">
        {/* AI Insights */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">💡</span> AI Insights</h3>
           
           <div className="flex-1 space-y-4">
              <div className="flex gap-3">
                 <div className="text-emerald-500 mt-0.5 text-lg font-bold leading-none">↗</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Logistics costs increased by 18% due to higher freight rates. Consider renegotiating contracts.</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-amber-500 mt-0.5 text-lg font-bold leading-none">🪙</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Potential savings of $32,000 identified in IT & Software renewals.</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-red-500 mt-0.5 text-sm font-bold leading-none">⚠️</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Travel expenses are 22% higher than budget. Review approval policies.</p>
              </div>
           </div>
        </div>

        {/* Cost Savings Opportunities */}
        <div className="col-span-5 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">🎯</span> Cost Savings Opportunities</h3>
              <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider">Opportunity</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Potential Savings</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Impact</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Status</th>
                    </tr>
                 </thead>
                 <tbody className="text-[10px] font-semibold text-slate-700">
                    {[
                       { opp: 'Renegotiate logistics contract', sav: '$12,000', imp: 'High', impColor: 'text-green-600 bg-green-50', st: 'Open', stColor: 'text-amber-600 bg-amber-50' },
                       { opp: 'Consolidate software licenses', sav: '$8,500', imp: 'Medium', impColor: 'text-amber-600 bg-amber-50', st: 'In Progress', stColor: 'text-blue-600 bg-blue-50' },
                       { opp: 'Optimize facility utilities', sav: '$6,200', imp: 'Medium', impColor: 'text-amber-600 bg-amber-50', st: 'Open', stColor: 'text-amber-600 bg-amber-50' },
                       { opp: 'Review travel policy', sav: '$5,300', imp: 'Low', impColor: 'text-slate-600 bg-slate-100', st: 'Planned', stColor: 'text-slate-600 bg-slate-100' },
                    ].map((item, i) => (
                       <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                          <td className="py-2.5 text-[#0B2550] font-bold">{item.opp}</td>
                          <td className="py-2.5 text-right font-mono text-[10px]">{item.sav}</td>
                          <td className="py-2.5 text-center"><span className={`inline-block px-2 py-0.5 rounded text-[9px] font-bold ${item.impColor}`}>{item.imp}</span></td>
                          <td className="py-2.5 text-center"><span className={`inline-block px-2 py-0.5 rounded text-[9px] font-bold border border-transparent ${item.stColor}`}>{item.st}</span></td>
                       </tr>
                    ))}
                 </tbody>
              </table>
           </div>
        </div>

        {/* Quick Actions */}
        <div className="col-span-3 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">⚡</span> Quick Actions</h3>
           
           <div className="grid grid-cols-2 gap-3 mt-4">
              <button className="flex flex-col items-center justify-center gap-2 p-4 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-xl">📊</span>
                 <span className="text-[10px] font-bold text-blue-700">Run Cost Analysis</span>
              </button>
              <button className="flex flex-col items-center justify-center gap-2 p-4 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-xl">🕒</span>
                 <span className="text-[10px] font-bold text-blue-700 text-center leading-tight">Compare with<br/>Budget</span>
              </button>
              <button className="flex flex-col items-center justify-center gap-2 p-4 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-xl">🎯</span>
                 <span className="text-[10px] font-bold text-blue-700 text-center leading-tight">Create Savings<br/>Plan</span>
              </button>
              <button className="flex flex-col items-center justify-center gap-2 p-4 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-xl">📥</span>
                 <span className="text-[10px] font-bold text-blue-700">Download Report</span>
              </button>
           </div>
        </div>
      </div>
      
    </div>
  );
}
