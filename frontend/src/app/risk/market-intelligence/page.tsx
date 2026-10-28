'use client';

import React from 'react';
import Link from 'next/link';

export default function MarketIntelligencePage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/risk/dashboard" className="hover:text-blue-600">Risk & Intelligence</Link> 
            <span className="text-slate-300">›</span> Market Intelligence
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Market Intelligence</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Track market trends, commodity prices, demand-supply signals and industry insights to make smarter sourcing decisions.</p>
        </div>
        <div className="flex items-center gap-3">
          <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 shadow-sm outline-none focus:border-blue-500">
            <option>Last 30 Days</option>
            <option>Last Quarter</option>
          </select>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            📄 Generate Market Report
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-4">
        {/* Commodity Price Index */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center text-green-600 text-xl">📈</div>
              <span className="text-sm font-bold text-slate-600 leading-tight">Commodity Price<br/>Index</span>
           </div>
           <div className="flex items-end gap-3 mt-2">
              <span className="text-3xl font-black text-[#0B2550] tracking-tight">128.5</span>
           </div>
           <div className="text-[10px] font-bold text-green-600 flex items-center gap-1 mt-1">↑ 4.2% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
        </div>

        {/* Supply Availability */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 text-xl">📊</div>
              <span className="text-sm font-bold text-slate-600 leading-tight">Supply<br/>Availability</span>
           </div>
           <div className="flex items-end gap-3 mt-2">
              <span className="text-3xl font-black text-[#0B2550] tracking-tight">92%</span>
           </div>
           <div className="text-[10px] font-bold text-green-600 flex items-center gap-1 mt-1">↑ 3% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
        </div>

        {/* Demand Outlook */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center text-red-600 text-xl">🛒</div>
              <span className="text-sm font-bold text-slate-600 leading-tight">Demand<br/>Outlook</span>
           </div>
           <div className="flex items-end gap-3 mt-2">
              <span className="text-3xl font-black text-[#0B2550] tracking-tight">High</span>
           </div>
           <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ Increasing <span className="text-slate-400 font-semibold uppercase tracking-wider">Next 3 months</span></div>
        </div>

        {/* Market Sentiment */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl">🌐</div>
              <span className="text-sm font-bold text-slate-600 leading-tight">Market<br/>Sentiment</span>
           </div>
           <div className="flex items-end gap-3 mt-2">
              <span className="text-3xl font-black text-amber-500 tracking-tight">Moderate</span>
           </div>
           <div className="text-[10px] font-bold text-slate-500 flex items-center gap-1 mt-1">Global index: 56 / 100</div>
        </div>

        {/* Currency Volatility */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden">
           <div className="flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xl">💲</div>
              <span className="text-sm font-bold text-slate-600 leading-tight">Currency<br/>Volatility</span>
           </div>
           <div className="flex items-end gap-3 mt-2">
              <span className="text-3xl font-black text-amber-500 tracking-tight">Medium</span>
           </div>
           <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↑ 2.1% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last month</span></div>
        </div>
      </div>

      {/* Main Charts Row */}
      <div className="grid grid-cols-3 gap-4">
        {/* Commodity Price Trends */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">📈</span> Commodity Price Trends</h3>
              <select className="text-[10px] font-bold text-slate-500 border border-slate-200 rounded px-2 py-1 outline-none bg-transparent cursor-pointer">
                 <option>Last 6 Months</option>
              </select>
           </div>
           
           <div className="flex items-center justify-center gap-4 text-[10px] font-bold text-slate-600 mb-6">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Aluminum</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> Copper</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Steel</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> Crude Oil</span>
           </div>
           
           <div className="h-48 flex items-end justify-between relative px-2">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-8">
                 <span>2,500</span><span>2,000</span><span>1,500</span><span>1,000</span><span>500</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[10px] font-bold text-slate-400 -mb-5 px-2">
                 <span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span>
              </div>
              
              <div className="absolute -left-12 top-1/2 -rotate-90 text-[9px] font-bold text-slate-400">Price (USD/MT)</div>
              
              <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
                 {/* Blue (Aluminum) */}
                 <path d="M0,40 L60,35 L120,40 L180,38 L240,30 L300,25" fill="none" stroke="#3b82f6" strokeWidth="2.5" />
                 {/* Red (Copper) */}
                 <path d="M0,80 L60,75 L120,70 L180,72 L240,65 L300,60" fill="none" stroke="#ef4444" strokeWidth="2.5" />
                 {/* Amber (Steel) */}
                 <path d="M0,120 L60,115 L120,110 L180,112 L240,105 L300,100" fill="none" stroke="#f59e0b" strokeWidth="2.5" />
                 {/* Green (Crude) */}
                 <path d="M0,160 L60,155 L120,150 L180,152 L240,145 L300,140" fill="none" stroke="#10b981" strokeWidth="2.5" />
                 
                 <circle cx="0" cy="40" r="3" fill="#3b82f6" /><circle cx="300" cy="25" r="3" fill="#3b82f6" />
                 <circle cx="0" cy="80" r="3" fill="#ef4444" /><circle cx="300" cy="60" r="3" fill="#ef4444" />
                 <circle cx="0" cy="120" r="3" fill="#f59e0b" /><circle cx="300" cy="100" r="3" fill="#f59e0b" />
                 <circle cx="0" cy="160" r="3" fill="#10b981" /><circle cx="300" cy="140" r="3" fill="#10b981" />
              </svg>
           </div>
        </div>

        {/* Global Demand by Region */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4"><span className="text-blue-600">🌍</span> Global Demand by Region</h3>
           
           <div className="flex items-center justify-center h-48 gap-8 mt-2">
              <div className="relative w-32 h-32">
                 <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                    <path className="text-blue-500" strokeWidth="6" strokeDasharray="42, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-green-500" strokeWidth="6" strokeDasharray="24, 100" strokeDashoffset="-42" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-amber-500" strokeWidth="6" strokeDasharray="20, 100" strokeDashoffset="-66" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-purple-500" strokeWidth="6" strokeDasharray="8, 100" strokeDashoffset="-86" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-red-500" strokeWidth="6" strokeDasharray="6, 100" strokeDashoffset="-94" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                 </svg>
                 <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="text-2xl font-black text-[#0B2550] leading-none">100%</span>
                    <span className="text-[8px] font-bold text-slate-500 w-16 leading-tight mt-1">Market Demand</span>
                 </div>
              </div>
              
              <div className="space-y-3">
                 <div className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-blue-500"></span>
                    <span className="text-[10px] font-bold text-slate-700 w-20">Asia Pacific</span>
                    <span className="text-[10px] font-black text-[#0B2550]">42%</span>
                 </div>
                 <div className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-green-500"></span>
                    <span className="text-[10px] font-bold text-slate-700 w-20">North America</span>
                    <span className="text-[10px] font-black text-[#0B2550]">24%</span>
                 </div>
                 <div className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span>
                    <span className="text-[10px] font-bold text-slate-700 w-20">Europe</span>
                    <span className="text-[10px] font-black text-[#0B2550]">20%</span>
                 </div>
                 <div className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-purple-500"></span>
                    <span className="text-[10px] font-bold text-slate-700 w-20">Middle East</span>
                    <span className="text-[10px] font-black text-[#0B2550]">8%</span>
                 </div>
                 <div className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-red-500"></span>
                    <span className="text-[10px] font-bold text-slate-700 w-20">Latin America</span>
                    <span className="text-[10px] font-black text-[#0B2550]">6%</span>
                 </div>
              </div>
           </div>
        </div>

        {/* Supply vs Demand Forecast */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4"><span className="text-blue-600">📊</span> Supply vs Demand Forecast</h3>
           
           <div className="flex items-center justify-end gap-4 text-[9px] font-bold text-slate-600 mb-2">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Supply</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> Demand</span>
           </div>
           
           <div className="h-44 flex items-end justify-between relative px-6 mt-2">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-7">
                 <span>1,000</span><span>800</span><span>600</span><span>400</span><span>200</span><span>0</span>
              </div>
              <div className="absolute -left-10 top-1/2 -rotate-90 text-[9px] font-bold text-slate-400">Volume (k MT)</div>
              
              {/* Bars */}
              <div className="relative w-full h-full flex justify-between items-end pb-0">
                 <div className="flex gap-1 items-end h-full relative z-10 w-1/4 justify-center">
                    <div className="w-6 bg-blue-500 rounded-t-sm" style={{height: '60%'}}></div>
                    <div className="w-6 bg-red-500 rounded-t-sm" style={{height: '65%'}}></div>
                    <div className="absolute -bottom-5 text-[9px] font-bold text-slate-400 whitespace-nowrap">Q3 2025</div>
                 </div>
                 <div className="flex gap-1 items-end h-full relative z-10 w-1/4 justify-center">
                    <div className="w-6 bg-blue-500 rounded-t-sm" style={{height: '58%'}}></div>
                    <div className="w-6 bg-red-500 rounded-t-sm" style={{height: '70%'}}></div>
                    <div className="absolute -bottom-5 text-[9px] font-bold text-slate-400 whitespace-nowrap">Q4 2025</div>
                 </div>
                 <div className="flex gap-1 items-end h-full relative z-10 w-1/4 justify-center">
                    <div className="w-6 bg-blue-500 rounded-t-sm" style={{height: '62%'}}></div>
                    <div className="w-6 bg-red-500 rounded-t-sm" style={{height: '78%'}}></div>
                    <div className="absolute -bottom-5 text-[9px] font-bold text-slate-400 whitespace-nowrap">Q1 2026</div>
                 </div>
                 <div className="flex gap-1 items-end h-full relative z-10 w-1/4 justify-center">
                    <div className="w-6 bg-blue-500 rounded-t-sm" style={{height: '65%'}}></div>
                    <div className="w-6 bg-red-500 rounded-t-sm" style={{height: '85%'}}></div>
                    <div className="absolute -bottom-5 text-[9px] font-bold text-slate-400 whitespace-nowrap">Q2 2026</div>
                 </div>
              </div>
           </div>
        </div>
      </div>

      {/* Secondary Row */}
      <div className="grid grid-cols-3 gap-4">
        {/* Top Market Insights */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">💡</span> Top Market Insights</h3>
              <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="flex-1 space-y-4">
              {[
                 { no: '1', color: 'bg-blue-500', text: 'Aluminum prices expected to rise by 8% in Q3 due to supply constraints in China.', date: 'Aug 25, 2025' },
                 { no: '2', color: 'bg-red-500', text: 'Semiconductor demand remains strong, driven by EV and AI growth.', date: 'Aug 24, 2025' },
                 { no: '3', color: 'bg-amber-500', text: 'Shipping costs in the Red Sea may remain elevated through Q4.', date: 'Aug 22, 2025' },
                 { no: '4', color: 'bg-green-500', text: 'Crude oil price volatility likely due to geopolitical tensions.', date: 'Aug 20, 2025' },
                 { no: '5', color: 'bg-purple-500', text: 'European Union to enforce new carbon border tax from Jan 2026.', date: 'Aug 18, 2025' },
              ].map((item, i) => (
                 <div key={i} className="flex gap-3 items-start border-b border-slate-50 pb-3">
                    <div className={`w-5 h-5 rounded-full ${item.color} text-white flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5`}>{item.no}</div>
                    <div>
                       <p className="text-xs font-semibold text-slate-700 leading-relaxed">{item.text}</p>
                       <p className="text-[9px] text-slate-400 mt-1">{item.date}</p>
                    </div>
                 </div>
              ))}
           </div>
        </div>

        {/* Market Risk Heat Map */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <div className="flex items-center justify-between mb-2">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">🌍</span> Market Risk Heat Map</h3>
           </div>
           
           <div className="flex-1 relative bg-slate-50 rounded-lg overflow-hidden flex items-center justify-center group border border-slate-100 mt-2 min-h-[220px]">
              <div className="absolute inset-0 opacity-40 bg-[url('https://upload.wikimedia.org/wikipedia/commons/e/ec/World_map_blank_without_borders.svg')] bg-contain bg-center bg-no-repeat"></div>
              
              {/* Overlay areas roughly matching image colors */}
              <div className="absolute inset-0 z-10 flex text-[8px]">
                 {/* This is a very rough mock to represent the colored zones on the map */}
              </div>
              
              {/* Legend */}
              <div className="absolute bottom-2 left-0 w-full flex justify-center gap-3 text-[9px] font-bold text-slate-500 z-20 bg-white/50 py-1">
                 <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> High Risk</span>
                 <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Medium Risk</span>
                 <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500"></span> Low Risk</span>
                 <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Stable</span>
              </div>
           </div>
        </div>

        {/* Trending Commodities */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><span className="text-blue-600">📊</span> Trending Commodities</h3>
              <button className="text-xs font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider">Commodity</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Current Price<br/>(USD/MT)</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Change<br/>(30 Days)</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider text-center">Trend</th>
                    </tr>
                 </thead>
                 <tbody className="text-[11px] font-semibold text-slate-700">
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2 text-[#0B2550] font-bold">Aluminum</td>
                       <td className="py-2 text-right font-mono">2,320</td>
                       <td className="py-2 text-right text-red-500">↑ 8.1%</td>
                       <td className="py-2 text-center text-red-500 text-sm">↗</td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2 text-[#0B2550] font-bold">Copper</td>
                       <td className="py-2 text-right font-mono">1,480</td>
                       <td className="py-2 text-right text-red-500">↑ 5.4%</td>
                       <td className="py-2 text-center text-red-500 text-sm">↗</td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2 text-[#0B2550] font-bold">Steel</td>
                       <td className="py-2 text-right font-mono">920</td>
                       <td className="py-2 text-right text-red-500">↑ 3.2%</td>
                       <td className="py-2 text-center text-red-500 text-sm">↗</td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2 text-[#0B2550] font-bold">Crude Oil</td>
                       <td className="py-2 text-right font-mono">78.5</td>
                       <td className="py-2 text-right text-green-500">↓ 2.1%</td>
                       <td className="py-2 text-center text-green-500 text-sm">↘</td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2 text-[#0B2550] font-bold">Nickel</td>
                       <td className="py-2 text-right font-mono">18,420</td>
                       <td className="py-2 text-right text-red-500">↑ 6.8%</td>
                       <td className="py-2 text-center text-red-500 text-sm">↗</td>
                    </tr>
                    <tr className="border-b border-slate-50 hover:bg-slate-50">
                       <td className="py-2 text-[#0B2550] font-bold">Lithium</td>
                       <td className="py-2 text-right font-mono">12,300</td>
                       <td className="py-2 text-right text-green-500">↓ 4.5%</td>
                       <td className="py-2 text-center text-green-500 text-sm">↘</td>
                    </tr>
                    <tr className="hover:bg-slate-50">
                       <td className="py-2 text-[#0B2550] font-bold">Natural Gas</td>
                       <td className="py-2 text-right font-mono">3.2</td>
                       <td className="py-2 text-right text-red-500">↑ 1.9%</td>
                       <td className="py-2 text-center text-red-500 text-sm">↗</td>
                    </tr>
                 </tbody>
              </table>
           </div>
        </div>
      </div>

      {/* Footer Card */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex items-center justify-between">
         <div className="flex items-center gap-4">
            <div className="w-12 h-12 bg-blue-600 rounded-full flex items-center justify-center text-white text-2xl shadow-md">🤖</div>
            <div>
               <h3 className="font-bold text-[#0B2550] text-sm">AI Market Summary</h3>
               <p className="text-xs text-slate-500 mt-1 max-w-4xl">Global supply risks are increasing due to geopolitical tensions and regulatory changes. Consider multi-sourcing and hedging strategies for critical commodities like aluminum and semiconductors.</p>
            </div>
         </div>
         <button className="border border-slate-200 text-blue-600 px-5 py-2 rounded-lg font-bold text-xs shadow-sm hover:bg-slate-50 transition-colors">
            View Detailed Analysis →
         </button>
      </div>
      
    </div>
  );
}
