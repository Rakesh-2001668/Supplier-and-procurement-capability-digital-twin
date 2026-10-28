'use client';

import React from 'react';
import Link from 'next/link';

export default function FinanceReportsPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/finance/dashboard" className="hover:text-blue-600">Finance & Payments</Link> 
            <span className="text-slate-300">›</span> Reports
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Finance Reports</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Get detailed insights into your financial performance, spending, and cash flow.</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 flex items-center gap-2">
            📅 Apr 1, 2025 - Aug 31, 2025
          </div>
          <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 outline-none shadow-sm cursor-pointer">
             <option>All Entities</option>
          </select>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            + Generate Report
          </button>
          <button className="border border-slate-200 bg-white text-slate-500 px-3 py-2 rounded-lg font-bold text-sm shadow-sm hover:bg-slate-50 transition-colors">
            •••
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        {/* Total Spend */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xl shrink-0">🪙</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Total Spend (YTD)</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">₹ 5,48,20,000</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 12% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last year</span></div>
           </div>
        </div>

        {/* Total Invoices */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl shrink-0">📄</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Total Invoices</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">1,284</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 8% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last year</span></div>
           </div>
        </div>

        {/* Total Payments */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xl shrink-0">💳</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Total Payments</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">₹ 4,96,75,000</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 15% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last year</span></div>
           </div>
        </div>

        {/* Outstanding Payables */}
        <div className="bg-white rounded-xl border border-red-50 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center text-red-600 text-xl shrink-0">🏦</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Outstanding Payables</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">₹ 51,45,000</div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ 10% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last year</span></div>
           </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col overflow-hidden">
         
         {/* Tabs */}
         <div className="flex items-center gap-6 border-b border-slate-200 px-6 pt-4">
            {['Overview', 'Spend Reports', 'Payment Reports', 'Invoice Reports', 'Vendor Reports', 'Tax Reports', 'Custom Reports'].map((tab, i) => (
               <button key={i} className={`pb-3 text-sm font-bold border-b-2 transition-colors ${i === 0 ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
                  {tab}
               </button>
            ))}
         </div>

         <div className="p-6 space-y-6">
            {/* Filters */}
            <div className="flex items-end gap-4">
               <div className="flex flex-col gap-1.5 flex-1">
                  <label className="text-[10px] font-bold text-slate-500">Report Type</label>
                  <select className="border border-slate-200 bg-white rounded-lg px-3 py-2 text-xs font-bold text-slate-700 outline-none w-full shadow-sm">
                     <option>All Reports</option>
                  </select>
               </div>
               <div className="flex flex-col gap-1.5 flex-1">
                  <label className="text-[10px] font-bold text-slate-500">Date Range</label>
                  <div className="border border-slate-200 bg-white rounded-lg px-3 py-2 text-xs font-bold text-slate-700 flex items-center gap-2 shadow-sm w-full">
                     📅 Apr 1, 2025 - Aug 31, 2025
                  </div>
               </div>
               <div className="flex flex-col gap-1.5 flex-1">
                  <label className="text-[10px] font-bold text-slate-500">Entity / Company</label>
                  <select className="border border-slate-200 bg-white rounded-lg px-3 py-2 text-xs font-bold text-slate-700 outline-none w-full shadow-sm">
                     <option>All Entities</option>
                  </select>
               </div>
               <div className="flex flex-col gap-1.5 flex-1">
                  <label className="text-[10px] font-bold text-slate-500">Currency</label>
                  <select className="border border-slate-200 bg-white rounded-lg px-3 py-2 text-xs font-bold text-slate-700 outline-none w-full shadow-sm">
                     <option>INR (₹)</option>
                  </select>
               </div>
               <div className="flex items-center gap-2">
                  <button className="bg-blue-600 text-white px-6 py-2 rounded-lg font-bold text-xs shadow-md hover:bg-blue-700 transition-colors">
                     Apply
                  </button>
                  <button className="border border-slate-200 bg-white text-slate-600 px-4 py-2 rounded-lg font-bold text-xs shadow-sm hover:bg-slate-50 transition-colors">
                     Reset
                  </button>
               </div>
            </div>

            {/* Charts Row */}
            <div className="grid grid-cols-12 gap-6">
               
               {/* Monthly Spend vs Payments */}
               <div className="col-span-5 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
                  <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📊</span> Monthly Spend vs Payments</h3>
                  
                  <div className="flex items-center justify-center gap-6 text-[10px] font-bold text-slate-600 mb-6 mt-4">
                     <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Total Spend</span>
                     <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> Total Payments</span>
                  </div>
                  
                  <div className="h-44 flex items-end justify-between relative px-2 mb-2 w-full">
                     <div className="absolute inset-0 border-b border-l border-slate-200"></div>
                     <div className="absolute inset-0 flex flex-col justify-between">
                        {[...Array(5)].map((_, i) => (
                           <div key={i} className="w-full border-t border-slate-100" style={{height: '1px'}}></div>
                        ))}
                     </div>
                     <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-8">
                        <span>2Cr</span><span>1.5Cr</span><span>1Cr</span><span>50L</span><span>0</span>
                     </div>
                     <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[9px] font-bold text-slate-400 -mb-5 px-6">
                        <span>Apr 2025</span><span>May 2025</span><span>Jun 2025</span><span>Jul 2025</span><span>Aug 2025</span>
                     </div>
                     
                     <div className="relative w-full h-full flex justify-between items-end pb-0 px-4 z-10">
                        {[
                           { m: 'Apr', s: 80, p: 65 },
                           { m: 'May', s: 75, p: 60 },
                           { m: 'Jun', s: 65, p: 50 },
                           { m: 'Jul', s: 70, p: 70 },
                           { m: 'Aug', s: 75, p: 60 },
                        ].map((d, i) => (
                           <div key={i} className="flex items-end h-full w-12 gap-1.5">
                              <div className="w-1/2 bg-blue-500 rounded-t-sm" style={{height: `${d.s}%`}}></div>
                              <div className="w-1/2 bg-emerald-500 rounded-t-sm" style={{height: `${d.p}%`}}></div>
                           </div>
                        ))}
                     </div>
                  </div>
               </div>

               {/* Spend by Category */}
               <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
                  <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">🎯</span> Spend by Category</h3>
                  
                  <div className="flex items-center justify-center gap-6 mt-6">
                     <div className="relative w-40 h-40 shrink-0">
                        <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                           <path className="text-blue-500" strokeWidth="7" strokeDasharray="28, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                           <path className="text-emerald-500" strokeWidth="7" strokeDasharray="18, 100" strokeDashoffset="-28" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                           <path className="text-purple-500" strokeWidth="7" strokeDasharray="15, 100" strokeDashoffset="-46" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                           <path className="text-indigo-400" strokeWidth="7" strokeDasharray="12, 100" strokeDashoffset="-61" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                           <path className="text-pink-500" strokeWidth="7" strokeDasharray="10, 100" strokeDashoffset="-73" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                           <path className="text-amber-500" strokeWidth="7" strokeDasharray="8, 100" strokeDashoffset="-83" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                           <path className="text-red-500" strokeWidth="7" strokeDasharray="9, 100" strokeDashoffset="-91" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                        </svg>
                        <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                           <span className="text-[15px] font-black text-[#0B2550] leading-tight">₹ 5.48 Cr</span>
                           <span className="text-[9px] font-bold text-slate-500 mt-0.5">Total Spend</span>
                        </div>
                     </div>
                     
                     <div className="space-y-1.5 flex-1">
                        {[
                           { label: 'IT Equipment', pct: '28%', color: 'bg-blue-500' },
                           { label: 'Office Supplies', pct: '18%', color: 'bg-emerald-500' },
                           { label: 'Services', pct: '15%', color: 'bg-purple-500' },
                           { label: 'Infrastructure', pct: '12%', color: 'bg-indigo-400' },
                           { label: 'Travel & Expense', pct: '10%', color: 'bg-pink-500' },
                           { label: 'Maintenance', pct: '8%', color: 'bg-amber-500' },
                           { label: 'Others', pct: '9%', color: 'bg-red-500' },
                        ].map((item, i) => (
                           <div key={i} className="flex items-center justify-between">
                              <div className="flex items-center gap-2"><span className={`w-2 h-2 rounded-full ${item.color}`}></span><span className="text-[10px] font-bold text-slate-700">{item.label}</span></div>
                              <span className="text-[10px] font-black text-[#0B2550]">{item.pct}</span>
                           </div>
                        ))}
                     </div>
                  </div>
               </div>

               {/* Right Panel Grid */}
               <div className="col-span-3 space-y-6">
                  {/* Top Vendors by Spend */}
                  <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
                     <div className="flex items-center justify-between mb-4">
                        <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">🏢</span> Top Vendors by Spend</h3>
                        <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
                     </div>
                     
                     <div className="space-y-3">
                        {[
                           { no: '1', color: 'bg-pink-100 text-pink-600', name: 'Tech Solutions Pvt Ltd', val: '₹ 1,28,50,000' },
                           { no: '2', color: 'bg-emerald-100 text-emerald-600', name: 'OfficeMart India', val: '₹ 78,20,000' },
                           { no: '3', color: 'bg-blue-100 text-blue-600', name: 'Global Services Ltd', val: '₹ 62,40,000' },
                           { no: '4', color: 'bg-purple-100 text-purple-600', name: 'InfraCore Systems', val: '₹ 45,60,000' },
                           { no: '5', color: 'bg-amber-100 text-amber-600', name: 'Travel Hub Pvt Ltd', val: '₹ 32,10,000' },
                        ].map((v, i) => (
                           <div key={i} className="flex items-center justify-between gap-2">
                              <div className="flex items-center gap-2">
                                 <div className={`w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold ${v.color}`}>{v.no}</div>
                                 <span className="text-[10px] font-bold text-[#0B2550] truncate w-28">{v.name}</span>
                              </div>
                              <span className="text-[10px] font-mono font-medium text-slate-500">{v.val}</span>
                           </div>
                        ))}
                     </div>
                  </div>

                  {/* Quick Actions */}
                  <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
                     <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-3 text-sm"><span className="text-blue-600">⚡</span> Quick Actions</h3>
                     <div className="grid grid-cols-2 gap-2">
                        <button className="flex items-center gap-1.5 p-2 border border-slate-200 rounded-lg hover:bg-slate-50 text-left">
                           <span className="text-blue-600 text-xs">📊</span>
                           <span className="text-[9px] font-bold text-slate-700">Generate Report</span>
                        </button>
                        <button className="flex items-center gap-1.5 p-2 border border-slate-200 rounded-lg hover:bg-slate-50 text-left">
                           <span className="text-blue-600 text-xs">📅</span>
                           <span className="text-[9px] font-bold text-slate-700">Schedule Report</span>
                        </button>
                        <button className="flex items-center gap-1.5 p-2 border border-slate-200 rounded-lg hover:bg-slate-50 text-left">
                           <span className="text-blue-600 text-xs">📥</span>
                           <span className="text-[9px] font-bold text-slate-700">Export Data</span>
                        </button>
                        <button className="flex items-center gap-1.5 p-2 border border-slate-200 rounded-lg hover:bg-slate-50 text-left">
                           <span className="text-blue-600 text-xs">⚙️</span>
                           <span className="text-[9px] font-bold text-slate-700">Custom Report</span>
                        </button>
                     </div>
                  </div>
               </div>
            </div>

            {/* Reports Table */}
            <div>
               <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">📄</span> Finance Reports</h3>
               <div className="overflow-x-auto rounded-lg border border-slate-200">
                  <table className="w-full text-left border-collapse">
                     <thead>
                        <tr className="border-b border-slate-100 bg-slate-50">
                           <th className="py-2.5 px-4 w-10"><input type="checkbox" className="rounded border-slate-300" /></th>
                           <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">#</th>
                           <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Report Name</th>
                           <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Report Type</th>
                           <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Period</th>
                           <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Generated On</th>
                           <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Generated By</th>
                           <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Status</th>
                           <th className="py-2.5 px-4 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Actions</th>
                        </tr>
                     </thead>
                     <tbody className="text-[11px] font-semibold text-slate-700">
                        {[
                           { no: '1', name: 'Monthly Spend Report', type: 'Spend Report', per: 'Aug 2025', g_on: 'Aug 31, 2025 10:24 AM', g_by: 'Alex Sharma', st: 'Completed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { no: '2', name: 'Vendor Payment Report', type: 'Payment Report', per: 'Aug 2025', g_on: 'Aug 31, 2025 09:18 AM', g_by: 'Priya Rao', st: 'Completed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { no: '3', name: 'Invoice Aging Report', type: 'Invoice Report', per: 'Aug 2025', g_on: 'Aug 30, 2025 04:12 PM', g_by: 'Neha Gupta', st: 'Completed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { no: '4', name: 'Tax Summary Report', type: 'Tax Report', per: 'Q2 2025', g_on: 'Aug 30, 2025 11:03 AM', g_by: 'Ravi Kumar', st: 'Completed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { no: '5', name: 'Cost Center Wise Report', type: 'Custom Report', per: 'Aug 2025', g_on: 'Aug 29, 2025 03:20 PM', g_by: 'Karthik T', st: 'Completed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { no: '6', name: 'Budget vs Actual Report', type: 'Budget Report', per: 'Aug 2025', g_on: 'Aug 28, 2025 01:45 PM', g_by: 'Sneha Patel', st: 'Completed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                           { no: '7', name: 'Cash Flow Statement', type: 'Financial Report', per: 'Q2 2025', g_on: 'Aug 27, 2025 09:10 AM', g_by: 'Arun Mehta', st: 'Completed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                        ].map((item, i) => (
                           <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                              <td className="py-2.5 px-4"><input type="checkbox" className="rounded border-slate-300" /></td>
                              <td className="py-2.5 px-2 text-slate-500">{item.no}</td>
                              <td className="py-2.5 px-2 font-bold text-blue-600 hover:underline cursor-pointer">{item.name}</td>
                              <td className="py-2.5 px-2 text-slate-600">{item.type}</td>
                              <td className="py-2.5 px-2 text-slate-500">{item.per}</td>
                              <td className="py-2.5 px-2 text-slate-500">{item.g_on}</td>
                              <td className="py-2.5 px-2 text-[#0B2550]">{item.g_by}</td>
                              <td className="py-2.5 px-2"><span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold border ${item.stColor}`}><span className={`w-1.5 h-1.5 rounded-full ${item.dot}`}></span> {item.st}</span></td>
                              <td className="py-2.5 px-4 text-right flex items-center justify-end gap-3 text-blue-600 font-bold text-[10px]">
                                 <button className="hover:underline">View</button>
                                 <button className="text-slate-400 hover:text-[#0B2550] text-lg leading-none">⋮</button>
                              </td>
                           </tr>
                        ))}
                     </tbody>
                  </table>
               </div>
               
               {/* Pagination */}
               <div className="pt-3 flex items-center justify-between text-[10px] font-bold text-slate-500">
                  <div>Showing 1 - 7 of 28 reports</div>
                  <div className="flex items-center gap-1.5">
                     <button className="w-6 h-6 flex items-center justify-center border border-slate-200 rounded hover:bg-slate-50">‹</button>
                     <button className="w-6 h-6 flex items-center justify-center border border-slate-200 rounded hover:bg-slate-50">1</button>
                     <button className="w-6 h-6 flex items-center justify-center bg-blue-600 text-white rounded">2</button>
                     <button className="w-6 h-6 flex items-center justify-center hover:bg-slate-50">3</button>
                     <button className="w-6 h-6 flex items-center justify-center hover:bg-slate-50">4</button>
                     <span>...</span>
                     <button className="w-6 h-6 flex items-center justify-center hover:bg-slate-50">28</button>
                     <button className="w-6 h-6 flex items-center justify-center border border-slate-200 rounded hover:bg-slate-50">›</button>
                  </div>
                  <div className="flex items-center gap-2">
                     <span>Rows per page</span>
                     <select className="border border-slate-200 rounded px-2 py-1 outline-none bg-transparent font-bold">
                        <option>10</option>
                     </select>
                  </div>
               </div>
            </div>

         </div>
      </div>
      
    </div>
  );
}
