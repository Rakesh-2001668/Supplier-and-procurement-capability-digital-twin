'use client';

import React from 'react';
import Link from 'next/link';

export default function RiskAlertsPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/risk/dashboard" className="hover:text-blue-600">Risk & Intelligence</Link> 
            <span className="text-slate-300">›</span> Risk Alerts
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Risk Alerts</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Stay ahead with real-time alerts on supply chain risks, compliance issues and market disruptions.</p>
        </div>
        <div className="flex items-center gap-3">
          <button className="border border-slate-200 text-slate-700 bg-white px-5 py-2 rounded-lg font-bold text-sm shadow-sm hover:bg-slate-50 transition-colors flex items-center gap-2">
            ⚙️ Alert Settings
          </button>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            + Create Alert
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-red-100 p-4 shadow-sm relative overflow-hidden flex items-center gap-4">
           <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center text-red-600 text-2xl shrink-0">🔔</div>
           <div className="flex-1">
              <div className="text-sm font-bold text-slate-600 mb-1">Open Alerts</div>
              <div className="flex items-end gap-3">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight leading-none">14</span>
                 <div className="flex flex-col">
                    <span className="text-[10px] font-bold text-red-500">↑ 4</span>
                    <span className="text-[9px] font-bold text-slate-400">vs last week</span>
                 </div>
              </div>
           </div>
        </div>

        <div className="bg-white rounded-xl border border-amber-100 p-4 shadow-sm relative overflow-hidden flex items-center gap-4">
           <div className="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 text-2xl shrink-0">⚠️</div>
           <div className="flex-1">
              <div className="text-sm font-bold text-slate-600 mb-1">High Severity</div>
              <div className="flex items-end gap-3">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight leading-none">6</span>
                 <div className="flex flex-col">
                    <span className="text-[10px] font-bold text-red-500">↑ 2</span>
                    <span className="text-[9px] font-bold text-slate-400">vs last week</span>
                 </div>
              </div>
           </div>
        </div>

        <div className="bg-white rounded-xl border border-blue-100 p-4 shadow-sm relative overflow-hidden flex items-center gap-4">
           <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-2xl shrink-0">⏱️</div>
           <div className="flex-1">
              <div className="text-sm font-bold text-slate-600 mb-1">In Review</div>
              <div className="flex items-end gap-3">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight leading-none">5</span>
                 <div className="flex flex-col">
                    <span className="text-[10px] font-bold text-red-500">↑ 1</span>
                    <span className="text-[9px] font-bold text-slate-400">vs last week</span>
                 </div>
              </div>
           </div>
        </div>

        <div className="bg-white rounded-xl border border-green-100 p-4 shadow-sm relative overflow-hidden flex items-center gap-4">
           <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center text-green-600 text-2xl shrink-0">✅</div>
           <div className="flex-1">
              <div className="text-sm font-bold text-slate-600 mb-1">Resolved (This Week)</div>
              <div className="flex items-end gap-3">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight leading-none">12</span>
                 <div className="flex flex-col">
                    <span className="text-[10px] font-bold text-green-500">↑ 33%</span>
                    <span className="text-[9px] font-bold text-slate-400">vs last week</span>
                 </div>
              </div>
           </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
         <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 outline-none w-36">
            <option>All Severity</option>
         </select>
         <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 outline-none w-36">
            <option>All Alert Types</option>
         </select>
         <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 outline-none w-32">
            <option>All Regions</option>
         </select>
         <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 outline-none w-36">
            <option>All Suppliers</option>
         </select>
         <div className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 flex items-center gap-2">
            📅 Aug 1, 2025 - Aug 31, 2025
         </div>
         <div className="flex-1 relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">🔍</span>
            <input type="text" placeholder="Search alerts..." className="w-full border border-slate-200 bg-white rounded-lg pl-9 pr-4 py-2 text-sm font-medium text-slate-700 outline-none" />
         </div>
      </div>

      <div className="grid grid-cols-4 gap-6">
         {/* Main Table */}
         <div className="col-span-3 bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col h-full">
            <div className="p-4 border-b border-slate-100 flex items-center justify-between">
               <h3 className="font-bold text-[#0B2550] flex items-center gap-2">Alerts (1 - 10 of 24)</h3>
               <button className="text-xs font-bold text-slate-600 border border-slate-200 rounded px-3 py-1 flex items-center gap-1 hover:bg-slate-50"><span className="text-[10px]">📥</span> Export</button>
            </div>
            
            <div className="overflow-x-auto flex-1">
               <table className="w-full text-left border-collapse min-w-[800px]">
                  <thead>
                     <tr className="border-b border-slate-100 bg-slate-50/50">
                        <th className="py-3 px-4 w-10"><input type="checkbox" className="rounded border-slate-300" /></th>
                        <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Date & Time</th>
                        <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Alert ID</th>
                        <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Supplier</th>
                        <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Alert Type</th>
                        <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Description</th>
                        <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Severity</th>
                        <th className="py-3 px-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Status</th>
                        <th className="py-3 px-4 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Action</th>
                     </tr>
                  </thead>
                  <tbody className="text-xs font-semibold text-slate-700">
                     {[
                        { date: 'Aug 25, 2025 10:24 AM', id: 'ALT-2025-0841', sup: 'Shenzhen Tech', type: 'Supply Disruption', desc: 'Port congestion in Shenzhen region may delay shipments (2-4 weeks)', sev: 'High', st: 'Open', sevColor: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-600', stColor: 'text-red-500 border-red-100' },
                        { date: 'Aug 24, 2025 04:12 PM', id: 'ALT-2025-0837', sup: 'Global Metals', type: 'Price Increase', desc: 'Aluminum prices expected to rise by 8% in Q3', sev: 'Medium', st: 'Open', sevColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500', stColor: 'text-red-500 border-red-100' },
                        { date: 'Aug 23, 2025 09:15 AM', id: 'ALT-2025-0831', sup: 'EuroPack', type: 'Compliance', desc: 'EU packaging regulation update requires action', sev: 'Medium', st: 'In Review', sevColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500', stColor: 'text-blue-500 border-blue-100 bg-blue-50' },
                        { date: 'Aug 22, 2025 02:48 PM', id: 'ALT-2025-0826', sup: 'Delta Electronics', type: 'Financial', desc: 'Credit rating downgraded by major agency', sev: 'High', st: 'Open', sevColor: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-600', stColor: 'text-red-500 border-red-100' },
                        { date: 'Aug 21, 2025 11:30 AM', id: 'ALT-2025-0819', sup: 'TransLogistics', type: 'Geopolitical', desc: 'Political unrest in key transport route', sev: 'High', st: 'Resolved', sevColor: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-600', stColor: 'text-emerald-500 border-emerald-100 bg-emerald-50' },
                        { date: 'Aug 20, 2025 03:20 PM', id: 'ALT-2025-0814', sup: 'AgriFoods Co.', type: 'ESG', desc: 'Water usage non-compliance risk identified', sev: 'Medium', st: 'In Review', sevColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500', stColor: 'text-blue-500 border-blue-100 bg-blue-50' },
                        { date: 'Aug 19, 2025 01:05 PM', id: 'ALT-2025-0808', sup: 'Sunrise Electronics', type: 'Cybersecurity', desc: 'Potential data breach risk from third-party vendor', sev: 'High', st: 'Open', sevColor: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-600', stColor: 'text-red-500 border-red-100' },
                        { date: 'Aug 18, 2025 10:45 AM', id: 'ALT-2025-0802', sup: 'MetaWorks Ltd.', type: 'Market', desc: 'Nickel price volatility (↑ 12% in 7 days)', sev: 'Medium', st: 'Resolved', sevColor: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500', stColor: 'text-emerald-500 border-emerald-100 bg-emerald-50' },
                        { date: 'Aug 17, 2025 04:18 PM', id: 'ALT-2025-0798', sup: 'GreenTech Materials', type: 'ESG', desc: 'Carbon emissions above target threshold', sev: 'Low', st: 'Resolved', sevColor: 'text-emerald-600 bg-emerald-50 border-emerald-100', dot: 'bg-emerald-500', stColor: 'text-emerald-500 border-emerald-100 bg-emerald-50' },
                        { date: 'Aug 16, 2025 09:50 AM', id: 'ALT-2025-0791', sup: 'LogiTrans Global', type: 'Natural Disaster', desc: 'Typhoon warning - potential impact on deliveries', sev: 'High', st: 'Open', sevColor: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-600', stColor: 'text-red-500 border-red-100' },
                     ].map((item, i) => (
                        <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                           <td className="py-2.5 px-4"><input type="checkbox" className="rounded border-slate-300" /></td>
                           <td className="py-2.5 px-2 text-[10px] text-slate-500 whitespace-pre-line leading-tight">{item.date}</td>
                           <td className="py-2.5 px-2 text-[10px] text-slate-500 font-mono">{item.id}</td>
                           <td className="py-2.5 px-2 text-[#0B2550] font-bold">{item.sup}</td>
                           <td className="py-2.5 px-2 text-slate-600">{item.type}</td>
                           <td className="py-2.5 px-2 text-[#0B2550] w-64 leading-tight">{item.desc}</td>
                           <td className="py-2.5 px-2 text-center"><span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-bold border ${item.sevColor}`}><span className={`w-1.5 h-1.5 rounded-full ${item.dot}`}></span> {item.sev}</span></td>
                           <td className="py-2.5 px-2 text-center"><span className={`font-bold border px-2 py-0.5 rounded text-[9px] ${item.stColor}`}>{item.st}</span></td>
                           <td className="py-2.5 px-4 text-right">
                              <button className="inline-flex items-center justify-center px-3 py-1 bg-blue-50 text-blue-600 rounded text-[10px] font-bold hover:bg-blue-100 mr-2 border border-blue-100">View</button>
                              <button className="text-slate-400 hover:text-[#0B2550]">⋮</button>
                           </td>
                        </tr>
                     ))}
                  </tbody>
               </table>
            </div>
         </div>

         {/* Sidebar Stats */}
         <div className="col-span-1 space-y-6">
            {/* Alert Severity Breakdown */}
            <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
               <h3 className="font-bold text-[#0B2550] mb-4 text-sm">Alert Severity Breakdown</h3>
               
               <div className="flex items-center justify-center h-32 gap-6 mt-2">
                  <div className="relative w-28 h-28 shrink-0">
                     <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                        <path className="text-emerald-500" strokeWidth="7" strokeDasharray="21, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                        <path className="text-blue-400" strokeWidth="7" strokeDasharray="12, 100" strokeDashoffset="-21" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                        <path className="text-red-500" strokeWidth="7" strokeDasharray="25, 100" strokeDashoffset="-33" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                        <path className="text-amber-500" strokeWidth="7" strokeDasharray="42, 100" strokeDashoffset="-58" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                     </svg>
                     <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                        <span className="text-2xl font-black text-[#0B2550] leading-none">24</span>
                        <span className="text-[9px] font-bold text-slate-500 mt-1 leading-tight">Total Alerts</span>
                     </div>
                  </div>
                  
                  <div className="space-y-2 flex-1">
                     <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-red-500"></span><span className="text-[10px] font-bold text-slate-700">High</span></div>
                        <span className="text-[10px] font-black text-[#0B2550]">6 <span className="text-slate-400 font-semibold">(25%)</span></span>
                     </div>
                     <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-amber-500"></span><span className="text-[10px] font-bold text-slate-700">Medium</span></div>
                        <span className="text-[10px] font-black text-[#0B2550]">10 <span className="text-slate-400 font-semibold">(42%)</span></span>
                     </div>
                     <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-emerald-500"></span><span className="text-[10px] font-bold text-slate-700">Low</span></div>
                        <span className="text-[10px] font-black text-[#0B2550]">5 <span className="text-slate-400 font-semibold">(21%)</span></span>
                     </div>
                     <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-blue-400"></span><span className="text-[10px] font-bold text-slate-700">Info</span></div>
                        <span className="text-[10px] font-black text-[#0B2550]">3 <span className="text-slate-400 font-semibold">(12%)</span></span>
                     </div>
                  </div>
               </div>
            </div>

            {/* Alert Trend */}
            <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
               <div className="flex items-center justify-between mb-4">
                  <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📊</span> Alert Trend</h3>
                  <select className="text-[9px] font-bold text-slate-500 border border-slate-200 rounded px-1 py-0.5 outline-none bg-transparent cursor-pointer">
                     <option>Last 30 Days</option>
                  </select>
               </div>
               
               <div className="h-32 flex items-end justify-between relative px-2 mb-6">
                  <div className="absolute inset-0 border-b border-l border-slate-200"></div>
                  <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-5">
                     <span>20</span><span>15</span><span>10</span><span>5</span><span>0</span>
                  </div>
                  <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[9px] font-bold text-slate-400 -mb-5 px-2">
                     <span>Aug 1</span><span>Aug 8</span><span>Aug 15</span><span>Aug 22</span><span>Aug 31</span>
                  </div>
                  
                  <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
                     <path d="M0,80 L75,70 L150,60 L225,50 L300,45" fill="none" stroke="#ef4444" strokeWidth="2" />
                     <path d="M0,50 L75,45 L150,40 L225,35 L300,30" fill="none" stroke="#f59e0b" strokeWidth="2" />
                     <path d="M0,110 L75,100 L150,105 L225,95 L300,90" fill="none" stroke="#10b981" strokeWidth="2" />
                     <path d="M0,120 L75,115 L150,110 L225,105 L300,100" fill="none" stroke="#3b82f6" strokeWidth="2" />
                     
                     <circle cx="0" cy="80" r="2.5" fill="#ef4444" /><circle cx="75" cy="70" r="2.5" fill="#ef4444" /><circle cx="150" cy="60" r="2.5" fill="#ef4444" /><circle cx="225" cy="50" r="2.5" fill="#ef4444" /><circle cx="300" cy="45" r="2.5" fill="#ef4444" />
                     <circle cx="0" cy="50" r="2.5" fill="#f59e0b" /><circle cx="75" cy="45" r="2.5" fill="#f59e0b" /><circle cx="150" cy="40" r="2.5" fill="#f59e0b" /><circle cx="225" cy="35" r="2.5" fill="#f59e0b" /><circle cx="300" cy="30" r="2.5" fill="#f59e0b" />
                  </svg>
               </div>
               
               <div className="flex items-center justify-center gap-3 text-[9px] font-bold text-slate-600 mt-2">
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> High</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Medium</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> Low</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Info</span>
               </div>
            </div>

            {/* Recent Notifications */}
            <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
               <div className="flex items-center justify-between mb-4">
                  <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">⚡</span> Recent Notifications</h3>
                  <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
               </div>
               
               <div className="space-y-4">
                  <div className="flex gap-3">
                     <div className="w-5 h-5 rounded-full bg-red-100 text-red-600 flex items-center justify-center text-[10px] shrink-0 mt-0.5">🔔</div>
                     <div>
                        <p className="text-[11px] font-bold text-[#0B2550] leading-tight">New high risk alert for Shenzhen Tech</p>
                        <p className="text-[9px] text-slate-400 mt-0.5">10 minutes ago</p>
                     </div>
                  </div>
                  <div className="flex gap-3">
                     <div className="w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-[10px] shrink-0 mt-0.5">ℹ️</div>
                     <div>
                        <p className="text-[11px] font-bold text-[#0B2550] leading-tight">EU regulation update affects 3 suppliers</p>
                        <p className="text-[9px] text-slate-400 mt-0.5">1 hour ago</p>
                     </div>
                  </div>
                  <div className="flex gap-3">
                     <div className="w-5 h-5 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center text-[10px] shrink-0 mt-0.5">⚠️</div>
                     <div>
                        <p className="text-[11px] font-bold text-[#0B2550] leading-tight">Aluminum price increase alert</p>
                        <p className="text-[9px] text-slate-400 mt-0.5">3 hours ago</p>
                     </div>
                  </div>
                  <div className="flex gap-3">
                     <div className="w-5 h-5 rounded-full bg-green-100 text-green-600 flex items-center justify-center text-[10px] shrink-0 mt-0.5">✅</div>
                     <div>
                        <p className="text-[11px] font-bold text-[#0B2550] leading-tight">Alert resolved: GreenTech Materials</p>
                        <p className="text-[9px] text-slate-400 mt-0.5">5 hours ago</p>
                     </div>
                  </div>
                  <div className="flex gap-3">
                     <div className="w-5 h-5 rounded-full bg-red-100 text-red-600 flex items-center justify-center text-[10px] shrink-0 mt-0.5">🔔</div>
                     <div>
                        <p className="text-[11px] font-bold text-[#0B2550] leading-tight">Typhoon warning in Asia Pacific</p>
                        <p className="text-[9px] text-slate-400 mt-0.5">8 hours ago</p>
                     </div>
                  </div>
               </div>
            </div>

         </div>
      </div>
      
    </div>
  );
}
