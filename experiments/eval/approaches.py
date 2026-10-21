"""Common interface and implementations for evaluation approaches.

Approaches:
- A: "Files + editable metadata" (data file plus manifest.json)
- B: "Git/DVC-style" (Git repository with content-addressed cache and pointer files)
- C: "Proposed blockchain framework" (Merkle tree + off-chain metadata + on-chain smart contract)
"""

from abc import ABC, abstractmethod
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable
import uuid

import numpy as np
import pandas as pd

from backend.chain import (
    ChainClient,
    default_chain_client,
)
from backend.fingerprint import compute_file_hash
from backend.registration import register_dataset_file
from backend.verify import verify_version
from experiments.tamper import consistent_local_forgery, modify_cells


class IntegrityGateError(Exception):
    """Raised when pre-training verification gate blocks execution."""

    def __init__(self, approach: str, status: str, details: dict[str, Any]):
        super().__init__(f"Gate blocked for approach {approach}: {status}")
        self.approach = approach
        self.status = status
        self.details = details


class BaselineApproach(ABC):
    """Abstract base class for provenance and integrity approaches."""

    name: str

    @abstractmethod
    def register(
        self,
        file_path: Path | str,
        parent_version_id: str | None = None,
        operation_type: str = "ingest",
        operation_params: dict[str, Any] | None = None,
        chunk_rows: int = 1000,
    ) -> dict[str, Any]:
        """Register a new dataset version."""
        pass

    @abstractmethod
    def verify(
        self,
        version_id: str,
        file_path: Path | str | None = None,
    ) -> dict[str, Any]:
        """Verify the integrity of a registered version."""
        pass

    @abstractmethod
    def storage_footprint(self, version_id: str) -> dict[str, Any]:
        """Measure storage consumption in bytes."""
        pass

    @abstractmethod
    def lineage(self, version_id: str) -> list[dict[str, Any]]:
        """Retrieve lineage history from root to version_id."""
        pass

    @abstractmethod
    def gate_wrapper(
        self,
        version_id: str,
        train_fn: Callable[[], Any],
    ) -> Any:
        """Execute train_fn only if verification gate passes."""
        pass

    @abstractmethod
    def apply_smart_attack(
        self,
        version_id: str,
        fraction: float = 0.01,
        seed: int = 42,
    ) -> dict[str, Any]:
        """Apply a sophisticated attack modifying the file and all local metadata."""
        pass


# -----------------------------------------------------------------------------
# Approach A: Files + Editable Metadata (manifest.json)
# -----------------------------------------------------------------------------

