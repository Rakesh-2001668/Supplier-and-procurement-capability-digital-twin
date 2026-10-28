'use client';
import { useQuery } from '@tanstack/react-query';
import { apiClient, TEST_TENANT_ID } from '@/lib/apiClient';


import React from 'react';
import Link from 'next/link';

export default function FinanceDashboardPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/finance/dashboard" className="hover:text-blue-600">Finance & Payments</Link> 
            <span className="text-slate-300">›</span> Finance Dashboard
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Finance Dashboard</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Track spending, payments, and supplier financial performance in one place.</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 flex items-center gap-2">
            📅 Aug 1, 2025 - Aug 31, 2025
          </div>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            📄 Export Report
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-4">
        {/* Total Spend */}
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

        {/* Open Invoices */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl shrink-0">📄</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Open Invoices</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">32</div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ 6 <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
           </div>
        </div>

        {/* Payments Made */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xl shrink-0">💳</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Payments Made</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 1,76,200</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 18% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
           </div>
        </div>

        {/* Pending Payments */}
        <div className="bg-white rounded-xl border border-red-50 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center text-red-600 text-xl shrink-0">🕒</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Pending Payments</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 72,300</div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ 8% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
           </div>
        </div>

        {/* Cost Savings */}
        <div className="bg-white rounded-xl border border-green-50 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center text-green-600 text-xl shrink-0">💰</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Cost Savings</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 18,450</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 24% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
           </div>
        </div>
      </div>

      {/* Main Charts Row 1 */}
      <div className="grid grid-cols-12 gap-4">
        {/* Monthly Spend Trend */}
        <div className="col-span-5 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📈</span> Monthly Spend Trend</h3>
              <select className="text-[10px] font-bold text-slate-500 border border-slate-200 rounded px-2 py-1 outline-none bg-transparent cursor-pointer">
                 <option>Last 8 Months</option>
              </select>
           </div>
           
           <div className="flex items-center justify-center gap-6 text-[10px] font-bold text-slate-600 mb-6 mt-2">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Total Spend</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500"></span> Payments Made</span>
           </div>
           
           <div className="h-44 flex items-end justify-between relative px-2 mb-2">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              
              {/* Add grid lines for background */}
              <div className="absolute inset-0 flex flex-col justify-between">
                 {[...Array(6)].map((_, i) => (
                    <div key={i} className="w-full border-t border-slate-100" style={{height: '1px'}}></div>
                 ))}
              </div>

              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-8">
                 <span>300K</span><span>250K</span><span>200K</span><span>150K</span><span>100K</span><span>50K</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[9px] font-bold text-slate-400 -mb-5 px-4">
                 <span>Jan</span><span>Feb</span><span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span>
              </div>
              
              {/* Fill areas under the lines */}
              <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
                 <defs>
                    <linearGradient id="blueGradient" x1="0" x2="0" y1="0" y2="1">
                       <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.2"/>
                       <stop offset="100%" stopColor="#3b82f6" stopOpacity="0"/>
                    </linearGradient>
                    <linearGradient id="greenGradient" x1="0" x2="0" y1="0" y2="1">
                       <stop offset="0%" stopColor="#22c55e" stopOpacity="0.2"/>
                       <stop offset="100%" stopColor="#22c55e" stopOpacity="0"/>
                    </linearGradient>
                 </defs>
                 
                 {/* Blue Area */}
                 <path d="M0,60 L40,65 L80,50 L120,45 L160,55 L200,40 L240,42 L280,30 L280,176 L0,176 Z" fill="url(#blueGradient)" />
                 {/* Green Area */}
                 <path d="M0,100 L40,95 L80,90 L120,85 L160,88 L200,80 L240,75 L280,70 L280,176 L0,176 Z" fill="url(#greenGradient)" />

                 {/* Blue Line (Total Spend) */}
                 <path d="M0,60 L40,65 L80,50 L120,45 L160,55 L200,40 L240,42 L280,30" fill="none" stroke="#3b82f6" strokeWidth="2.5" />
                 
                 {/* Green Line (Payments Made) */}
                 <path d="M0,100 L40,95 L80,90 L120,85 L160,88 L200,80 L240,75 L280,70" fill="none" stroke="#22c55e" strokeWidth="2.5" />
                 
                 {/* Data Points */}
                 {[0, 40, 80, 120, 160, 200, 240, 280].map((cx, i) => {
                    const blueY = [60, 65, 50, 45, 55, 40, 42, 30][i];
                    const greenY = [100, 95, 90, 85, 88, 80, 75, 70][i];
                    return (
                       <g key={i}>
                          <circle cx={cx} cy={blueY} r="3.5" fill="#3b82f6" stroke="#fff" strokeWidth="1" />
                          <circle cx={cx} cy={greenY} r="3.5" fill="#22c55e" stroke="#fff" strokeWidth="1" />
                       </g>
                    )
                 })}
              </svg>
           </div>
        </div>

        {/* Spend by Category */}
        <div className="col-span-3 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">📄</span> Spend by Category</h3>
           
           <div className="flex items-center justify-center gap-4 mt-2">
              <div className="relative w-36 h-36 shrink-0">
                 <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                    <path className="text-blue-500" strokeWidth="7" strokeDasharray="32, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-amber-500" strokeWidth="7" strokeDasharray="18, 100" strokeDashoffset="-32" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-orange-500" strokeWidth="7" strokeDasharray="15, 100" strokeDashoffset="-50" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-purple-500" strokeWidth="7" strokeDasharray="12, 100" strokeDashoffset="-65" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-cyan-500" strokeWidth="7" strokeDasharray="10, 100" strokeDashoffset="-77" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-red-400" strokeWidth="7" strokeDasharray="8, 100" strokeDashoffset="-87" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
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
                    { label: 'Components', val: '18%', color: 'bg-amber-500' },
                    { label: 'Logistics', val: '15%', color: 'bg-orange-500' },
                    { label: 'Services', val: '12%', color: 'bg-purple-500' },
                    { label: 'Capital Equipment', val: '10%', color: 'bg-cyan-500' },
                    { label: 'MRO', val: '8%', color: 'bg-red-400' },
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
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-right">% of Total</th>
                    </tr>
                 </thead>
                 <tbody className="text-[11px] font-semibold text-slate-700">
                    {[
                       { no: '1', color: 'bg-blue-600', name: 'Global Metals Inc.', spend: '52,400', pct: '21%' },
                       { no: '2', color: 'bg-emerald-500', name: 'EuroPack Solutions', spend: '38,750', pct: '16%' },
                       { no: '3', color: 'bg-amber-500', name: 'TransLogistics', spend: '28,300', pct: '11%' },
                       { no: '4', color: 'bg-purple-500', name: 'Shenzhen Tech', spend: '24,600', pct: '10%' },
                       { no: '5', color: 'bg-red-500', name: 'AgriFoods Co.', spend: '18,950', pct: '8%' },
                    ].map((s, i) => (
                       <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                          <td className="py-2"><div className={`w-4 h-4 rounded-full ${s.color} text-white flex items-center justify-center text-[9px] font-bold`}>{s.no}</div></td>
                          <td className="py-2 text-[#0B2550] font-bold">{s.name}</td>
                          <td className="py-2 text-right font-mono text-[10px]">{s.spend}</td>
                          <td className="py-2 text-right font-black text-[#0B2550]">{s.pct}</td>
                       </tr>
                    ))}
                 </tbody>
              </table>
           </div>
        </div>
      </div>

      {/* Main Charts Row 2 */}
      <div className="grid grid-cols-12 gap-4">
        {/* Invoice Status */}
        <div className="col-span-3 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">📄</span> Invoice Status</h3>
           
           <div className="flex items-center justify-center gap-4 mt-2">
              <div className="relative w-32 h-32 shrink-0">
                 <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                    <path className="text-emerald-500" strokeWidth="7" strokeDasharray="59, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-amber-500" strokeWidth="7" strokeDasharray="19, 100" strokeDashoffset="-59" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-red-500" strokeWidth="7" strokeDasharray="12, 100" strokeDashoffset="-78" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-purple-500" strokeWidth="7" strokeDasharray="6, 100" strokeDashoffset="-90" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-slate-400" strokeWidth="7" strokeDasharray="3, 100" strokeDashoffset="-96" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                 </svg>
                 <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="text-2xl font-black text-[#0B2550] leading-none">64</span>
                    <span className="text-[9px] font-bold text-slate-500 mt-1">Total Invoices</span>
                 </div>
              </div>
              
              <div className="space-y-3 flex-1">
                 {[
                    { label: 'Paid', num: '38', pct: '(59%)', color: 'bg-emerald-500' },
                    { label: 'Pending', num: '12', pct: '(19%)', color: 'bg-amber-500' },
                    { label: 'Overdue', num: '8', pct: '(12%)', color: 'bg-red-500' },
                    { label: 'In Dispute', num: '4', pct: '(6%)', color: 'bg-purple-500' },
                    { label: 'Draft', num: '2', pct: '(3%)', color: 'bg-slate-400' },
                 ].map((item, i) => (
                    <div key={i} className="flex items-center justify-between">
                       <div className="flex items-center gap-2"><span className={`w-2.5 h-2.5 rounded-full ${item.color}`}></span><span className="text-[10px] font-bold text-slate-700">{item.label}</span></div>
                       <span className="text-[10px] font-black text-[#0B2550]">{item.num} <span className="text-slate-400">{item.pct}</span></span>
                    </div>
                 ))}
              </div>
           </div>
        </div>

        {/* Upcoming Payments */}
        <div className="col-span-6 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📅</span> Upcoming Payments</h3>
              <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Due Date</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Supplier</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Amount (USD)</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Status</th>
                    </tr>
                 </thead>
                 <tbody className="text-[11px] font-semibold text-slate-700">
                    {[
                       { date: 'Aug 28, 2025', sup: 'EuroPack Solutions', amt: '12,500', st: 'Due in 3 days', stColor: 'text-amber-600 bg-amber-50 border-amber-100' },
                       { date: 'Aug 30, 2025', sup: 'TransLogistics', amt: '8,200', st: 'Due in 5 days', stColor: 'text-amber-600 bg-amber-50 border-amber-100' },
                       { date: 'Sep 02, 2025', sup: 'Global Metals Inc.', amt: '15,000', st: 'Due in 8 days', stColor: 'text-blue-600 bg-blue-50 border-blue-100' },
                       { date: 'Sep 05, 2025', sup: 'AgriFoods Co.', amt: '6,800', st: 'Due in 11 days', stColor: 'text-blue-600 bg-blue-50 border-blue-100' },
                       { date: 'Sep 10, 2025', sup: 'Delta Electronics', amt: '9,400', st: 'Due in 16 days', stColor: 'text-slate-600 bg-slate-50 border-slate-200' },
                    ].map((item, i) => (
                       <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                          <td className="py-2.5 text-slate-500">{item.date}</td>
                          <td className="py-2.5 text-[#0B2550] font-bold">{item.sup}</td>
                          <td className="py-2.5 text-right font-mono font-black text-[#0B2550]">{item.amt}</td>
                          <td className="py-2.5 text-center"><span className={`inline-flex items-center px-2 py-0.5 rounded text-[9px] font-bold border ${item.stColor}`}>{item.st}</span></td>
                       </tr>
                    ))}
                 </tbody>
              </table>
           </div>
        </div>

        {/* Payment Method Mix */}
        <div className="col-span-3 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">💳</span> Payment Method Mix</h3>
           
           <div className="flex items-center justify-center gap-4 mt-2">
              <div className="relative w-32 h-32 shrink-0">
                 <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                    <path className="text-blue-500" strokeWidth="7" strokeDasharray="62, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-green-500" strokeWidth="7" strokeDasharray="18, 100" strokeDashoffset="-62" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-amber-500" strokeWidth="7" strokeDasharray="10, 100" strokeDashoffset="-80" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-purple-500" strokeWidth="7" strokeDasharray="6, 100" strokeDashoffset="-90" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-slate-400" strokeWidth="7" strokeDasharray="4, 100" strokeDashoffset="-96" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                 </svg>
                 <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="text-[13px] font-black text-[#0B2550] leading-none">$ 1,76,200</span>
                    <span className="text-[8px] font-bold text-slate-500 mt-1">Payments Made</span>
                 </div>
              </div>
              
              <div className="space-y-3 flex-1">
                 {[
                    { label: 'Bank Transfer', val: '62%', color: 'bg-blue-500' },
                    { label: 'Credit Card', val: '18%', color: 'bg-green-500' },
                    { label: 'Letter of Credit', val: '10%', color: 'bg-amber-500' },
                    { label: 'Digital Wallet', val: '6%', color: 'bg-purple-500' },
                    { label: 'Other', val: '4%', color: 'bg-slate-400' },
                 ].map((item, i) => (
                    <div key={i} className="flex items-center justify-between">
                       <div className="flex items-center gap-2"><span className={`w-2 h-2 rounded-full ${item.color}`}></span><span className="text-[10px] font-bold text-slate-700">{item.label}</span></div>
                       <span className="text-[10px] font-black text-[#0B2550]">{item.val}</span>
                    </div>
                 ))}
              </div>
           </div>
        </div>
      </div>

      {/* Main Charts Row 3 */}
      <div className="grid grid-cols-12 gap-4">
        {/* Key Insights */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">💡</span> Key Insights</h3>
           
           <div className="flex-1 space-y-4">
              <div className="flex gap-3">
                 <div className="text-emerald-500 mt-0.5 text-lg font-bold leading-none">↗</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Total spend increased by 12% due to higher raw material costs.</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-red-500 mt-0.5 text-sm font-bold leading-none">⚠️</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">8 invoices are overdue. Follow up with suppliers to avoid disruptions.</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-blue-500 mt-0.5 text-lg font-bold leading-none">🪙</div>
                 <p className="text-[11px] font-semibold text-[#0B2550] leading-relaxed">Cost savings improved by 24% through better supplier negotiation.</p>
              </div>
           </div>
        </div>

        {/* Outstanding Payables by Aging */}
        <div className="col-span-5 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-6 text-sm"><span className="text-blue-600">📊</span> Outstanding Payables by Aging</h3>
           
           <div className="h-32 flex items-end justify-between relative px-8 mt-4">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-8">
                 <span>40K</span><span>30K</span><span>20K</span><span>10K</span><span>0</span>
              </div>
              <div className="absolute -left-12 top-1/2 -rotate-90 text-[9px] font-bold text-slate-400">Amount (USD)</div>
              
              {/* Bars */}
              <div className="relative w-full h-full flex justify-between items-end pb-0 px-4">
                 {[
                    { label: '0-30 days', val: 18600, h: 46.5, color: 'bg-blue-500' },
                    { label: '31-60 days', val: 22400, h: 56, color: 'bg-amber-500' },
                    { label: '61-90 days', val: 19200, h: 48, color: 'bg-red-500' },
                    { label: '> 90 days', val: 12100, h: 30.25, color: 'bg-purple-500' },
                 ].map((d, i) => (
                    <div key={i} className="flex flex-col justify-end items-center h-full w-12 group relative">
                       <div className={`w-10 ${d.color} rounded-t-sm transition-all`} style={{height: `${d.h}%`}}></div>
                       <span className="absolute -top-5 text-[10px] font-black text-[#0B2550]">{d.val.toLocaleString()}</span>
                       <span className="absolute -bottom-6 text-[10px] font-bold text-slate-500 whitespace-nowrap">{d.label}</span>
                    </div>
                 ))}
              </div>
           </div>
        </div>

        {/* Quick Actions */}
        <div className="col-span-3 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">⚡</span> Quick Actions</h3>
           
           <div className="grid grid-cols-2 gap-3 mt-4">
              <button className="flex flex-col items-center justify-center gap-2 p-4 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-xl">📤</span>
                 <span className="text-[10px] font-bold text-blue-700">Upload Invoice</span>
              </button>
              <button className="flex flex-col items-center justify-center gap-2 p-4 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-xl">💳</span>
                 <span className="text-[10px] font-bold text-blue-700">Make a Payment</span>
              </button>
              <button className="flex flex-col items-center justify-center gap-2 p-4 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-xl">🔄</span>
                 <span className="text-[10px] font-bold text-blue-700 text-center leading-tight">Reconcile<br/>Transactions</span>
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
