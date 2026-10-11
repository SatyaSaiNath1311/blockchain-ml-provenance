"""Controlled dataset tampering attack library.

All functions operate strictly on a file path or isolated temporary storage copy.
They never touch the production storage directory.
"""

import json
import shutil
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from backend.fingerprint import (
    build_merkle_tree,
    compute_canonical_metadata_digest,
    compute_file_hash,
    split_csv_into_chunks,
)


def modify_cells(
    file_path: Path | str,
    fraction: float = 0.01,
    seed: int = 42,
) -> dict[str, Any]:
    """Modify cell values in random rows. Guarantees output bytes differ from input."""
    p = Path(file_path).resolve()
    orig_bytes = p.read_bytes()
    df = pd.read_csv(p)
    rng = np.random.default_rng(seed)

    n = len(df)
    k = max(1, int(round(fraction * n)))
    selected_indices = rng.choice(n, size=min(k, n), replace=False)

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != "id"]
    target_col = numeric_cols[0] if numeric_cols else df.columns[-1]

    for idx in selected_indices:
        current_val = df.at[idx, target_col]
        if isinstance(current_val, (int, np.integer)):
            df.at[idx, target_col] = int(current_val + 77)
        elif isinstance(current_val, (float, np.floating)):
            df.at[idx, target_col] = round(float(current_val + 555.55), 2)
        else:
            df.at[idx, target_col] = f"{current_val}_TAMPERED"

    df.to_csv(p, index=False)
    assert p.read_bytes() != orig_bytes, "Output bytes must differ from input bytes"
    return {
        "attack": "modify_cells",
        "fraction": fraction,
        "rows_modified": [int(x) for x in selected_indices],
        "target_column": target_col,
    }


def delete_rows(
    file_path: Path | str,
    fraction: float = 0.01,
    seed: int = 42,
) -> dict[str, Any]:
    """Delete rows from the dataset. Guarantees output bytes differ from input."""
    p = Path(file_path).resolve()
    orig_bytes = p.read_bytes()
    df = pd.read_csv(p)
    rng = np.random.default_rng(seed)

    n = len(df)
    k = max(1, int(round(fraction * n)))
    if k >= n:
        k = max(1, n - 1)

    delete_indices = rng.choice(n, size=k, replace=False)
    df = df.drop(index=delete_indices).reset_index(drop=True)
    df.to_csv(p, index=False)
    assert p.read_bytes() != orig_bytes, "Output bytes must differ from input bytes"
    return {
        "attack": "delete_rows",
        "fraction": fraction,
        "rows_deleted": [int(x) for x in delete_indices],
        "remaining_rows": len(df),
    }


def insert_rows(
    file_path: Path | str,
    fraction: float = 0.01,
    seed: int = 42,
) -> dict[str, Any]:
    """Insert duplicate/synthetic rows in the middle. Guarantees output bytes differ from input."""
    p = Path(file_path).resolve()
    orig_bytes = p.read_bytes()
    df = pd.read_csv(p)
    rng = np.random.default_rng(seed)

    n = len(df)
    k = max(1, int(round(fraction * n)))
    # Sample rows to clone with distinct IDs
    sample_indices = rng.choice(n, size=k, replace=True)
    insert_chunk = df.iloc[sample_indices].copy()
    if "id" in insert_chunk.columns:
        insert_chunk["id"] = np.arange(900000, 900000 + k)

    split_pt = n // 2
    top = df.iloc[:split_pt]
    bottom = df.iloc[split_pt:]
    combined = pd.concat([top, insert_chunk, bottom], ignore_index=True)
    combined.to_csv(p, index=False)
    assert p.read_bytes() != orig_bytes, "Output bytes must differ from input bytes"
    return {
        "attack": "insert_rows",
        "fraction": fraction,
        "rows_inserted": k,
        "insert_position": split_pt,
        "new_total_rows": len(combined),
    }


