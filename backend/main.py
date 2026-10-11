import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

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
    split_csv_into_chunks,
)
from backend.verify import _strip_0x, verify_version
from backend.ml_pipeline import (
    IntegrityGateError,
    preprocess_and_register,
    train_on_version,
    reproduce_training_run,
)

load_dotenv()

DEFAULT_MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB default


def get_storage_dir() -> Path:
    """Resolve storage root from environment or default."""
    return Path(os.getenv("STORAGE_DIR", "./storage")).resolve()


def get_max_upload_size() -> int:
    """Resolve max upload size in bytes from environment or default."""
    try:
        return int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(DEFAULT_MAX_UPLOAD_SIZE)))
    except ValueError:
        return DEFAULT_MAX_UPLOAD_SIZE


def get_code_revision() -> tuple[str, bool]:
    """Capture current Git commit hash and whether the working tree is dirty."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        status_out = subprocess.check_output(
            ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        is_dirty = len(status_out) > 0
        return commit, is_dirty
    except Exception:
        return "unknown", False


def get_software_versions() -> dict[str, str]:
    """Capture runtime software versions of critical libraries."""
    versions = {"python": platform.python_version()}
    for pkg in ["pandas", "numpy", "scikit-learn", "web3", "fastapi"]:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except Exception:
            versions[pkg] = "unknown"
    return versions


def sanitize_filename(filename: str | None) -> str:
    """Validate and sanitize filename against path traversal."""
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: path traversal characters detected",
        )

    sanitized = Path(filename).name.strip()
    if not sanitized or sanitized.startswith("."):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename",
        )

    if not sanitized.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files (.csv) are supported",
        )

    return sanitized


def validate_operation_type(op_type: str | None, is_root: bool = False) -> str:
    """Validate operation type constraints."""
    if not op_type or not op_type.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="operation_type is required and cannot be empty",
        )
    op = op_type.strip()
    if len(op) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="operation_type must be at most 64 characters",
        )
    if is_root and op != "ingest":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Root version operation_type must be 'ingest'",
        )
    if not is_root and op == "ingest":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only root versions may use operation_type 'ingest'",
        )
    return op


def parse_operation_params(raw_json: str | None) -> dict[str, Any]:
    """Parse JSON string of operation parameters."""
    if not raw_json or not raw_json.strip():
        return {}
    try:
        parsed = json.loads(raw_json)
        if not isinstance(parsed, dict):
            raise ValueError("operation_params must be a JSON object")
        return parsed
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed operation_params JSON: {exc}",
        )


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


app = FastAPI(
    title="ML Provenance API",
    description="Lightweight Blockchain Framework for Data Provenance and Integrity in ML Pipelines",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "ml-provenance-backend",
        "phase": 6,
        "timestamp": time.time(),
    }


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@app.post("/datasets", status_code=status.HTTP_201_CREATED)
async def upload_root_dataset(
    file: UploadFile = File(...),
    chunk_rows: int = Form(1000),
) -> dict[str, Any]:
    """Ingest, fingerprint, and anchor on-chain the root version (v1) of a new dataset."""
    if chunk_rows < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="chunk_rows must be at least 1",
        )

    safe_filename = sanitize_filename(file.filename)
    dataset_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    operation_type = validate_operation_type("ingest", is_root=True)
    operation_params: dict[str, Any] = {}

    storage_root = get_storage_dir()
    max_size = get_max_upload_size()

    # Layout: uploads/<dataset_id>/<version_id>/<filename>
    upload_dir = storage_root / "uploads" / dataset_id / version_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_file_path = upload_dir / safe_filename

    hasher = hashlib.sha256()
    size_bytes = 0

    try:
        with open(target_file_path, "wb") as out_f:
            while chunk := await file.read(65536):
                size_bytes += len(chunk)
                if size_bytes > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File exceeds maximum allowed size ({max_size} bytes)",
                    )
                hasher.update(chunk)
                out_f.write(chunk)

        if size_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes)",
            )

        file_hash = hasher.hexdigest()

        # Parse check
        try:
            pd.read_csv(target_file_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Uploaded file is not a valid parseable CSV: {exc}",
            )

        with open(target_file_path, "rb") as f:
            raw_bytes = f.read()

        chunks = split_csv_into_chunks(raw_bytes, chunk_rows=chunk_rows)
        merkle_root, tree_levels = build_merkle_tree(chunks)

        # Off-chain tree
        trees_dir = storage_root / "trees"
        trees_dir.mkdir(parents=True, exist_ok=True)
        with open(trees_dir / f"{version_id}.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "num_chunks": len(chunks),
                    "chunk_rows": chunk_rows,
                    "merkle_root": merkle_root,
                    "levels": tree_levels,
                },
                f,
                indent=2,
            )

        # Provenance block
        commit_hash, is_dirty = get_code_revision()
        created_at = datetime.now(timezone.utc).isoformat()
        provenance = {
            "operation_type": operation_type,
            "operation_params": operation_params,
            "software_versions": get_software_versions(),
            "code_commit_hash": commit_hash,
            "code_dirty": is_dirty,
            "operation_timestamp": created_at,
        }

        metadata_payload = {
            "dataset_id": dataset_id,
            "version_id": version_id,
            "parent_version_id": None,
            "filename": safe_filename,
            "size_bytes": size_bytes,
            "file_type": "text/csv",
            "created_at": created_at,
            "chunk_rows": chunk_rows,
            "num_chunks": len(chunks),
            "file_hash": file_hash,
            "merkle_root": merkle_root,
            "provenance": provenance,
        }

        # Digest covers the entire metadata object without metadata_digest field
        metadata_digest = compute_canonical_metadata_digest(metadata_payload)
        metadata_payload["metadata_digest"] = metadata_digest

        metadata_dir = storage_root / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        with open(metadata_dir / f"{version_id}.json", "w", encoding="utf-8") as f:
            json.dump(metadata_payload, f, indent=2)

        # On-chain registration
        try:
            receipt = default_chain_client.register_version(
                dataset_id=dataset_id,
                version_id=version_id,
                parent_version_id=None,
                file_hash=file_hash,
                merkle_root=merkle_root,
                num_chunks=len(chunks),
                metadata_digest=metadata_digest,
            )
        except (ChainUnavailable, StaleDeployment) as exc:
            cleanup_version_files(storage_root, dataset_id, version_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        except ContractRevert as exc:
            cleanup_version_files(storage_root, dataset_id, version_id)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Contract reverted with {exc.error_name}",
            ) from exc
        except Exception as exc:
            cleanup_version_files(storage_root, dataset_id, version_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to record on-chain: {exc}",
            ) from exc

        # Save receipt off-chain
        receipts_dir = storage_root / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        with open(receipts_dir / f"{version_id}.json", "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        return {"metadata": metadata_payload, "receipt": receipt}

    except HTTPException:
        cleanup_version_files(storage_root, dataset_id, version_id)
        raise
    except Exception as exc:
        cleanup_version_files(storage_root, dataset_id, version_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@app.post("/datasets/{dataset_id}/versions", status_code=status.HTTP_201_CREATED)
async def upload_derived_version(
    dataset_id: str,
    parent_version_id: str = Form(...),
    operation_type: str = Form(...),
    operation_params: str = Form("{}"),
    chunk_rows: int = Form(1000),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Ingest, validate, fingerprint, and anchor on-chain a derived version linked to parent."""
    # 1. Validate inputs before touching disk
    try:
        uuid.UUID(dataset_id)
        parent_uuid = str(uuid.UUID(parent_version_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dataset_id and parent_version_id must be valid UUIDs",
        )

    op_type = validate_operation_type(operation_type, is_root=False)
    op_params = parse_operation_params(operation_params)
    safe_filename = sanitize_filename(file.filename)
    if chunk_rows < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="chunk_rows must be at least 1",
        )

    # 2. Pre-check parent on-chain
    try:
        if not default_chain_client.version_exists(parent_uuid):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent version {parent_uuid} not found on blockchain",
            )
        parent_rec = default_chain_client.get_version(parent_uuid)
        if parent_rec["dataset_id"] != dataset_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Parent version belongs to a different dataset",
            )
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise

    version_id = str(uuid.uuid4())
    storage_root = get_storage_dir()
    max_size = get_max_upload_size()

    upload_dir = storage_root / "uploads" / dataset_id / version_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_file_path = upload_dir / safe_filename

    hasher = hashlib.sha256()
    size_bytes = 0

    try:
        # Stream file to disk while hashing
        with open(target_file_path, "wb") as out_f:
            while chunk := await file.read(65536):
                size_bytes += len(chunk)
                if size_bytes > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File exceeds maximum allowed size ({max_size} bytes)",
                    )
                hasher.update(chunk)
                out_f.write(chunk)

        if size_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes)",
            )

        file_hash = hasher.hexdigest()

        try:
            pd.read_csv(target_file_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Uploaded file is not a valid parseable CSV: {exc}",
            )

        with open(target_file_path, "rb") as f:
            raw_bytes = f.read()

        chunks = split_csv_into_chunks(raw_bytes, chunk_rows=chunk_rows)
        merkle_root, tree_levels = build_merkle_tree(chunks)

        # Off-chain tree
        trees_dir = storage_root / "trees"
        trees_dir.mkdir(parents=True, exist_ok=True)
        with open(trees_dir / f"{version_id}.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "parent_version_id": parent_uuid,
                    "num_chunks": len(chunks),
                    "chunk_rows": chunk_rows,
                    "merkle_root": merkle_root,
                    "levels": tree_levels,
                },
                f,
                indent=2,
            )

        # Provenance block
        commit_hash, is_dirty = get_code_revision()
        created_at = datetime.now(timezone.utc).isoformat()
        provenance = {
            "operation_type": op_type,
            "operation_params": op_params,
            "software_versions": get_software_versions(),
            "code_commit_hash": commit_hash,
            "code_dirty": is_dirty,
            "operation_timestamp": created_at,
        }

        metadata_payload = {
            "dataset_id": dataset_id,
            "version_id": version_id,
            "parent_version_id": parent_uuid,
            "filename": safe_filename,
            "size_bytes": size_bytes,
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
        with open(metadata_dir / f"{version_id}.json", "w", encoding="utf-8") as f:
            json.dump(metadata_payload, f, indent=2)

        # On-chain registration
        try:
            receipt = default_chain_client.register_version(
                dataset_id=dataset_id,
                version_id=version_id,
                parent_version_id=parent_uuid,
                file_hash=file_hash,
                merkle_root=merkle_root,
                num_chunks=len(chunks),
                metadata_digest=metadata_digest,
            )
        except (ChainUnavailable, StaleDeployment) as exc:
            cleanup_version_files(storage_root, dataset_id, version_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        except ContractRevert as exc:
            cleanup_version_files(storage_root, dataset_id, version_id)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Contract reverted with {exc.error_name}",
            ) from exc
        except Exception as exc:
            cleanup_version_files(storage_root, dataset_id, version_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to record on-chain: {exc}",
            ) from exc

        # Save receipt off-chain
        receipts_dir = storage_root / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        with open(receipts_dir / f"{version_id}.json", "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        return {"metadata": metadata_payload, "receipt": receipt}

    except HTTPException:
        cleanup_version_files(storage_root, dataset_id, version_id)
        raise
    except Exception as exc:
        cleanup_version_files(storage_root, dataset_id, version_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@app.get("/datasets/{dataset_id}")
def get_dataset_info(dataset_id: str) -> dict[str, Any]:
    """Retrieve dataset info and version list directly from blockchain."""
    try:
        uuid.UUID(dataset_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found",
        )

    try:
        versions = default_chain_client.get_dataset_versions(dataset_id)
        if not versions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} has no registered versions",
            )
        return {
            "dataset_id": dataset_id,
            "version_count": len(versions),
            "versions": versions,
        }
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@app.get("/datasets/{dataset_id}/versions")
def get_dataset_versions_list(dataset_id: str) -> list[dict[str, Any]]:
    """Retrieve all versions registered on-chain for a dataset."""
    try:
        uuid.UUID(dataset_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found",
        )

    try:
        version_ids = default_chain_client.get_dataset_versions(dataset_id)
        if not version_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found on-chain",
            )
        return [default_chain_client.get_version(v_id) for v_id in version_ids]
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@app.get("/versions/{version_id}")
def get_version_details(version_id: str) -> dict[str, Any]:
    """Fetch on-chain version record, off-chain metadata, receipt, and verify digest match."""
    try:
        uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_id} not found",
        )

    try:
        if not default_chain_client.version_exists(version_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version_id} not found on blockchain",
            )
        chain_record = default_chain_client.get_version(version_id)
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    storage_root = get_storage_dir()

    # Load off-chain metadata if present
    meta_path = storage_root / "metadata" / f"{version_id}.json"
    off_chain_metadata = None
    metadata_digest_matches_chain = False

    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                off_chain_metadata = json.load(f)

            # Recompute canonical metadata digest independently
            meta_copy = {k: v for k, v in off_chain_metadata.items() if k != "metadata_digest"}
            recomputed = compute_canonical_metadata_digest(meta_copy)

            on_chain_digest = chain_record["metadata_digest"]
            if on_chain_digest.startswith("0x"):
                on_chain_digest = on_chain_digest[2:]

            metadata_digest_matches_chain = recomputed.lower() == on_chain_digest.lower()
        except Exception:
            metadata_digest_matches_chain = False
    else:
        metadata_digest_matches_chain = False

    # Load off-chain receipt if present
    receipt_path = storage_root / "receipts" / f"{version_id}.json"
    receipt = None
    if receipt_path.exists():
        try:
            with open(receipt_path, "r", encoding="utf-8") as f:
                receipt = json.load(f)
        except Exception:
            pass

    return {
        "version_id": version_id,
        "dataset_id": chain_record["dataset_id"],
        "parent_version_id": chain_record["parent_version_id"],
        "on_chain": chain_record,
        "off_chain_metadata": off_chain_metadata,
        "receipt": receipt,
        "metadata_digest_matches_chain": metadata_digest_matches_chain,
    }


