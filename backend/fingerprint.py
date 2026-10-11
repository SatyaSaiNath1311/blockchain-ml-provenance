"""Pure-function fingerprinting module for ML dataset integrity and provenance.

Zero web framework dependencies. Handles streaming file hashing, row-based chunking
with exact byte preservation, domain-separated Merkle trees, chunk diff localization,
and canonical metadata digestion.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import BinaryIO, Sequence

# RFC 6962-style domain separation prefixes
LEAF_PREFIX = b"\x00"
INTERNAL_PREFIX = b"\x01"


def compute_file_hash(data: bytes | BinaryIO | Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hex digest of exact file bytes in a streaming fashion.
    
    Supports bytes, open binary file-like objects, or file paths.
    """
    hasher = hashlib.sha256()

    if isinstance(data, bytes):
        hasher.update(data)
    elif isinstance(data, (str, Path)):
        path = Path(data)
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
    else:  # BinaryIO / stream
        # Read from current position
        pos = data.tell() if hasattr(data, "tell") else None
        while chunk := data.read(chunk_size):
            hasher.update(chunk)
        if pos is not None and hasattr(data, "seek"):
            data.seek(pos)

    return hasher.hexdigest()


def split_csv_into_chunks(file_bytes: bytes, chunk_rows: int = 1000) -> list[bytes]:
    """Split raw CSV bytes into row blocks while strictly preserving all original bytes.

    Invariants and guarantees:
    - b"".join(chunks) == file_bytes exactly.
    - Chunk 0 contains the raw header row (including its trailing newline if present).
    - Chunks 1..K contain up to chunk_rows data rows each.
    - Preserves CRLF (\\r\\n), LF (\\n), missing trailing newlines, and empty lines.
    - Note: Newlines inside quoted fields are treated as line breaks by splitlines;
      this remains fully deterministic and byte-preserving across all runs.
    """
    if chunk_rows < 1:
        raise ValueError(f"chunk_rows must be >= 1, got {chunk_rows}")

    if not file_bytes:
        return [b""]

    # splitlines(keepends=True) preserves exact line terminators without re-encoding
    lines = file_bytes.splitlines(keepends=True)
    if not lines:
        return [file_bytes]

    # Chunk 0 is the header line
    header_chunk = lines[0]
    data_lines = lines[1:]

    if not data_lines:
        return [header_chunk]

    chunks: list[bytes] = [header_chunk]
    for i in range(0, len(data_lines), chunk_rows):
        block = b"".join(data_lines[i : i + chunk_rows])
        chunks.append(block)

    return chunks


def hash_leaf(chunk_bytes: bytes) -> str:
    """Hash a leaf node with RFC 6962 domain separation: SHA-256(0x00 || chunk_bytes)."""
    return hashlib.sha256(LEAF_PREFIX + chunk_bytes).hexdigest()


def hash_internal(left_hex: str, right_hex: str) -> str:
    """Hash an internal node: SHA-256(0x01 || left_32_bytes || right_32_bytes)."""
    left_bytes = bytes.fromhex(left_hex)
    right_bytes = bytes.fromhex(right_hex)
    return hashlib.sha256(INTERNAL_PREFIX + left_bytes + right_bytes).hexdigest()


def build_merkle_tree(chunks: Sequence[bytes]) -> tuple[str, list[list[str]]]:
    """Build a domain-separated Merkle tree over chunk bytes.

    - Leaf hash: SHA-256(0x00 || chunk_bytes)
    - Internal hash: SHA-256(0x01 || left || right)
    - If a level has an odd number of nodes (> 1), duplicate the last node.
    - Note on collision prevention: Because odd-node duplication causes
      e.g. [a, b, c] and [a, b, c, c] to share the exact same Merkle root,
      integrity verification must check BOTH merkle_root AND num_chunks.

    Returns:
        (merkle_root_hex, tree_levels)
        where tree_levels[0] is the leaf list, and tree_levels[-1] is [merkle_root_hex].
    """
    if not chunks:
        # Empty tree convention
        empty_leaf = hash_leaf(b"")
        return empty_leaf, [[empty_leaf]]

    # Level 0: leaves
    current_level = [hash_leaf(chunk) for chunk in chunks]
    tree_levels: list[list[str]] = [current_level]

    while len(current_level) > 1:
        # If odd number of nodes, duplicate the last node
        if len(current_level) % 2 != 0:
            current_level = list(current_level) + [current_level[-1]]

        next_level: list[str] = []
        for i in range(0, len(current_level), 2):
            parent = hash_internal(current_level[i], current_level[i + 1])
            next_level.append(parent)

        tree_levels.append(next_level)
        current_level = next_level

    merkle_root = tree_levels[-1][0]
    return merkle_root, tree_levels


def find_modified_chunks(
    original_leaves: Sequence[str],
    modified_leaves: Sequence[str],
) -> list[int]:
    """Identify indices of chunks that differ between original and modified trees.

    Handles different chunk counts:
    - Compares overlapping indices (0 .. min_len - 1).
    - Appends all trailing indices (min_len .. max_len - 1) as missing or extra chunks.

    IMPORTANT NOTE:
    Row insertions or deletions in the middle of a CSV shift the row boundaries
    of all subsequent chunks. Consequently, an insertion or deletion in chunk K
    will cause chunk K and all subsequent chunks (K+1, K+2, ...) to differ.
    This is expected behavior for fixed-row chunking.
    """
    diff_indices: list[int] = []
    min_len = min(len(original_leaves), len(modified_leaves))
    max_len = max(len(original_leaves), len(modified_leaves))

    for idx in range(min_len):
        if original_leaves[idx] != modified_leaves[idx]:
            diff_indices.append(idx)

    # Any extra or truncated chunks are marked as modified
    for idx in range(min_len, max_len):
        diff_indices.append(idx)

    return diff_indices


def compute_canonical_metadata_digest(metadata: dict) -> str:
    """Compute SHA-256 digest of canonical JSON metadata (sorted keys, no whitespace)."""
    canonical_json = json.dumps(
        metadata,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical_json).hexdigest()
