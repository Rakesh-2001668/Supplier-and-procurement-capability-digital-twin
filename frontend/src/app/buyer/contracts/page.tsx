'use client';

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { FileSignature, Search, Clock, CheckCircle } from 'lucide-react';
import { useState } from 'react';

export default function ContractsPage() {
  const [searchTerm, setSearchTerm] = useState('');

  // Fetch tenantId
  const tenantId = typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || "buyer-mock" : "buyer-mock";

  const { data: contracts, isLoading } = useQuery({
    queryKey: ['contracts', tenantId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/contracts?tenant_id=${tenantId}`);
      return res.data;
    }
  });

  const getStatusBadge = (status: string) => {
    switch(status) {
      case 'FULLY_SIGNED': return <span className="bg-green-100 text-green-700 px-3 py-1 rounded-full text-xs font-bold flex items-center gap-1 w-max"><CheckCircle size={14}/> Signed</span>;
      case 'SENT_FOR_SIGNATURE': return <span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-full text-xs font-bold flex items-center gap-1 w-max"><Clock size={14}/> Pending Signatures</span>;
      default: return <span className="bg-gray-100 text-gray-700 px-3 py-1 rounded-full text-xs font-bold w-max">{status}</span>;
    }
  };

  const filtered = contracts?.filter((c: any) => c.id.toLowerCase().includes(searchTerm.toLowerCase()));

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
            <FileSignature size={32} />
            Contract Lifecycle Management
          </h1>
          <p className="text-gray-500 mt-1">Review, negotiate, and e-sign digital agreements.</p>
        </div>
        
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
          <input 
            type="text" 
            placeholder="Search contracts..." 
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[#0B2550] outline-none w-64 shadow-sm"
          />
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-md overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center text-gray-500 animate-pulse">Loading Contracts Vault...</div>
        ) : (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-100">
                <th className="p-4 text-sm font-semibold text-gray-600">Contract ID</th>
                <th className="p-4 text-sm font-semibold text-gray-600">Related PO</th>
                <th className="p-4 text-sm font-semibold text-gray-600">Supplier ID</th>
                <th className="p-4 text-sm font-semibold text-gray-600">Status</th>
                <th className="p-4 text-sm font-semibold text-gray-600 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="text-sm divide-y divide-gray-100">
              {filtered?.map((contract: any) => (
                <tr key={contract.id} className="hover:bg-gray-50 transition-colors">
                  <td className="p-4 font-mono font-medium text-[#0B2550]">{contract.id.split('-')[0]}...</td>
                  <td className="p-4 text-gray-600 font-bold">{contract.po_id}</td>
                  <td className="p-4 text-gray-600 font-mono text-xs">{contract.supplier_tenant_id}</td>
                  <td className="p-4">{getStatusBadge(contract.status)}</td>
                  <td className="p-4 text-right">
                    <button 
                      onClick={() => window.location.href=`/buyer/contracts/${contract.id}`}
                      className="px-4 py-2 bg-white text-[#0B2550] border border-gray-200 hover:bg-gray-50 font-semibold rounded-md shadow-sm transition-colors"
                    >
                      View & Sign
                    </button>
                  </td>
                </tr>
              ))}
              
              {filtered?.length === 0 && (
                 <tr><td colSpan={5} className="p-8 text-center text-gray-500">No contracts found.</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
