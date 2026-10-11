"""Core verification engine for dataset provenance and cryptographic integrity."""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from backend.chain import (
    ChainClient,
    ChainUnavailable,
    ContractRevert,
    StaleDeployment,
    default_chain_client,
)
from backend.fingerprint import (
    build_merkle_tree,
    compute_canonical_metadata_digest,
    compute_file_hash,
    find_modified_chunks,
    split_csv_into_chunks,
)


def _strip_0x(hex_str: str | None) -> str:
    if not hex_str:
        return ""
    return hex_str[2:].lower() if hex_str.startswith("0x") else hex_str.lower()


def verify_version(
    version_id: str | uuid.UUID,
    file_path: Path | str | None = None,
    storage_dir: Path | str | None = None,
    chain_client: ChainClient | None = None,
) -> dict[str, Any]:
    """Verify cryptographic integrity, Merkle tree localization, and on-chain lineage of a version.

    Expected values come EXCLUSIVELY from the blockchain smart contract.
    Returns:
        status: VERIFIED | TAMPERING_DETECTED | NOT_VERIFIABLE
        reason: Explanation of verification outcome
        checks: Individual check outcomes (True, False, or None if artifact missing/unperformed)
        details: Expected and actual hashes, chunk diffs, rollback info
        timings_ms: Execution duration for hashing, merkle, chain read, and total
    """
    t_total_start = time.perf_counter()
    v_id = str(version_id)
    client = chain_client or default_chain_client

    if storage_dir is None:
        storage_root = Path(os.getenv("STORAGE_DIR", "./storage")).resolve()
    else:
        storage_root = Path(storage_dir).resolve()

    # 1. Fetch expected values from the blockchain
    t_chain_start = time.perf_counter()
    try:
        on_chain_rec = client.get_version(v_id)
    finally:
        chain_read_ms = (time.perf_counter() - t_chain_start) * 1000.0

    dataset_id = on_chain_rec["dataset_id"]
    expected_file_hash = _strip_0x(on_chain_rec["file_hash"])
    expected_merkle_root = _strip_0x(on_chain_rec["merkle_root"])
    expected_num_chunks = int(on_chain_rec["num_chunks"])
    expected_metadata_digest = _strip_0x(on_chain_rec["metadata_digest"])
    expected_parent_version_id = on_chain_rec["parent_version_id"]
    expected_timestamp = int(on_chain_rec["timestamp"])

    checks: dict[str, bool | None] = {
        "file_hash_match": None,
        "merkle_root_match": None,
        "num_chunks_match": None,
        "tree_integrity": None,
        "metadata_digest_match": None,
        "lineage_consistency": None,
    }

    details: dict[str, Any] = {
        "version_id": v_id,
        "dataset_id": dataset_id,
        "expected_file_hash": expected_file_hash,
        "actual_file_hash": None,
        "expected_merkle_root": expected_merkle_root,
        "actual_merkle_root": None,
        "expected_num_chunks": expected_num_chunks,
        "actual_num_chunks": None,
        "changed_chunks": [],
        "extra_chunks": [],
        "missing_chunks": [],
        "localization_available": False,
        "localization_note": None,
        "matches_version_id": None,
        "lineage_summary": {
            "chain_parent_id": expected_parent_version_id,
            "chain_timestamp": expected_timestamp,
        },
    }

    hashing_ms = 0.0
    merkle_ms = 0.0

    # 2. Locate target file
    resolved_file_path: Path | None = None
    if file_path is not None:
        p = Path(file_path).resolve()
        if p.exists() and p.is_file():
            resolved_file_path = p
    else:
        # Locate file by scanning uploads/<dataset_id>/<version_id>/ directory directly
        upload_dir = storage_root / "uploads" / dataset_id / v_id
        if upload_dir.exists() and upload_dir.is_dir():
            candidates = [f for f in upload_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
            if candidates:
                resolved_file_path = candidates[0]

    # 3. Off-chain tree inspection (Untrusted tree check)
    stored_tree_leaves: list[str] | None = None
    tree_path = storage_root / "trees" / f"{v_id}.json"
    if tree_path.exists() and tree_path.is_file():
        try:
            with open(tree_path, "r", encoding="utf-8") as f:
                tree_data = json.load(f)
            stored_levels = tree_data.get("levels", [])
            if stored_levels and len(stored_levels) > 0:
                stored_tree_leaves = stored_levels[0]

                # Recompute root from stored leaves to verify tree integrity
                t_tree_check = time.perf_counter()
                curr_level = stored_tree_leaves
                while len(curr_level) > 1:
                    next_level = []
                    if len(curr_level) % 2 != 0:
                        curr_level = curr_level + [curr_level[-1]]
                    for i in range(0, len(curr_level), 2):
                        l_bytes = bytes.fromhex(curr_level[i])
                        r_bytes = bytes.fromhex(curr_level[i + 1])
                        parent_hash = hashlib.sha256(b"\x01" + l_bytes + r_bytes).hexdigest()
                        next_level.append(parent_hash)
                    curr_level = next_level

                recomputed_tree_root = _strip_0x(curr_level[0])
                checks["tree_integrity"] = (recomputed_tree_root == expected_merkle_root)
                merkle_ms += (time.perf_counter() - t_tree_check) * 1000.0
            else:
                checks["tree_integrity"] = False
        except Exception:
            checks["tree_integrity"] = False
    else:
        checks["tree_integrity"] = None

    # 4. Read file and compute cryptographic hashes
    actual_chunks = None
    if resolved_file_path is not None:
        try:
            raw_bytes = resolved_file_path.read_bytes()

            t_hash_start = time.perf_counter()
            actual_file_hash = compute_file_hash(raw_bytes)
            hashing_ms = (time.perf_counter() - t_hash_start) * 1000.0
            details["actual_file_hash"] = actual_file_hash
            checks["file_hash_match"] = (actual_file_hash.lower() == expected_file_hash.lower())

            # Read chunk_rows from off-chain metadata if available, else default 1000
            meta_path = storage_root / "metadata" / f"{v_id}.json"
            chunk_rows = 1000
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        m_data = json.load(f)
                        chunk_rows = int(m_data.get("chunk_rows", m_data.get("provenance", {}).get("chunk_rows", 1000)))
                except Exception:
                    chunk_rows = 1000

            t_merkle_start = time.perf_counter()
            actual_chunks = split_csv_into_chunks(raw_bytes, chunk_rows=chunk_rows)
            actual_merkle_root, actual_levels = build_merkle_tree(actual_chunks)
            merkle_ms += (time.perf_counter() - t_merkle_start) * 1000.0

            details["actual_merkle_root"] = actual_merkle_root
            details["actual_num_chunks"] = len(actual_chunks)
            checks["merkle_root_match"] = (actual_merkle_root.lower() == expected_merkle_root.lower())
            checks["num_chunks_match"] = (len(actual_chunks) == expected_num_chunks)

            # Localization: only if stored tree leaves matched on-chain root
            if checks["tree_integrity"] is True and stored_tree_leaves is not None:
                orig_len = len(stored_tree_leaves)
                act_len = len(actual_levels[0])
                changed = find_modified_chunks(stored_tree_leaves, actual_levels[0])
                extra = list(range(orig_len, act_len)) if act_len > orig_len else []
                missing = list(range(act_len, orig_len)) if orig_len > act_len else []
                details["changed_chunks"] = changed
                details["extra_chunks"] = extra
                details["missing_chunks"] = missing
                details["localization_available"] = True
                details["localization_note"] = (
                    "Note: insertions or deletions shift later chunk boundaries."
                )
            elif checks["tree_integrity"] is False:
                details["localization_available"] = False
                details["localization_note"] = (
                    "Stored Merkle tree does not match on-chain root; localization unavailable."
                )
            else:
                details["localization_available"] = False
                details["localization_note"] = (
                    "Tree file missing or unreadable; localization unavailable."
                )

            # Rollback / Version swap detection
            if checks["file_hash_match"] is False:
                try:
                    dataset_versions = client.get_dataset_versions(dataset_id)
                    for other_v_id in dataset_versions:
                        if other_v_id != v_id:
                            other_rec = client.get_version(other_v_id)
                            if _strip_0x(other_rec["file_hash"]).lower() == actual_file_hash.lower():
                                details["matches_version_id"] = other_v_id
                                break
                except Exception:
                    pass

        except Exception:
            checks["file_hash_match"] = None
            checks["merkle_root_match"] = None
            checks["num_chunks_match"] = None

    # 5. Off-chain metadata digest verification
    meta_path = storage_root / "metadata" / f"{v_id}.json"
    off_chain_meta = None
    if meta_path.exists() and meta_path.is_file():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                off_chain_meta = json.load(f)
            meta_copy = {k: v for k, v in off_chain_meta.items() if k != "metadata_digest"}
            recomputed_digest = compute_canonical_metadata_digest(meta_copy)
            checks["metadata_digest_match"] = (recomputed_digest.lower() == expected_metadata_digest.lower())
        except Exception:
            checks["metadata_digest_match"] = False
    else:
        checks["metadata_digest_match"] = None

    # 6. Lineage consistency verification (walk to root on-chain)
    t_lineage_start = time.perf_counter()
    lineage_ok = True
    lineage_reason = "Lineage intact"
    try:
        visited = set()
        curr_id = v_id
        prev_timestamp = None

        while curr_id:
            if curr_id in visited:
                lineage_ok = False
                lineage_reason = f"Lineage cycle detected at version {curr_id}"
                break
            visited.add(curr_id)

            node_rec = client.get_version(curr_id)
            if node_rec["dataset_id"] != dataset_id:
                lineage_ok = False
                lineage_reason = (
                    f"Lineage version {curr_id} dataset mismatch: "
                    f"expected {dataset_id}, got {node_rec['dataset_id']}"
                )
                break

            node_ts = int(node_rec["timestamp"])
            if prev_timestamp is not None and node_ts > prev_timestamp:
                # We are walking child -> parent backwards, so parent timestamp must be <= child timestamp
                lineage_ok = False
                lineage_reason = (
                    f"Non-monotonic timestamps: parent {curr_id} ({node_ts}) "
                    f"> child ({prev_timestamp})"
                )
                break
            prev_timestamp = node_ts

            curr_id = node_rec.get("parent_version_id")

        # Also check off-chain metadata parent pointer against on-chain parent pointer
        if off_chain_meta is not None:
            off_chain_parent = off_chain_meta.get("parent_version_id")
            if off_chain_parent != expected_parent_version_id:
                lineage_ok = False
                lineage_reason = (
                    f"Off-chain metadata parent_version_id ({off_chain_parent}) "
                    f"does not match on-chain parent ({expected_parent_version_id})"
                )

        checks["lineage_consistency"] = lineage_ok
        details["lineage_summary"]["ancestors_count"] = len(visited)
        details["lineage_summary"]["note"] = lineage_reason

    except Exception as exc:
        checks["lineage_consistency"] = False
        details["lineage_summary"]["note"] = f"Lineage traversal error: {exc}"

    # 7. Overall status determination with uniform precedence
    failed_checks = [name for name, res in checks.items() if res is False]
    unperformed_checks = [name for name, res in checks.items() if res is None]

    if failed_checks:
        status = "TAMPERING_DETECTED"
        reason = f"Integrity check failed: {', '.join(failed_checks)}"
        if details.get("matches_version_id"):
            reason += f" (Matches registered version {details['matches_version_id']} - rollback detected)"
        if not lineage_ok:
            reason += f" ({lineage_reason})"
    elif unperformed_checks:
        status = "NOT_VERIFIABLE"
        reason = f"Verification incomplete due to missing artifact(s): {', '.join(unperformed_checks)}"
    else:
        status = "VERIFIED"
        reason = "All cryptographic fingerprints, Merkle tree leaves, metadata digests, and on-chain lineage are valid."

    t_total_end = time.perf_counter()
    total_ms = (t_total_end - t_total_start) * 1000.0

    # Ensure total_ms >= hashing_ms
    if total_ms < hashing_ms:
        total_ms = hashing_ms + merkle_ms + chain_read_ms

    timings_ms = {
        "chain_read_ms": round(chain_read_ms, 3),
        "hashing_ms": round(hashing_ms, 3),
        "merkle_ms": round(merkle_ms, 3),
        "total_ms": round(total_ms, 3),
    }

    return {
        "status": status,
        "reason": reason,
        "checks": checks,
        "details": details,
        "timings_ms": timings_ms,
    }
