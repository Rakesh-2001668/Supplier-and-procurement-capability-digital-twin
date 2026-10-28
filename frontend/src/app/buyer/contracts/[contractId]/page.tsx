'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { FileSignature, ShieldCheck, PenTool, CheckCircle, Download, FileText, Clock } from 'lucide-react';
import { useParams } from 'next/navigation';
import { useState } from 'react';

export default function ContractSignaturePage() {
  const { contractId } = useParams();
  const [signatureData, setSignatureData] = useState('');

  const tenantId = typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || "buyer-mock" : "buyer-mock";

  const { data: contract, isLoading, refetch } = useQuery({
    queryKey: ['contract', contractId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/contracts/${contractId}?tenant_id=${tenantId}`);
      return res.data;
    },
    enabled: !!contractId
  });

  const handleSign = async () => {
    if (!signatureData) {
      alert("Please enter a valid signature or digital ID.");
      return;
    }
    
    try {
      await apiClient.post(`/api/v1/contracts/${contractId}/sign?tenant_id=${tenantId}`, {
        signature_data: signatureData
      });
      alert("Contract successfully signed!");
      refetch();
    } catch (error) {
      alert("Failed to sign contract");
    }
  };

  if (isLoading) {
    return <div className="p-12 text-center text-gray-500 animate-pulse">Loading Document...</div>;
  }

  if (!contract) {
    return <div className="p-12 text-center text-red-500">Contract not found.</div>;
  }

  // Determine if the current user (tenant) has signed it
  const isBuyer = tenantId.toLowerCase().includes('buyer');
  const hasMySignature = isBuyer ? contract.buyer_signature : contract.supplier_signature;
  const isFullySigned = contract.status === 'FULLY_SIGNED';

  return (
    <div className="max-w-5xl mx-auto space-y-6 pb-12">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
            <FileText size={32} />
            Digital Contract Document
          </h1>
          <p className="text-gray-500 mt-1">ID: {contract.id}</p>
        </div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 px-4 py-2 border border-gray-300 bg-white rounded-md text-gray-700 hover:bg-gray-50 transition-colors font-medium shadow-sm">
            <Download size={18} /> Download PDF
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-lg border border-gray-200 overflow-hidden flex">
        {/* Document Viewer */}
        <div className="w-2/3 bg-gray-50 p-8 border-r border-gray-200 min-h-[600px] overflow-y-auto font-serif">
          <div className="bg-white p-12 shadow-sm min-h-full whitespace-pre-wrap text-gray-800 leading-relaxed border border-gray-100">
             {contract.document_content}
             
             <div className="mt-16 pt-8 border-t border-gray-300 grid grid-cols-2 gap-12">
                <div>
                  <p className="text-gray-500 text-sm mb-4 uppercase tracking-widest font-sans font-bold">Buyer Signature</p>
                  {contract.buyer_signature ? (
                     <div className="text-[#0B2550] font-script text-2xl italic border-b border-gray-300 pb-2">
                       {contract.buyer_signature}
                     </div>
                  ) : (
                     <div className="border-b border-dashed border-gray-400 h-10 w-full opacity-50"></div>
                  )}
                </div>
                <div>
                  <p className="text-gray-500 text-sm mb-4 uppercase tracking-widest font-sans font-bold">Supplier Signature</p>
                  {contract.supplier_signature ? (
                     <div className="text-[#0B2550] font-script text-2xl italic border-b border-gray-300 pb-2">
                       {contract.supplier_signature}
                     </div>
                  ) : (
                     <div className="border-b border-dashed border-gray-400 h-10 w-full opacity-50"></div>
                  )}
                </div>
             </div>
          </div>
        </div>

        {/* Action Panel */}
        <div className="w-1/3 p-6 flex flex-col bg-white">
          <h3 className="text-xl font-bold text-[#0B2550] mb-6 flex items-center gap-2">
            <ShieldCheck className="text-green-600" /> Audit Trail
          </h3>

          <div className="space-y-6 flex-1">
             <div className="relative pl-6 border-l-2 border-green-500">
               <div className="absolute -left-1.5 top-0 w-3 h-3 rounded-full bg-green-500"></div>
               <p className="font-bold text-gray-800 text-sm">Contract Generated</p>
               <p className="text-xs text-gray-500 mt-1">From Purchase Order {contract.po_id}</p>
             </div>
             
             {contract.supplier_signature && (
               <div className="relative pl-6 border-l-2 border-green-500">
                 <div className="absolute -left-1.5 top-0 w-3 h-3 rounded-full bg-green-500"></div>
                 <p className="font-bold text-gray-800 text-sm">Supplier Signed</p>
                 <p className="text-xs text-gray-500 mt-1">Digital Identity Verified</p>
               </div>
             )}

             {contract.buyer_signature && (
               <div className="relative pl-6 border-l-2 border-green-500">
                 <div className="absolute -left-1.5 top-0 w-3 h-3 rounded-full bg-green-500"></div>
                 <p className="font-bold text-gray-800 text-sm">Buyer Signed</p>
                 <p className="text-xs text-gray-500 mt-1">Digital Identity Verified</p>
               </div>
             )}

             {isFullySigned && (
               <div className="relative pl-6 border-l-2 border-blue-500">
                 <div className="absolute -left-1.5 top-0 w-3 h-3 rounded-full bg-blue-500"></div>
                 <p className="font-bold text-blue-700 text-sm">Legally Binding</p>
                 <p className="text-xs text-blue-600 mt-1">Executed on {new Date(contract.signed_at).toLocaleString()}</p>
               </div>
             )}
          </div>

          <div className="mt-8 pt-6 border-t border-gray-100">
            {isFullySigned ? (
               <div className="bg-green-50 text-green-800 p-4 rounded-lg flex items-center gap-3">
                 <CheckCircle size={24} className="text-green-600" />
                 <div>
                   <p className="font-bold text-sm">Contract Executed</p>
                   <p className="text-xs mt-1">No further action required.</p>
                 </div>
               </div>
            ) : hasMySignature ? (
               <div className="bg-blue-50 text-blue-800 p-4 rounded-lg flex items-center gap-3">
                 <Clock size={24} className="text-blue-600" />
                 <div>
                   <p className="font-bold text-sm">Awaiting Counterparty</p>
                   <p className="text-xs mt-1">You have signed this document.</p>
                 </div>
               </div>
            ) : (
               <div className="space-y-4">
                 <div>
                   <label className="block text-sm font-bold text-gray-700 mb-2">Digital Signature</label>
                   <input 
                     type="text"
                     value={signatureData}
                     onChange={(e) => setSignatureData(e.target.value)}
                     placeholder="Type full name to sign"
                     className="w-full border border-gray-300 rounded-lg p-3 outline-none focus:ring-2 focus:ring-[#0B2550]"
                   />
                 </div>
                 <button 
                   onClick={handleSign}
                   className="w-full py-3 bg-[#0B2550] text-white rounded-lg font-bold hover:bg-blue-900 transition-colors flex items-center justify-center gap-2 shadow-md"
                 >
                   <PenTool size={18} /> Sign Document Now
                 </button>
                 <p className="text-xs text-gray-400 text-center px-4">
                   By signing, you agree to the terms and conditions outlined in the document and certify that this digital signature is legally binding.
                 </p>
               </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
