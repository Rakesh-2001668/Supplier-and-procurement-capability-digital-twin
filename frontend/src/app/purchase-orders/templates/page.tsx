"use client";

import React, { useState } from 'react';
import Link from 'next/link';

export default function POTemplatesPage() {
  const [toast, setToast] = useState<string | null>(null);

  const showFeedback = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const templates = [
    { id: 1, name: "Standard PO Template", desc: "General purchase order template for regular procurement.", category: "Standard", catColor: "text-blue-600 bg-blue-50", dept: "Procurement", version: "v2.1", date: "Sep 10, 2025", by: "Alex Sharma", status: "Active", statColor: "text-green-700 bg-green-100" },
    { id: 2, name: "Raw Material PO", desc: "Template for raw material procurement.", category: "Raw Material", catColor: "text-amber-600 bg-amber-50", dept: "Manufacturing", version: "v1.3", date: "Sep 08, 2025", by: "Priya Menon", status: "Active", statColor: "text-green-700 bg-green-100" },
    { id: 3, name: "Capital Equipment PO", desc: "Template for capital equipment purchases.", category: "Capital Goods", catColor: "text-purple-600 bg-purple-50", dept: "Engineering", version: "v1.0", date: "Sep 05, 2025", by: "Karthik S", status: "Active", statColor: "text-green-700 bg-green-100" },
    { id: 4, name: "Service PO Template", desc: "Template for service contracts and external services.", category: "Services", catColor: "text-sky-600 bg-sky-50", dept: "Facilities", version: "v1.2", date: "Sep 01, 2025", by: "Anita Rao", status: "Active", statColor: "text-green-700 bg-green-100" },
    { id: 5, name: "IT Hardware PO", desc: "Template for IT hardware and software procurement.", category: "IT", catColor: "text-pink-600 bg-pink-50", dept: "IT", version: "v1.1", date: "Aug 28, 2025", by: "Rohit Verma", status: "Active", statColor: "text-green-700 bg-green-100" },
    { id: 6, name: "MRO Supplies PO", desc: "Template for maintenance, repair and operations supplies.", category: "MRO", catColor: "text-emerald-600 bg-emerald-50", dept: "Maintenance", version: "v1.0", date: "Aug 25, 2025", by: "Neha Kapoor", status: "Draft", statColor: "text-slate-600 bg-slate-100" },
    { id: 7, name: "Project Procurement PO", desc: "Template for project-based procurement.", category: "Project", catColor: "text-indigo-600 bg-indigo-50", dept: "Project Management", version: "v1.4", date: "Aug 20, 2025", by: "Vikram Das", status: "Active", statColor: "text-green-700 bg-green-100" },
    { id: 8, name: "Custom PO Template", desc: "Custom template for special requirements.", category: "Custom", catColor: "text-fuchsia-600 bg-fuchsia-50", dept: "Finance", version: "v1.1", date: "Aug 18, 2025", by: "Priya Menon", status: "Inactive", statColor: "text-red-700 bg-red-100" },
  ];

  return (
    <div className="flex flex-col h-full animate-fade-in-up bg-[#f8fafc]">
      {toast && (
        <div className="fixed top-5 right-5 z-50 bg-blue-600 text-white px-5 py-3 rounded-xl shadow-xl font-bold text-xs animate-in fade-in">
          {toast}
        </div>
      )}
      {/* Header */}
      <div className="flex justify-between items-end mb-6 shrink-0">
         <div>
            <div className="text-[10px] text-slate-500 font-extrabold uppercase tracking-widest mb-1.5 flex items-center gap-2"><span>Purchase Orders</span><span className="text-slate-300">›</span><span className="text-[#0B2550]">PO Templates</span></div>
            <h1 className="text-3xl font-black text-[#0B2550] tracking-tight">PO Templates</h1>
            <p className="text-xs text-slate-500 font-medium mt-1">Create and manage purchase order templates to standardize your purchasing process.</p>
         </div>
         <Link href="/purchase-orders/create">
         <button onClick={() => showFeedback('+ Create Template')}  className="px-5 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-extrabold hover:bg-blue-700 shadow-md transition-all flex items-center gap-2">
            <span>+</span> Create Template
         </button>
         </Link>
      </div>

      <div className="flex gap-6 flex-1 min-h-0">
         {/* Main Content (Left) */}
         <div className="flex-1 flex flex-col min-w-0">
            {/* KPI Cards */}
            <div className="grid grid-cols-4 gap-4 mb-6 shrink-0">
               <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center text-xl">📄</div>
                  <div><div className="text-[10px] text-slate-500 font-bold uppercase">Total Templates</div><div className="text-2xl font-black text-[#0B2550] leading-none my-1">12</div><div className="text-[9px] font-bold text-green-600 flex items-center gap-1">↑ 20% <span className="text-slate-400 font-medium">vs last month</span></div></div>
               </div>
               <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-amber-50 text-amber-500 flex items-center justify-center text-xl">⭐</div>
                  <div><div className="text-[10px] text-slate-500 font-bold uppercase">Standard Templates</div><div className="text-2xl font-black text-[#0B2550] leading-none my-1">8</div><div className="text-[9px] font-bold text-green-600 flex items-center gap-1">↑ 14% <span className="text-slate-400 font-medium">vs last month</span></div></div>
               </div>
               <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-indigo-50 text-indigo-500 flex items-center justify-center text-xl">👥</div>
                  <div><div className="text-[10px] text-slate-500 font-bold uppercase">Department Templates</div><div className="text-2xl font-black text-[#0B2550] leading-none my-1">4</div><div className="text-[9px] font-bold text-green-600 flex items-center gap-1">↓ 33% <span className="text-slate-400 font-medium">vs last month</span></div></div>
               </div>
               <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-red-50 text-red-500 flex items-center justify-center text-xl">⏱️</div>
                  <div><div className="text-[10px] text-slate-500 font-bold uppercase">Recently Used</div><div className="text-2xl font-black text-[#0B2550] leading-none my-1">6</div><div className="text-[9px] font-bold text-green-600 flex items-center gap-1">↑ 50% <span className="text-slate-400 font-medium">vs last month</span></div></div>
               </div>
            </div>

            <div className="bg-white border border-slate-200 rounded-2xl shadow-sm flex-1 flex flex-col min-h-0">
               {/* Filters */}
               <div className="p-5 border-b border-slate-100 shrink-0 bg-slate-50/50">
                  <div className="flex gap-4 items-end">
                     <div className="flex-1 relative">
                        <span className="absolute left-3 top-2.5 text-slate-400">🔍</span>
                        <input type="text" placeholder="Search template name, description..." className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 outline-none focus:border-blue-500" />
                     </div>
                     <div className="w-48">
                        <label className="block text-[10px] font-bold text-[#0B2550] mb-1">Category</label>
                        <select className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 outline-none bg-white"><option>All Categories</option></select>
                     </div>
                     <div className="w-48">
                        <label className="block text-[10px] font-bold text-[#0B2550] mb-1">Department</label>
                        <select className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 outline-none bg-white"><option>All Departments</option></select>
                     </div>
                     <div className="w-48">
                        <label className="block text-[10px] font-bold text-[#0B2550] mb-1">Status</label>
                        <select className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 outline-none bg-white"><option>All Statuses</option></select>
                     </div>
                     <button onClick={() => showFeedback('Clear All')}  className="text-xs font-bold text-blue-600 hover:underline mx-2">Clear All</button>
                     <button onClick={() => showFeedback('Apply Filters')}  className="px-5 py-2 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-700 shadow-sm">Apply Filters</button>
                  </div>
               </div>

               {/* Table */}
               <div className="flex-1 overflow-auto custom-scrollbar">
                  <table className="w-full text-left border-collapse min-w-max">
                     <thead className="sticky top-0 bg-white z-10 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
                        <tr className="border-b border-slate-200 text-[10px] font-extrabold text-[#0B2550] tracking-wider">
                           <th className="py-3 px-4 w-10"><input type="checkbox" className="rounded text-blue-600 focus:ring-blue-500" /></th>
                           <th className="py-3 px-3">Template Name ↕</th>
                           <th className="py-3 px-3">Category ↕</th>
                           <th className="py-3 px-3">Department ↕</th>
                           <th className="py-3 px-3">Version</th>
                           <th className="py-3 px-3">Last Updated ↕</th>
                           <th className="py-3 px-3 text-center">Status ↕</th>
                           <th className="py-3 px-4 text-center">Actions</th>
                        </tr>
                     </thead>
                     <tbody className="divide-y divide-slate-100">
                        {templates.map((tpl) => (
                           <tr key={tpl.id} className="text-[11px] font-bold text-[#0B2550] hover:bg-slate-50 transition-colors group">
                              <td className="py-4 px-4 align-top"><input type="checkbox" className="rounded text-blue-600 focus:ring-blue-500 mt-1" /></td>
                              <td className="py-4 px-3 align-top">
                                 <div className="flex items-start gap-3">
                                    <div className="text-blue-600 mt-0.5 text-lg">📄</div>
                                    <div>
                                       <div className="text-blue-600 cursor-pointer hover:underline text-xs">{tpl.name}</div>
                                       <div className="text-[10px] text-slate-500 font-medium mt-0.5">{tpl.desc}</div>
                                    </div>
                                 </div>
                              </td>
                              <td className="py-4 px-3 align-top pt-5"><span className={`px-2 py-1 rounded text-[10px] font-extrabold ${tpl.catColor}`}>{tpl.category}</span></td>
                              <td className="py-4 px-3 align-top pt-5 text-slate-600 font-semibold">{tpl.dept}</td>
                              <td className="py-4 px-3 align-top pt-5 text-slate-500">{tpl.version}</td>
                              <td className="py-4 px-3 align-top pt-4">
                                 <div className="text-slate-600 font-semibold">{tpl.date}</div>
                                 <div className="text-[9px] text-slate-400 font-medium">by {tpl.by}</div>
                              </td>
                              <td className="py-4 px-3 align-top pt-5 text-center"><span className={`px-2 py-1 rounded text-[10px] font-extrabold ${tpl.statColor}`}>{tpl.status}</span></td>
                              <td className="py-4 px-4 align-top pt-5 text-center text-slate-400 font-black cursor-pointer hover:text-blue-600">⋮</td>
                           </tr>
                        ))}
                     </tbody>
                  </table>
               </div>
               
               {/* Pagination */}
               <div className="p-4 border-t border-slate-100 flex justify-between items-center shrink-0">
                  <div className="text-[11px] text-slate-500 font-semibold">Showing 1 - 8 of 12 templates</div>
                  <div className="flex items-center gap-1">
                     <button onClick={() => showFeedback('«')}  className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-400 hover:bg-slate-50">«</button>
                     <button onClick={() => showFeedback('‹')}  className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-400 hover:bg-slate-50">‹</button>
                     <button onClick={() => showFeedback('1')}  className="w-7 h-7 rounded bg-blue-600 text-white flex items-center justify-center text-[11px] font-bold">1</button>
                     <button onClick={() => showFeedback('2')}  className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-600 hover:bg-slate-50 text-[11px] font-bold">2</button>
                     <button onClick={() => showFeedback('3')}  className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-600 hover:bg-slate-50 text-[11px] font-bold">3</button>
                     <button onClick={() => showFeedback('›')}  className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-400 hover:bg-slate-50">›</button>
                     <button onClick={() => showFeedback('»')}  className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-400 hover:bg-slate-50">»</button>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-600">
                     <span>Rows per page</span>
                     <select className="border border-slate-200 rounded px-2 py-1 outline-none"><option>10</option></select>
                  </div>
               </div>
            </div>
         </div>

         {/* Right Sidebar */}
         <div className="w-[360px] shrink-0 flex flex-col gap-6 overflow-y-auto custom-scrollbar pb-6">
            
            {/* Template Preview */}
            <div className="bg-white border border-slate-200 rounded-2xl shadow-sm flex flex-col h-[300px] overflow-hidden">
               <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                  <h3 className="text-[11px] font-black text-[#0B2550]">Template Preview</h3>
                  <button onClick={() => showFeedback('🔍 Full Screen')}  className="text-[10px] font-bold text-blue-600 hover:underline flex items-center gap-1"><span>🔍</span> Full Screen</button>
               </div>
               <div className="flex-1 bg-slate-100 p-4 flex items-center justify-center overflow-hidden">
                  {/* Miniature PO document representation */}
                  <div className="bg-white w-full h-full rounded shadow-sm border border-slate-200 p-3 text-[5px] flex flex-col justify-between overflow-hidden">
                     <div className="flex justify-between items-start border-b border-slate-100 pb-2">
                        <div>
                           <div className="font-bold text-[6px] text-blue-800 flex items-center gap-1"><span className="w-2 h-2 bg-blue-800 rounded"></span> SupplyTwin</div>
                           <div className="text-slate-400 mt-0.5">Smarter Suppliers. Stronger Tomorrow.</div>
                        </div>
                        <div className="text-right">
                           <div className="font-bold text-slate-700">PO NO: PO-2025-001</div>
                           <div className="text-slate-400 mt-0.5">Date: Sep 10, 2025</div>
                           <div className="text-slate-400">Version: v2.1</div>
                        </div>
                     </div>
                     <div className="text-center font-bold text-[7px] my-2 text-slate-800">PURCHASE ORDER</div>
                     <div className="flex justify-between mb-2">
                        <div><div className="font-bold text-slate-700">Bill To:</div><div className="font-bold text-slate-800">SupplyTwin Pvt Ltd</div><div className="text-slate-500">123 Business Park, Chennai</div><div className="text-slate-500">Tamil Nadu, India - 600001</div></div>
                        <div><div className="font-bold text-slate-700">Ship To:</div><div className="font-bold text-slate-800">SupplyTwin Warehouse</div><div className="text-slate-500">456 Industrial Area, Chennai</div><div className="text-slate-500">Tamil Nadu, India - 600058</div></div>
                     </div>
                     <div className="flex-1 border border-slate-100 mt-2">
                        <div className="bg-slate-50 border-b border-slate-100 flex px-1 py-0.5 font-bold text-slate-600">
                           <div className="flex-[0.5]">#</div><div className="flex-[3]">Item Description</div><div className="flex-1 text-right">Qty</div><div className="flex-1 text-center">Unit</div><div className="flex-[1.5] text-right">Unit Price</div><div className="flex-[1.5] text-right">Amount</div>
                        </div>
                        <div className="flex px-1 py-0.5 text-slate-500">
                           <div className="flex-[0.5]">1</div><div className="flex-[3]">[Item Description]</div><div className="flex-1 text-right">100</div><div className="flex-1 text-center">Nos</div><div className="flex-[1.5] text-right">₹0.00</div><div className="flex-[1.5] text-right">₹0.00</div>
                        </div>
                        <div className="flex px-1 py-0.5 text-slate-500 bg-slate-50/50">
                           <div className="flex-[0.5]">2</div><div className="flex-[3]">[Item Description]</div><div className="flex-1 text-right">50</div><div className="flex-1 text-center">Nos</div><div className="flex-[1.5] text-right">₹0.00</div><div className="flex-[1.5] text-right">₹0.00</div>
                        </div>
                     </div>
                     <div className="flex justify-end mt-2">
                        <div className="w-1/2 text-right">
                           <div className="flex justify-between"><span className="text-slate-500">Sub Total</span><span className="text-slate-700 font-bold">₹0.00</span></div>
                           <div className="flex justify-between my-0.5"><span className="text-slate-500">Taxes (GST 18%)</span><span className="text-slate-700 font-bold">₹0.00</span></div>
                           <div className="flex justify-between border-t border-slate-200 pt-0.5 mt-0.5"><span className="text-blue-800 font-bold">Total Amount</span><span className="text-blue-800 font-bold">₹0.00</span></div>
                        </div>
                     </div>
                  </div>
               </div>
            </div>

            {/* Template Details */}
            <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
               <div className="flex justify-between items-center mb-4">
                  <h3 className="text-sm font-black text-[#0B2550] flex items-center gap-2"><span className="text-blue-600 text-lg">📄</span> Template Details</h3>
                  <button onClick={() => showFeedback('✏️ Edit')}  className="px-3 py-1 border border-blue-200 rounded text-[10px] font-bold text-blue-600 hover:bg-blue-50 flex items-center gap-1"><span>✏️</span> Edit</button>
               </div>
               <div className="space-y-3 text-[11px]">
                  <div className="flex"><span className="w-28 text-slate-500 font-semibold">Template Name</span><span className="flex-1 font-bold text-[#0B2550]">: Standard PO Template</span></div>
                  <div className="flex"><span className="w-28 text-slate-500 font-semibold">Category</span><span className="flex-1 flex items-center gap-1 font-bold text-[#0B2550]">: <span className="text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">Standard</span></span></div>
                  <div className="flex"><span className="w-28 text-slate-500 font-semibold">Department</span><span className="flex-1 font-bold text-[#0B2550]">: Procurement</span></div>
                  <div className="flex"><span className="w-28 text-slate-500 font-semibold">Version</span><span className="flex-1 font-bold text-[#0B2550]">: v2.1</span></div>
                  <div className="flex"><span className="w-28 text-slate-500 font-semibold">Status</span><span className="flex-1 flex items-center gap-1 font-bold text-[#0B2550]">: <span className="text-green-700 font-extrabold">Active</span></span></div>
                  <div className="flex"><span className="w-28 text-slate-500 font-semibold">Last Updated</span><span className="flex-1 font-bold text-[#0B2550]">: Sep 10, 2025 by Alex Sharma</span></div>
                  <div className="flex"><span className="w-28 text-slate-500 font-semibold">Description</span><span className="flex-1 font-medium text-slate-600">: General purchase order template for regular procurement.</span></div>
               </div>
            </div>

            {/* Quick Actions */}
            <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
               <h3 className="text-sm font-black text-[#0B2550] mb-4 flex items-center gap-2"><span className="text-blue-600 text-lg">☁️</span> Quick Actions</h3>
               <div className="grid grid-cols-2 gap-3">
                  <Link href="/purchase-orders/create" className="border border-slate-200 rounded-xl p-3 hover:bg-slate-50 transition-colors flex flex-col gap-2">
                     <div className="text-blue-600">📄</div>
                     <div><div className="text-[10px] font-bold text-[#0B2550]">Use Template</div><div className="text-[9px] text-slate-500">Create a new PO</div></div>
                  </Link>
                  <button onClick={() => showFeedback('✏️                      Edit TemplateModify template details')}  className="border border-slate-200 rounded-xl p-3 hover:bg-slate-50 transition-colors text-left flex flex-col gap-2">
                     <div className="text-blue-600">✏️</div>
                     <div><div className="text-[10px] font-bold text-[#0B2550]">Edit Template</div><div className="text-[9px] text-slate-500">Modify template details</div></div>
                  </button>
                  <button onClick={() => showFeedback('📑                      DuplicateCreate a copy')}  className="border border-slate-200 rounded-xl p-3 hover:bg-slate-50 transition-colors text-left flex flex-col gap-2">
                     <div className="text-blue-600">📑</div>
                     <div><div className="text-[10px] font-bold text-[#0B2550]">Duplicate</div><div className="text-[9px] text-slate-500">Create a copy</div></div>
                  </button>
                  <button onClick={() => showFeedback('📥                      DownloadPDF / Word / Excel')}  className="border border-slate-200 rounded-xl p-3 hover:bg-slate-50 transition-colors text-left flex flex-col gap-2">
                     <div className="text-blue-600">📥</div>
                     <div><div className="text-[10px] font-bold text-[#0B2550]">Download</div><div className="text-[9px] text-slate-500">PDF / Word / Excel</div></div>
                  </button>
               </div>
            </div>

            <div className="bg-blue-50/50 border border-blue-100 rounded-2xl p-6 shadow-sm">
               <h3 className="text-sm font-black text-[#0B2550] mb-3 flex items-center gap-2"><span className="w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-xs">?</span> Need Help?</h3>
               <ul className="space-y-2 text-[11px] font-bold text-blue-600">
                  <li className="hover:underline cursor-pointer">How to create PO templates</li>
                  <li className="hover:underline cursor-pointer">Template field reference guide</li>
                  <li className="hover:underline cursor-pointer">Best practices for PO templates</li>
                  <li className="hover:underline cursor-pointer">Watch video: PO templates</li>
               </ul>
               <button onClick={() => showFeedback('Open Guide →')}  className="mt-4 text-[11px] font-extrabold text-[#0B2550] flex items-center gap-1 hover:underline">Open Guide →</button>
            </div>
         </div>
      </div>
    </div>
  );
}
