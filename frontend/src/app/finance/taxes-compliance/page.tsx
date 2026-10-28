'use client';

import React from 'react';
import Link from 'next/link';

export default function TaxesCompliancePage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/finance/dashboard" className="hover:text-blue-600">Finance & Payments</Link> 
            <span className="text-slate-300">›</span> Taxes & Compliance
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Taxes & Compliance</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Stay compliant with tax regulations, statutory filings, and regulatory requirements.</p>
        </div>
        <div className="flex items-center gap-3">
          <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 outline-none shadow-sm cursor-pointer">
             <option>📅 FY 2025-26</option>
          </select>
          <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 outline-none shadow-sm cursor-pointer">
             <option>All Entities</option>
          </select>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            📥 Upload Document
          </button>
          <button className="border border-slate-200 bg-white text-slate-500 px-3 py-2 rounded-lg font-bold text-sm shadow-sm hover:bg-slate-50 transition-colors">
            •••
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        {/* Total Tax Liability */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xl shrink-0">📄</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Total Tax Liability (YTD)</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">₹ 28,45,000</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 12% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last year</span></div>
           </div>
        </div>

        {/* Taxes Paid */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl shrink-0">✓</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Taxes Paid (YTD)</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">₹ 22,80,000</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 15% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last year</span></div>
           </div>
        </div>

        {/* Upcoming Due */}
        <div className="bg-white rounded-xl border border-amber-50 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 text-xl shrink-0">🕒</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Upcoming Due (Next 30 Days)</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">6</div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ 2 <span className="text-slate-400 font-semibold uppercase tracking-wider">filings pending</span></div>
           </div>
        </div>

        {/* Overdue Filings */}
        <div className="bg-white rounded-xl border border-red-50 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center text-red-600 text-xl shrink-0">⚠️</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Overdue Filings</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">2</div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ 1 <span className="text-slate-400 font-semibold uppercase tracking-wider">requires immediate action</span></div>
           </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex gap-6 h-[720px]">
         {/* Left Side */}
         <div className="flex-1 flex flex-col min-w-[800px] bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            
            {/* Tabs */}
            <div className="flex items-center gap-6 border-b border-slate-200 px-6 pt-4">
               {['Tax Filings', 'Compliance Calendar', 'Statutory Registers', 'Reports', 'Settings'].map((tab, i) => (
                  <button key={i} className={`pb-3 text-sm font-bold border-b-2 transition-colors ${i === 0 ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
                     {tab}
                  </button>
               ))}
            </div>

            <div className="flex-1 overflow-auto p-6 space-y-6 flex flex-col">
               
               {/* Filters */}
               <div className="flex items-center gap-3">
                  <div className="font-bold text-[#0B2550] flex items-center gap-2 text-sm mr-auto"><span className="text-blue-600">📄</span> Tax Filings</div>
                  <select className="border border-slate-200 bg-white rounded-lg px-3 py-2 text-[10px] font-bold text-slate-700 outline-none w-36 shadow-sm">
                     <option>All Tax Types</option>
                  </select>
                  <select className="border border-slate-200 bg-white rounded-lg px-3 py-2 text-[10px] font-bold text-slate-700 outline-none w-32 shadow-sm">
                     <option>All Status</option>
                  </select>
                  <div className="relative shadow-sm rounded-lg w-48">
                     <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-xs">🔍</span>
                     <input type="text" placeholder="Search filings..." className="w-full border border-slate-200 bg-slate-50 rounded-lg pl-8 pr-2 py-2 text-[10px] font-medium text-slate-700 outline-none" />
                  </div>
               </div>

               {/* Table Container */}
               <div className="flex-1 border border-slate-200 rounded-lg overflow-hidden flex flex-col">
                  <div className="flex-1 overflow-auto">
                     <table className="w-full text-left border-collapse min-w-[800px]">
                        <thead className="sticky top-0 bg-slate-50 shadow-sm z-10">
                           <tr className="border-b border-slate-100">
                              <th className="py-2.5 px-4 w-10"><input type="checkbox" className="rounded border-slate-300" /></th>
                              <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Filing Type</th>
                              <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Period</th>
                              <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Due Date</th>
                              <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Filed Date</th>
                              <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Amount (₹)</th>
                              <th className="py-2.5 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Status</th>
                              <th className="py-2.5 px-4 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Actions</th>
                           </tr>
                        </thead>
                        <tbody className="text-[11px] font-semibold text-slate-700">
                           {[
                              { type: 'GST Return (GSTR-1)', per: 'Jul 2025', due: 'Aug 11, 2025', filed: 'Aug 08, 2025', amt: '12,45,000', st: 'Filed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                              { type: 'GST Return (GSTR-3B)', per: 'Jul 2025', due: 'Aug 20, 2025', filed: 'Aug 20, 2025', amt: '8,32,000', st: 'Filed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                              { type: 'TDS Return (Form 26Q)', per: 'Q2 2025', due: 'Jul 31, 2025', filed: 'Jul 30, 2025', amt: '4,12,000', st: 'Filed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                              { type: 'TCS Return (Form 27EQ)', per: 'Q2 2025', due: 'Jul 15, 2025', filed: 'Jul 14, 2025', amt: '1,25,000', st: 'Filed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                              { type: 'Advance Tax (IT)', per: 'Q2 2025', due: 'Sep 15, 2025', filed: '-', amt: '5,00,000', st: 'Pending', stColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500' },
                              { type: 'Professional Tax', per: 'Jul 2025', due: 'Aug 31, 2025', filed: '-', amt: '45,000', st: 'Overdue', stColor: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-600' },
                              { type: 'PF ECR', per: 'Aug 2025', due: 'Aug 15, 2025', filed: 'Aug 14, 2025', amt: '1,80,000', st: 'Filed', stColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500' },
                              { type: 'ESI Return', per: 'Jul 2025', due: 'Aug 15, 2025', filed: '-', amt: '62,000', st: 'Pending', stColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500' },
                           ].map((item, i) => (
                              <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                                 <td className="py-3 px-4"><input type="checkbox" className="rounded border-slate-300" /></td>
                                 <td className="py-3 px-2 text-[#0B2550]">{item.type}</td>
                                 <td className="py-3 px-2 text-blue-600 font-medium">{item.per}</td>
                                 <td className="py-3 px-2 text-slate-500">{item.due}</td>
                                 <td className="py-3 px-2 text-slate-500">{item.filed}</td>
                                 <td className="py-3 px-2 text-right font-mono text-[#0B2550] font-bold">{item.amt}</td>
                                 <td className="py-3 px-2 text-center"><span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold border ${item.stColor}`}><span className={`w-1.5 h-1.5 rounded-full ${item.dot}`}></span> {item.st}</span></td>
                                 <td className="py-3 px-4 text-right flex items-center justify-end gap-3 text-blue-600">
                                    <button className="hover:text-blue-800 text-sm">👁️</button>
                                    <button className="text-slate-400 hover:text-slate-600 text-lg leading-none">•••</button>
                                 </td>
                              </tr>
                           ))}
                        </tbody>
                     </table>
                  </div>
                  
                  {/* Pagination */}
                  <div className="border-t border-slate-200 p-2.5 flex items-center justify-between text-[10px] font-bold text-slate-500">
                     <div>Showing 1 - 8 of 24 filings</div>
                     <div className="flex items-center gap-1.5">
                        <button className="w-5 h-5 flex items-center justify-center border border-slate-200 rounded hover:bg-slate-50">‹</button>
                        <button className="w-5 h-5 flex items-center justify-center bg-blue-600 text-white rounded">1</button>
                        <button className="w-5 h-5 flex items-center justify-center hover:bg-slate-50">2</button>
                        <button className="w-5 h-5 flex items-center justify-center hover:bg-slate-50">3</button>
                        <button className="w-5 h-5 flex items-center justify-center border border-slate-200 rounded hover:bg-slate-50">›</button>
                     </div>
                     <div className="flex items-center gap-2">
                        <select className="border border-slate-200 rounded px-1.5 py-0.5 outline-none bg-transparent font-bold">
                           <option>10 per page</option>
                        </select>
                     </div>
                  </div>
               </div>
               
               {/* Bottom 2 Cards */}
               <div className="grid grid-cols-2 gap-6 h-48 shrink-0">
                  {/* Compliance Status */}
                  <div className="border border-slate-200 rounded-xl p-5 flex flex-col relative overflow-hidden bg-gradient-to-br from-white to-slate-50/50">
                     <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-3 text-sm"><span className="text-blue-600">📄</span> Compliance Status</h3>
                     <div className="flex-1 flex items-center gap-6">
                        <div className="relative w-28 h-28 shrink-0 ml-2">
                           <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                              <path className="text-emerald-500" strokeWidth="6" strokeDasharray="92, 100" stroke="currentColor" fill="none" d="M18 3.0845 a 14.9155 14.9155 0 0 1 0 29.831 a 14.9155 14.9155 0 0 1 0 -29.831" />
                              <path className="text-red-500" strokeWidth="6" strokeDasharray="4, 100" strokeDashoffset="-92" stroke="currentColor" fill="none" d="M18 3.0845 a 14.9155 14.9155 0 0 1 0 29.831 a 14.9155 14.9155 0 0 1 0 -29.831" />
                              <path className="text-amber-500" strokeWidth="6" strokeDasharray="2, 100" strokeDashoffset="-96" stroke="currentColor" fill="none" d="M18 3.0845 a 14.9155 14.9155 0 0 1 0 29.831 a 14.9155 14.9155 0 0 1 0 -29.831" />
                              <path className="text-slate-300" strokeWidth="6" strokeDasharray="2, 100" strokeDashoffset="-98" stroke="currentColor" fill="none" d="M18 3.0845 a 14.9155 14.9155 0 0 1 0 29.831 a 14.9155 14.9155 0 0 1 0 -29.831" />
                           </svg>
                           <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                              <span className="text-lg font-black text-[#0B2550] leading-none">92%</span>
                              <span className="text-[8px] font-bold text-slate-500 mt-1">Compliant</span>
                           </div>
                        </div>
                        <div className="flex-1 space-y-2.5">
                           <div className="flex items-center justify-between text-[10px] font-bold">
                              <span className="flex items-center gap-1.5 text-slate-600"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> Compliant</span>
                              <span className="text-[#0B2550]">22</span>
                           </div>
                           <div className="flex items-center justify-between text-[10px] font-bold">
                              <span className="flex items-center gap-1.5 text-slate-600"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Pending</span>
                              <span className="text-[#0B2550]">4</span>
                           </div>
                           <div className="flex items-center justify-between text-[10px] font-bold">
                              <span className="flex items-center gap-1.5 text-slate-600"><span className="w-2 h-2 rounded-full bg-red-500"></span> Overdue</span>
                              <span className="text-[#0B2550]">2</span>
                           </div>
                           <div className="flex items-center justify-between text-[10px] font-bold">
                              <span className="flex items-center gap-1.5 text-slate-600"><span className="w-2 h-2 rounded-full bg-slate-400"></span> Not Applicable</span>
                              <span className="text-[#0B2550]">1</span>
                           </div>
                        </div>
                     </div>
                  </div>

                  {/* Recent Notifications */}
                  <div className="border border-slate-200 rounded-xl p-5 flex flex-col relative overflow-hidden bg-gradient-to-br from-white to-slate-50/50">
                     <div className="flex items-center justify-between mb-3">
                        <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📅</span> Recent Notifications</h3>
                        <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
                     </div>
                     <div className="flex-1 space-y-3 overflow-auto pr-2">
                        <div className="flex items-start justify-between gap-4">
                           <div className="flex gap-2">
                              <div className="w-4 h-4 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 font-bold text-[9px] mt-0.5 shrink-0">✓</div>
                              <p className="text-[10px] font-bold text-[#0B2550]">GSTR-1 filed successfully for Jul 2025</p>
                           </div>
                           <span className="text-[9px] text-slate-400 whitespace-nowrap shrink-0">Aug 08, 2025 10:24 AM</span>
                        </div>
                        <div className="flex items-start justify-between gap-4">
                           <div className="flex gap-2">
                              <div className="w-4 h-4 rounded-full bg-red-100 flex items-center justify-center text-red-600 font-bold text-[9px] mt-0.5 shrink-0">!</div>
                              <p className="text-[10px] font-bold text-[#0B2550]">Professional Tax payment overdue</p>
                           </div>
                           <span className="text-[9px] text-slate-400 whitespace-nowrap shrink-0">Aug 01, 2025 09:00 AM</span>
                        </div>
                        <div className="flex items-start justify-between gap-4">
                           <div className="flex gap-2">
                              <div className="w-4 h-4 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-bold text-[9px] mt-0.5 shrink-0">i</div>
                              <p className="text-[10px] font-bold text-[#0B2550]">New GST circular issued by CBIC</p>
                           </div>
                           <span className="text-[9px] text-slate-400 whitespace-nowrap shrink-0">Jul 28, 2025 04:15 PM</span>
                        </div>
                        <div className="flex items-start justify-between gap-4">
                           <div className="flex gap-2">
                              <div className="w-4 h-4 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 font-bold text-[9px] mt-0.5 shrink-0">!</div>
                              <p className="text-[10px] font-bold text-[#0B2550]">TDS return due in 5 days</p>
                           </div>
                           <span className="text-[9px] text-slate-400 whitespace-nowrap shrink-0">Jul 26, 2025 11:30 AM</span>
                        </div>
                     </div>
                  </div>
               </div>

            </div>
         </div>

         {/* Right Side Panel */}
         <div className="w-[320px] flex flex-col gap-6 shrink-0">
            
            {/* Compliance Calendar */}
            <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
               <div className="flex items-center justify-between mb-4">
                  <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📅</span> Compliance Calendar</h3>
                  <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
               </div>
               
               <div className="border border-slate-100 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-4">
                     <button className="text-slate-400 hover:text-blue-600 font-bold">‹</button>
                     <span className="text-xs font-bold text-[#0B2550]">August 2025</span>
                     <button className="text-slate-400 hover:text-blue-600 font-bold">›</button>
                  </div>
                  
                  <div className="grid grid-cols-7 gap-1 text-center mb-2">
                     {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => (
                        <div key={d} className="text-[9px] font-bold text-slate-400">{d}</div>
                     ))}
                  </div>
                  
                  <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-medium text-slate-600">
                     {[
                        { d: '27', out: true }, { d: '28', out: true }, { d: '29', out: true }, { d: '30', out: true }, { d: '31', out: true },
                        { d: '1' }, { d: '2' }, { d: '3' }, { d: '4' }, { d: '5' }, { d: '6' }, { d: '7' },
                        { d: '8', dot: 'emerald' }, { d: '9' }, { d: '10' }, { d: '11', dot: 'emerald' }, { d: '12' }, { d: '13' }, { d: '14', dot: 'emerald' },
                        { d: '15', dot: 'amber' }, { d: '16' }, { d: '17' }, { d: '18' }, { d: '19' }, { d: '20', dot: 'emerald' }, { d: '21' },
                        { d: '22' }, { d: '23' }, { d: '24' }, { d: '25' }, { d: '26' }, { d: '27' }, { d: '28', dot: 'red', active: true },
                        { d: '29' }, { d: '30' }, { d: '31', dot: 'amber' }, { d: '1', out: true }, { d: '2', out: true }
                     ].map((d, i) => (
                        <div key={i} className={`relative flex items-center justify-center h-6 rounded ${d.out ? 'text-slate-300' : ''} ${d.active ? 'bg-blue-50 text-blue-600 font-bold' : 'hover:bg-slate-50'}`}>
                           {d.d}
                           {d.dot && (
                              <div className={`absolute bottom-0.5 w-1 h-1 rounded-full ${d.dot === 'emerald' ? 'bg-emerald-500' : d.dot === 'amber' ? 'bg-amber-500' : 'bg-red-500'}`}></div>
                           )}
                        </div>
                     ))}
                  </div>
               </div>
               
               <div className="flex items-center justify-center gap-3 text-[9px] font-bold text-slate-500 mt-4">
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Filed</span>
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Due Soon</span>
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-red-500"></span> Overdue</span>
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-blue-500"></span> Today</span>
               </div>
            </div>

            {/* Upcoming Deadlines */}
            <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
               <div className="flex items-center justify-between mb-4">
                  <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-red-500">⏰</span> Upcoming Deadlines</h3>
                  <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
               </div>
               
               <div className="space-y-4">
                  {[
                     { m: 'AUG', d: '31', title: 'Professional Tax - Jul 2025', amt: '₹ 45,000', badge: 'Overdue', badgeColor: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-500' },
                     { m: 'SEP', d: '15', title: 'Advance Tax (Q2)', amt: '₹ 5,00,000', badge: 'In 4 days', badgeColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500' },
                     { m: 'SEP', d: '20', title: 'GST Return (GSTR-3B)', amt: '₹ 8,50,000', badge: 'In 9 days', badgeColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500' },
                     { m: 'SEP', d: '30', title: 'PF ECR - Aug 2025', amt: '₹ 1,85,000', badge: 'In 19 days', badgeColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500' },
                  ].map((p, i) => (
                     <div key={i} className="flex gap-3 border-b border-slate-50 pb-3">
                        <div className="flex flex-col items-center justify-center w-9 h-9 rounded bg-slate-50 border border-slate-100 shrink-0">
                           <span className="text-[8px] font-bold text-red-500 leading-none">{p.m}</span>
                           <span className="text-[11px] font-black text-[#0B2550]">{p.d}</span>
                        </div>
                        <div className="flex-1">
                           <div className="flex items-start justify-between gap-1 mb-1">
                              <p className="text-[10px] font-bold text-[#0B2550] leading-tight">{p.title}</p>
                              <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] font-bold border ${p.badgeColor} shrink-0`}>
                                 <span className={`w-1 h-1 rounded-full ${p.dot}`}></span> {p.badge}
                              </span>
                           </div>
                           <p className="text-[10px] font-mono text-slate-500">{p.amt}</p>
                        </div>
                     </div>
                  ))}
               </div>
            </div>

            {/* Quick Actions */}
            <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex-1">
               <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-3 text-sm"><span className="text-blue-600">⚡</span> Quick Actions</h3>
               
               <div className="grid grid-cols-2 gap-2">
                  <button className="flex items-center gap-2 p-2 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors text-left">
                     <span className="text-blue-600 text-xs">📄</span>
                     <span className="text-[9px] font-bold text-slate-700">File GST Return</span>
                  </button>
                  <button className="flex items-center gap-2 p-2 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors text-left">
                     <span className="text-blue-600 text-xs">🏦</span>
                     <span className="text-[9px] font-bold text-slate-700">File TDS Return</span>
                  </button>
                  <button className="flex items-center gap-2 p-2 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors text-left">
                     <span className="text-blue-600 text-xs">🧮</span>
                     <span className="text-[9px] font-bold text-slate-700">Calculate Tax</span>
                  </button>
                  <button className="flex items-center gap-2 p-2 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors text-left">
                     <span className="text-blue-600 text-xs">📥</span>
                     <span className="text-[9px] font-bold text-slate-700">Download Reports</span>
                  </button>
               </div>
            </div>

         </div>
      </div>
      
    </div>
  );
}
