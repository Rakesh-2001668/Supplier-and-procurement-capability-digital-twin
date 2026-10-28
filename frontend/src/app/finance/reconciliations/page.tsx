'use client';

import React from 'react';
import Link from 'next/link';

export default function ReconciliationsPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/finance/dashboard" className="hover:text-blue-600">Finance & Payments</Link> 
            <span className="text-slate-300">›</span> Reconciliations
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Reconciliations</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Match and reconcile invoices, payments and bank transactions to ensure financial accuracy.</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 flex items-center gap-2">
            📅 Aug 1, 2025 - Aug 31, 2025
          </div>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            + Start Reconciliation
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-4">
        {/* Total Transactions */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xl shrink-0">✅</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Total Transactions</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">1,248</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 12% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
           </div>
        </div>

        {/* Matched */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl shrink-0">🔗</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Matched</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">1,102</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 15% <span className="text-slate-400 font-semibold uppercase tracking-wider">(88%)</span></div>
           </div>
        </div>

        {/* Unmatched */}
        <div className="bg-white rounded-xl border border-amber-50 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 text-xl shrink-0">🕒</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Unmatched</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">96</div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ 5% <span className="text-slate-400 font-semibold uppercase tracking-wider">(8%)</span></div>
           </div>
        </div>

        {/* Exceptions */}
        <div className="bg-white rounded-xl border border-red-50 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center text-red-600 text-xl shrink-0">⚠️</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Exceptions</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">50</div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ 25% <span className="text-slate-400 font-semibold uppercase tracking-wider">(4%)</span></div>
           </div>
        </div>

        {/* Avg. Reconciliation Time */}
        <div className="bg-white rounded-xl border border-purple-50 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-purple-100 flex items-center justify-center text-purple-600 text-xl shrink-0">📅</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Avg. Reconciliation Time</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">1.8 days</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↓ 30% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
           </div>
        </div>
      </div>

      {/* Main Charts Row 1 */}
      <div className="grid grid-cols-12 gap-4">
        {/* Reconciliation Trend */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📊</span> Reconciliation Trend</h3>
              <select className="text-[10px] font-bold text-slate-500 border border-slate-200 rounded px-2 py-1 outline-none bg-transparent cursor-pointer">
                 <option>Last 6 Months</option>
              </select>
           </div>
           
           <div className="h-44 flex items-end justify-between relative px-2 mb-2">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              
              <div className="absolute inset-0 flex flex-col justify-between">
                 {[...Array(7)].map((_, i) => (
                    <div key={i} className="w-full border-t border-slate-100" style={{height: '1px'}}></div>
                 ))}
              </div>

              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-6">
                 <span>300</span><span>250</span><span>200</span><span>150</span><span>100</span><span>50</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[9px] font-bold text-slate-400 -mb-5 px-6">
                 <span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span>
              </div>
              
              <div className="relative w-full h-full flex justify-between items-end pb-0 px-4 z-10">
                 {[
                    { m: 'Mar', c1: 45, c2: 15, c3: 5 },
                    { m: 'Apr', c1: 50, c2: 18, c3: 8 },
                    { m: 'May', c1: 60, c2: 20, c3: 7 },
                    { m: 'Jun', c1: 65, c2: 22, c3: 10 },
                    { m: 'Jul', c1: 70, c2: 25, c3: 12 },
                    { m: 'Aug', c1: 75, c2: 20, c3: 15 },
                 ].map((d, i) => (
                    <div key={i} className="flex flex-col justify-end items-center h-full w-8">
                       <div className="w-6 bg-red-500 rounded-t-sm" style={{height: `${d.c3}%`}}></div>
                       <div className="w-6 bg-amber-500" style={{height: `${d.c2}%`}}></div>
                       <div className="w-6 bg-emerald-500" style={{height: `${d.c1}%`}}></div>
                    </div>
                 ))}
              </div>
           </div>
           
           <div className="flex items-center justify-center gap-6 text-[10px] font-bold text-slate-600 mt-6">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> Matched</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Unmatched</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> Exceptions</span>
           </div>
        </div>

        {/* Match Status Distribution */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">📄</span> Match Status Distribution</h3>
           
           <div className="flex items-center justify-center gap-6 mt-2">
              <div className="relative w-36 h-36 shrink-0">
                 <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                    <path className="text-emerald-500" strokeWidth="7" strokeDasharray="88, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-amber-500" strokeWidth="7" strokeDasharray="8, 100" strokeDashoffset="-88" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-red-500" strokeWidth="7" strokeDasharray="4, 100" strokeDashoffset="-96" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                 </svg>
                 <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="text-2xl font-black text-[#0B2550] leading-tight">1,248</span>
                    <span className="text-[9px] font-bold text-slate-500 mt-1 leading-tight">Transactions</span>
                 </div>
              </div>
              
              <div className="space-y-4 flex-1">
                 {[
                    { label: 'Matched', pct: '88%', color: 'bg-emerald-500' },
                    { label: 'Unmatched', pct: '8%', color: 'bg-amber-500' },
                    { label: 'Exceptions', pct: '4%', color: 'bg-red-500' },
                 ].map((item, i) => (
                    <div key={i} className="flex items-center justify-between">
                       <div className="flex items-center gap-2"><span className={`w-3 h-3 rounded-full ${item.color}`}></span><span className="text-xs font-bold text-slate-700">{item.label}</span></div>
                       <span className="text-sm font-black text-[#0B2550]">{item.pct}</span>
                    </div>
                 ))}
              </div>
           </div>
        </div>

        {/* Reconciliation by Account */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-6">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">🏦</span> Reconciliation by Account</h3>
              <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="space-y-4 mt-2">
              {[
                 { label: 'Operating Account', val: '420', w1: 75, w2: 15, w3: 10 },
                 { label: 'AP Payments', val: '312', w1: 85, w2: 10, w3: 5 },
                 { label: 'Supplier Advances', val: '208', w1: 65, w2: 25, w3: 10 },
                 { label: 'Tax Payments', val: '156', w1: 90, w2: 8, w3: 2 },
                 { label: 'Payroll', val: '98', w1: 95, w2: 5, w3: 0 },
                 { label: 'Other', val: '54', w1: 70, w2: 20, w3: 10 },
              ].map((item, i) => (
                 <div key={i} className="flex items-center justify-between gap-4">
                    <span className="text-[10px] font-bold text-[#0B2550] w-28 truncate">{item.label}</span>
                    <div className="flex-1 h-3 bg-slate-100 rounded-sm flex overflow-hidden">
                       <div className={`h-full bg-emerald-500`} style={{ width: `${item.w1}%` }}></div>
                       <div className={`h-full bg-amber-500`} style={{ width: `${item.w2}%` }}></div>
                       <div className={`h-full bg-red-500`} style={{ width: `${item.w3}%` }}></div>
                    </div>
                    <span className="text-[11px] font-black text-blue-600 w-8 text-right">{item.val}</span>
                 </div>
              ))}
           </div>
           <div className="flex items-center justify-center gap-6 text-[9px] font-bold text-slate-500 mt-4">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> Matched</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Unmatched</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> Exceptions</span>
           </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex gap-6 h-[600px]">
         {/* Left Side: Table */}
         <div className="flex-1 flex flex-col min-w-[800px]">
            {/* Filters */}
            <div className="flex items-center gap-2 mb-4">
               <select className="border border-slate-200 bg-white rounded-lg px-2 py-2 text-[10px] font-bold text-slate-700 outline-none w-28 shadow-sm">
                  <option>All Accounts</option>
               </select>
               <select className="border border-slate-200 bg-white rounded-lg px-2 py-2 text-[10px] font-bold text-slate-700 outline-none w-32 shadow-sm">
                  <option>All Transaction Types</option>
               </select>
               <select className="border border-slate-200 bg-white rounded-lg px-2 py-2 text-[10px] font-bold text-slate-700 outline-none w-24 shadow-sm">
                  <option>All Status</option>
               </select>
               <select className="border border-slate-200 bg-white rounded-lg px-2 py-2 text-[10px] font-bold text-slate-700 outline-none w-28 shadow-sm">
                  <option>All Suppliers</option>
               </select>
               <div className="border border-slate-200 bg-white rounded-lg px-2 py-2 text-[10px] font-bold text-slate-700 flex items-center gap-1 shadow-sm shrink-0">
                  📅 Aug 1, 2025 - Aug 31, 2025
               </div>
               <div className="flex-1 relative shadow-sm rounded-lg min-w-[150px]">
                  <span className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400 text-xs">🔍</span>
                  <input type="text" placeholder="Search transactions..." className="w-full border border-slate-200 bg-white rounded-lg pl-7 pr-2 py-2 text-[10px] font-medium text-slate-700 outline-none" />
               </div>
               <button className="border border-slate-200 text-slate-600 bg-white px-2 py-2 rounded-lg font-bold text-[10px] hover:bg-slate-50 flex items-center gap-1 shadow-sm shrink-0">
                  <span>⧨</span> Filters
               </button>
               <button className="border border-slate-200 text-slate-600 bg-white px-2 py-2 rounded-lg font-bold text-[10px] hover:bg-slate-50 flex items-center gap-1 shadow-sm shrink-0">
                  <span>📥</span> Export
               </button>
            </div>

            {/* Table Container */}
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col flex-1 overflow-hidden">
               <div className="flex-1 overflow-auto">
                  <table className="w-full text-left border-collapse min-w-[800px]">
                     <thead className="sticky top-0 bg-white shadow-sm z-10">
                        <tr className="border-b border-slate-100 bg-slate-50/50">
                           <th className="py-3 px-3 w-8"><input type="checkbox" className="rounded border-slate-300" /></th>
                           <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Date</th>
                           <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Reference</th>
                           <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Type</th>
                           <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Description</th>
                           <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Supplier/Counterparty</th>
                           <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Amount (USD)</th>
                           <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Match Status</th>
                           <th className="py-3 px-3 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Actions</th>
                        </tr>
                     </thead>
                     <tbody className="text-[11px] font-semibold text-slate-700">
                        {[
                           { date: 'Aug 31, 2025', ref: 'TXN-2025-0831', type: 'Bank Transaction', desc: 'ACH Payment', sup: 'Global Metals Inc.', amt: '12,500', st: 'Matched', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { date: 'Aug 30, 2025', ref: 'INV-2025-1120', type: 'Invoice', desc: 'Raw material supply', sup: 'EuroPack Solutions', amt: '18,200', st: 'Matched', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { date: 'Aug 29, 2025', ref: 'PAY-2025-0841', type: 'Payment', desc: 'Supplier Payment', sup: 'TransLogistics', amt: '8,200', st: 'Matched', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { date: 'Aug 28, 2025', ref: 'TXN-2025-0828', type: 'Bank Transaction', desc: 'Wire Transfer', sup: 'Shenzhen Tech', amt: '24,600', st: 'Unmatched', stColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500', sel: true },
                           { date: 'Aug 27, 2025', ref: 'INV-2025-1119', type: 'Invoice', desc: 'Packaging materials', sup: 'AgriFoods Co.', amt: '6,800', st: 'Matched', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { date: 'Aug 26, 2025', ref: 'TXN-2025-0825', type: 'Bank Transaction', desc: 'Card Payment', sup: 'Delta Electronics', amt: '9,400', st: 'Matched', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { date: 'Aug 25, 2025', ref: 'TXN-2025-0825', type: 'Bank Transaction', desc: 'NEFT Transfer', sup: 'GreenTech Materials', amt: '15,700', st: 'Exception', stColor: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-600' },
                           { date: 'Aug 24, 2025', ref: 'INV-2025-1114', type: 'Invoice', desc: 'Components', sup: 'Nordic Components', amt: '11,300', st: 'Matched', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { date: 'Aug 22, 2025', ref: 'TXN-2025-0822', type: 'Bank Transaction', desc: 'Bank Charges', sup: 'Bank', amt: '120', st: 'Unmatched', stColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500' },
                           { date: 'Aug 20, 2025', ref: 'INV-2025-1112', type: 'Invoice', desc: 'Electronics parts', sup: 'Sunrise Electronics', amt: '7,650', st: 'Matched', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                        ].map((item, i) => (
                           <tr key={i} className={`border-b border-slate-50 hover:bg-slate-50 ${item.sel ? 'bg-amber-50/30' : ''}`}>
                              <td className="py-2.5 px-3"><input type="checkbox" className="rounded border-slate-300" defaultChecked={item.sel} /></td>
                              <td className="py-2.5 px-2 text-slate-500">{item.date}</td>
                              <td className="py-2.5 px-2 font-mono text-blue-600 hover:underline cursor-pointer">{item.ref}</td>
                              <td className="py-2.5 px-2 text-blue-600 font-medium">{item.type}</td>
                              <td className="py-2.5 px-2 text-[#0B2550]">{item.desc}</td>
                              <td className="py-2.5 px-2 text-[#0B2550] font-bold">{item.sup}</td>
                              <td className="py-2.5 px-2 text-right font-mono text-[#0B2550]">{item.amt}</td>
                              <td className="py-2.5 px-2 text-center"><span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-bold border ${item.stColor}`}><span className={`w-1.5 h-1.5 rounded-full ${item.dot}`}></span> {item.st}</span></td>
                              <td className="py-2.5 px-3 text-right flex items-center justify-end gap-2 text-slate-400">
                                 <button className="hover:text-blue-600">...</button>
                              </td>
                           </tr>
                        ))}
                     </tbody>
                  </table>
               </div>
               
               {/* Pagination */}
               <div className="border-t border-slate-200 p-3 flex items-center justify-between text-xs text-slate-500">
                  <div>Showing 1 - 10 of 1,248 transactions</div>
                  <div className="flex items-center gap-2">
                     <button className="w-6 h-6 flex items-center justify-center border border-slate-200 rounded hover:bg-slate-50">‹</button>
                     <button className="w-6 h-6 flex items-center justify-center bg-blue-600 text-white rounded">1</button>
                     <button className="w-6 h-6 flex items-center justify-center hover:bg-slate-50">2</button>
                     <button className="w-6 h-6 flex items-center justify-center hover:bg-slate-50">3</button>
                     <button className="w-6 h-6 flex items-center justify-center hover:bg-slate-50">4</button>
                     <button className="w-6 h-6 flex items-center justify-center hover:bg-slate-50">5</button>
                     <span>...</span>
                     <button className="w-6 h-6 flex items-center justify-center hover:bg-slate-50">125</button>
                     <button className="w-6 h-6 flex items-center justify-center border border-slate-200 rounded hover:bg-slate-50">›</button>
                  </div>
                  <select className="border border-slate-200 rounded px-2 py-1 outline-none bg-transparent">
                     <option>10 per page</option>
                  </select>
               </div>
            </div>
         </div>

         {/* Right Side Panel - Transaction Details */}
         <div className="w-[340px] bg-white rounded-xl border border-slate-200 shadow-lg flex flex-col shrink-0 overflow-hidden relative border-t-4 border-t-amber-500">
            
            <div className="p-4 border-b border-slate-100 flex items-start justify-between">
               <div>
                  <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm mb-1"><span className="text-blue-600">📄</span> Transaction Details</h3>
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold border text-amber-600 bg-amber-50 border-amber-100">
                     <span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Unmatched
                  </span>
               </div>
               <button className="text-slate-400 hover:text-slate-600 text-lg leading-none">×</button>
            </div>
            
            <div className="flex-1 overflow-auto p-4 space-y-4">
               <div className="grid grid-cols-2 gap-y-3 gap-x-2 text-xs">
                  <div className="text-slate-500 font-medium">Reference</div>
                  <div className="font-mono text-[#0B2550] font-bold">TXN-2025-0828</div>
                  
                  <div className="text-slate-500 font-medium">Date</div>
                  <div className="text-[#0B2550]">Aug 28, 2025</div>
                  
                  <div className="text-slate-500 font-medium">Type</div>
                  <div className="text-[#0B2550]">Bank Transaction</div>
                  
                  <div className="text-slate-500 font-medium">Amount (USD)</div>
                  <div className="font-mono text-[#0B2550] font-black">24,600.00</div>
                  
                  <div className="text-slate-500 font-medium">Description</div>
                  <div className="text-[#0B2550]">Wire Transfer</div>
                  
                  <div className="text-slate-500 font-medium">Supplier</div>
                  <div className="text-[#0B2550] font-bold">Shenzhen Tech</div>
                  
                  <div className="text-slate-500 font-medium">Account</div>
                  <div className="text-[#0B2550]">Operating Account</div>
                  
                  <div className="text-slate-500 font-medium">Matched With</div>
                  <div className="text-slate-400">-</div>
               </div>
               
               <div className="pt-4 border-t border-slate-100">
                  <div className="flex items-center justify-between mb-3">
                     <h4 className="font-bold text-[#0B2550] text-sm">Suggested Matches</h4>
                     <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold bg-purple-50 text-purple-600 border border-purple-100">
                        ✨ AI Suggestion
                     </span>
                  </div>
                  
                  <div className="space-y-2">
                     <label className="flex items-start gap-3 p-3 border border-blue-200 bg-blue-50/50 rounded-lg cursor-pointer">
                        <input type="radio" name="match" className="mt-0.5" defaultChecked />
                        <div className="flex-1 text-xs">
                           <div className="flex justify-between font-bold text-[#0B2550] mb-0.5">
                              <span>INV-2025-1117</span>
                              <span className="font-mono">24,600.00</span>
                           </div>
                           <div className="flex justify-between text-slate-500 text-[10px]">
                              <span>Shenzhen Tech</span>
                              <span>Aug 24, 2025</span>
                           </div>
                        </div>
                     </label>
                     
                     <label className="flex items-start gap-3 p-3 border border-slate-200 rounded-lg cursor-pointer hover:bg-slate-50">
                        <input type="radio" name="match" className="mt-0.5" />
                        <div className="flex-1 text-xs">
                           <div className="flex justify-between font-bold text-[#0B2550] mb-0.5">
                              <span>INV-2025-1105</span>
                              <span className="font-mono">24,600.00</span>
                           </div>
                           <div className="flex justify-between text-slate-500 text-[10px]">
                              <span>Shenzhen Tech</span>
                              <span>Aug 20, 2025</span>
                           </div>
                        </div>
                     </label>
                  </div>
               </div>
            </div>
            
            <div className="p-4 border-t border-slate-200 bg-slate-50/50 space-y-3">
               <div className="flex gap-3">
                  <button className="flex-1 bg-blue-600 text-white py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors">
                     Match
                  </button>
                  <button className="flex-1 bg-white border border-slate-200 text-slate-700 py-2 rounded-lg font-bold text-xs shadow-sm hover:bg-slate-50">
                     Mark as Exception
                  </button>
               </div>
               <button className="text-blue-600 text-xs font-bold hover:underline flex items-center gap-1 mx-auto">
                  <span>📝</span> Add Note
               </button>
            </div>
         </div>
      </div>
      
    </div>
  );
}
