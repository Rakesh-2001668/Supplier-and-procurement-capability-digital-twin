"""
Lineage Model & Traversal Engine (Principle P10)
AlphaHelion Purchasing Intelligence Cloud
Maintains explicit, typed document links across the complete lifecycle:
Demand/MRP -> PR -> RFQ -> Award -> Contract -> PO -> ASN -> GR/SES -> Invoice -> Savings
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid

class LineageEngine:
    def __init__(self):
        # In-memory document_link store with fast indexing
        self.links: List[Dict[str, Any]] = []

    def record_link(
        self,
        tenant_id: str,
        from_type: str,
        from_id: str,
        to_type: str,
        to_id: str,
        link_type: str,
        from_line: int = 1,
        to_line: int = 1,
        created_by: str = "system"
    ) -> Dict[str, Any]:
        """
        Records an explicit lineage link between two business documents.
        Link types:
        - converted_from (e.g. PR from PLANNED_ORDER)
        - sourced_by (e.g. AWARD from RFQ)
        - priced_by_contract (e.g. PO from CONTRACT)
        - ordered_from (e.g. PO from PR)
        - shipped_against (e.g. ASN from PO)
        - received_against (e.g. GR from PO/ASN)
        - invoiced_against (e.g. INVOICE from PO/GR)
        - settled_by (e.g. CREDIT_NOTE against INVOICE)
        - realised_from (e.g. SAVINGS from INVOICE)
        - posted_as (e.g. ERP_DOC from INVOICE)
        """
        # Avoid duplicate links
        for existing in self.links:
            if (
                existing["tenant_id"] == tenant_id
                and existing["from_type"] == from_type
                and existing["from_id"] == from_id
                and existing["to_type"] == to_type
                and existing["to_id"] == to_id
                and existing["link_type"] == link_type
            ):
                return existing

        link_record = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "from_type": from_type,
            "from_id": from_id,
            "from_line": from_line,
            "to_type": to_type,
            "to_id": to_id,
            "to_line": to_line,
            "link_type": link_type,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": created_by
        }
        self.links.append(link_record)
        return link_record

    def get_document_chain(self, tenant_id: str, doc_type: str, doc_id: str) -> Dict[str, Any]:
        """
        Traverses both upstream (predecessors) and downstream (successors)
        to return the complete end-to-end lineage graph for an object.
        """
        upstream = []
        downstream = []

        # Find upstream predecessors (where to_id == doc_id)
        queue = [(doc_type, doc_id)]
        visited = set()
        while queue:
            curr_type, curr_id = queue.pop(0)
            key = (curr_type, curr_id)
            if key in visited:
                continue
            visited.add(key)

            for l in self.links:
                if l["tenant_id"] == tenant_id and l["to_type"] == curr_type and l["to_id"] == curr_id:
                    upstream.append(l)
                    queue.append((l["from_type"], l["from_id"]))

        # Find downstream successors (where from_id == doc_id)
        queue = [(doc_type, doc_id)]
        visited = set()
        while queue:
            curr_type, curr_id = queue.pop(0)
            key = (curr_type, curr_id)
            if key in visited:
                continue
            visited.add(key)

            for l in self.links:
                if l["tenant_id"] == tenant_id and l["from_type"] == curr_type and l["from_id"] == curr_id:
                    downstream.append(l)
                    queue.append((l["to_type"], l["to_id"]))

        # Flatten ordered lineage summary
        all_doc_ids = []
        for l in upstream:
            if l["from_id"] not in all_doc_ids:
                all_doc_ids.append(l["from_id"])
        if doc_id not in all_doc_ids:
            all_doc_ids.append(doc_id)
        for l in downstream:
            if l["to_id"] not in all_doc_ids:
                all_doc_ids.append(l["to_id"])

        return {
            "root_document": {"type": doc_type, "id": doc_id},
            "lineage_sequence": all_doc_ids,
            "upstream_links": upstream,
            "downstream_links": downstream,
            "total_links": len(upstream) + len(downstream)
        }

    def get_lineage_for_document(self, doc_id: str, tenant_id: str = "axion-mobility") -> Dict[str, Any]:
        """
        Deduces doc_type from link records and returns unified node and link graph.
        """
        doc_type = "DOCUMENT"
        for l in self.links:
            if l["from_id"] == doc_id:
                doc_type = l["from_type"]
                break
            elif l["to_id"] == doc_id:
                doc_type = l["to_type"]
                break

        chain = self.get_document_chain(tenant_id=tenant_id, doc_type=doc_type, doc_id=doc_id)

        nodes = []
        for did in chain["lineage_sequence"]:
            ntype = "DOCUMENT"
            for l in self.links:
                if l["from_id"] == did:
                    ntype = l["from_type"]
                    break
                elif l["to_id"] == did:
                    ntype = l["to_type"]
                    break
            nodes.append({"id": did, "type": ntype})

        return {
            "root_document": chain["root_document"],
            "nodes": nodes,
            "lineage_sequence": chain["lineage_sequence"],
            "upstream_links": chain["upstream_links"],
            "downstream_links": chain["downstream_links"],
            "total_links": chain["total_links"]
        }

# Global singleton engine
lineage_engine = LineageEngine()

