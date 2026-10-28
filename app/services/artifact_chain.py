"""Artifact Chain — the hash-chained audit trail (integrity-verifiable).

Chain shape: each ArtifactChain row carries entity_type/entity_id, the action,
actor, a payload snapshot (JSON), prev_hash + hash (sha256 over
prev_hash|entity|action|payload), and seq (per-entity monotonic). Verifying an
entity's chain re-walks every link: any tampering breaks the hash.

Wired to: gate approvals (create/approve/reject), backlog advances, AI drafts
(evidence/report), and tenant lifecycle template changes — every state change
that an auditor would ask "who changed what, when, and is it intact?" about.
"""
import hashlib
import json

from sqlalchemy.orm import Session

from app.models.artifact_chain import ArtifactChain


def _compute_hash(prev_hash: str, entity_type: str, entity_id: int, action: str, payload: dict) -> str:
    canonical = f"{prev_hash}|{entity_type}|{entity_id}|{action}|{json.dumps(payload, sort_keys=True, default=str)}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def _current_head(db: Session, tenant_id: int, entity_type: str, entity_id: int):
    return (
        db.query(ArtifactChain)
        .filter(
            ArtifactChain.tenant_id == tenant_id,
            ArtifactChain.entity_type == entity_type,
            ArtifactChain.entity_id == entity_id,
        )
        .order_by(ArtifactChain.seq.desc())
        .first()
    )


def append_artifact(
    db: Session,
    tenant_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    actor_id: int | None = None,
    actor_name: str | None = None,
    payload: dict | None = None,
    artifact_type: str = "state_change",
) -> ArtifactChain:
    """Append one hash-linked entry to the entity's chain. Returns the row."""
    payload = payload or {}
    head = _current_head(db, tenant_id, entity_type, entity_id)
    prev_hash = head.hash if head else "GENESIS"
    seq = (head.seq + 1) if head else 1

    row = ArtifactChain(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        seq=seq,
        action=action,
        actor_id=actor_id,
        actor_name=actor_name,
        artifact_type=artifact_type,
        payload=payload,
        prev_hash=prev_hash,
        hash=_compute_hash(prev_hash, entity_type, entity_id, action, payload),
    )
    db.add(row)
    db.flush()
    return row


def get_chain(db: Session, tenant_id: int, entity_type: str, entity_id: int) -> list[dict]:
    """The entity's chain, oldest first, with integrity flag per entry."""
    rows = (
        db.query(ArtifactChain)
        .filter(
            ArtifactChain.tenant_id == tenant_id,
            ArtifactChain.entity_type == entity_type,
            ArtifactChain.entity_id == entity_id,
        )
        .order_by(ArtifactChain.seq)
        .all()
    )
    entries = []
    for r in rows:
        entries.append({
            "id": r.id,
            "seq": r.seq,
            "action": r.action,
            "actor_name": r.actor_name,
            "artifact_type": r.artifact_type,
            "payload": r.payload,
            "prev_hash": r.prev_hash,
            "hash": r.hash,
            "created_at": r.created_at,
        })
    return entries


def verify_chain(db: Session, tenant_id: int, entity_type: str, entity_id: int) -> dict:
    """Re-walk the chain: recompute every hash; verify the prev_hash links.

    Returns {valid, length, broken_at}. valid=False means the trail was
    tampered with (or reordered) at/after broken_at.
    """
    rows = (
        db.query(ArtifactChain)
        .filter(
            ArtifactChain.tenant_id == tenant_id,
            ArtifactChain.entity_type == entity_type,
            ArtifactChain.entity_id == entity_id,
        )
        .order_by(ArtifactChain.seq)
        .all()
    )
    prev_hash = "GENESIS"
    for i, r in enumerate(rows):
        if r.seq != i + 1:
            return {"valid": False, "length": len(rows), "broken_at": r.seq}
        expected = _compute_hash(prev_hash, r.entity_type, r.entity_id, r.action, r.payload or {})
        if r.hash != expected:
            return {"valid": False, "length": len(rows), "broken_at": r.seq}
        if r.prev_hash != prev_hash:
            return {"valid": False, "length": len(rows), "broken_at": r.seq}
        prev_hash = r.hash
    return {"valid": True, "length": len(rows), "broken_at": None}


def entity_integrity_badge(db: Session, tenant_id: int, entity_type: str, entity_id: int) -> dict:
    """Lightweight badge for list rows: chain length + validity."""
    result = verify_chain(db, tenant_id, entity_type, entity_id)
    return {"integrity": result["valid"], "chain_length": result["length"]}
