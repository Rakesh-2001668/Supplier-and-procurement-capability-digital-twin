'use client';

import React, { useState } from 'react';
import { 
  ChevronRight, Truck, Package, Calendar, MapPin, Check,
  Settings, ArrowRight, CheckCircle, FileText, UploadCloud, Info, CheckCircle2, Box
} from 'lucide-react';
import Link from 'next/link';
import { apiClient, TEST_SUPPLIER_TENANT_ID } from '@/lib/apiClient';

export default function CreateASN() {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [carrier, setCarrier] = useState('FedEx Aerospace Freight');
  const [trackingNumber, setTrackingNumber] = useState('FX-889120412-US');
  const [shipmentDate, setShipmentDate] = useState(new Date().toLocaleDateString());
  const [grossWeight, setGrossWeight] = useState('150');
  const [packagesCount, setPackagesCount] = useState(2);
  const [cocNumber, setCocNumber] = useState('COC-AS9100D-APEX-2026');
  const [notes, setNotes] = useState('Precision CNC parts packed in vacuum sealed anti-corrosion VCI bags with shock sensors.');
  const [resultData, setResultData] = useState<any>(null);

  const poData = {
    id: 'PO-2025-00123',
    buyer: 'SupplyTwin Enterprise Corp',
    shipTo: 'Aerospace Integration Facility, Seattle, WA',
    expectedDate: 'Oct 18, 2025',
  };

  const [items, setItems] = useState([
    { id: 1, code: 'FG-SENS-HSG-30', desc: 'Hermetically Sealed Avionics Sensor Housings', ordered: 50, previouslyShipped: 0, toShip: 50, uom: 'pcs' },
    { id: 2, code: 'FG-ACT-SHF-01', desc: 'Precision Flight-Actuator Drive Shafts (CMM Certified)', ordered: 20, previouslyShipped: 0, toShip: 20, uom: 'pcs' },
    { id: 3, code: 'FG-FLG-ASMY-88', desc: 'Micro-Tolerance Aerospace Flange Mount Assembly', ordered: 40, previouslyShipped: 0, toShip: 40, uom: 'pcs' },
  ]);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      const itemsPayload = items.map(i => ({
        sku: i.code,
        name: i.desc,
        quantity: i.toShip
      }));

      const res = await apiClient.post(`/api/v1/procurement/purchase-orders/${poData.id}/asn`, {
        carrier: carrier,
        tracking_number: trackingNumber,
        estimated_delivery: poData.expectedDate,
        packages_count: Number(packagesCount),
        coc_number: cocNumber,
        notes: notes,
        shipped_quantity: items.reduce((acc, i) => acc + i.toShip, 0),
        items: itemsPayload,
        tenant_id: TEST_SUPPLIER_TENANT_ID
      });

      setResultData(res.data);
      setIsSuccess(true);
    } catch (err: any) {
      console.error(err);
      alert(err.response?.data?.detail || 'Error transmitting ASN and updating inventory.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isSuccess) {
    const asnId = resultData?.asn_id || 'ASN-CONFIRMED';
    const deductions = resultData?.deductions || [];

    return (
      <div className="max-w-4xl mx-auto space-y-6 pt-10 pb-20 animate-in fade-in duration-500 text-center">
        <div className="w-20 h-20 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4 border-2 border-emerald-300">
           <Truck size={40} className="text-emerald-700"/>
        </div>
        <h1 className="text-3xl font-black text-[#0B2550] tracking-tight mb-2">Advance Ship Notice (ASN) Transmitted</h1>
        <p className="text-gray-600 font-medium text-base max-w-lg mx-auto">
          Your shipment notice <span className="font-mono font-bold text-blue-700">{asnId}</span> has been transmitted to the buyer. Purchase order {poData.id} has been marked as <strong>SHIPPED</strong>.
        </p>

        {/* Live Inventory Deduction Summary */}
        <div className="bg-emerald-50/70 border border-emerald-200 rounded-2xl p-5 max-w-md mx-auto text-left shadow-sm">
          <div className="flex items-center gap-2 text-emerald-900 font-black text-xs uppercase tracking-wider mb-2">
            <CheckCircle2 size={16} className="text-emerald-600" />
            Inventory Stock Deducted from Finished Goods Depot
          </div>
          <div className="space-y-1.5 text-xs">
            {deductions.length > 0 ? (
              deductions.map((d: any, idx: number) => (
                <div key={idx} className="flex justify-between items-center bg-white p-2 rounded-lg border border-emerald-100">
                  <div>
                    <span className="font-bold text-slate-800">{d.name}</span>
                    <span className="font-mono text-[10px] text-blue-600 ml-1.5">{d.sku}</span>
                  </div>
                  <div className="font-bold text-rose-600">
                    -{d.deducted_qty} pcs <span className="text-[10px] text-slate-500 font-normal">({d.balance_after} left)</span>
                  </div>
                </div>
              ))
            ) : (
              <p className="text-slate-600 text-xs">Finished goods items successfully deducted and logged in movement audit trail.</p>
            )}
          </div>
        </div>
        
        <div className="flex flex-wrap gap-3 justify-center mt-6">
           <Link href="/supplier/orders" className="px-5 py-2.5 bg-gray-100 text-gray-700 font-bold text-sm rounded-xl hover:bg-gray-200 transition-colors">
             Back to Orders
           </Link>
           <Link href="/supplier/inventory" className="px-5 py-2.5 bg-emerald-600 text-white font-bold text-sm rounded-xl hover:bg-emerald-700 transition-colors flex items-center gap-2 shadow">
             <Box size={16} /> View in Inventory Ledger
           </Link>
           <Link href="/supplier/invoices/create" className="px-5 py-2.5 bg-blue-600 text-white font-bold text-sm rounded-xl hover:bg-blue-700 transition-colors">
             Generate Commercial Invoice
           </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-24 pt-6">
      <div className="flex justify-between items-end">
        <div>
            <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-2">
               <span>Supplier Portal</span> <ChevronRight size={12}/> <span>Fulfillment</span> <ChevronRight size={12}/> <span className="text-[#0B2550]">Create ASN</span>
            </div>
            <h1 className="text-3xl font-black text-[#0B2550] mb-1">Advance Ship Notice (ASN)</h1>
            <p className="text-gray-500 font-medium flex items-center gap-2">
                Fulfilling order <span className="px-2 py-0.5 bg-blue-100 text-blue-800 rounded text-xs font-bold border border-blue-200">{poData.id}</span>
                <span className="text-slate-400">&bull;</span>
                <span className="text-xs text-slate-600">Buyer: <strong>{poData.buyer}</strong></span>
            </p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
         <div className="xl:col-span-2 space-y-6">
            
            {/* Shipment Details */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
               <h2 className="text-lg font-bold text-[#0B2550] flex items-center gap-2 mb-6"><Truck className="text-blue-500" size={20}/> Shipment Tracking & Logistics Info</h2>
               
               <div className="grid grid-cols-2 gap-6">
                  <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Freight Carrier <span className="text-red-500">*</span></label>
                      <select 
                        value={carrier} 
                        onChange={(e) => setCarrier(e.target.value)} 
                        className="w-full border border-gray-300 rounded-lg p-2.5 outline-none bg-white font-medium text-slate-800"
                      >
                        <option value="FedEx Aerospace Freight">FedEx Aerospace Freight</option>
                        <option value="DHL Global Forwarding">DHL Global Forwarding</option>
                        <option value="BlueDart Logistics">BlueDart Logistics</option>
                        <option value="Direct Dedicated Hauler">Direct Dedicated Hauler</option>
                      </select>
                  </div>
                  <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Waybill / Tracking Number <span className="text-red-500">*</span></label>
                      <input 
                        type="text" 
                        value={trackingNumber} 
                        onChange={(e) => setTrackingNumber(e.target.value)} 
                        className="w-full border border-gray-300 rounded-lg p-2.5 outline-none font-mono font-bold text-slate-800 focus:ring-2 focus:ring-blue-500" 
                      />
                  </div>
                  <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Shipment Date <span className="text-red-500">*</span></label>
                      <div className="relative">
                        <input 
                          type="text" 
                          value={shipmentDate} 
                          onChange={(e) => setShipmentDate(e.target.value)} 
                          className="w-full border border-gray-300 rounded-lg p-2.5 pl-10 outline-none text-slate-800" 
                        />
                        <Calendar size={16} className="absolute left-3 top-3 text-gray-400"/>
                      </div>
                  </div>
                  <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Certificate of Conformance (CoC) #</label>
                      <input 
                        type="text" 
                        value={cocNumber} 
                        onChange={(e) => setCocNumber(e.target.value)} 
                        className="w-full border border-gray-300 rounded-lg p-2.5 outline-none font-mono text-slate-800" 
                      />
                  </div>
               </div>
            </div>

            {/* Line Items */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col overflow-hidden">
               <div className="p-6 border-b border-gray-100 flex justify-between items-center bg-gradient-to-r from-blue-50/50 to-white">
                   <h2 className="text-lg font-bold text-[#0B2550] flex items-center gap-2">
                     <Package className="text-blue-500" size={20}/> Items in this Shipment
                   </h2>
                   <span className="text-xs text-emerald-700 font-semibold bg-emerald-50 px-3 py-1 rounded-full border border-emerald-200 flex items-center gap-1">
                     <CheckCircle size={14} /> Auto-deducts from Finished Goods Depot
                   </span>
               </div>
               
               <div className="overflow-x-auto p-6">
                  <table className="w-full text-sm text-left">
                     <thead className="text-gray-500 font-bold border-b-2 border-gray-100">
                        <tr>
                           <th className="pb-3">SKU Code</th>
                           <th className="pb-3">Product Description</th>
                           <th className="pb-3 text-center text-gray-400">Ordered</th>
                           <th className="pb-3 text-center text-blue-600 bg-blue-50 rounded-t-lg">Ship Qty <span className="text-red-500">*</span></th>
                           <th className="pb-3 text-center">Unit</th>
                        </tr>
                     </thead>
                     <tbody className="divide-y divide-gray-100">
                        {items.map((item, index) => (
                           <tr key={item.id} className="hover:bg-gray-50">
                              <td className="py-3 font-mono text-xs font-bold text-blue-700">{item.code}</td>
                              <td className="py-3 font-medium text-gray-800">{item.desc}</td>
                              <td className="py-3 text-center text-gray-400 font-medium">{item.ordered}</td>
                              <td className="py-2 text-center bg-blue-50/30">
                                 <input 
                                    type="number" 
                                    min="1"
                                    max={item.ordered}
                                    value={item.toShip} 
                                    onChange={(e) => {
                                       const newItems = [...items];
                                       newItems[index].toShip = parseInt(e.target.value, 10) || 0;
                                       setItems(newItems);
                                    }}
                                    className="w-20 border border-blue-300 rounded p-1.5 text-center font-bold text-blue-900 outline-none" 
                                 />
                              </td>
                              <td className="py-3 text-center text-gray-500">{item.uom}</td>
                           </tr>
                        ))}
                     </tbody>
                  </table>
               </div>
            </div>
         </div>

         {/* RIGHT COLUMN */}
         <div className="xl:col-span-1 space-y-6">
            <div className="bg-blue-50 rounded-xl border border-blue-100 p-6">
               <h3 className="font-bold text-blue-900 mb-4 flex items-center gap-2"><MapPin size={18}/> Delivery Destination</h3>
               <p className="text-sm text-blue-800 leading-relaxed mb-4">{poData.shipTo}</p>
               <div className="text-sm border-t border-blue-200 pt-3 flex justify-between">
                  <span className="text-blue-700">Expected Arrival:</span>
                  <span className="font-bold text-blue-900">{poData.expectedDate}</span>
               </div>
            </div>

            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
               <h3 className="font-bold text-[#0B2550] mb-4 flex items-center gap-2"><Package size={18} className="text-blue-500"/> Packaging Details</h3>
               <div className="space-y-4">
                  <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Total Gross Weight (kg)</label>
                      <input 
                        type="text" 
                        value={grossWeight} 
                        onChange={(e) => setGrossWeight(e.target.value)} 
                        className="w-full border border-gray-300 rounded-lg p-2.5 outline-none text-sm text-slate-800" 
                      />
                  </div>
                  <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Number of Packages / Pallets</label>
                      <input 
                        type="number" 
                        value={packagesCount} 
                        onChange={(e) => setPackagesCount(Number(e.target.value))} 
                        className="w-full border border-gray-300 rounded-lg p-2.5 outline-none text-sm text-slate-800" 
                      />
                  </div>
                  <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Packaging Notes</label>
                      <textarea 
                        rows={2} 
                        value={notes} 
                        onChange={(e) => setNotes(e.target.value)} 
                        className="w-full border border-gray-300 rounded-lg p-2 outline-none text-xs text-slate-800" 
                      />
                  </div>
               </div>
            </div>
         </div>
      </div>

      <div className="fixed bottom-0 left-0 right-0 md:left-64 bg-white border-t border-gray-200 p-4 px-8 flex justify-between items-center z-40 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)]">
        <Link href="/supplier/orders" className="px-6 py-2.5 text-gray-600 bg-white border border-gray-300 font-bold rounded-lg hover:bg-gray-50">Cancel</Link>
        <button 
          onClick={handleSubmit} 
          disabled={isSubmitting} 
          className={`px-8 py-2.5 bg-blue-600 text-white font-bold rounded-lg shadow-md flex items-center gap-2 ${isSubmitting ? 'opacity-70' : 'hover:bg-blue-700'}`}
        >
             {isSubmitting ? 'Transmitting ASN & Deducting Inventory...' : <><Check size={18}/> Transmit ASN & Ship</>}
        </button>
      </div>
    </div>
  );
}