@app.get("/versions/{version_id}/lineage")
def get_version_lineage(version_id: str) -> list[dict[str, Any]]:
    """Retrieve full ancestor lineage (root -> target) purely from on-chain parent links."""
    try:
        uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_id} not found",
        )

    try:
        if not default_chain_client.version_exists(version_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version_id} not found on blockchain",
            )
        return default_chain_client.get_lineage(version_id)
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@app.get("/versions/{version_id}/verify")
def verify_version_endpoint_get(version_id: str) -> dict[str, Any]:
    """Verify cryptographic integrity and lineage of a stored version."""
    try:
        uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed version ID: {version_id}",
        )

    try:
        if not default_chain_client.version_exists(version_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version_id} not registered on blockchain",
            )
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    storage_root = get_storage_dir()
    return verify_version(
        version_id=version_id,
        file_path=None,
        storage_dir=storage_root,
        chain_client=default_chain_client,
    )


@app.post("/versions/{version_id}/verify")
async def verify_version_endpoint_post(
    version_id: str,
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    """Verify an uploaded file against the registered on-chain version."""
    try:
        uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed version ID: {version_id}",
        )

    try:
        if not default_chain_client.version_exists(version_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version_id} not registered on blockchain",
            )
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    storage_root = get_storage_dir()
    max_size = get_max_upload_size()

    temp_path: Path | None = None
    if file is not None and file.filename:
        sanitized = sanitize_filename(file.filename)
        temp_dir = storage_root / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"verify_{uuid.uuid4()}_{sanitized}"

        try:
            total_bytes = 0
            with open(temp_path, "wb") as f_out:
                while chunk := await file.read(64 * 1024):
                    total_bytes += len(chunk)
                    if total_bytes > max_size:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File exceeds maximum upload size limit ({max_size} bytes)",
                        )
                    f_out.write(chunk)

            return verify_version(
                version_id=version_id,
                file_path=temp_path,
                storage_dir=storage_root,
                chain_client=default_chain_client,
            )
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
    else:
        # If no file uploaded, verify stored version
        return verify_version(
            version_id=version_id,
            file_path=None,
            storage_dir=storage_root,
            chain_client=default_chain_client,
        )


