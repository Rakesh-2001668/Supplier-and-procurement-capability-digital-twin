'use client';

import React from 'react';
import Link from 'next/link';

export default function SupplierRiskPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Breadcrumb & Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/risk/dashboard" className="hover:text-blue-600">Risk & Intelligence</Link> 
            <span className="text-slate-300">›</span> 
            <Link href="/risk/supplier-risk" className="hover:text-blue-600">Supplier Risk</Link>
            <span className="text-slate-300">›</span> Supplier Details
          </div>
          <div className="flex items-center gap-4">
             <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Shenzhen Tech Components</h1>
             <span className="bg-red-50 text-red-600 px-3 py-1 rounded-full text-xs font-bold border border-red-100 flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-600"></span> High Risk</span>
          </div>
          <p className="text-sm text-slate-500 font-medium mt-1">SUP-1001 | Electronics Components | Shenzhen, China</p>
        </div>
        <div className="flex items-center gap-3">
          <button className="border border-slate-200 text-slate-700 bg-white px-5 py-2 rounded-lg font-bold text-sm shadow-sm hover:bg-slate-50 transition-colors flex items-center gap-2">
            🔔 Monitor
          </button>
          <button className="border border-slate-200 text-slate-700 bg-white px-5 py-2 rounded-lg font-bold text-sm shadow-sm hover:bg-slate-50 transition-colors flex items-center gap-2">
            📄 Request Information
          </button>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            ✔️ Create Action
          </button>
          <button className="border border-slate-200 text-slate-700 bg-white w-10 h-10 rounded-lg font-bold text-sm shadow-sm hover:bg-slate-50 transition-colors flex items-center justify-center">
            ...
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-8 border-b border-slate-200 px-2">
         {['Overview', 'Risk Assessment', 'Financial Health', 'Compliance & ESG', 'Geopolitical Exposure', 'Supply Disruption', 'Documents', 'Activity Log'].map((tab, i) => (
            <button key={i} className={`pb-3 text-sm font-bold border-b-2 transition-colors ${i === 0 ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'}`}>
               {tab}
            </button>
         ))}
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-4">
        {/* Risk Score */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm flex items-center justify-between">
           <div>
              <div className="text-sm font-bold text-slate-600 flex items-center gap-2 mb-2">
                 <span className="text-red-500">❌</span> Risk Score
              </div>
              <div className="flex items-end gap-1">
                 <span className="text-3xl font-black text-[#0B2550] tracking-tight">78</span>
                 <span className="text-sm font-bold text-slate-400 mb-1">/ 100</span>
              </div>
              <span className="text-xs font-bold text-red-500 mt-1 block">High Risk</span>
           </div>
           
           <div className="w-16 h-16 relative">
              <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                 <path className="text-slate-100" strokeWidth="4" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                 <path className="text-red-500" strokeWidth="4" strokeDasharray="78, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
              </svg>
           </div>
        </div>

        {/* Risk Level */}
        <div className="bg-white rounded-xl border border-red-100 p-4 shadow-sm flex flex-col justify-center items-center">
           <div className="w-8 h-8 rounded-full bg-red-100 flex items-center justify-center text-red-600 mb-2">🛡️</div>
           <span className="text-sm font-bold text-slate-600 mb-1">Risk Level</span>
           <span className="text-lg font-black text-red-500 tracking-tight bg-red-50 px-3 py-1 rounded-lg">High</span>
        </div>

        {/* Last Assessed */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center text-blue-600">📅</div>
              <span className="text-sm font-bold text-slate-600">Last Assessed</span>
           </div>
           <div className="text-xl font-black text-[#0B2550] tracking-tight mt-1">Aug 25, 2025</div>
           <div className="text-[10px] font-bold text-green-600 flex items-center gap-1 mt-1">↑ 12 days ago</div>
        </div>

        {/* Supplier Since */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-slate-50 flex items-center justify-center text-slate-600">🏢</div>
              <span className="text-sm font-bold text-slate-600">Supplier Since</span>
           </div>
           <div className="text-xl font-black text-[#0B2550] tracking-tight mt-1">Jan 10, 2022</div>
           <div className="text-[10px] font-bold text-slate-500 mt-1">3.6 years</div>
        </div>

        {/* Total Spend */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden">
           <div className="absolute top-0 right-0 p-4 opacity-10 text-3xl">💰</div>
           <div className="flex items-center gap-2 mb-2">
              <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center text-blue-600">📄</div>
              <span className="text-sm font-bold text-slate-600">Total Spend (YTD)</span>
           </div>
           <div className="text-xl font-black text-[#0B2550] tracking-tight mt-1">₹ 2,35,00,000</div>
           <div className="text-[10px] font-bold text-green-600 flex items-center gap-1 mt-1">↑ 8% vs last year</div>
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-3 gap-4">
        {/* Key Risk Indicators */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">🔑</span> Key Risk Indicators</h3>
           </div>
           
           <div className="space-y-4">
              {[
                { label: 'Financial Stability', val: 82, color: 'bg-red-500' },
                { label: 'Geopolitical Exposure', val: 68, color: 'bg-amber-500' },
                { label: 'Supply Disruption', val: 76, color: 'bg-red-500' },
                { label: 'Compliance & Regulatory', val: 62, color: 'bg-amber-400' },
                { label: 'ESG', val: 35, color: 'bg-emerald-500' },
                { label: 'Cybersecurity', val: 58, color: 'bg-blue-400' },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between gap-4">
                   <span className="text-xs font-bold text-slate-700 w-36 truncate">{item.label}</span>
                   <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
                      <div className={`h-full ${item.color} rounded-full`} style={{ width: `${item.val}%` }}></div>
                   </div>
                   <span className="text-xs font-black text-[#0B2550] w-8 text-right">{item.val}</span>
                </div>
              ))}
           </div>
        </div>

        {/* Risk Trend */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">📊</span> Risk Trend</h3>
              <div className="flex flex-col items-end">
                 <span className="text-xs font-bold text-red-500 bg-red-50 px-1.5 py-0.5 rounded">↑ +18%</span>
                 <span className="text-[9px] font-bold text-slate-400 mt-0.5">vs last 6 months</span>
              </div>
           </div>
           
           <div className="h-48 flex items-end justify-between relative px-2 mt-4">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-5">
                 <span>100</span><span>80</span><span>60</span><span>40</span><span>20</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[10px] font-bold text-slate-400 -mb-5 px-2">
                 <span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span>
              </div>
              
              <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
                 <defs>
                    <linearGradient id="gradRed" x1="0" y1="0" x2="0" y2="1">
                       <stop offset="0%" stopColor="#ef4444" stopOpacity="0.2" />
                       <stop offset="100%" stopColor="#ef4444" stopOpacity="0" />
                    </linearGradient>
                 </defs>
                 <path d="M0,150 L60,135 L120,120 L180,105 L240,90 L300,75 L300,200 L0,200 Z" fill="url(#gradRed)" />
                 <path d="M0,150 L60,135 L120,120 L180,105 L240,90 L300,75" fill="none" stroke="#ef4444" strokeWidth="2" />
                 <circle cx="0" cy="150" r="3" fill="#ef4444" /><circle cx="60" cy="135" r="3" fill="#ef4444" />
                 <circle cx="120" cy="120" r="3" fill="#ef4444" /><circle cx="180" cy="105" r="3" fill="#ef4444" />
                 <circle cx="240" cy="90" r="3" fill="#ef4444" /><circle cx="300" cy="75" r="3" fill="#ef4444" />
              </svg>
           </div>
        </div>

        {/* Risk Summary */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-red-500">⚠️</span> Risk Summary</h3>
           </div>
           
           <div className="flex-1 space-y-4">
              <div className="flex gap-3 items-start">
                 <div className="w-1.5 h-1.5 rounded-full bg-red-500 mt-1.5 shrink-0"></div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed">Increased geopolitical risk due to regional tensions.</p>
              </div>
              <div className="flex gap-3 items-start">
                 <div className="w-1.5 h-1.5 rounded-full bg-red-500 mt-1.5 shrink-0"></div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed">Recent port congestion causing shipment delays (2-4 weeks).</p>
              </div>
              <div className="flex gap-3 items-start">
                 <div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-1.5 shrink-0"></div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed">Financial ratios indicate higher leverage.</p>
              </div>
              <div className="flex gap-3 items-start">
                 <div className="w-1.5 h-1.5 rounded-full bg-red-500 mt-1.5 shrink-0"></div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed">Regulatory changes in export controls may impact supply.</p>
              </div>
              <div className="flex gap-3 items-start">
                 <div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-1.5 shrink-0"></div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed">No major ESG concerns identified.</p>
              </div>
           </div>
           
           <button className="text-xs font-bold text-blue-600 hover:underline text-right mt-4">View Detailed Analysis →</button>
        </div>
      </div>

      {/* Bottom Grid */}
      <div className="grid grid-cols-3 gap-4">
         {/* Recent Alerts */}
         <div className="col-span-1 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4">
               <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-red-500">🔔</span> Recent Alerts</h3>
               <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
            </div>
            
            <div className="space-y-3">
               {[
                  { date: 'Aug 25, 2025', alert: 'Port congestion in Shenzhen region', sev: 'High', status: 'Open', sCol: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-600', stCol: 'text-red-500' },
                  { date: 'Aug 18, 2025', alert: 'Increase in raw material prices', sev: 'Medium', status: 'Open', sCol: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500', stCol: 'text-red-500' },
                  { date: 'Aug 12, 2025', alert: 'Regulatory change (EU export controls)', sev: 'Medium', status: 'In Review', sCol: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500', stCol: 'text-blue-500' },
                  { date: 'Jul 28, 2025', alert: 'Late shipment (PO-4587)', sev: 'High', status: 'Resolved', sCol: 'text-red-600 bg-red-50 border-red-100', dot: 'bg-red-600', stCol: 'text-emerald-500' },
                  { date: 'Jul 15, 2025', alert: 'Adverse media coverage', sev: 'Medium', status: 'Resolved', sCol: 'text-amber-600 bg-amber-50 border-amber-100', dot: 'bg-amber-500', stCol: 'text-emerald-500' },
               ].map((a, i) => (
                  <div key={i} className="flex items-center justify-between border-b border-slate-50 pb-2">
                     <div>
                        <div className="text-xs font-bold text-[#0B2550] w-40 truncate">{a.alert}</div>
                        <div className="text-[10px] text-slate-400 mt-0.5">{a.date}</div>
                     </div>
                     <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold border ${a.sCol}`}><span className={`w-1.5 h-1.5 rounded-full ${a.dot}`}></span> {a.sev}</span>
                     <span className={`text-[10px] font-bold w-12 text-right ${a.stCol}`}>{a.status}</span>
                  </div>
               ))}
            </div>
         </div>
         
         {/* Open Actions */}
         <div className="col-span-1 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4">
               <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">✓</span> Open Actions</h3>
               <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
            </div>
            
            <div className="space-y-3">
               {[
                  { action: 'Request updated financial statements', owner: 'Priya S.', ini: 'PS', date: 'Aug 30, 2025', status: 'Open', stCol: 'text-red-500 bg-red-50' },
                  { action: 'Assess alternate suppliers', owner: 'Rahul K.', ini: 'RK', date: 'Sep 05, 2025', status: 'Open', stCol: 'text-red-500 bg-red-50' },
                  { action: 'Review compliance documents', owner: 'Neha D.', ini: 'ND', date: 'Aug 28, 2025', status: 'In Progress', stCol: 'text-blue-500 bg-blue-50' },
                  { action: 'Schedule supplier risk review meeting', owner: 'Alex S.', ini: 'AS', date: 'Sep 02, 2025', status: 'Open', stCol: 'text-red-500 bg-red-50' },
               ].map((a, i) => (
                  <div key={i} className="flex items-center justify-between border-b border-slate-50 pb-2">
                     <div className="w-40">
                        <div className="text-xs font-bold text-[#0B2550] truncate">{a.action}</div>
                        <div className="text-[10px] text-slate-500 flex items-center gap-1 mt-1">
                           <div className="w-4 h-4 rounded-full bg-purple-600 text-white flex items-center justify-center text-[8px] font-bold">{a.ini}</div>
                           {a.owner} • <span className="text-slate-400">{a.date}</span>
                        </div>
                     </div>
                     <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${a.stCol}`}>{a.status}</span>
                  </div>
               ))}
            </div>
         </div>
         
         {/* Supplier Details */}
         <div className="col-span-1 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4"><span className="text-slate-400">📄</span> Supplier Details</h3>
            
            <div className="space-y-3">
               <div className="grid grid-cols-3 gap-2 border-b border-slate-50 pb-2">
                  <div className="text-xs text-slate-500">Supplier Name</div>
                  <div className="col-span-2 text-xs font-bold text-[#0B2550]">Shenzhen Tech Components</div>
               </div>
               <div className="grid grid-cols-3 gap-2 border-b border-slate-50 pb-2">
                  <div className="text-xs text-slate-500">Supplier ID</div>
                  <div className="col-span-2 text-xs font-bold text-[#0B2550]">SUP-1001</div>
               </div>
               <div className="grid grid-cols-3 gap-2 border-b border-slate-50 pb-2">
                  <div className="text-xs text-slate-500">Category</div>
                  <div className="col-span-2 text-xs font-bold text-[#0B2550]">Electronics Components</div>
               </div>
               <div className="grid grid-cols-3 gap-2 border-b border-slate-50 pb-2">
                  <div className="text-xs text-slate-500">Entity Type</div>
                  <div className="col-span-2 text-xs font-bold text-[#0B2550]">Manufacturer</div>
               </div>
               <div className="grid grid-cols-3 gap-2 border-b border-slate-50 pb-2">
                  <div className="text-xs text-slate-500">Address</div>
                  <div className="col-span-2 text-xs font-bold text-[#0B2550] leading-relaxed">Block A, Tech Park<br/>Nanshan District<br/>Shenzhen, Guangdong 518000<br/>China</div>
               </div>
               <div className="grid grid-cols-3 gap-2 border-b border-slate-50 pb-2">
                  <div className="text-xs text-slate-500">Primary Contact</div>
                  <div className="col-span-2 text-xs font-bold text-[#0B2550]">Li Wei</div>
               </div>
               <div className="grid grid-cols-3 gap-2 border-b border-slate-50 pb-2">
                  <div className="text-xs text-slate-500">Email</div>
                  <div className="col-span-2 text-xs font-bold text-blue-600 hover:underline">li.wei@shenzhentech.cn</div>
               </div>
               <div className="grid grid-cols-3 gap-2 border-b border-slate-50 pb-2">
                  <div className="text-xs text-slate-500">Phone</div>
                  <div className="col-span-2 text-xs font-bold text-[#0B2550]">+86 755 1234 5678</div>
               </div>
               <div className="grid grid-cols-3 gap-2">
                  <div className="text-xs text-slate-500">Website</div>
                  <div className="col-span-2 text-xs font-bold text-blue-600 hover:underline">www.shenzhentech.cn</div>
               </div>
            </div>
         </div>
      </div>
      
    </div>
  );
}
