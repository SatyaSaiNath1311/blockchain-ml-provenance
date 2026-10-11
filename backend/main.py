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
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from backend.fingerprint import (
    build_merkle_tree,
    compute_canonical_metadata_digest,
    split_csv_into_chunks,
)

# Load configuration from environment / .env
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
        "phase": 2,
        "timestamp": time.time(),
    }


def sanitize_filename(filename: str | None) -> str:
    """Validate and sanitize filename against path traversal and forbidden characters."""
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    # Reject obvious traversal patterns
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


@app.post("/datasets", status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile = File(...),
    chunk_rows: int = Form(1000),
) -> dict[str, Any]:
    """Ingest, validate, chunk, and fingerprint a CSV dataset.

    - Protects against path traversal.
    - Streams directly to disk while computing file hash.
    - Enforces configurable upload size limit.
    - Validates CSV parseability with pandas.
    - Builds domain-separated Merkle tree and saves full tree off-chain.
    - Persists canonical metadata and computes metadata_digest.
    """
    if chunk_rows < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="chunk_rows must be at least 1",
        )

    safe_filename = sanitize_filename(file.filename)
    dataset_id = str(uuid.uuid4())
    storage_root = get_storage_dir()
    max_size = get_max_upload_size()

    upload_dir = storage_root / "uploads" / dataset_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_target_path = upload_dir / safe_filename

    hasher = hashlib.sha256()
    size_bytes = 0

    try:
        # Stream file to disk while hashing
        with open(temp_target_path, "wb") as out_f:
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

        # Validate that pandas can parse the CSV
        try:
            pd.read_csv(temp_target_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Uploaded file is not a valid parseable CSV: {exc}",
            )

        # Read exact raw bytes to preserve line breaks and construct Merkle tree
        with open(temp_target_path, "rb") as f:
            raw_bytes = f.read()

        chunks = split_csv_into_chunks(raw_bytes, chunk_rows=chunk_rows)
        merkle_root, tree_levels = build_merkle_tree(chunks)

        # Save tree off-chain
        trees_dir = storage_root / "trees"
        trees_dir.mkdir(parents=True, exist_ok=True)
        tree_path = trees_dir / f"{dataset_id}.json"
        with open(tree_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dataset_id": dataset_id,
                    "num_chunks": len(chunks),
                    "chunk_rows": chunk_rows,
                    "merkle_root": merkle_root,
                    "levels": tree_levels,
                },
                f,
                indent=2,
            )

        # Prepare metadata
        created_at = datetime.now(timezone.utc).isoformat()
        metadata_payload = {
            "dataset_id": dataset_id,
            "filename": safe_filename,
            "size_bytes": size_bytes,
            "file_type": "text/csv",
            "created_at": created_at,
            "chunk_rows": chunk_rows,
            "num_chunks": len(chunks),
            "file_hash": file_hash,
            "merkle_root": merkle_root,
        }

        # Compute metadata digest over canonical JSON representation
        metadata_digest = compute_canonical_metadata_digest(metadata_payload)
        metadata_payload["metadata_digest"] = metadata_digest

        # Save metadata off-chain
        metadata_dir = storage_root / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = metadata_dir / f"{dataset_id}.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata_payload, f, indent=2)

        return metadata_payload

    except Exception:
        # Clean up partial upload directory on failure
        if upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)
        raise


@app.get("/datasets/{dataset_id}")
def get_dataset_metadata(dataset_id: str) -> dict[str, Any]:
    """Retrieve off-chain dataset metadata by dataset ID."""
    try:
        # Validate that dataset_id is a valid UUID to prevent path traversal
        uuid.UUID(dataset_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found",
        )

    storage_root = get_storage_dir()
    metadata_path = storage_root / "metadata" / f"{dataset_id}.json"

    if not metadata_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found",
        )

    with open(metadata_path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)