class ApproachA(BaselineApproach):
    """Baseline A: Flat files with an editable manifest.json stored alongside."""

    name = "Approach A (Files + Manifest)"

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir = self.base_dir / "versions"
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def register(
        self,
        file_path: Path | str,
        parent_version_id: str | None = None,
        operation_type: str = "ingest",
        operation_params: dict[str, Any] | None = None,
        chunk_rows: int = 1000,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        src = Path(file_path).resolve()
        file_bytes = src.read_bytes()

        t_h = time.perf_counter()
        hasher = hashlib.sha256()
        for i in range(0, len(file_bytes), 65536):
            hasher.update(file_bytes[i : i + 65536])
        file_hash = hasher.hexdigest()
        hashing_ms = (time.perf_counter() - t_h) * 1000.0

        v_id = str(uuid.uuid4())
        v_dir = self.versions_dir / v_id
        v_dir.mkdir(parents=True, exist_ok=True)
        dst_file = v_dir / src.name
        dst_file.write_bytes(file_bytes)

        manifest = {
            "version_id": v_id,
            "parent_version_id": parent_version_id,
            "filename": src.name,
            "size_bytes": len(file_bytes),
            "file_hash": file_hash,
            "operation_type": operation_type,
            "operation_params": operation_params or {},
            "timestamp": time.time(),
        }
        manifest_path = v_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        total_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "version_id": v_id,
            "file_hash": file_hash,
            "manifest_path": manifest_path,
            "file_path": dst_file,
            "timings": {
                "hashing_ms": hashing_ms,
                "merkle_ms": 0.0,
                "tx_latency_ms": 0.0,
                "total_ms": total_ms,
            },
        }

    def verify(
        self,
        version_id: str,
        file_path: Path | str | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        v_dir = self.versions_dir / version_id
        manifest_path = v_dir / "manifest.json"

        if not manifest_path.exists():
            return {
                "status": "NOT_VERIFIABLE",
                "detected": True,
                "file_hash_match": None,
                "manifest_intact": False,
                "timings": {"hashing_ms": 0.0, "merkle_ms": 0.0, "chain_read_ms": 0.0, "total_ms": 0.0},
            }

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            return {
                "status": "NOT_VERIFIABLE",
                "detected": True,
                "file_hash_match": None,
                "manifest_intact": False,
                "timings": {"hashing_ms": 0.0, "merkle_ms": 0.0, "chain_read_ms": 0.0, "total_ms": 0.0},
            }

        target_file = Path(file_path).resolve() if file_path else (v_dir / manifest["filename"])
        if not target_file.exists():
            return {
                "status": "NOT_VERIFIABLE",
                "detected": True,
                "file_hash_match": None,
                "manifest_intact": True,
                "timings": {"hashing_ms": 0.0, "merkle_ms": 0.0, "chain_read_ms": 0.0, "total_ms": 0.0},
            }

        t_h = time.perf_counter()
        hasher = hashlib.sha256()
        with open(target_file, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        actual_hash = hasher.hexdigest()
        hashing_ms = (time.perf_counter() - t_h) * 1000.0

        match = (actual_hash.lower() == manifest["file_hash"].lower())
        status = "VERIFIED" if match else "TAMPERING_DETECTED"
        total_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "status": status,
            "detected": (status != "VERIFIED"),
            "file_hash_match": match,
            "manifest_intact": True,
            "actual_hash": actual_hash,
            "expected_hash": manifest["file_hash"],
            "timings": {
                "hashing_ms": hashing_ms,
                "merkle_ms": 0.0,
                "chain_read_ms": 0.0,
                "total_ms": total_ms,
            },
        }

    def storage_footprint(self, version_id: str) -> dict[str, Any]:
        v_dir = self.versions_dir / version_id
        manifest_path = v_dir / "manifest.json"
        manifest_bytes = manifest_path.stat().st_size if manifest_path.exists() else 0

        data_files = [f for f in v_dir.iterdir() if f.is_file() and f.name != "manifest.json"]
        raw_bytes = data_files[0].stat().st_size if data_files else 0

        return {
            "raw_dataset_bytes": raw_bytes,
            "off_chain_metadata_bytes": manifest_bytes,
            "total_off_chain_bytes": manifest_bytes,
            "on_chain_calldata_bytes": 0,
            "on_chain_storage_slots": 0,
            "gas_used": 0,
        }

    def lineage(self, version_id: str) -> list[dict[str, Any]]:
        trail = []
        curr = version_id
        while curr:
            v_dir = self.versions_dir / curr
            manifest_path = v_dir / "manifest.json"
            if not manifest_path.exists():
                break
            with open(manifest_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            trail.append(meta)
            curr = meta.get("parent_version_id")
        return list(reversed(trail))

    def gate_wrapper(self, version_id: str, train_fn: Callable[[], Any]) -> Any:
        res = self.verify(version_id)
        if res["status"] != "VERIFIED":
            raise IntegrityGateError(self.name, res["status"], res)
        return train_fn()

    def apply_smart_attack(
        self,
        version_id: str,
        fraction: float = 0.01,
        seed: int = 42,
    ) -> dict[str, Any]:
        """Tamper file and rewrite manifest.json hash so local verification passes."""
        v_dir = self.versions_dir / version_id
        manifest_path = v_dir / "manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        data_file = v_dir / manifest["filename"]
        tamper_info = modify_cells(data_file, fraction=fraction, seed=seed)

        # Recompute hash and update manifest
        new_hash = compute_file_hash(data_file.read_bytes())
        manifest["file_hash"] = new_hash
        manifest["size_bytes"] = data_file.stat().st_size
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return {
            "attack": "smart_attacker_manifest_rewritten",
            "tamper_info": tamper_info,
            "forged_hash": new_hash,
        }


# -----------------------------------------------------------------------------
# Approach B: Git/DVC-Style Versioning
# -----------------------------------------------------------------------------

class ApproachB(BaselineApproach):
    """Baseline B: Git repo with content-addressed cache and pointer files.

    Threat model: Attacker has write access to the local repo, including history rewriting
    (git commit --amend), but has no write access to a remote repository.
    """

    name = "Approach B (Git/DVC-style)"

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.repo_dir = self.base_dir / "repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)

        self.cache_dir = self.base_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.pointers_dir = self.repo_dir / "pointers"
        self.pointers_dir.mkdir(parents=True, exist_ok=True)

        self.data_dir = self.repo_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Git repo if not already initialized
        if not (self.repo_dir / ".git").exists():
            subprocess.check_call(["git", "init", "-b", "main"], cwd=self.repo_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.check_call(["git", "config", "user.name", "Eval Benchmark"], cwd=self.repo_dir)
            subprocess.check_call(["git", "config", "user.email", "eval@example.com"], cwd=self.repo_dir)
            # Initial commit
            readme = self.repo_dir / "README.md"
            readme.write_text("# Dataset Repo\n", encoding="utf-8")
            subprocess.check_call(["git", "add", "README.md"], cwd=self.repo_dir, stdout=subprocess.DEVNULL)
            subprocess.check_call(["git", "commit", "-m", "Initial commit"], cwd=self.repo_dir, stdout=subprocess.DEVNULL)

    def register(
        self,
        file_path: Path | str,
        parent_version_id: str | None = None,
        operation_type: str = "ingest",
        operation_params: dict[str, Any] | None = None,
        chunk_rows: int = 1000,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        src = Path(file_path).resolve()
        file_bytes = src.read_bytes()

        t_h = time.perf_counter()
        hasher = hashlib.sha256()
        for i in range(0, len(file_bytes), 65536):
            hasher.update(file_bytes[i : i + 65536])
        file_hash = hasher.hexdigest()
        hashing_ms = (time.perf_counter() - t_h) * 1000.0

        v_id = str(uuid.uuid4())

        # 1. Content-addressed cache
        c_bucket = self.cache_dir / file_hash[:2]
        c_bucket.mkdir(parents=True, exist_ok=True)
        cached_file = c_bucket / file_hash[2:]
        if not cached_file.exists():
            cached_file.write_bytes(file_bytes)

        # 2. Working copy
        v_data_dir = self.data_dir / v_id
        v_data_dir.mkdir(parents=True, exist_ok=True)
        working_file = v_data_dir / src.name
        working_file.write_bytes(file_bytes)

        # 3. Pointer file tracked in Git
        pointer = {
            "version_id": v_id,
            "parent_version_id": parent_version_id,
            "filename": src.name,
            "size_bytes": len(file_bytes),
            "file_hash": file_hash,
            "operation_type": operation_type,
            "operation_params": operation_params or {},
            "timestamp": time.time(),
        }
        pointer_path = self.pointers_dir / f"{v_id}.dvc"
        with open(pointer_path, "w", encoding="utf-8") as f:
            json.dump(pointer, f, indent=2)

        # 4. Commit pointer to Git
        rel_ptr = f"pointers/{v_id}.dvc"
        subprocess.check_call(["git", "add", rel_ptr], cwd=self.repo_dir, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", f"Add version {v_id}"], cwd=self.repo_dir, stdout=subprocess.DEVNULL)

        total_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "version_id": v_id,
            "file_hash": file_hash,
            "pointer_path": pointer_path,
            "working_file": working_file,
            "timings": {
                "hashing_ms": hashing_ms,
                "merkle_ms": 0.0,
                "tx_latency_ms": 0.0,
                "total_ms": total_ms,
            },
        }

    def verify(
        self,
        version_id: str,
        file_path: Path | str | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        rel_ptr = f"pointers/{version_id}.dvc"

        # Check pointer at HEAD
        try:
            ptr_raw = subprocess.check_output(
                ["git", "show", f"HEAD:{rel_ptr}"],
                cwd=self.repo_dir,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8")
            head_pointer = json.loads(ptr_raw)
        except Exception:
            return {
                "status": "NOT_VERIFIABLE",
                "detected": True,
                "file_hash_match": None,
                "pointer_clean": False,
                "timings": {"hashing_ms": 0.0, "merkle_ms": 0.0, "chain_read_ms": 0.0, "total_ms": 0.0},
            }

        # Check git status for uncommitted changes to pointer
        status_out = subprocess.check_output(
            ["git", "status", "--porcelain", rel_ptr],
            cwd=self.repo_dir,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
        pointer_clean = (len(status_out) == 0)

        # Verify working file hash
        target_file = Path(file_path).resolve() if file_path else (self.data_dir / version_id / head_pointer["filename"])
        if not target_file.exists():
            return {
                "status": "NOT_VERIFIABLE",
                "detected": True,
                "file_hash_match": None,
                "pointer_clean": pointer_clean,
                "timings": {"hashing_ms": 0.0, "merkle_ms": 0.0, "chain_read_ms": 0.0, "total_ms": 0.0},
            }

        t_h = time.perf_counter()
        hasher = hashlib.sha256()
        with open(target_file, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        actual_hash = hasher.hexdigest()
        hashing_ms = (time.perf_counter() - t_h) * 1000.0

        hash_match = (actual_hash.lower() == head_pointer["file_hash"].lower())
        # If pointer has uncommitted modifications, tampering is detected
        if not pointer_clean or not hash_match:
            status = "TAMPERING_DETECTED"
        else:
            status = "VERIFIED"

        total_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "status": status,
            "detected": (status != "VERIFIED"),
            "file_hash_match": hash_match,
            "pointer_clean": pointer_clean,
            "actual_hash": actual_hash,
            "expected_hash": head_pointer["file_hash"],
            "timings": {
                "hashing_ms": hashing_ms,
                "merkle_ms": 0.0,
                "chain_read_ms": 0.0,
                "total_ms": total_ms,
            },
        }

    def storage_footprint(self, version_id: str) -> dict[str, Any]:
        ptr_file = self.pointers_dir / f"{version_id}.dvc"
        ptr_bytes = ptr_file.stat().st_size if ptr_file.exists() else 0

        # Calculate .git/objects size
        git_objects_bytes = 0
        git_obj_dir = self.repo_dir / ".git" / "objects"
        if git_obj_dir.exists():
            for p in git_obj_dir.rglob("*"):
                if p.is_file():
                    git_objects_bytes += p.stat().st_size

        v_data = self.data_dir / version_id
        raw_bytes = 0
        if v_data.exists():
            for f in v_data.iterdir():
                if f.is_file():
                    raw_bytes = f.stat().st_size
                    break

        total_off_chain = ptr_bytes + git_objects_bytes

        return {
            "raw_dataset_bytes": raw_bytes,
            "off_chain_metadata_bytes": total_off_chain,
            "total_off_chain_bytes": total_off_chain,
            "on_chain_calldata_bytes": 0,
            "on_chain_storage_slots": 0,
            "gas_used": 0,
        }

    def lineage(self, version_id: str) -> list[dict[str, Any]]:
        trail = []
        curr = version_id
        while curr:
            ptr_file = self.pointers_dir / f"{curr}.dvc"
            if not ptr_file.exists():
                break
            with open(ptr_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            trail.append(meta)
            curr = meta.get("parent_version_id")
        return list(reversed(trail))

    def gate_wrapper(self, version_id: str, train_fn: Callable[[], Any]) -> Any:
        res = self.verify(version_id)
        if res["status"] != "VERIFIED":
            raise IntegrityGateError(self.name, res["status"], res)
        return train_fn()

    def apply_smart_attack(
        self,
        version_id: str,
        fraction: float = 0.01,
        seed: int = 42,
    ) -> dict[str, Any]:
        """Tamper file, update pointer, and rewrite Git commit (git commit --amend).

        Threat model: Attacker has local write access and rewrites local Git history.
        Because HEAD now contains the forged hash and working directory is clean,
        local verification passes without detection.
        """
        ptr_file = self.pointers_dir / f"{version_id}.dvc"
        with open(ptr_file, "r", encoding="utf-8") as f:
            pointer = json.load(f)

        data_file = self.data_dir / version_id / pointer["filename"]
        tamper_info = modify_cells(data_file, fraction=fraction, seed=seed)

        new_bytes = data_file.read_bytes()
        new_hash = compute_file_hash(new_bytes)

        # Update cache
        c_bucket = self.cache_dir / new_hash[:2]
        c_bucket.mkdir(parents=True, exist_ok=True)
        (c_bucket / new_hash[2:]).write_bytes(new_bytes)

        # Update pointer
        pointer["file_hash"] = new_hash
        pointer["size_bytes"] = len(new_bytes)
        with open(ptr_file, "w", encoding="utf-8") as f:
            json.dump(pointer, f, indent=2)

        # Amend Git commit
        rel_ptr = f"pointers/{version_id}.dvc"
        subprocess.check_call(["git", "add", rel_ptr], cwd=self.repo_dir, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "--amend", "--no-edit"], cwd=self.repo_dir, stdout=subprocess.DEVNULL)

        return {
            "attack": "smart_attacker_git_amended",
            "tamper_info": tamper_info,
            "forged_hash": new_hash,
        }


# -----------------------------------------------------------------------------
# Approach C: Proposed Blockchain Framework
# -----------------------------------------------------------------------------

class ApproachC(BaselineApproach):
    """Proposed Framework: Merkle tree chunking + on-chain smart contract anchoring."""

    name = "Approach C (Proposed Blockchain Framework)"

    def __init__(
        self,
        storage_dir: Path | str,
        chain_client: ChainClient | None = None,
    ):
        self.storage_dir = Path(storage_dir).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.client = chain_client or default_chain_client

    def register(
        self,
        file_path: Path | str,
        parent_version_id: str | None = None,
        operation_type: str = "ingest",
        operation_params: dict[str, Any] | None = None,
        chunk_rows: int = 1000,
    ) -> dict[str, Any]:
        src = Path(file_path).resolve()
        file_bytes = src.read_bytes()

        res = register_dataset_file(
            file_bytes=file_bytes,
            filename=src.name,
            parent_version_id=parent_version_id,
            operation_type=operation_type,
            operation_params=operation_params or {},
            chunk_rows=chunk_rows,
            storage_dir=self.storage_dir,
            chain_client=self.client,
        )

        return {
            "version_id": res["version_id"],
            "dataset_id": res["dataset_id"],
            "file_hash": res["metadata"]["file_hash"],
            "merkle_root": res["metadata"]["merkle_root"],
            "metadata": res["metadata"],
            "receipt": res["receipt"],
            "timings": res["timings"],
        }

    def verify(
        self,
        version_id: str,
        file_path: Path | str | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()

        # If file_path not given, find it in uploads
        target_file = None
        if file_path:
            target_file = Path(file_path).resolve()
        else:
            meta_path = self.storage_dir / "metadata" / f"{version_id}.json"
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                d_id = meta.get("dataset_id")
                fn = meta.get("filename")
                if d_id and fn:
                    candidate = self.storage_dir / "uploads" / d_id / version_id / fn
                    if candidate.exists():
                        target_file = candidate

        # Detailed breakdown measurements
        hashing_ms = 0.0
        if target_file and target_file.exists():
            t_h = time.perf_counter()
            with open(target_file, "rb") as f:
                hasher = hashlib.sha256()
                while chunk := f.read(65536):
                    hasher.update(chunk)
            hashing_ms = (time.perf_counter() - t_h) * 1000.0

        t_chain = time.perf_counter()
        try:
            on_chain_rec = self.client.get_version(version_id)
            chain_read_ms = (time.perf_counter() - t_chain) * 1000.0
        except Exception:
            chain_read_ms = (time.perf_counter() - t_chain) * 1000.0

        # Run verify_version
        v_res = verify_version(
            version_id=version_id,
            file_path=target_file,
            storage_dir=self.storage_dir,
            chain_client=self.client,
        )
        total_ms = (time.perf_counter() - t0) * 1000.0

        merkle_ms = max(0.0, total_ms - hashing_ms - chain_read_ms)

        detected = (v_res["status"] != "VERIFIED")
        return {
            "status": v_res["status"],
            "detected": detected,
            "file_hash_match": v_res["checks"].get("file_hash_match"),
            "merkle_root_match": v_res["checks"].get("merkle_root_match"),
            "metadata_digest_match": v_res["checks"].get("metadata_digest_match"),
            "verification_result": v_res,
            "timings": {
                "hashing_ms": hashing_ms,
                "merkle_ms": merkle_ms,
                "chain_read_ms": chain_read_ms,
                "total_ms": total_ms,
            },
        }

    def storage_footprint(self, version_id: str) -> dict[str, Any]:
        # Off-chain: metadata + tree + receipt
        meta_file = self.storage_dir / "metadata" / f"{version_id}.json"
        tree_file = self.storage_dir / "trees" / f"{version_id}.json"
        rcpt_file = self.storage_dir / "receipts" / f"{version_id}.json"

        meta_bytes = meta_file.stat().st_size if meta_file.exists() else 0
        tree_bytes = tree_file.stat().st_size if tree_file.exists() else 0
        rcpt_bytes = rcpt_file.stat().st_size if rcpt_file.exists() else 0
        total_off_chain = meta_bytes + tree_bytes + rcpt_bytes

        raw_bytes = 0
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            raw_bytes = meta.get("size_bytes", 0)

        # On-chain footprint
        # VersionRecord struct (8 slots):
        # datasetId (slot 0), versionId (slot 1), parentVersionId (slot 2),
        # fileHash (slot 3), merkleRoot (slot 4), numChunks uint32 alone (slot 5),
        # metadataDigest (slot 6), submitter+timestamp packed (slot 7).
        # Plus _versionExists[versionId] (1 slot) and datasetVersions push
        # (array length + element = 2 slots). Total 11 locations written.
        # Root: parentVersionId is zero-valued (10 new nonzero). Child: all 11 are nonzero (10 new + 1 update).
        on_chain_slots = 11
        gas_used = 0
        calldata_bytes = 4 + 7 * 32  # 4 bytes selector + 7 params (228 bytes)
        if rcpt_file.exists():
            with open(rcpt_file, "r", encoding="utf-8") as f:
                rcpt = json.load(f)
            gas_used = rcpt.get("gas_used", 0)

        return {
            "raw_dataset_bytes": raw_bytes,
            "off_chain_metadata_bytes": total_off_chain,
            "total_off_chain_bytes": total_off_chain,
            "tree_json_bytes": tree_bytes,
            "metadata_json_bytes": meta_bytes,
            "receipt_json_bytes": rcpt_bytes,
            "on_chain_calldata_bytes": calldata_bytes,
            "on_chain_storage_slots": on_chain_slots,
            "gas_used": gas_used,
        }

    def lineage(self, version_id: str) -> list[dict[str, Any]]:
        # Query chain
        rec = self.client.get_version(version_id)
        d_id = rec["dataset_id"]
        all_v_ids = self.client.get_dataset_versions(d_id)

        # Filter trail up to version_id
        trail = []
        for vid in all_v_ids:
            v_rec = self.client.get_version(vid)
            trail.append(v_rec)
            if vid == version_id:
                break
        return trail

    def gate_wrapper(self, version_id: str, train_fn: Callable[[], Any]) -> Any:
        res = self.verify(version_id)
        if res["status"] != "VERIFIED":
            raise IntegrityGateError(self.name, res["status"], res)
        return train_fn()

    def apply_smart_attack(
        self,
        version_id: str,
        fraction: float = 0.01,
        seed: int = 42,
    ) -> dict[str, Any]:
        """Simulate consistent local forgery. Modifies CSV, tree, and metadata.

        Because on-chain smart contract state is immutable, Approach C catches this forgery.
        """
        meta_file = self.storage_dir / "metadata" / f"{version_id}.json"
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        dataset_id = meta["dataset_id"]

        attack_info = consistent_local_forgery(
            storage_dir=self.storage_dir,
            dataset_id=dataset_id,
            version_id=version_id,
            tamper_fraction=fraction,
            seed=seed,
        )
        return attack_info