def flip_labels(
    file_path: Path | str,
    fraction: float = 0.01,
    seed: int = 42,
) -> dict[str, Any]:
    """Flip classification labels. Guarantees output bytes differ from input."""
    p = Path(file_path).resolve()
    orig_bytes = p.read_bytes()
    df = pd.read_csv(p)
    rng = np.random.default_rng(seed)

    label_col = "approved" if "approved" in df.columns else df.columns[-1]
    n = len(df)
    k = max(1, int(round(fraction * n)))
    flip_indices = rng.choice(n, size=min(k, n), replace=False)

    for idx in flip_indices:
        val = df.at[idx, label_col]
        if isinstance(val, (int, np.integer)) and val in (0, 1):
            df.at[idx, label_col] = 1 - val
        elif isinstance(val, (float, np.floating)) and val in (0.0, 1.0):
            df.at[idx, label_col] = 1.0 - val
        else:
            df.at[idx, label_col] = f"FLIPPED_{val}"

    df.to_csv(p, index=False)
    assert p.read_bytes() != orig_bytes, "Output bytes must differ from input bytes"
    return {
        "attack": "flip_labels",
        "fraction": fraction,
        "label_column": label_col,
        "flipped_rows": [int(x) for x in flip_indices],
    }


def swap_columns(
    file_path: Path | str,
    seed: int = 42,
) -> dict[str, Any]:
    """Swap positions of two non-identical columns. Guarantees output bytes differ from input."""
    p = Path(file_path).resolve()
    orig_bytes = p.read_bytes()
    df = pd.read_csv(p)

    cols = list(df.columns)
    if len(cols) < 2:
        raise ValueError("Cannot swap columns in single-column dataset")

    # Pick two columns with non-identical values
    col1, col2 = None, None
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            if not df[cols[i]].equals(df[cols[j]]):
                col1, col2 = cols[i], cols[j]
                i_idx, j_idx = i, j
                break
        if col1:
            break

    if not col1:
        col1, col2 = cols[0], cols[1]
        i_idx, j_idx = 0, 1

    cols[i_idx], cols[j_idx] = cols[j_idx], cols[i_idx]
    df = df[cols]
    df.to_csv(p, index=False)
    assert p.read_bytes() != orig_bytes, "Output bytes must differ from input bytes"
    return {
        "attack": "swap_columns",
        "swapped": [col1, col2],
    }


def replace_file(
    file_path: Path | str,
    replacement_source_path: Path | str | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Replace target file completely. Guarantees output bytes differ from input."""
    p = Path(file_path).resolve()
    orig_bytes = p.read_bytes()

    if replacement_source_path:
        src = Path(replacement_source_path).resolve()
        shutil.copy2(src, p)
    else:
        # Generate completely different CSV
        dummy_df = pd.DataFrame({
            "col_a": [100, 200, 300, 400],
            "col_b": ["x", "y", "z", "w"],
            "col_c": [9.9, 8.8, 7.7, 6.6],
        })
        dummy_df.to_csv(p, index=False)

    assert p.read_bytes() != orig_bytes, "Output bytes must differ from input bytes"
    return {
        "attack": "replace_file",
        "target": str(p),
    }


def rollback_to_version(
    target_file_path: Path | str,
    older_version_file_path: Path | str,
) -> dict[str, Any]:
    """Roll back target file by overwriting with an older version's file."""
    target = Path(target_file_path).resolve()
    older = Path(older_version_file_path).resolve()
    orig_bytes = target.read_bytes()

    shutil.copy2(older, target)
    assert target.read_bytes() != orig_bytes, "Older version file must differ from target"
    return {
        "attack": "rollback_to_version",
        "target": str(target),
        "source": str(older),
    }


def modify_preprocessing_output(
    file_path: Path | str,
    fraction: float = 0.01,
    seed: int = 42,
) -> dict[str, Any]:
    """Tamper with numerical preprocessing outputs (e.g. min-max scaled values)."""
    p = Path(file_path).resolve()
    orig_bytes = p.read_bytes()
    df = pd.read_csv(p)
    rng = np.random.default_rng(seed)

    numeric_cols = [c for c in df.columns if pd.api.types.is_float_dtype(df[c])]
    if not numeric_cols:
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != "id"]

    col = numeric_cols[0]
    n = len(df)
    k = max(1, int(round(fraction * n)))
    selected = rng.choice(n, size=min(k, n), replace=False)

    for idx in selected:
        df.at[idx, col] = 999.99  # Corrupt normal [0, 1] range

    df.to_csv(p, index=False)
    assert p.read_bytes() != orig_bytes, "Output bytes must differ from input bytes"
    return {
        "attack": "modify_preprocessing_output",
        "fraction": fraction,
        "tampered_column": col,
        "rows_tampered": [int(x) for x in selected],
    }


