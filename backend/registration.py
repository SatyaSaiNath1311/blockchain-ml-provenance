"""Shared registration logic for dataset versions.

Used by both FastAPI upload endpoints and evaluation benchmarking (Approach C).
Handles file saving, streaming SHA-256 hashing, Merkle tree construction,
canonical metadata digest generation, on-chain contract anchoring, and receipt persistence.
"""

import hashlib
import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

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
    split_csv_into_chunks,
)
from backend.ml_pipeline import get_software_versions


def get_code_revision() -> tuple[str, bool]:
    """Retrieve current Git commit hash and whether the repo is dirty."""
    import subprocess

    try:
        commit = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode("utf-8")
            .strip()
        )
        status_out = (
            subprocess.check_output(
                ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL
            )
            .decode("utf-8")
            .strip()
        )
        # Filter out experiments/results/ from dirty detection
        lines = [line for line in status_out.splitlines() if line.strip() and not line[3:].startswith("experiments/results")]
        is_dirty = len(lines) > 0
        return commit, is_dirty
    except Exception:
        return "unknown", False


def cleanup_version_files(
    storage_root: Path,
    dataset_id: str,
    version_id: str,
) -> None:
    """Delete all off-chain files created for a version upon transaction failure."""
    upload_dir = storage_root / "uploads" / dataset_id / version_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)

    tree_path = storage_root / "trees" / f"{version_id}.json"
    if tree_path.exists():
        tree_path.unlink(missing_ok=True)

    meta_path = storage_root / "metadata" / f"{version_id}.json"
    if meta_path.exists():
        meta_path.unlink(missing_ok=True)

    receipt_path = storage_root / "receipts" / f"{version_id}.json"
    if receipt_path.exists():
        receipt_path.unlink(missing_ok=True)


def register_dataset_file(
    file_bytes: bytes,
    filename: str,
    dataset_id: str | None = None,
    version_id: str | None = None,
    parent_version_id: str | None = None,
    operation_type: str = "ingest",
    operation_params: dict[str, Any] | None = None,
    chunk_rows: int = 1000,
    storage_dir: Path | str | None = None,
    chain_client: ChainClient | None = None,
) -> dict[str, Any]:
    """Register and anchor a dataset file on-chain.

    Measures hashing_ms, merkle_ms, tx_latency_ms, and total_ms.
    Cleans up off-chain files if transaction fails.
    """
    total_start = time.perf_counter()

    client = chain_client or default_chain_client
    storage_root = Path(storage_dir or os.getenv("STORAGE_DIR", "./storage")).resolve()
    op_params = operation_params or {}

    d_id = dataset_id
    if not d_id and parent_version_id:
        try:
            parent_rec = client.get_version(parent_version_id)
            d_id = parent_rec["dataset_id"]
        except Exception:
            parent_meta = storage_root / "metadata" / f"{parent_version_id}.json"
            if parent_meta.exists():
                with open(parent_meta, "r", encoding="utf-8") as f:
                    d_id = json.load(f).get("dataset_id")
    if not d_id:
        d_id = str(uuid.uuid4())

    v_id = version_id or str(uuid.uuid4())

    # 1. Write file to disk and stream SHA-256
    upload_dir = storage_root / "uploads" / d_id / v_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_file_path = upload_dir / filename

    h_start = time.perf_counter()
    hasher = hashlib.sha256()
    hasher.update(file_bytes)
    file_hash = hasher.hexdigest()
    hashing_ms = (time.perf_counter() - h_start) * 1000.0

    target_file_path.write_bytes(file_bytes)

    try:
        # Validate parseable CSV
        try:
            pd.read_csv(target_file_path)
        except Exception as exc:
            raise ValueError(f"Uploaded file is not a valid parseable CSV: {exc}") from exc

        # 2. Split chunks and build Merkle tree
        m_start = time.perf_counter()
        chunks = split_csv_into_chunks(file_bytes, chunk_rows=chunk_rows)
        merkle_root, tree_levels = build_merkle_tree(chunks)
        merkle_ms = (time.perf_counter() - m_start) * 1000.0

        # Save tree off-chain
        trees_dir = storage_root / "trees"
        trees_dir.mkdir(parents=True, exist_ok=True)
        with open(trees_dir / f"{v_id}.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dataset_id": d_id,
                    "version_id": v_id,
                    "parent_version_id": parent_version_id,
                    "num_chunks": len(chunks),
                    "chunk_rows": chunk_rows,
                    "merkle_root": merkle_root,
                    "levels": tree_levels,
                },
                f,
                indent=2,
            )

        # 3. Build metadata
        commit_hash, is_dirty = get_code_revision()
        created_at = datetime.now(timezone.utc).isoformat()
        provenance = {
            "operation_type": operation_type,
            "operation_params": op_params,
            "software_versions": get_software_versions(),
            "code_commit_hash": commit_hash,
            "code_dirty": is_dirty,
            "operation_timestamp": created_at,
        }

        metadata_payload = {
            "dataset_id": d_id,
            "version_id": v_id,
            "parent_version_id": parent_version_id,
            "filename": filename,
            "size_bytes": len(file_bytes),
            "file_type": "text/csv",
            "created_at": created_at,
            "chunk_rows": chunk_rows,
            "num_chunks": len(chunks),
            "file_hash": file_hash,
            "merkle_root": merkle_root,
            "provenance": provenance,
        }

        metadata_digest = compute_canonical_metadata_digest(metadata_payload)
        metadata_payload["metadata_digest"] = metadata_digest

        metadata_dir = storage_root / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        with open(metadata_dir / f"{v_id}.json", "w", encoding="utf-8") as f:
            json.dump(metadata_payload, f, indent=2)

        # 4. On-chain transaction
        tx_start = time.perf_counter()
        try:
            receipt = client.register_version(
                dataset_id=d_id,
                version_id=v_id,
                parent_version_id=parent_version_id,
                file_hash=file_hash,
                merkle_root=merkle_root,
                num_chunks=len(chunks),
                metadata_digest=metadata_digest,
            )
        except Exception:
            cleanup_version_files(storage_root, d_id, v_id)
            raise
        tx_latency_ms = (time.perf_counter() - tx_start) * 1000.0

        # Save receipt off-chain
        receipts_dir = storage_root / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        with open(receipts_dir / f"{v_id}.json", "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        total_ms = (time.perf_counter() - total_start) * 1000.0

        return {
            "dataset_id": d_id,
            "version_id": v_id,
            "metadata": metadata_payload,
            "receipt": receipt,
            "target_file_path": target_file_path,
            "timings": {
                "hashing_ms": hashing_ms,
                "merkle_ms": merkle_ms,
                "tx_latency_ms": tx_latency_ms,
                "total_ms": total_ms,
            },
        }

    except Exception:
        cleanup_version_files(storage_root, d_id, v_id)
        raise