# -----------------------------------------------------------------------------
# Phase 6: ML Pipeline, Experiment Anchoring & Reproducibility Endpoints
# -----------------------------------------------------------------------------

@app.post("/versions/{version_id}/preprocess", status_code=status.HTTP_201_CREATED)
def preprocess_version_endpoint(version_id: str) -> dict[str, Any]:
    """Deterministically clean a verified dataset version and register as child."""
    try:
        uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed version ID: {version_id}",
        )

    try:
        if not default_chain_client.version_exists(version_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version_id} not registered on blockchain",
            )
        storage_root = get_storage_dir()
        return preprocess_and_register(
            version_id=version_id,
            storage_dir=storage_root,
            chain_client=default_chain_client,
        )
    except IntegrityGateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "IntegrityGateError",
                "message": str(exc),
                "status": exc.status,
                "verification_result": exc.verification_result,
            },
        ) from exc
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.post("/versions/{version_id}/train", status_code=status.HTTP_201_CREATED)
def train_version_endpoint(
    version_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify integrity gate and train baseline model on dataset version."""
    try:
        uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed version ID: {version_id}",
        )

    try:
        if not default_chain_client.version_exists(version_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version_id} not registered on blockchain",
            )
        storage_root = get_storage_dir()
        return train_on_version(
            version_id=version_id,
            config=config,
            storage_dir=storage_root,
            chain_client=default_chain_client,
        )
    except IntegrityGateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "IntegrityGateError",
                "message": str(exc),
                "status": exc.status,
                "verification_result": exc.verification_result,
            },
        ) from exc
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.get("/experiments/{run_id}")
def get_experiment_endpoint(run_id: str) -> dict[str, Any]:
    """Retrieve full on-chain and off-chain training run record."""
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed run ID: {run_id}",
        )

    try:
        if not default_chain_client.run_exists(run_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Training run {run_id} not recorded on blockchain",
            )
        chain_run = default_chain_client.get_run(run_id)
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    storage_root = get_storage_dir()
    exp_path = storage_root / "experiments" / f"{run_id}.json"
    if not exp_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment record for {run_id} not found off-chain",
        )

    with open(exp_path, "r", encoding="utf-8") as f:
        record = json.load(f)

    meta_copy = {k: v for k, v in record.items() if k != "experiment_digest"}
    recomputed_digest = compute_canonical_metadata_digest(meta_copy)
    on_chain_digest = _strip_0x(chain_run["experiment_digest"])
    digest_matches = (recomputed_digest.lower() == on_chain_digest.lower())

    # Check model artifact intactness (hashing only, no unpickling)
    model_path = storage_root / "models" / run_id / "model.joblib"
    model_artifact_intact = False
    if model_path.exists():
        actual_model_hash = compute_file_hash(model_path.read_bytes())
        model_artifact_intact = (actual_model_hash.lower() == record.get("model_artifact_sha256", "").lower())

    receipt_path = storage_root / "experiments" / f"{run_id}.receipt.json"
    receipt = None
    if receipt_path.exists():
        try:
            with open(receipt_path, "r", encoding="utf-8") as f:
                receipt = json.load(f)
        except Exception:
            pass

    return {
        "run_id": run_id,
        "dataset_version_id": chain_run["dataset_version_id"],
        "on_chain": chain_run,
        "experiment_record": record,
        "receipt": receipt,
        "experiment_digest_matches_chain": digest_matches,
        "model_artifact_intact": model_artifact_intact,
    }


@app.get("/versions/{version_id}/experiments")
def get_version_experiments_endpoint(version_id: str) -> list[str]:
    """List training run IDs recorded for a dataset version directly from blockchain events."""
    try:
        uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed version ID: {version_id}",
        )

    try:
        if not default_chain_client.version_exists(version_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version_id} not registered on blockchain",
            )
        return default_chain_client.get_runs_for_version(version_id)
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@app.post("/experiments/{run_id}/reproduce")
def reproduce_experiment_endpoint(run_id: str) -> dict[str, Any]:
    """Execute verification-gated deterministic reproducibility check."""
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed run ID: {run_id}",
        )

    try:
        if not default_chain_client.run_exists(run_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Training run {run_id} not recorded on blockchain",
            )
        storage_root = get_storage_dir()
        return reproduce_training_run(
            run_id=run_id,
            storage_dir=storage_root,
            chain_client=default_chain_client,
        )
    except (ChainUnavailable, StaleDeployment) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)

