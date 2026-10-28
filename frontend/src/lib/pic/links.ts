// Deep links for document types (lineage, audit, copilot evidence).
// Invoices are linked by id because supplier invoice numbers can contain "/".

const ROUTES: Record<string, string> = {
  REQUISITION: '/pic/requisitions/',
  PURCHASE_ORDER: '/pic/purchase-orders/',
  SOURCING_EVENT: '/pic/sourcing/',
  CONTRACT: '/pic/contracts/',
  INVOICE: '/pic/invoices/',
  GOODS_RECEIPT: '/pic/receiving/',
  MATERIAL_REQUEST: '/pic/materials/',
  MRP_RUN: '/pic/mrp/',
  SUPPLIER: '/pic/suppliers/',
};

export function docHref(type: string, ref: string, id?: string): string | null {
  const base = ROUTES[type];
  if (!base) return null;
  if (type === 'INVOICE' && id) return base + id;
  return base + encodeURIComponent(ref);
}

export const TYPE_LABEL: Record<string, string> = {
  MRP_RUN: 'MRP run', PLANNED_ORDER: 'Planned order', REQUISITION: 'Requisition', SOURCING_EVENT: 'Sourcing event', CONTRACT: 'Contract',
  PURCHASE_ORDER: 'Purchase order', ASN: 'ASN', GOODS_RECEIPT: 'Goods receipt', RETURN_DELIVERY: 'Return delivery', INVOICE: 'Invoice',
  CREDIT_NOTE: 'Credit note', PAYMENT: 'Payment', ERP_DOCUMENT: 'ERP document', MATERIAL_REQUEST: 'Material request', MATERIAL: 'Material',
  SAVINGS_INITIATIVE: 'Savings', SERVICE_ENTRY: 'Service entry',
};
