'use client';

import React from 'react';
import Link from 'next/link';

export default function GeopoliticalRiskPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/risk/dashboard" className="hover:text-blue-600">Risk & Intelligence</Link> 
            <span className="text-slate-300">›</span> Geopolitical Risk
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Geopolitical Risk</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Monitor global events and their impact on your supply chain.</p>
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
      <div className="grid grid-cols-4 gap-4">
        {/* High Risk Countries */}
        <div className="bg-white rounded-xl border border-red-100 p-4 shadow-sm relative overflow-hidden">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center text-red-600 text-xl">🛡️</div>
              <span className="text-sm font-bold text-slate-600">High Risk Countries</span>
           </div>
           <div className="flex items-end gap-3 mt-2">
              <span className="text-4xl font-black text-[#0B2550] tracking-tight">8</span>
              <span className="text-xs font-bold text-red-500 bg-red-50 px-1.5 py-0.5 rounded flex items-center mb-1.5">↑ 2</span>
           </div>
           <div className="text-[10px] font-semibold text-slate-400 mt-1 uppercase tracking-wider">vs last month</div>
        </div>

        {/* Medium Risk Countries */}
        <div className="bg-white rounded-xl border border-amber-100 p-4 shadow-sm relative overflow-hidden">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 text-xl">⚠️</div>
              <span className="text-sm font-bold text-slate-600">Medium Risk Countries</span>
           </div>
           <div className="flex items-end gap-3 mt-2">
              <span className="text-4xl font-black text-[#0B2550] tracking-tight">24</span>
              <span className="text-xs font-bold text-green-600 bg-green-50 px-1.5 py-0.5 rounded flex items-center mb-1.5">↓ 5</span>
           </div>
           <div className="text-[10px] font-semibold text-slate-400 mt-1 uppercase tracking-wider">vs last month</div>
        </div>

        {/* Low Risk Countries */}
        <div className="bg-white rounded-xl border border-green-100 p-4 shadow-sm relative overflow-hidden">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center text-green-600 text-xl">✅</div>
              <span className="text-sm font-bold text-slate-600">Low Risk Countries</span>
           </div>
           <div className="flex items-end gap-3 mt-2">
              <span className="text-4xl font-black text-[#0B2550] tracking-tight">156</span>
              <span className="text-xs font-bold text-red-500 bg-red-50 px-1.5 py-0.5 rounded flex items-center mb-1.5">↑ 3</span>
           </div>
           <div className="text-[10px] font-semibold text-slate-400 mt-1 uppercase tracking-wider">vs last month</div>
        </div>

        {/* Global Risk Index */}
        <div className="bg-white rounded-xl border border-blue-100 p-4 shadow-sm relative overflow-hidden">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl">📊</div>
              <span className="text-sm font-bold text-slate-600">Global Risk Index</span>
           </div>
           <div className="flex items-end gap-3 mt-2">
              <span className="text-4xl font-black text-[#0B2550] tracking-tight">56 <span className="text-lg text-slate-400">/ 100</span></span>
              <span className="text-xs font-bold text-red-500 bg-red-50 px-1.5 py-0.5 rounded flex items-center mb-1.5">↑ 6</span>
           </div>
           <div className="text-[10px] font-semibold text-slate-400 mt-1 uppercase tracking-wider">vs last month</div>
        </div>
      </div>

      {/* Main Row */}
      <div className="grid grid-cols-5 gap-4">
        {/* Heat Map */}
        <div className="col-span-3 bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">🌍</span> Geopolitical Risk Heat Map</h3>
              <select className="text-xs font-bold text-slate-500 border border-slate-200 rounded px-2 py-1 outline-none bg-transparent cursor-pointer">
                 <option>All Regions</option>
              </select>
           </div>
           
           <div className="flex-1 relative bg-slate-50 rounded-lg overflow-hidden flex items-center justify-center group border border-slate-100 min-h-[350px]">
              <div className="absolute inset-0 opacity-50 bg-[url('https://upload.wikimedia.org/wikipedia/commons/e/ec/World_map_blank_without_borders.svg')] bg-contain bg-center bg-no-repeat"></div>
              
              {/* Highlighted map areas placeholder using CSS overlay logic - simplified for demo */}
              
              {/* Map Pins */}
              <div className="absolute top-[25%] left-[55%] flex flex-col items-center">
                 <div className="text-[10px] font-bold text-[#0B2550] mb-1 text-center bg-white/80 px-1 rounded backdrop-blur-sm">Russia<br/><span className="text-red-500">High Risk</span></div>
                 <div className="w-2.5 h-2.5 rounded-full bg-red-500 shadow-[0_0_0_4px_rgba(239,68,68,0.2)]"></div>
              </div>

              <div className="absolute top-[30%] left-[48%] flex flex-col items-center">
                 <div className="w-2 h-2 rounded-full bg-red-500 shadow-[0_0_0_4px_rgba(239,68,68,0.2)]"></div>
                 <div className="text-[9px] font-bold text-[#0B2550] mt-1 text-center bg-white/80 px-1 rounded backdrop-blur-sm">Ukraine<br/><span className="text-red-500">High Risk</span></div>
              </div>

              <div className="absolute top-[40%] left-[72%] flex flex-col items-center">
                 <div className="text-[10px] font-bold text-[#0B2550] mb-1 text-center bg-white/80 px-1 rounded backdrop-blur-sm">China<br/><span className="text-amber-500">Medium Risk</span></div>
                 <div className="w-2.5 h-2.5 rounded-full bg-amber-500 shadow-[0_0_0_4px_rgba(245,158,11,0.2)]"></div>
              </div>

              <div className="absolute top-[38%] left-[53%] flex flex-col items-center">
                 <div className="w-2 h-2 rounded-full bg-red-500 shadow-[0_0_0_4px_rgba(239,68,68,0.2)]"></div>
                 <div className="text-[9px] font-bold text-[#0B2550] mt-1 text-center bg-white/80 px-1 rounded backdrop-blur-sm">Israel<br/><span className="text-red-500">High Risk</span></div>
              </div>

              <div className="absolute top-[55%] left-[28%] flex flex-col items-center">
                 <div className="text-[9px] font-bold text-[#0B2550] mb-1 text-center bg-white/80 px-1 rounded backdrop-blur-sm">Venezuela<br/><span className="text-amber-500">Medium Risk</span></div>
                 <div className="w-2 h-2 rounded-full bg-amber-500 shadow-[0_0_0_4px_rgba(245,158,11,0.2)]"></div>
              </div>
              
              {/* Legend */}
              <div className="absolute bottom-4 left-4 bg-white/90 p-3 rounded-lg shadow-sm border border-slate-200 backdrop-blur-sm space-y-2">
                 <div className="flex items-center gap-2 text-xs font-bold text-slate-600"><span className="w-3 h-3 rounded-full bg-red-500"></span> High Risk</div>
                 <div className="flex items-center gap-2 text-xs font-bold text-slate-600"><span className="w-3 h-3 rounded-full bg-amber-500"></span> Medium Risk</div>
                 <div className="flex items-center gap-2 text-xs font-bold text-slate-600"><span className="w-3 h-3 rounded-full bg-blue-500"></span> Low Risk</div>
                 <div className="flex items-center gap-2 text-xs font-bold text-slate-600"><span className="w-3 h-3 rounded-full bg-slate-300"></span> Stable</div>
              </div>
           </div>
        </div>

        {/* Recent Alerts */}
        <div className="col-span-2 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-red-500">🔔</span> Recent Geopolitical Alerts</h3>
              <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Date</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Country/Region</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Event</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Impact</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Severity</th>
                    </tr>
                 </thead>
                 <tbody className="text-[11px] font-semibold text-slate-700">
                    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                       <td className="py-3 text-slate-500">Aug 25, 2025</td>
                       <td className="py-3 text-[#0B2550] font-bold flex items-center gap-1.5"><span className="text-base">🇺🇦</span> Ukraine</td>
                       <td className="py-3 text-[#0B2550]">Increased military activity</td>
                       <td className="py-3 text-slate-600">Supply disruption risk (energy, metals)</td>
                       <td className="py-3 text-center"><span className="inline-flex items-center gap-1 bg-red-50 text-red-600 px-2 py-0.5 rounded text-[10px] font-bold border border-red-100"><span className="w-1.5 h-1.5 rounded-full bg-red-600"></span> High</span></td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                       <td className="py-3 text-slate-500">Aug 24, 2025</td>
                       <td className="py-3 text-[#0B2550] font-bold flex items-center gap-1.5"><span className="text-base">📍</span> Red Sea</td>
                       <td className="py-3 text-[#0B2550]">Shipping route tensions</td>
                       <td className="py-3 text-slate-600">Delays in logistics (2-4 weeks)</td>
                       <td className="py-3 text-center"><span className="inline-flex items-center gap-1 bg-red-50 text-red-600 px-2 py-0.5 rounded text-[10px] font-bold border border-red-100"><span className="w-1.5 h-1.5 rounded-full bg-red-600"></span> High</span></td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                       <td className="py-3 text-slate-500">Aug 22, 2025</td>
                       <td className="py-3 text-[#0B2550] font-bold flex items-center gap-1.5"><span className="text-base">🇹🇼</span> Taiwan</td>
                       <td className="py-3 text-[#0B2550]">Heightened regional tensions</td>
                       <td className="py-3 text-slate-600">Semiconductor supply risk</td>
                       <td className="py-3 text-center"><span className="inline-flex items-center gap-1 bg-red-50 text-red-600 px-2 py-0.5 rounded text-[10px] font-bold border border-red-100"><span className="w-1.5 h-1.5 rounded-full bg-red-600"></span> High</span></td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                       <td className="py-3 text-slate-500">Aug 20, 2025</td>
                       <td className="py-3 text-[#0B2550] font-bold flex items-center gap-1.5"><span className="text-base">🇻🇪</span> Venezuela</td>
                       <td className="py-3 text-[#0B2550]">Regulatory changes</td>
                       <td className="py-3 text-slate-600">Oil & raw material supply impact</td>
                       <td className="py-3 text-center"><span className="inline-flex items-center gap-1 bg-amber-50 text-amber-600 px-2 py-0.5 rounded text-[10px] font-bold border border-amber-100"><span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium</span></td>
                    </tr>
                    <tr className="hover:bg-slate-50 transition-colors">
                       <td className="py-3 text-slate-500">Aug 18, 2025</td>
                       <td className="py-3 text-[#0B2550] font-bold flex items-center gap-1.5"><span className="text-base">🌍</span> West Africa</td>
                       <td className="py-3 text-[#0B2550]">Political unrest</td>
                       <td className="py-3 text-slate-600">Logistics disruption risk</td>
                       <td className="py-3 text-center"><span className="inline-flex items-center gap-1 bg-amber-50 text-amber-600 px-2 py-0.5 rounded text-[10px] font-bold border border-amber-100"><span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium</span></td>
                    </tr>
                 </tbody>
              </table>
           </div>
        </div>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-3 gap-4">
        {/* Top Affected Categories */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">📦</span> Top Affected Categories</h3>
           </div>
           
           <div className="flex items-center justify-between text-[10px] font-extrabold text-slate-400 uppercase tracking-wider mb-2">
              <span className="w-32">Category</span>
              <span className="flex-1">Impact Level</span>
              <span className="w-20 text-right">Affected Suppliers</span>
           </div>
           
           <div className="space-y-4">
              {[
                { label: 'Energy & Fuels', val: 32, width: 90, color: 'bg-red-500' },
                { label: 'Metals & Minerals', val: 28, width: 80, color: 'bg-red-500' },
                { label: 'Electronics & Semiconductors', val: 18, width: 50, color: 'bg-amber-500' },
                { label: 'Agriculture & Food', val: 15, width: 40, color: 'bg-amber-400' },
                { label: 'Logistics & Shipping', val: 14, width: 35, color: 'bg-amber-400' },
                { label: 'Chemicals', val: 9, width: 25, color: 'bg-blue-400' },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between gap-4">
                   <span className="text-xs font-bold text-[#0B2550] w-36 truncate">{item.label}</span>
                   <div className="flex-1 h-3.5 bg-slate-100 rounded overflow-hidden">
                      <div className={`h-full ${item.color} rounded`} style={{ width: `${item.width}%` }}></div>
                   </div>
                   <span className="text-xs font-black text-slate-600 w-12 text-right">{item.val}</span>
                </div>
              ))}
           </div>
        </div>

        {/* Risk Trend */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">📈</span> Risk Trend</h3>
           </div>
           
           <div className="flex items-center justify-center gap-4 text-xs font-bold text-slate-600 mb-6">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Global Index</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> High Risk Countries</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Medium Risk Countries</span>
           </div>
           
           <div className="h-40 flex items-end justify-between relative px-2">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-5">
                 <span>100</span><span>80</span><span>60</span><span>40</span><span>20</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[10px] font-bold text-slate-400 -mb-5 px-2">
                 <span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span>
              </div>
              
              <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
                 {/* Blue (Global Index) */}
                 <path d="M0,70 L60,65 L120,70 L180,68 L240,60 L300,56" fill="none" stroke="#3b82f6" strokeWidth="2.5" />
                 {/* Red */}
                 <path d="M0,140 L60,135 L120,130 L180,128 L240,120 L300,115" fill="none" stroke="#ef4444" strokeWidth="2.5" />
                 {/* Amber */}
                 <path d="M0,110 L60,105 L120,100 L180,100 L240,95 L300,90" fill="none" stroke="#f59e0b" strokeWidth="2.5" />
                 
                 <circle cx="0" cy="70" r="3.5" fill="#3b82f6" /><circle cx="60" cy="65" r="3.5" fill="#3b82f6" />
                 <circle cx="120" cy="70" r="3.5" fill="#3b82f6" /><circle cx="180" cy="68" r="3.5" fill="#3b82f6" />
                 <circle cx="240" cy="60" r="3.5" fill="#3b82f6" /><circle cx="300" cy="56" r="3.5" fill="#3b82f6" />
                 
                 <circle cx="0" cy="140" r="3" fill="#ef4444" /><circle cx="300" cy="115" r="3" fill="#ef4444" />
                 <circle cx="0" cy="110" r="3" fill="#f59e0b" /><circle cx="300" cy="90" r="3" fill="#f59e0b" />
              </svg>
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
                 <div className="text-red-500 mt-0.5 font-bold">↗</div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed"><strong className="text-[#0B2550]">Escalating tensions in the Red Sea</strong> may extend shipping delays into Q4.</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-amber-500 mt-0.5 font-bold">↗</div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed"><strong className="text-[#0B2550]">Sanctions on Russian entities</strong> continue to impact metal supply chains.</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-blue-500 mt-0.5 font-bold">📄</div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed"><strong className="text-[#0B2550]">Taiwan Strait risk</strong> may affect semiconductor availability. Consider dual sourcing.</p>
              </div>
              <div className="flex gap-3">
                 <div className="text-green-500 mt-0.5 font-bold">↘</div>
                 <p className="text-xs font-semibold text-slate-700 leading-relaxed"><strong className="text-[#0B2550]">Political stability improving in Brazil</strong>, reducing supply risk for agricultural goods.</p>
              </div>
           </div>
           
           <button className="w-full py-2 border border-slate-200 rounded-lg text-blue-600 font-bold text-xs mt-4 hover:bg-slate-50 transition-colors">
              View Detailed Analysis →
           </button>
        </div>
      </div>
      
    </div>
  );
}
