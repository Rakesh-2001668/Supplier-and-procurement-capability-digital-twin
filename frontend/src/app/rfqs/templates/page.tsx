"use client";
import React, { useState } from 'react';
import Link from 'next/link';

export default function RFQTemplates() {
  const [selectedItems, setSelectedItems] = useState<number[]>([]);
  
  const handleGenericAction = (actionName: string) => {
    alert(`Action triggered: ${actionName}\n\nThis feature is currently being integrated with the backend APIs.`);
  };

  const toggleSelection = (id: number) => {
    setSelectedItems(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);
  };

  const toggleAll = () => {
    if (selectedItems.length > 0) setSelectedItems([]);
    else setSelectedItems([1,2,3,4,5,6,7,8]);
  };

  const templates = [
    { id: 1, name: "Standard RFQ Template", desc: "General RFQ template for all procurement categories.", cat: "Standard", catCol: "bg-blue-50 text-blue-600", dept: "Procurement", ver: "v2.1", date: "Sep 10, 2024", author: "Alex Sharma", stat: "Active", statCol: "bg-green-100 text-green-700" },
    { id: 2, name: "Raw Material RFQ", desc: "Template for sourcing raw materials.", cat: "Raw Material", catCol: "bg-amber-50 text-amber-600", dept: "Manufacturing", ver: "v1.3", date: "Sep 08, 2024", author: "Priya Menon", stat: "Active", statCol: "bg-green-100 text-green-700" },
    { id: 3, name: "Capital Equipment RFQ", desc: "Template for machinery and equipment.", cat: "Capital Goods", catCol: "bg-purple-50 text-purple-600", dept: "Engineering", ver: "v1.0", date: "Sep 05, 2024", author: "Karthik S", stat: "Active", statCol: "bg-green-100 text-green-700" },
    { id: 4, name: "Service RFQ", desc: "Template for service contracts and external services.", cat: "Services", catCol: "bg-cyan-50 text-cyan-600", dept: "Facilities", ver: "v1.2", date: "Sep 01, 2024", author: "Anita Rao", stat: "Active", statCol: "bg-green-100 text-green-700" },
    { id: 5, name: "IT Hardware RFQ", desc: "Template for IT hardware and software procurement.", cat: "IT", catCol: "bg-red-50 text-red-600", dept: "IT", ver: "v1.1", date: "Aug 28, 2024", author: "Rohit Verma", stat: "Active", statCol: "bg-green-100 text-green-700" },
    { id: 6, name: "MRO Supplies RFQ", desc: "Template for maintenance, repair and operations supplies.", cat: "MRO", catCol: "bg-emerald-50 text-emerald-600", dept: "Maintenance", ver: "v1.0", date: "Aug 25, 2024", author: "Neha Kapoor", stat: "Draft", statCol: "bg-slate-100 text-slate-700" },
    { id: 7, name: "Project Procurement RFQ", desc: "Template for project-based procurement.", cat: "Project", catCol: "bg-indigo-50 text-indigo-600", dept: "Project Management", ver: "v1.4", date: "Aug 20, 2024", author: "Vikram Das", stat: "Active", statCol: "bg-green-100 text-green-700" },
    { id: 8, name: "Custom RFQ Template", desc: "Custom template for special requirements.", cat: "Custom", catCol: "bg-pink-50 text-pink-600", dept: "Finance", ver: "v1.0", date: "Aug 18, 2024", author: "Priya Menon", stat: "Inactive", statCol: "bg-red-100 text-red-700" },
  ];

  return (
    <div className="flex flex-col h-full animate-fade-in-up bg-[#f8fafc]">
      <div className="flex justify-between items-end shrink-0 px-8 pt-8 pb-6">
         <div>
            <div className="text-[10px] text-slate-500 font-extrabold uppercase tracking-widest mb-1.5 flex items-center gap-2"><span>RFQ Management</span><span className="text-slate-300">›</span><span className="text-[#0B2550]">Templates</span></div>
            <h1 className="text-3xl font-black text-[#0B2550] tracking-tight">RFQ Templates</h1>
            <p className="text-xs text-slate-500 font-medium mt-1">Create and manage reusable RFQ templates to standardize your sourcing process.</p>
         </div>
         <button onClick={() => handleGenericAction('Create Template')} className="px-5 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-extrabold hover:bg-blue-700 shadow-sm transition-all flex items-center gap-2">
            <span>+</span> Create Template
         </button>
      </div>

      <div className="flex gap-6 flex-1 min-h-0 px-8 pb-8">
         <div className="flex-1 flex flex-col min-w-0">
            {/* KPI Cards */}
            <div className="grid grid-cols-4 gap-4 mb-6 shrink-0">
               <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center text-xl">📄</div>
                  <div><div className="text-[10px] text-slate-500 font-bold uppercase">Total Templates</div><div className="text-xl font-black text-[#0B2550] leading-none my-1 flex items-end gap-2">12 <span className="text-[9px] font-bold text-green-600">↑ 20%</span></div><div className="text-[9px] font-medium text-slate-400">vs last month</div></div>
               </div>
               <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-amber-50 text-amber-500 flex items-center justify-center text-xl">⭐</div>
                  <div><div className="text-[10px] text-slate-500 font-bold uppercase">Standard Templates</div><div className="text-xl font-black text-[#0B2550] leading-none my-1 flex items-end gap-2">8 <span className="text-[9px] font-bold text-green-600">↑ 14%</span></div><div className="text-[9px] font-medium text-slate-400">vs last month</div></div>
               </div>
               <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-indigo-50 text-indigo-500 flex items-center justify-center text-xl">👥</div>
                  <div><div className="text-[10px] text-slate-500 font-bold uppercase">Department Templates</div><div className="text-xl font-black text-[#0B2550] leading-none my-1 flex items-end gap-2">4 <span className="text-[9px] font-bold text-green-600">↑ 33%</span></div><div className="text-[9px] font-medium text-slate-400">vs last month</div></div>
               </div>
               <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-red-50 text-red-500 flex items-center justify-center text-xl">🕒</div>
                  <div><div className="text-[10px] text-slate-500 font-bold uppercase">Recently Used</div><div className="text-xl font-black text-[#0B2550] leading-none my-1 flex items-end gap-2">6 <span className="text-[9px] font-bold text-green-600">↑ 50%</span></div><div className="text-[9px] font-medium text-slate-400">vs last month</div></div>
               </div>
            </div>

            <div className="bg-white border border-slate-200 rounded-2xl shadow-sm flex-1 flex flex-col min-h-0">
               {/* Filters */}
               <div className="p-4 border-b border-slate-100 shrink-0 bg-slate-50/50 flex gap-4 items-end">
                  <div className="relative flex-1">
                     <span className="absolute left-3 top-2.5 text-slate-400">🔍</span>
                     <input type="text" placeholder="Search template name, description..." className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 outline-none focus:border-blue-500 bg-white" />
                  </div>
                  <div className="w-48">
                     <label className="block text-[9px] font-bold text-[#0B2550] mb-0.5">Category</label>
                     <select className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 outline-none bg-white"><option>All Categories</option></select>
                  </div>
                  <div className="w-48">
                     <label className="block text-[9px] font-bold text-[#0B2550] mb-0.5">Department</label>
                     <select className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 outline-none bg-white"><option>All Departments</option></select>
                  </div>
                  <div className="w-48">
                     <label className="block text-[9px] font-bold text-[#0B2550] mb-0.5">Status</label>
                     <select className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 outline-none bg-white"><option>All Statuses</option></select>
                  </div>
                  <button onClick={() => handleGenericAction('Clear All')} className="text-xs font-bold text-slate-500 hover:text-slate-700 px-2 mb-1.5">Clear All</button>
                  <button onClick={() => handleGenericAction('Apply Filters')} className="px-4 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-700 mb-1">Apply Filters</button>
               </div>

               {/* Table */}
               <div className="flex-1 overflow-auto custom-scrollbar">
                  <table className="w-full text-left border-collapse min-w-max">
                     <thead className="sticky top-0 bg-white z-10 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
                        <tr className="border-b border-slate-200 text-[10px] font-extrabold text-[#0B2550] tracking-wider">
                           <th className="py-3 px-4 w-10"><input type="checkbox" onChange={toggleAll} checked={selectedItems.length > 0} className="rounded text-blue-600 focus:ring-blue-500 cursor-pointer" /></th>
                           <th className="py-3 px-2">Template Name ↕</th>
                           <th className="py-3 px-2 text-center">Category ↕</th>
                           <th className="py-3 px-2 text-center">Department ↕</th>
                           <th className="py-3 px-2 text-center">Version ↕</th>
                           <th className="py-3 px-2">Last Updated ↕</th>
                           <th className="py-3 px-2 text-center">Status ↕</th>
                           <th className="py-3 px-4 text-center">Actions</th>
                        </tr>
                     </thead>
                     <tbody className="divide-y divide-slate-100">
                        {templates.map((tpl, i) => (
                           <tr key={tpl.id} className="text-[11px] font-bold text-[#0B2550] hover:bg-slate-50 transition-colors cursor-pointer" onClick={() => toggleSelection(i)}>
                              <td className="py-4 px-4"><input type="checkbox" checked={selectedItems.includes(i)} readOnly className="rounded text-blue-600 focus:ring-blue-500 cursor-pointer" /></td>
                              <td className="py-4 px-2">
                                 <div className="flex items-start gap-3">
                                    <div className="text-lg text-blue-600">📄</div>
                                    <div className="w-48">
                                       <div className="text-[11px] font-bold text-blue-600 hover:underline">{tpl.name}</div>
                                       <div className="text-[10px] text-slate-500 font-normal leading-tight mt-0.5">{tpl.desc}</div>
                                    </div>
                                 </div>
                              </td>
                              <td className="py-4 px-2 text-center"><span className={`px-2 py-1 rounded text-[10px] ${tpl.catCol}`}>{tpl.cat}</span></td>
                              <td className="py-4 px-2 text-center text-slate-600 font-medium">{tpl.dept}</td>
                              <td className="py-4 px-2 text-center text-slate-600 font-medium">{tpl.ver}</td>
                              <td className="py-4 px-2">
                                 <div className="text-[11px] font-bold text-[#0B2550]">{tpl.date}</div>
                                 <div className="text-[10px] text-slate-500 font-normal">by {tpl.author}</div>
                              </td>
                              <td className="py-4 px-2 text-center"><span className={`px-2 py-1 rounded text-[10px] ${tpl.statCol}`}>{tpl.stat}</span></td>
                              <td className="py-4 px-4 text-center text-slate-400 font-black hover:text-blue-600" onClick={(e) => { e.stopPropagation(); handleGenericAction('Template Actions'); }}>⋮</td>
                           </tr>
                        ))}
                     </tbody>
                  </table>
               </div>
               
               {/* Pagination */}
               <div className="p-4 border-t border-slate-100 flex justify-between items-center shrink-0 bg-white">
                  <div className="text-[11px] text-slate-500 font-semibold">Showing 1 - 8 of 12 templates</div>
                  <div className="flex items-center gap-1">
                     <button onClick={() => handleGenericAction('First')} className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-400 hover:bg-slate-50">«</button>
                     <button onClick={() => handleGenericAction('Prev')} className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-400 hover:bg-slate-50">‹</button>
                     <button className="w-7 h-7 rounded bg-blue-600 text-white flex items-center justify-center text-[11px] font-bold">1</button>
                     <button onClick={() => handleGenericAction('Page 2')} className="w-7 h-7 rounded border border-transparent flex items-center justify-center text-slate-600 hover:bg-slate-50">2</button>
                     <button onClick={() => handleGenericAction('Page 3')} className="w-7 h-7 rounded border border-transparent flex items-center justify-center text-slate-600 hover:bg-slate-50">3</button>
                     <button onClick={() => handleGenericAction('Next')} className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-400 hover:bg-slate-50">›</button>
                     <button onClick={() => handleGenericAction('Last')} className="w-7 h-7 rounded border border-slate-200 flex items-center justify-center text-slate-400 hover:bg-slate-50">»</button>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-600">
                     <span>Rows per page</span>
                     <select className="border border-slate-200 rounded px-2 py-1 outline-none"><option>10</option></select>
                  </div>
               </div>
            </div>
         </div>

         {/* Right Sidebar */}
         <div className="w-[300px] shrink-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
            
            {/* Template Preview */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm relative">
               <h3 className="text-sm font-black text-[#0B2550] mb-4">Template Preview</h3>
               <button onClick={() => handleGenericAction('Full Screen')} className="absolute top-4 right-5 text-[9px] text-slate-600 font-bold border border-slate-200 rounded px-2 py-1 hover:bg-slate-50 flex items-center gap-1">⛶ Full Screen</button>
               
               <div className="border border-slate-200 rounded-lg p-4 bg-slate-50/50 h-64 overflow-hidden relative shadow-inner">
                  <div className="flex justify-between items-start mb-6">
                     <div className="flex items-center gap-2">
                        <div className="w-6 h-6 bg-blue-700 text-white font-black text-[10px] flex items-center justify-center rounded">ST</div>
                        <div className="leading-none"><div className="text-[10px] font-black text-[#0B2550]">SupplyTwin</div><div className="text-[6px] text-slate-500">Smarter Suppliers. Stronger Tomorrow.</div></div>
                     </div>
                     <div className="text-right">
                        <div className="text-[8px] font-bold text-[#0B2550]">Template: Standard RFQ Template</div>
                        <div className="text-[8px] text-slate-500">Version: v2.1</div>
                        <div className="text-[8px] text-slate-500">Last Updated: Sep 10, 2024</div>
                     </div>
                  </div>
                  
                  <div className="text-center text-[11px] font-black text-[#0B2550] mb-4 underline">REQUEST FOR QUOTATION (RFQ)</div>
                  
                  <div className="text-[9px] font-black text-[#0B2550] mb-2">1. General Information</div>
                  <table className="w-full text-[8px] text-[#0B2550] mb-4">
                     <tbody>
                        <tr><td className="py-0.5 text-slate-500 w-24">RFQ Reference No.</td><td className="py-0.5">[Auto-generate]</td></tr>
                        <tr><td className="py-0.5 text-slate-500">Title</td><td className="py-0.5">[Enter RFQ Title]</td></tr>
                        <tr><td className="py-0.5 text-slate-500">Description</td><td className="py-0.5">[Enter description]</td></tr>
                        <tr><td className="py-0.5 text-slate-500">Category</td><td className="py-0.5">[Select Category]</td></tr>
                        <tr><td className="py-0.5 text-slate-500">Department</td><td className="py-0.5">[Select Department]</td></tr>
                        <tr><td className="py-0.5 text-slate-500">Response Deadline</td><td className="py-0.5">[Select Date]</td></tr>
                     </tbody>
                  </table>

                  <div className="text-[9px] font-black text-[#0B2550] mb-2">2. Items & Specifications</div>
                  <table className="w-full text-[8px] text-left border-collapse">
                     <thead className="bg-slate-200">
                        <tr><th className="py-1 px-1 font-semibold">#</th><th className="py-1 px-1 font-semibold">Item Description</th><th className="py-1 px-1 font-semibold">Qty</th><th className="py-1 px-1 font-semibold">Unit</th><th className="py-1 px-1 font-semibold">Specifications</th></tr>
                     </thead>
                     <tbody className="bg-white">
                        <tr><td className="py-1 px-1 border border-slate-200">1</td><td className="py-1 px-1 border border-slate-200">[Item Description]</td><td className="py-1 px-1 border border-slate-200">[Qty]</td><td className="py-1 px-1 border border-slate-200">[Unit]</td><td className="py-1 px-1 border border-slate-200">[Specifications]</td></tr>
                     </tbody>
                  </table>
                  
                  <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-slate-50 to-transparent"></div>
               </div>
            </div>

            {/* Template Details */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm relative">
               <h3 className="text-sm font-black text-[#0B2550] mb-4 flex items-center gap-2"><span className="text-blue-500 text-lg">📄</span> Template Details</h3>
               <button onClick={() => handleGenericAction('Edit Details')} className="absolute top-4 right-5 text-[10px] text-blue-600 font-bold border border-slate-200 rounded px-2 py-1 hover:bg-slate-50 flex items-center gap-1">✏️ Edit</button>
               
               <table className="w-full text-[10px] font-semibold text-[#0B2550]">
                  <tbody>
                     <tr><td className="py-1 text-slate-500 w-24">Template Name</td><td className="py-1">: Standard RFQ Template</td></tr>
                     <tr><td className="py-1 text-slate-500">Category</td><td className="py-1">: Standard</td></tr>
                     <tr><td className="py-1 text-slate-500">Department</td><td className="py-1">: Procurement</td></tr>
                     <tr><td className="py-1 text-slate-500">Version</td><td className="py-1">: v2.1</td></tr>
                     <tr><td className="py-1 text-slate-500">Status</td><td className="py-1">: <span className="text-green-600 font-black">Active</span></td></tr>
                     <tr><td className="py-1 text-slate-500 align-top">Last Updated</td><td className="py-1">: Sep 10, 2024 by Alex Sharma</td></tr>
                     <tr><td className="py-1 text-slate-500 align-top">Description</td><td className="py-1 leading-snug">: General RFQ template for all procurement categories.</td></tr>
                  </tbody>
               </table>
            </div>

            {/* Quick Actions */}
            <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
               <h3 className="text-sm font-black text-[#0B2550] mb-4 flex items-center gap-2"><span className="text-blue-500 text-lg">⚡</span> Quick Actions</h3>
               <div className="grid grid-cols-2 gap-3">
                  <button onClick={() => handleGenericAction('Use Template')} className="p-3 border border-slate-200 rounded-xl hover:bg-slate-50 flex flex-col gap-2 transition-colors text-left group">
                     <div className="text-blue-600 text-lg">📄</div><div className="text-[10px] font-bold text-[#0B2550]">Use Template</div><div className="text-[9px] text-slate-500">Create a new RFQ</div>
                  </button>
                  <button onClick={() => handleGenericAction('Edit Template')} className="p-3 border border-slate-200 rounded-xl hover:bg-slate-50 flex flex-col gap-2 transition-colors text-left group">
                     <div className="text-blue-600 text-lg">✏️</div><div className="text-[10px] font-bold text-[#0B2550]">Edit Template</div><div className="text-[9px] text-slate-500">Modify template details</div>
                  </button>
                  <button onClick={() => handleGenericAction('Duplicate')} className="p-3 border border-slate-200 rounded-xl hover:bg-slate-50 flex flex-col gap-2 transition-colors text-left group">
                     <div className="text-blue-600 text-lg">📋</div><div className="text-[10px] font-bold text-[#0B2550]">Duplicate</div><div className="text-[9px] text-slate-500">Create a copy</div>
                  </button>
                  <button onClick={() => handleGenericAction('Download Template')} className="p-3 border border-slate-200 rounded-xl hover:bg-slate-50 flex flex-col gap-2 transition-colors text-left group">
                     <div className="text-blue-600 text-lg">📥</div><div className="text-[10px] font-bold text-[#0B2550]">Download</div><div className="text-[9px] text-slate-500">PDF / Word / Excel</div>
                  </button>
               </div>
            </div>
            
            {/* Help */}
            <div className="bg-blue-50/50 border border-blue-100 rounded-2xl p-6 shadow-sm">
               <h3 className="text-sm font-black text-[#0B2550] mb-3 flex items-center gap-2"><span className="w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-xs">?</span> Need Help?</h3>
               <ul className="space-y-2 text-[11px] font-bold text-blue-600">
                  <li className="hover:underline cursor-pointer">How to create RFQ templates</li>
                  <li className="hover:underline cursor-pointer">Template best practices</li>
                  <li className="hover:underline cursor-pointer">Managing templates</li>
                  <li className="hover:underline cursor-pointer">Watch video: Templates</li>
               </ul>
               <button className="mt-4 text-[11px] font-extrabold text-[#0B2550] flex items-center gap-1 hover:underline">Open Guide →</button>
            </div>
         </div>
      </div>
    </div>
  );
}
