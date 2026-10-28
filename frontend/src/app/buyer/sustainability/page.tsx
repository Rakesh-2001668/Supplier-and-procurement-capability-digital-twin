'use client';

import React, { useState } from 'react';
import { Leaf, TrendingDown, Target, CloudRain, ShieldCheck, AlertCircle, Calculator } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { PieChart, Pie, Cell, Tooltip as RechartsTooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend } from 'recharts';

const COLORS = ['#0B2550', '#3b82f6', '#10b981', '#f59e0b'];

export default function BuyerSustainability() {
  const { data: esg, isLoading } = useQuery({
    queryKey: ['scope3-emissions'],
    queryFn: async () => {
      const res = await fetch('http://localhost:8080/api/v1/esg/scope3-emissions');
      return res.json();
    }
  });

  const [calcForm, setCalcForm] = useState({ material: 'aluminum', quantity_kg: 1000, distance_km: 5000, transport_mode: 'sea' });
  const [calcResult, setCalcResult] = useState<any>(null);

  const handleCalculate = async (e: React.FormEvent) => {
    e.preventDefault();
    const res = await fetch('http://localhost:8080/api/v1/esg/carbon-calculator', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(calcForm)
    });
    setCalcResult(await res.json());
  };

  if (isLoading) return <div className="p-8 text-gray-500">Loading ESG Dashboard...</div>;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
            <Leaf size={32} className="text-green-600" />
            Scope 3 Emissions Command Center
          </h1>
          <p className="text-gray-500 mt-1">Track, analyze, and reduce your supply chain carbon footprint.</p>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
          <div className="flex items-center gap-3 text-gray-500 font-bold mb-2 uppercase text-sm"><CloudRain size={18}/> Total Scope 3 YTD</div>
          <div className="text-4xl font-black text-[#0B2550]">{esg?.total_emissions_mt.toLocaleString()} <span className="text-xl text-gray-400">MT COâ‚‚e</span></div>
          <div className="mt-2 text-green-600 font-bold text-sm flex items-center gap-1"><TrendingDown size={14}/> {esg?.yoy_reduction_percent}% vs Last Year</div>
        </div>
        <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
          <div className="flex items-center gap-3 text-gray-500 font-bold mb-2 uppercase text-sm"><Target size={18}/> Carbon Budget Utilization</div>
          <div className="text-4xl font-black text-[#0B2550]">{((esg?.total_emissions_mt / esg?.carbon_budget_mt) * 100).toFixed(1)}%</div>
          <div className="w-full bg-gray-200 rounded-full h-2 mt-3">
            <div className="bg-green-500 h-2 rounded-full" style={{ width: `${(esg?.total_emissions_mt / esg?.carbon_budget_mt) * 100}%` }}></div>
          </div>
        </div>
        <div className="bg-green-50 p-6 rounded-xl shadow-sm border border-green-200 flex flex-col justify-center items-center text-center">
          <ShieldCheck size={32} className="text-green-600 mb-2"/>
          <h3 className="font-bold text-green-900">SBTi Compliant</h3>
          <p className="text-green-700 text-sm mt-1">Your supply chain emissions are aligning with the 1.5Â°C global warming target pathway.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Charts */}
        <div className="lg:col-span-2 bg-white rounded-xl shadow-sm border border-gray-200 p-6 h-96 flex flex-col">
          <h3 className="font-bold text-gray-800 mb-4">Monthly Emissions Trend</h3>
          <div className="flex-1">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={esg?.monthly_trend}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="month" tick={{fill: '#6b7280'}} axisLine={false} tickLine={false} />
                <YAxis tick={{fill: '#6b7280'}} axisLine={false} tickLine={false} />
                <RechartsTooltip cursor={{fill: 'transparent'}} />
                <Bar dataKey="emissions" fill="#0B2550" radius={[4, 4, 0, 0]} name="MT COâ‚‚e" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 h-96 flex flex-col">
          <h3 className="font-bold text-gray-800 mb-4">Emissions by Source</h3>
          <div className="flex-1">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={esg?.breakdown_by_source} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                  {esg?.breakdown_by_source.map((entry: any, index: number) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <RechartsTooltip />
                <Legend verticalAlign="bottom" height={36}/>
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Top Suppliers & Carbon Calculator */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
          <div className="p-4 bg-gray-50 border-b border-gray-100 font-bold text-gray-800">High-Impact Suppliers</div>
          <div className="divide-y divide-gray-100">
            {esg?.top_emitting_suppliers.map((sup: any, idx: number) => (
              <div key={idx} className="p-4 flex justify-between items-center hover:bg-gray-50">
                <div>
                  <h4 className="font-bold text-[#0B2550]">{sup.supplier_name}</h4>
                  <p className="text-xs text-gray-500">Target: <span className={sup.reduction_target === 'Missed' ? 'text-red-500 font-bold' : 'text-green-500 font-bold'}>{sup.reduction_target}</span></p>
                </div>
                <div className="text-right">
                  <div className="font-black text-gray-800">{sup.emissions_mt.toLocaleString()} MT</div>
                  <div className={`text-xs font-bold px-2 py-0.5 rounded inline-block mt-1 ${sup.intensity === 'High' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'}`}>{sup.intensity} Intensity</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="lg:col-span-2 bg-[#0B2550] text-white rounded-xl shadow-md p-6 flex flex-col justify-between">
           <div>
             <h3 className="font-bold text-lg mb-2 flex items-center gap-2"><Calculator /> PO Carbon Calculator</h3>
             <p className="text-blue-200 text-sm mb-6">Simulate the environmental impact of a new purchase order before routing it.</p>
           </div>
           
           <form onSubmit={handleCalculate} className="grid grid-cols-4 gap-4 mb-6">
             <div>
               <label className="text-xs text-blue-300 font-bold uppercase block mb-1">Material</label>
               <select value={calcForm.material} onChange={e=>setCalcForm({...calcForm, material: e.target.value})} className="w-full bg-white/10 border border-blue-800 rounded p-2 outline-none">
                 <option value="aluminum" className="text-black">Aluminum</option>
                 <option value="steel" className="text-black">Steel</option>
                 <option value="plastic" className="text-black">Plastic</option>
                 <option value="electronic" className="text-black">Electronics</option>
               </select>
             </div>
             <div>
               <label className="text-xs text-blue-300 font-bold uppercase block mb-1">Qty (kg)</label>
               <input type="number" value={calcForm.quantity_kg} onChange={e=>setCalcForm({...calcForm, quantity_kg: Number(e.target.value)})} className="w-full bg-white/10 border border-blue-800 rounded p-2 outline-none" />
             </div>
             <div>
               <label className="text-xs text-blue-300 font-bold uppercase block mb-1">Distance (km)</label>
               <input type="number" value={calcForm.distance_km} onChange={e=>setCalcForm({...calcForm, distance_km: Number(e.target.value)})} className="w-full bg-white/10 border border-blue-800 rounded p-2 outline-none" />
             </div>
             <div>
               <label className="text-xs text-blue-300 font-bold uppercase block mb-1">Transport</label>
               <select value={calcForm.transport_mode} onChange={e=>setCalcForm({...calcForm, transport_mode: e.target.value})} className="w-full bg-white/10 border border-blue-800 rounded p-2 outline-none">
                 <option value="sea" className="text-black">Ocean Freight</option>
                 <option value="air" className="text-black">Air Freight</option>
                 <option value="road" className="text-black">Trucking</option>
                 <option value="rail" className="text-black">Rail</option>
               </select>
             </div>
             <button type="submit" className="col-span-4 bg-green-500 hover:bg-green-400 text-green-950 font-bold py-2 rounded transition-colors">
               Calculate Footprint
             </button>
           </form>

           {calcResult && (
             <div className="bg-white/10 rounded-lg p-4 grid grid-cols-3 gap-4 border border-blue-800">
               <div>
                 <div className="text-xs text-blue-300 font-bold uppercase">Manufacturing</div>
                 <div className="text-xl font-black">{calcResult.manufacturing_emissions_kg.toLocaleString()} <span className="text-sm font-normal">kg COâ‚‚e</span></div>
               </div>
               <div>
                 <div className="text-xs text-blue-300 font-bold uppercase">Logistics</div>
                 <div className="text-xl font-black">{calcResult.transport_emissions_kg.toLocaleString()} <span className="text-sm font-normal">kg COâ‚‚e</span></div>
               </div>
               <div className="border-l border-blue-800 pl-4">
                 <div className="text-xs text-green-400 font-bold uppercase">Total Impact</div>
                 <div className="text-2xl font-black text-green-400">{calcResult.total_co2e_kg.toLocaleString()} <span className="text-sm font-normal text-green-600">kg COâ‚‚e</span></div>
               </div>
             </div>
           )}
        </div>
      </div>
    </div>
  );
}
