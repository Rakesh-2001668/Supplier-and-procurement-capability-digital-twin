"use client";
import React, { useState } from 'react';
import Link from 'next/link';

export default function InventoryReportsPage() {
  const [activeTab, setActiveTab] = useState('Overview');
  
  const tabs = ['Overview', 'Stock Reports', 'Movement Reports', 'Valuation Reports', 'Ageing Reports', 'Reorder Reports', 'Custom Reports'];
  
  const reports = [
    { id: 1, name: "Stock Movement Report", type: "Movement Report", date: "Aug 1, 2025 - Aug 31, 2025", generatedOn: "Aug 31, 2025 10:24 AM", user: "Alex Sharma", status: "Completed" },
    { id: 2, name: "Low Stock Report", type: "Reorder Report", date: "Aug 1, 2025 - Aug 31, 2025", generatedOn: "Aug 31, 2025 09:18 AM", user: "Alex Sharma", status: "Completed" },
    { id: 3, name: "Inventory Valuation Report", type: "Valuation Report", date: "Aug 1, 2025 - Aug 31, 2025", generatedOn: "Aug 30, 2025 04:12 PM", user: "Priya Rao", status: "Completed" },
    { id: 4, name: "Ageing Report", type: "Ageing Report", date: "Jul 1, 2025 - Aug 31, 2025", generatedOn: "Aug 30, 2025 11:03 AM", user: "Neha Gupta", status: "Completed" },
    { id: 5, name: "Category Summary Report", type: "Category Report", date: "Aug 1, 2025 - Aug 31, 2025", generatedOn: "Aug 29, 2025 03:20 PM", user: "Ravi Kumar", status: "Completed" },
  ];

  return (
    <div className="p-8 animate-fade-in-up bg-[#f8fafc] min-h-full">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div>
          <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/inventory" className="hover:text-blue-600">INVENTORY</Link> <span className="text-slate-300">›</span> INVENTORY REPORTS
          </div>
          <h1 className="text-3xl font-bold text-[#0B2550] tracking-tight mb-1">Inventory Reports</h1>
          <p className="text-sm text-slate-500 font-medium">Get insights into your inventory performance, usage, and trends.</p>
        </div>
        <div className="flex gap-3">
          <button className="px-5 py-2.5 border border-slate-300 text-blue-600 font-bold text-sm rounded-lg shadow-sm hover:bg-slate-50 transition-colors flex items-center gap-2 bg-white">
            <span className="text-lg leading-none">📅</span> Schedule Report
          </button>
          <button className="px-5 py-2.5 bg-blue-600 text-white font-bold text-sm rounded-lg shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">
            <span className="text-lg leading-none">+</span> Generate Report
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-8 border-b border-slate-200 mb-6 px-2">
         {tabs.map((tab) => (
            <button
               key={tab}
               onClick={() => setActiveTab(tab)}
               className={`py-3 text-sm font-bold border-b-2 transition-colors ${activeTab === tab ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-[#0B2550]'}`}
            >
               {tab}
            </button>
         ))}
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center text-xl shrink-0 font-bold">📦</div>
          <div>
            <div className="text-2xl font-black text-[#0B2550]">1,248</div>
            <div className="text-[11px] font-bold text-slate-500 mb-0.5">Total Items</div>
            <div className="text-[10px] font-bold text-emerald-600">↑ 12% vs last month</div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center text-xl shrink-0 font-bold">🛢️</div>
          <div>
            <div className="text-xl font-black text-[#0B2550]">₹ 48.75 Lakhs</div>
            <div className="text-[11px] font-bold text-slate-500 mb-0.5">Total Inventory Value</div>
            <div className="text-[10px] font-bold text-emerald-600">↑ 8% vs last month</div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center text-xl shrink-0 font-bold">→</div>
          <div>
            <div className="text-2xl font-black text-[#0B2550]">620</div>
            <div className="text-[11px] font-bold text-slate-500 mb-0.5">Total Goods In</div>
            <div className="text-[10px] font-bold text-emerald-600">↑ 15% vs last month</div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-red-50 text-red-500 flex items-center justify-center text-xl shrink-0 font-bold">←</div>
          <div>
            <div className="text-2xl font-black text-[#0B2550]">514</div>
            <div className="text-[11px] font-bold text-slate-500 mb-0.5">Total Goods Out</div>
            <div className="text-[10px] font-bold text-emerald-600">↑ 10% vs last month</div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-amber-50 text-amber-500 flex items-center justify-center text-xl shrink-0 font-bold">⏱</div>
          <div>
            <div className="text-2xl font-black text-[#0B2550]">42</div>
            <div className="text-[11px] font-bold text-slate-500 mb-0.5">Items Low in Stock</div>
            <div className="text-[10px] font-bold text-red-500">↑ 20% vs last month</div>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-4 mb-6 items-end">
         <div className="flex flex-col flex-[1.5]">
           <label className="text-[10px] font-bold text-[#0B2550] mb-1">Date Range</label>
           <div className="relative">
             <span className="absolute left-3 top-1/2 -translate-y-1/2 text-blue-600">📅</span>
             <input type="text" defaultValue="Aug 1, 2025 - Aug 31, 2025" className="w-full pl-9 pr-8 py-2 border border-slate-300 rounded-lg text-sm font-semibold text-[#0B2550] bg-white outline-none shadow-sm" />
             <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400">⌄</span>
           </div>
         </div>
         <div className="flex flex-col flex-1">
           <label className="text-[10px] font-bold text-[#0B2550] mb-1">Report Type</label>
           <select className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-semibold text-[#0B2550] bg-white outline-none shadow-sm">
             <option>All Reports</option>
           </select>
         </div>
         <div className="flex flex-col flex-1">
           <label className="text-[10px] font-bold text-[#0B2550] mb-1">Category</label>
           <select className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-semibold text-[#0B2550] bg-white outline-none shadow-sm">
             <option>All Categories</option>
           </select>
         </div>
         <div className="flex flex-col flex-1">
           <label className="text-[10px] font-bold text-[#0B2550] mb-1">Warehouse</label>
           <select className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-semibold text-[#0B2550] bg-white outline-none shadow-sm">
             <option>All Warehouses</option>
           </select>
         </div>
         
         <button className="px-6 py-2 bg-blue-600 text-white font-bold text-sm rounded-lg shadow-sm hover:bg-blue-700 transition-colors shrink-0">Apply</button>
         <button className="px-6 py-2 border border-slate-300 text-slate-600 font-bold text-sm rounded-lg shadow-sm hover:bg-slate-50 transition-colors bg-white shrink-0">Reset</button>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-3 gap-6 mb-6">
         {/* Line Chart */}
         <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
            <div className="flex justify-between items-start mb-4">
               <h3 className="text-sm font-extrabold text-[#0B2550]">Stock Movement Trend</h3>
               <div className="flex gap-4 text-[10px] font-bold">
                  <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> <span className="text-slate-600">Goods In</span></div>
                  <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500"></span> <span className="text-slate-600">Goods Out</span></div>
               </div>
            </div>
            <div className="h-48 relative border-l border-b border-slate-200 ml-4 pb-2">
               {/* Y-Axis */}
               <div className="absolute -left-6 top-0 bottom-0 flex flex-col justify-between text-[9px] font-medium text-slate-400 py-1">
                  <span>400</span><span>300</span><span>200</span><span>100</span><span>0</span>
               </div>
               {/* X-Axis */}
               <div className="absolute -bottom-6 left-0 right-0 flex justify-between text-[9px] font-medium text-slate-400">
                  <span>Aug 1</span><span>Aug 5</span><span>Aug 10</span><span>Aug 15</span><span>Aug 20</span><span>Aug 25</span><span>Aug 31</span>
               </div>
               {/* Grid lines */}
               <div className="absolute inset-0 flex flex-col justify-between">
                  <div className="w-full h-px bg-slate-100"></div><div className="w-full h-px bg-slate-100"></div><div className="w-full h-px bg-slate-100"></div><div className="w-full h-px bg-slate-100"></div><div className="w-full h-px bg-slate-100"></div>
               </div>
               {/* Line visual (simplified SVG approximation) */}
               <svg className="absolute inset-0 w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 100 100">
                  <path d="M0,60 L15,55 L30,40 L45,65 L60,45 L75,50 L85,60 L100,45" fill="none" stroke="#10b981" strokeWidth="2" strokeLinejoin="round" />
                  <path d="M0,80 L15,75 L30,65 L45,75 L60,65 L75,70 L85,60 L100,75" fill="none" stroke="#ef4444" strokeWidth="2" strokeLinejoin="round" />
                  <circle cx="0" cy="60" r="2" fill="#10b981" />
                  <circle cx="15" cy="55" r="2" fill="#10b981" />
                  <circle cx="30" cy="40" r="2" fill="#10b981" />
                  <circle cx="0" cy="80" r="2" fill="#ef4444" />
                  <circle cx="15" cy="75" r="2" fill="#ef4444" />
                  <circle cx="30" cy="65" r="2" fill="#ef4444" />
               </svg>
            </div>
         </div>
         
         {/* Donut Chart */}
         <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
            <h3 className="text-sm font-extrabold text-[#0B2550] mb-4">Inventory by Category</h3>
            <div className="flex items-center gap-6 h-48">
               <div className="relative w-36 h-36 shrink-0 mx-auto">
                 <div className="absolute inset-0 rounded-full border-[16px] border-blue-500" style={{clipPath: 'polygon(0 0, 100% 0, 100% 100%, 50% 50%)'}}></div>
                 <div className="absolute inset-0 rounded-full border-[16px] border-emerald-500" style={{clipPath: 'polygon(100% 100%, 50% 100%, 50% 50%)'}}></div>
                 <div className="absolute inset-0 rounded-full border-[16px] border-amber-400" style={{clipPath: 'polygon(50% 100%, 0 100%, 50% 50%)'}}></div>
                 <div className="absolute inset-0 rounded-full border-[16px] border-purple-500" style={{clipPath: 'polygon(0 100%, 0 50%, 50% 50%)'}}></div>
                 <div className="absolute inset-0 rounded-full border-[16px] border-slate-400" style={{clipPath: 'polygon(0 50%, 0 0, 50% 50%)'}}></div>
                 <div className="absolute inset-0 flex flex-col items-center justify-center bg-white m-3 rounded-full shadow-inner">
                    <span className="text-xl font-black text-[#0B2550] leading-none mb-1">1,248</span>
                    <span className="text-[10px] font-bold text-slate-500">Items</span>
                 </div>
               </div>
               
               <div className="flex-1 flex flex-col gap-2 justify-center">
                  {[
                     { color: 'bg-blue-500', name: 'IT Equipment', val: '28%' },
                     { color: 'bg-emerald-500', name: 'Furniture', val: '18%' },
                     { color: 'bg-amber-400', name: 'Office Supplies', val: '15%' },
                     { color: 'bg-blue-300', name: 'Safety', val: '12%' },
                     { color: 'bg-purple-500', name: 'Chemicals', val: '10%' },
                     { color: 'bg-indigo-400', name: 'Accessories', val: '8%' },
                     { color: 'bg-slate-400', name: 'Others', val: '9%' },
                  ].map(cat => (
                     <div key={cat.name} className="flex justify-between items-center text-[10px]">
                        <div className="flex items-center gap-1.5 font-bold text-slate-600"><span className={`w-2 h-2 rounded-full ${cat.color}`}></span> {cat.name}</div>
                        <div className="font-extrabold text-[#0B2550]">{cat.val}</div>
                     </div>
                  ))}
               </div>
            </div>
         </div>
         
         {/* Bar Chart */}
         <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
            <h3 className="text-sm font-extrabold text-[#0B2550] mb-4">Stock by Warehouse</h3>
            <div className="h-48 relative border-l border-b border-slate-200 ml-6 pb-6">
               {/* Y-Axis */}
               <div className="absolute -left-7 top-0 bottom-6 flex flex-col justify-between text-[9px] font-medium text-slate-400 py-1">
                  <span>500</span><span>400</span><span>300</span><span>200</span><span>100</span><span>0</span>
               </div>
               {/* Grid lines */}
               <div className="absolute inset-0 bottom-6 flex flex-col justify-between">
                  <div className="w-full h-px bg-slate-100"></div><div className="w-full h-px bg-slate-100"></div><div className="w-full h-px bg-slate-100"></div><div className="w-full h-px bg-slate-100"></div><div className="w-full h-px bg-slate-100"></div><div className="w-full h-px bg-slate-100"></div>
               </div>
               {/* Bars */}
               <div className="absolute inset-x-2 bottom-6 top-0 flex justify-between items-end">
                  <div className="w-8 flex flex-col items-center gap-1">
                     <span className="text-[10px] font-bold text-[#0B2550]">420</span>
                     <div className="w-full bg-blue-500 rounded-t" style={{height: '84%'}}></div>
                  </div>
                  <div className="w-8 flex flex-col items-center gap-1">
                     <span className="text-[10px] font-bold text-[#0B2550]">280</span>
                     <div className="w-full bg-emerald-500 rounded-t" style={{height: '56%'}}></div>
                  </div>
                  <div className="w-8 flex flex-col items-center gap-1">
                     <span className="text-[10px] font-bold text-[#0B2550]">220</span>
                     <div className="w-full bg-amber-400 rounded-t" style={{height: '44%'}}></div>
                  </div>
                  <div className="w-8 flex flex-col items-center gap-1">
                     <span className="text-[10px] font-bold text-[#0B2550]">180</span>
                     <div className="w-full bg-purple-500 rounded-t" style={{height: '36%'}}></div>
                  </div>
                  <div className="w-8 flex flex-col items-center gap-1">
                     <span className="text-[10px] font-bold text-[#0B2550]">148</span>
                     <div className="w-full bg-slate-400 rounded-t" style={{height: '30%'}}></div>
                  </div>
               </div>
               {/* X-Axis */}
               <div className="absolute -bottom-8 left-0 right-0 flex justify-between items-start text-[9px] font-bold text-slate-500 text-center px-1">
                  <div className="w-10 leading-tight">Main<br/>Warehouse</div>
                  <div className="w-10 leading-tight">Chennai<br/>Branch</div>
                  <div className="w-10 leading-tight">Bangalore<br/>Branch</div>
                  <div className="w-10 leading-tight">Hyderabad<br/>Branch</div>
                  <div className="w-10 leading-tight mt-1">Others</div>
               </div>
            </div>
         </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col">
         <div className="px-5 py-4 border-b border-slate-200">
            <h3 className="text-sm font-extrabold text-[#0B2550]">Recent Reports</h3>
         </div>
         <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse whitespace-nowrap">
               <thead>
                  <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="py-3 px-5 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">#</th>
                  <th className="py-3 px-5 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Report Name</th>
                  <th className="py-3 px-5 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Report Type</th>
                  <th className="py-3 px-5 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Date Range</th>
                  <th className="py-3 px-5 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Generated On</th>
                  <th className="py-3 px-5 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Generated By</th>
                  <th className="py-3 px-5 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider">Status</th>
                  <th className="py-3 px-5 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider text-center">Actions</th>
                  </tr>
               </thead>
               <tbody>
                  {reports.map((report) => (
                  <tr key={report.id} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                     <td className="py-4 px-5 text-xs font-semibold text-slate-500">{report.id}</td>
                     <td className="py-4 px-5 text-xs font-bold text-[#0B2550]">{report.name}</td>
                     <td className="py-4 px-5 text-xs font-semibold text-slate-600">{report.type}</td>
                     <td className="py-4 px-5 text-xs font-semibold text-slate-600">{report.date}</td>
                     <td className="py-4 px-5 text-xs font-semibold text-[#0B2550]">{report.generatedOn}</td>
                     <td className="py-4 px-5 text-xs font-semibold text-slate-600">{report.user}</td>
                     <td className="py-4 px-5">
                        <span className="px-2.5 py-1 rounded text-[10px] font-bold bg-emerald-100 text-emerald-700 inline-block">
                           {report.status}
                        </span>
                     </td>
                     <td className="py-4 px-5 text-center flex items-center justify-center gap-2">
                        <button className="text-blue-600 text-[11px] font-bold hover:underline px-2">View</button>
                        <button className="text-blue-600 font-bold px-2">⋮</button>
                     </td>
                  </tr>
                  ))}
               </tbody>
            </table>
         </div>
         <div className="p-4 border-t border-slate-200 flex items-center justify-between text-xs font-semibold mt-auto bg-white">
            <span className="text-slate-500">Showing 1 - 5 of 28 reports</span>
            <div className="flex gap-1.5 items-center">
               <button className="w-7 h-7 flex items-center justify-center text-blue-600 hover:bg-blue-50 rounded">{'«'}</button>
               <button className="w-7 h-7 flex items-center justify-center text-blue-600 hover:bg-blue-50 rounded">{'<'}</button>
               <button className="w-7 h-7 flex items-center justify-center bg-blue-600 text-white rounded">1</button>
               <button className="w-7 h-7 flex items-center justify-center text-blue-600 hover:bg-blue-50 rounded">2</button>
               <button className="w-7 h-7 flex items-center justify-center text-blue-600 hover:bg-blue-50 rounded">3</button>
               <button className="w-7 h-7 flex items-center justify-center text-blue-600 hover:bg-blue-50 rounded">4</button>
               <button className="w-7 h-7 flex items-center justify-center text-blue-600 hover:bg-blue-50 rounded">5</button>
               <button className="w-7 h-7 flex items-center justify-center text-blue-600 hover:bg-blue-50 rounded">6</button>
               <button className="w-7 h-7 flex items-center justify-center text-blue-600 hover:bg-blue-50 rounded">{'>'}</button>
               <button className="w-7 h-7 flex items-center justify-center text-blue-600 hover:bg-blue-50 rounded">{'»'}</button>
            </div>
            <div className="flex items-center gap-2">
               <span className="text-slate-500">Rows per page</span>
               <select className="border border-slate-300 rounded px-2 py-1 bg-white outline-none text-blue-600 font-bold">
                  <option>5</option>
               </select>
            </div>
         </div>
      </div>
    </div>
  );
}
