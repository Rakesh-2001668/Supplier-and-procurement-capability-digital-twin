'use client';

import React from 'react';
import Link from 'next/link';

export default function BudgetsForecastsPage() {
  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/finance/dashboard" className="hover:text-blue-600">Finance & Payments</Link> 
            <span className="text-slate-300">›</span> Budgets & Forecasts
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight">Budgets & Forecasts</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">Plan, monitor and forecast your financial performance with real-time insights.</p>
        </div>
        <div className="flex items-center gap-3">
          <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 outline-none shadow-sm cursor-pointer">
             <option>📅 FY 2025-26</option>
          </select>
          <select className="border border-slate-200 bg-white rounded-lg px-4 py-2 text-sm font-bold text-slate-700 outline-none shadow-sm cursor-pointer w-48">
             <option>All Departments</option>
          </select>
          <button className="bg-blue-600 text-white px-5 py-2 rounded-lg font-bold text-sm shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            + Create Budget
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        {/* Total Budget */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 text-xl shrink-0">💵</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Total Budget</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 12,00,000</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 8% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last year</span></div>
           </div>
        </div>

        {/* Actual Spend */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl shrink-0">🪙</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Actual Spend (YTD)</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 8,45,300</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↑ 12% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs same period last year</span></div>
           </div>
        </div>

        {/* Forecast Spend */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-purple-100 flex items-center justify-center text-purple-600 text-xl shrink-0">📊</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Forecast Spend (FY)</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 11,60,000</div>
              <div className="text-[10px] font-bold text-green-500 flex items-center gap-1 mt-1">↓ 3% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs budget</span></div>
           </div>
        </div>

        {/* Projected Variance */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm relative overflow-hidden flex flex-col gap-2">
           <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 text-xl shrink-0">🎯</div>
              <div className="text-sm font-bold text-slate-600 leading-tight">Projected Variance</div>
           </div>
           <div>
              <div className="text-3xl font-black text-[#0B2550] tracking-tight">$ 40,000</div>
              <div className="text-[10px] font-bold text-red-500 flex items-center gap-1 mt-1">↓ 67% <span className="text-slate-400 font-semibold uppercase tracking-wider">vs last forecast</span></div>
           </div>
        </div>
      </div>

      {/* Main Charts Row 1 */}
      <div className="grid grid-cols-12 gap-4">
        {/* Budget vs Actual vs Forecast */}
        <div className="col-span-6 bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📄</span> Budget vs Actual vs Forecast</h3>
              <select className="text-[10px] font-bold text-slate-500 border border-slate-200 rounded px-2 py-1 outline-none bg-transparent cursor-pointer">
                 <option>Monthly</option>
              </select>
           </div>
           
           <div className="flex items-center justify-center gap-6 text-[10px] font-bold text-slate-600 mb-6 mt-2">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Budget</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> Actual</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span> Forecast</span>
           </div>
           
           <div className="h-56 flex items-end justify-between relative px-2 mb-2 w-full">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              
              <div className="absolute inset-0 flex flex-col justify-between">
                 {[...Array(6)].map((_, i) => (
                    <div key={i} className="w-full border-t border-slate-100" style={{height: '1px'}}></div>
                 ))}
              </div>

              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-8">
                 <span>250K</span><span>200K</span><span>150K</span><span>100K</span><span>50K</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[9px] font-bold text-slate-400 -mb-5 px-6">
                 <span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span><span>Sep</span><span>Oct</span><span>Nov</span><span>Dec</span><span>Jan</span><span>Feb</span><span>Mar</span>
              </div>
              
              <div className="relative w-full h-full flex justify-between items-end pb-0 px-4 z-10">
                 {[
                    { m: 'Apr', b: 40, a: 38 },
                    { m: 'May', b: 45, a: 42 },
                    { m: 'Jun', b: 48, a: 45 },
                    { m: 'Jul', b: 52, a: 50 },
                    { m: 'Aug', b: 58, a: 55 },
                    { m: 'Sep', b: 62, a: 60 },
                    { m: 'Oct', b: 68, a: 65 },
                    { m: 'Nov', b: 70, a: 72 },
                    { m: 'Dec', b: 75, a: 78 },
                    { m: 'Jan', b: 80, a: 0 },
                    { m: 'Feb', b: 85, a: 0 },
                    { m: 'Mar', b: 90, a: 0 },
                 ].map((d, i) => (
                    <div key={i} className="flex flex-col justify-end items-center h-full w-4 md:w-6 gap-0.5">
                       <div className="flex items-end h-full w-full gap-0.5">
                          <div className="w-1/2 bg-blue-500 rounded-t-sm" style={{height: `${d.b}%`}}></div>
                          {d.a > 0 && <div className="w-1/2 bg-emerald-500 rounded-t-sm" style={{height: `${d.a}%`}}></div>}
                       </div>
                    </div>
                 ))}
              </div>

              {/* Yellow Line (Forecast) */}
              <svg className="absolute inset-0 h-full w-full z-20 pointer-events-none" preserveAspectRatio="none">
                 <path d="M20,130 L55,120 L90,115 L125,108 L160,100 L195,95 L230,85 L265,80 L300,70 L335,65 L370,55 L405,50" fill="none" stroke="#f59e0b" strokeWidth="2" strokeDasharray="4,4" />
                 {[20, 55, 90, 125, 160, 195, 230, 265, 300, 335, 370, 405].map((cx, i) => {
                    const cy = [130, 120, 115, 108, 100, 95, 85, 80, 70, 65, 55, 50][i];
                    return <circle key={i} cx={cx} cy={cy} r="3" fill="#f59e0b" />
                 })}
              </svg>
           </div>
        </div>

        {/* Spend by Category (YTD) */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">🎯</span> Spend by Category (YTD)</h3>
           
           <div className="flex items-center justify-center gap-6 mt-2">
              <div className="relative w-40 h-40 shrink-0">
                 <svg viewBox="0 0 36 36" className="w-full h-full transform -rotate-90">
                    <path className="text-blue-500" strokeWidth="7" strokeDasharray="28, 100" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-emerald-500" strokeWidth="7" strokeDasharray="18, 100" strokeDashoffset="-28" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-amber-500" strokeWidth="7" strokeDasharray="15, 100" strokeDashoffset="-46" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-purple-500" strokeWidth="7" strokeDasharray="12, 100" strokeDashoffset="-61" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-orange-500" strokeWidth="7" strokeDasharray="10, 100" strokeDashoffset="-73" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-red-500" strokeWidth="7" strokeDasharray="8, 100" strokeDashoffset="-83" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-indigo-400" strokeWidth="7" strokeDasharray="5, 100" strokeDashoffset="-91" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    <path className="text-slate-400" strokeWidth="7" strokeDasharray="4, 100" strokeDashoffset="-96" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                 </svg>
                 <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                    <span className="text-[15px] font-black text-[#0B2550] leading-tight">$ 8,45,300</span>
                    <span className="text-[9px] font-bold text-slate-500 mt-0.5">Actual Spend</span>
                 </div>
              </div>
              
              <div className="space-y-1.5 flex-1">
                 {[
                    { label: 'Operations', pct: '28%', color: 'bg-blue-500' },
                    { label: 'Manufacturing', pct: '18%', color: 'bg-emerald-500' },
                    { label: 'IT & Software', pct: '15%', color: 'bg-amber-500' },
                    { label: 'Facilities', pct: '12%', color: 'bg-purple-500' },
                    { label: 'Marketing', pct: '10%', color: 'bg-orange-500' },
                    { label: 'HR', pct: '8%', color: 'bg-red-500' },
                    { label: 'Travel & Expenses', pct: '5%', color: 'bg-indigo-400' },
                    { label: 'Other', pct: '4%', color: 'bg-slate-400' },
                 ].map((item, i) => (
                    <div key={i} className="flex items-center justify-between">
                       <div className="flex items-center gap-2"><span className={`w-2 h-2 rounded-full ${item.color}`}></span><span className="text-[10px] font-bold text-slate-700">{item.label}</span></div>
                       <span className="text-[10px] font-black text-[#0B2550]">{item.pct}</span>
                    </div>
                 ))}
              </div>
           </div>
        </div>

        {/* Forecast Accuracy */}
        <div className="col-span-2 bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-6 text-sm"><span className="text-blue-600">🎯</span> Forecast Accuracy</h3>
           
           <div className="flex-1 flex flex-col items-center justify-center -mt-6">
              <div className="flex items-center gap-3 mb-2">
                 <div className="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-500 text-2xl">✓</div>
                 <div>
                    <div className="text-3xl font-black text-[#0B2550]">97%</div>
                 </div>
              </div>
              <div className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full mb-6">Within acceptable range</div>
              
              <div className="w-full h-3 bg-slate-100 rounded-sm overflow-hidden mb-8">
                 <div className="h-full bg-emerald-500 rounded-sm" style={{width: '97%'}}></div>
              </div>
              
              <div className="w-full space-y-3 pt-4 border-t border-slate-100">
                 <div className="flex justify-between items-center text-xs">
                    <span className="text-slate-500 font-bold text-[10px]">MAPE (Mean Absolute % Error)</span>
                    <span className="font-black text-[#0B2550]">3.2%</span>
                 </div>
                 <div className="flex justify-between items-center text-xs">
                    <span className="text-slate-500 font-bold text-[10px]">Last Forecast (Jul 2025)</span>
                    <span className="font-black text-[#0B2550]">5.8%</span>
                 </div>
              </div>
           </div>
        </div>
      </div>

      {/* Main Charts Row 2 */}
      <div className="grid grid-cols-12 gap-4">
        {/* Department Budget Overview */}
        <div className="col-span-7 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">🏢</span> Department Budget Overview</h3>
              <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Department</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Budget (USD)</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Actual (YTD)</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Forecast (FY)</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-right">Variance</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center">% Used</th>
                       <th className="py-2 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider"></th>
                    </tr>
                 </thead>
                 <tbody className="text-[11px] font-semibold text-slate-700">
                    {[
                       { dept: 'Manufacturing', bud: '3,00,000', act: '2,48,700', for: '2,95,000', var: '- 5,000', varColor: 'text-emerald-500', pct: 83, bar: 'bg-emerald-500' },
                       { dept: 'R&D', bud: '1,50,000', act: '1,12,300', for: '1,48,000', var: '- 2,000', varColor: 'text-emerald-500', pct: 75, bar: 'bg-emerald-500' },
                       { dept: 'Sales & Marketing', bud: '1,20,000', act: '98,400', for: '1,18,000', var: '- 2,000', varColor: 'text-emerald-500', pct: 82, bar: 'bg-amber-500' },
                       { dept: 'IT & Software', bud: '1,00,000', act: '84,600', for: '1,05,000', var: '+ 5,000', varColor: 'text-red-500', pct: 85, bar: 'bg-emerald-500' },
                       { dept: 'Operations', bud: '1,80,000', act: '1,21,800', for: '1,75,000', var: '- 5,000', varColor: 'text-emerald-500', pct: 68, bar: 'bg-amber-500' },
                       { dept: 'HR', bud: '75,000', act: '54,200', for: '72,000', var: '- 3,000', varColor: 'text-emerald-500', pct: 72, bar: 'bg-amber-500' },
                       { dept: 'Facilities', bud: '60,000', act: '47,300', for: '58,000', var: '- 2,000', varColor: 'text-emerald-500', pct: 79, bar: 'bg-amber-500' },
                       { dept: 'Travel & Expenses', bud: '45,000', act: '32,700', for: '40,000', var: '- 5,000', varColor: 'text-emerald-500', pct: 73, bar: 'bg-amber-500' },
                       { dept: 'Other', bud: '70,000', act: '45,300', for: '69,000', var: '- 1,000', varColor: 'text-emerald-500', pct: 65, bar: 'bg-amber-500' },
                    ].map((item, i) => (
                       <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                          <td className="py-2.5 text-[#0B2550] font-bold text-[10px]">{item.dept}</td>
                          <td className="py-2.5 text-right font-mono font-medium">{item.bud}</td>
                          <td className="py-2.5 text-right font-mono font-medium">{item.act}</td>
                          <td className="py-2.5 text-right font-mono font-medium">{item.for}</td>
                          <td className={`py-2.5 text-right font-mono font-bold ${item.varColor}`}>{item.var}</td>
                          <td className="py-2.5 text-center font-bold text-[#0B2550]">{item.pct}%</td>
                          <td className="py-2.5 px-2 w-20">
                             <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                                <div className={`h-full ${item.bar} rounded-full`} style={{width: `${item.pct}%`}}></div>
                             </div>
                          </td>
                       </tr>
                    ))}
                 </tbody>
              </table>
           </div>
        </div>

        {/* 12-Month Forecast */}
        <div className="col-span-5 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">📈</span> 12-Month Forecast</h3>
           
           <div className="flex items-center justify-center gap-6 text-[10px] font-bold text-slate-600 mb-6 mt-2">
              <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-blue-500"></span><span className="w-1.5 h-1.5 rounded-full bg-blue-500 -ml-2.5"></span> Actual Spend</span>
              <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-purple-500"></span><span className="w-1.5 h-1.5 rounded-full bg-purple-500 -ml-2.5"></span> Forecast</span>
              <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-emerald-500"></span><span className="w-1.5 h-1.5 rounded-full bg-emerald-500 -ml-2.5"></span> Budget</span>
           </div>
           
           <div className="h-56 flex items-end justify-between relative px-2 mb-2">
              <div className="absolute inset-0 border-b border-l border-slate-200"></div>
              
              <div className="absolute inset-0 flex flex-col justify-between">
                 {[...Array(6)].map((_, i) => (
                    <div key={i} className="w-full border-t border-slate-100" style={{height: '1px'}}></div>
                 ))}
              </div>

              {/* Vertical line separating Actual and Forecast */}
              <div className="absolute top-0 bottom-0 left-[50%] border-l border-dashed border-slate-300 z-0"></div>
              <div className="absolute top-10 left-[60%] text-[9px] font-bold text-slate-400 bg-white/80 px-2 py-0.5 rounded flex items-center">
                 <span className="opacity-50 mr-1">⟵</span> Forecast Period <span className="opacity-50 ml-1">⟶</span>
              </div>

              <div className="absolute left-0 bottom-0 top-0 w-full flex flex-col justify-between text-[9px] font-bold text-slate-400 -ml-8">
                 <span>250K</span><span>200K</span><span>150K</span><span>100K</span><span>50K</span><span>0</span>
              </div>
              <div className="absolute left-0 bottom-0 right-0 w-full flex justify-between text-[9px] font-bold text-slate-400 -mb-5 px-4">
                 <span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span><span>Sep</span><span>Oct</span><span>Nov</span><span>Dec</span><span>Jan</span><span>Feb</span><span>Mar</span>
              </div>
              
              <svg className="absolute inset-0 h-full w-full z-10" preserveAspectRatio="none">
                 {/* Blue Line (Actual) */}
                 <path d="M15,160 L45,150 L75,140 L105,130 L135,120 L165,110" fill="none" stroke="#3b82f6" strokeWidth="2" />
                 {[15, 45, 75, 105, 135, 165].map((cx, i) => {
                    const cy = [160, 150, 140, 130, 120, 110][i];
                    return <circle key={i} cx={cx} cy={cy} r="3" fill="#3b82f6" stroke="#fff" strokeWidth="1" />
                 })}

                 {/* Purple Line (Forecast) */}
                 <path d="M165,110 L195,100 L225,90 L255,80 L285,70 L315,60 L345,55" fill="none" stroke="#a855f7" strokeWidth="2" strokeDasharray="4,2" />
                 {[195, 225, 255, 285, 315, 345].map((cx, i) => {
                    const cy = [100, 90, 80, 70, 60, 55][i];
                    return <circle key={i} cx={cx} cy={cy} r="3" fill="#a855f7" stroke="#fff" strokeWidth="1" />
                 })}

                 {/* Green Line (Budget) */}
                 <path d="M165,95 L195,90 L225,85 L255,80 L285,75 L315,70 L345,65" fill="none" stroke="#10b981" strokeWidth="2" strokeDasharray="4,2" />
                 {[165, 195, 225, 255, 285, 315, 345].map((cx, i) => {
                    const cy = [95, 90, 85, 80, 75, 70, 65][i];
                    return <circle key={i} cx={cx} cy={cy} r="3" fill="#10b981" stroke="#fff" strokeWidth="1" />
                 })}
              </svg>
           </div>
        </div>
      </div>

      {/* Main Charts Row 3 */}
      <div className="grid grid-cols-12 gap-4">
        {/* Recent Budget Activities */}
        <div className="col-span-5 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-blue-600">📄</span> Recent Budget Activities</h3>
              <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                 <thead>
                    <tr className="border-b border-slate-100">
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider">Date</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider">Activity</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider">Details</th>
                       <th className="py-2 text-[9px] font-extrabold text-slate-400 uppercase tracking-wider">User</th>
                    </tr>
                 </thead>
                 <tbody className="text-[11px] font-semibold text-slate-700">
                    {[
                       { date: 'Aug 30, 2025', act: 'Forecast Updated', dot: 'bg-blue-500', det: 'Q3 forecast revised (Operations)', usr: 'Priya Iyer' },
                       { date: 'Aug 28, 2025', act: 'Budget Approved', dot: 'bg-emerald-500', det: 'IT budget increase by $5,000', usr: 'Ravi Kumar' },
                       { date: 'Aug 25, 2025', act: 'Variance Alert', dot: 'bg-amber-500', det: 'Marketing spend 12% above budget', usr: 'System' },
                       { date: 'Aug 22, 2025', act: 'New Budget', dot: 'bg-purple-500', det: 'FY 2025-26 budget created', usr: 'Alex Sharma' },
                    ].map((item, i) => (
                       <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                          <td className="py-3 text-slate-500 text-[10px]">{item.date}</td>
                          <td className="py-3 text-[#0B2550] font-bold text-[10px] flex items-center gap-2"><span className={`w-1.5 h-1.5 rounded-full ${item.dot}`}></span> {item.act}</td>
                          <td className="py-3 text-slate-600 text-[10px]">{item.det}</td>
                          <td className="py-3 text-slate-500 text-[10px]">{item.usr}</td>
                       </tr>
                    ))}
                 </tbody>
              </table>
           </div>
        </div>

        {/* Key Alerts */}
        <div className="col-span-4 bg-white rounded-xl border border-slate-200 p-5 shadow-sm flex flex-col">
           <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-[#0B2550] flex items-center gap-2 text-sm"><span className="text-red-500">🔔</span> Key Alerts</h3>
              <button className="text-[10px] font-bold text-blue-600 hover:underline">View All</button>
           </div>
           
           <div className="flex-1 space-y-4">
              {[
                 { icon: '!', iconColor: 'bg-red-100 text-red-600', text: 'Marketing spend is 12% above budget', date: 'Aug 25, 2025' },
                 { icon: 'i', iconColor: 'bg-blue-100 text-blue-600', text: 'IT forecast exceeds budget by $5,000', date: 'Aug 23, 2025' },
                 { icon: 'i', iconColor: 'bg-blue-100 text-blue-600', text: 'Travel expenses trending higher (+15%)', date: 'Aug 20, 2025' },
                 { icon: '!', iconColor: 'bg-amber-100 text-amber-600', text: 'Facilities budget utilization at 90%', date: 'Aug 18, 2025' },
              ].map((alert, i) => (
                 <div key={i} className="flex items-start gap-3">
                    <div className={`w-5 h-5 rounded-full flex items-center justify-center font-bold text-xs shrink-0 mt-0.5 ${alert.iconColor}`}>{alert.icon}</div>
                    <div className="flex-1 flex justify-between items-start gap-2">
                       <p className="text-[11px] font-semibold text-[#0B2550] leading-tight">{alert.text}</p>
                       <span className="text-[9px] text-slate-400 whitespace-nowrap">{alert.date}</span>
                    </div>
                 </div>
              ))}
           </div>
        </div>

        {/* Quick Actions */}
        <div className="col-span-3 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
           <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4 text-sm"><span className="text-blue-600">⚡</span> Quick Actions</h3>
           
           <div className="grid grid-cols-2 gap-3 mt-2">
              <button className="flex items-center gap-2 p-3 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-sm">📄</span>
                 <span className="text-[10px] font-bold text-blue-700 text-left">Create<br/>Budget</span>
              </button>
              <button className="flex items-center gap-2 p-3 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-sm">📈</span>
                 <span className="text-[10px] font-bold text-blue-700 text-left">Update<br/>Forecast</span>
              </button>
              <button className="flex items-center gap-2 p-3 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-sm">⚖️</span>
                 <span className="text-[10px] font-bold text-blue-700 text-left">Compare<br/>Scenarios</span>
              </button>
              <button className="flex items-center gap-2 p-3 border border-blue-100 bg-blue-50/50 rounded-xl hover:bg-blue-100 transition-colors">
                 <span className="text-blue-600 text-sm">📥</span>
                 <span className="text-[10px] font-bold text-blue-700 text-left">Download<br/>Report</span>
              </button>
           </div>
        </div>
      </div>
      
    </div>
  );
}