def forge_metadata(
    metadata_path: Path | str,
    field: str = "parent_version_id",
    new_value: Any = None,
) -> dict[str, Any]:
    """Edit off-chain metadata JSON fields."""
    p = Path(metadata_path).resolve()
    with open(p, "r", encoding="utf-8") as f:
        meta = json.load(f)

    old_val = meta.get(field)
    if new_value is None:
        new_value = "00000000-0000-0000-0000-000000000000" if "id" in field else "FORGED_VALUE"

    meta[field] = new_value
    # Recompute metadata_digest to simulate attacker forging digest as well
    meta_copy = {k: v for k, v in meta.items() if k != "metadata_digest"}
    meta["metadata_digest"] = compute_canonical_metadata_digest(meta_copy)

    with open(p, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return {
        "attack": "forge_metadata",
        "field": field,
        "old_value": old_val,
        "new_value": new_value,
    }


def consistent_local_forgery(
    storage_dir: Path | str,
    dataset_id: str,
    version_id: str,
    tamper_fraction: float = 0.01,
    seed: int = 42,
) -> dict[str, Any]:
    """Simulate a sophisticated attacker tampering with CSV, local tree, and metadata consistently.

    The attacker modifies the CSV, recomputes the Merkle tree leaves and root,
    writes the new tree to trees/<version_id>.json, and updates metadata/<version_id>.json
    with the new file hash, Merkle root, and digest.
    This demonstrates why on-chain anchoring is required: off-chain self-consistency
    cannot defeat verification because the chain root and hash remain immutable.
    """
    root = Path(storage_dir).resolve()
    upload_dir = root / "uploads" / dataset_id / version_id
    csv_files = [f for f in upload_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
    if not csv_files:
        raise FileNotFoundError(f"No CSV file found in {upload_dir}")
    csv_path = csv_files[0]

    # 1. Tamper CSV
    mod_info = modify_cells(csv_path, fraction=tamper_fraction, seed=seed)

    # 2. Recompute new hash and Merkle tree
    tampered_bytes = csv_path.read_bytes()
    new_file_hash = compute_file_hash(tampered_bytes)
    meta_path = root / "metadata" / f"{version_id}.json"
    chunk_rows = 1000
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            old_meta = json.load(f)
            chunk_rows = int(old_meta.get("chunk_rows", 1000))

    new_chunks = split_csv_into_chunks(tampered_bytes, chunk_rows=chunk_rows)
    new_root, new_levels = build_merkle_tree(new_chunks)

    # 3. Overwrite local tree
    tree_path = root / "trees" / f"{version_id}.json"
    with open(tree_path, "w", encoding="utf-8") as f:
        json.dump({"root": new_root, "levels": new_levels}, f, indent=2)

    # 4. Overwrite local metadata
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["file_hash"] = new_file_hash
        meta["merkle_root"] = new_root
        meta["num_chunks"] = len(new_chunks)
        meta_copy = {k: v for k, v in meta.items() if k != "metadata_digest"}
        meta["metadata_digest"] = compute_canonical_metadata_digest(meta_copy)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    return {
        "attack": "consistent_local_forgery",
        "csv_modification": mod_info,
        "forged_file_hash": new_file_hash,
        "forged_merkle_root": new_root,
    }
