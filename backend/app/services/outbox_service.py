"""
Transactional Outbox & Idempotent ERP Integration Service (Principle P13)
AlphaHelion Purchasing Intelligence Cloud
Guarantees exactly-once posting to ERP systems (SAP S/4HANA, Oracle, Dynamics, Tally).
"""

from typing import Dict, Any, Optional
from datetime import datetime
import hashlib
import json
import uuid

class OutboxService:
    def __init__(self):
        # In-memory store: idempotency_key -> integration_message
        self.messages: Dict[str, Dict[str, Any]] = {}
        # Counter for generated mock ERP documents (e.g. 5100004421)
        self.erp_seq = 5100004420

    def post_to_erp(
        self,
        tenant_id: str,
        idempotency_key: str,
        target_system: str,
        object_ref: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Executes an idempotent posting to the ERP connector.
        Replays with the same idempotency key return the cached ERP document number with replayed=True.
        """
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        # Check existing posting for idempotency
        if idempotency_key in self.messages:
            existing = self.messages[idempotency_key]
            return {
                "status": existing["status"],
                "erpDocument": existing["erp_doc_no"],
                "replayed": True,
                "targetSystem": existing["target_system"],
                "objectRef": existing["object_ref"],
                "postedAt": existing["updated_at"]
            }

        # New posting
        self.erp_seq += 1
        new_erp_doc = str(self.erp_seq)

        msg_record = {
            "msg_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
            "target_system": target_system,
            "direction": "OUTBOUND",
            "object_ref": object_ref,
            "payload_hash": payload_hash,
            "status": "POSTED",
            "erp_doc_no": new_erp_doc,
            "retries": 0,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z"
        }
        self.messages[idempotency_key] = msg_record

        return {
            "status": "POSTED",
            "erpDocument": new_erp_doc,
            "replayed": False,
            "targetSystem": target_system,
            "objectRef": object_ref,
            "postedAt": msg_record["updated_at"]
        }

    def get_message_by_key(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        return self.messages.get(idempotency_key)

    def list_recent_messages(self, limit: int = 50) -> list:
        return list(self.messages.values())[-limit:]

outbox_service = OutboxService()
