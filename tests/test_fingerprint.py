"""Unit tests for the fingerprinting engine (backend/fingerprint.py)."""

import hashlib
import json
import pytest
from backend.fingerprint import (
    build_merkle_tree,
    compute_canonical_metadata_digest,
    compute_file_hash,
    find_modified_chunks,
    split_csv_into_chunks,
)


def test_chunk_byte_preservation_invariant():
    """Verify that b"".join(chunks) == original_bytes across all line endings and structures."""
    test_cases = [
        # Standard LF with trailing newline
        b"header_a,header_b\n1,foo\n2,bar\n3,baz\n",
        # CRLF line endings
        b"header_a,header_b\r\n1,foo\r\n2,bar\r\n3,baz\r\n",
        # Mixed line endings
        b"header_a,header_b\r\n1,foo\n2,bar\r\n3,baz\n",
        # Missing trailing newline
        b"header_a,header_b\n1,foo\n2,bar",
        # Missing trailing newline with CRLF
        b"header_a,header_b\r\n1,foo\r\n2,bar",
        # Trailing empty lines
        b"header_a,header_b\n1,foo\n\n",
        # Header only without trailing newline
        b"header_a,header_b",
        # Header only with trailing newline
        b"header_a,header_b\n",
        # Quoted newlines inside fields (treated deterministically as row breaks by splitlines)
        b'id,text\n1,"line1\nline2"\n2,simple\n',
    ]

    for chunk_rows in [1, 2, 5, 1000]:
        for raw_bytes in test_cases:
            chunks = split_csv_into_chunks(raw_bytes, chunk_rows=chunk_rows)
            # Critical invariant: no byte loss, no re-encoding, exact byte identity
            assert b"".join(chunks) == raw_bytes, (
                f"Failed invariant for chunk_rows={chunk_rows}: {chunks!r} != {raw_bytes!r}"
            )


def test_known_answer_merkle_tree():
    """Known-Answer Test (KAT): verify Merkle root against hardcoded constants and independent hashlib calculations."""
    c0 = b"id,name\n"
    c1 = b"1,alice\n"
    c2 = b"2,bob\n"
    chunks = [c0, c1, c2]

    # Precomputed hardcoded expected values
    EXPECTED_L0 = "b056aa197240ab36c500392bf6f26c54086469712494a4bc6d95952cc782b6f0"
    EXPECTED_L1 = "d00c7b0d249a86b4ce13a0e7e63e16be7c858c8b700dc287535e71c5d31e28b5"
    EXPECTED_L2 = "04bd73527866f8ce12b64dff771c0b36e332076f24743acc582ea14678563463"
    EXPECTED_P0 = "e1bc729bfdd5da88c3f6b27c9d2f5da842f719afc356efa9b74dfe16cb82e91d"
    EXPECTED_P1 = "333119547db832135f3665ad29eb7cf372bfc2307fc38aab9b52d101eb3fd4d3"
    EXPECTED_ROOT = "bdbec1574a81ba03ddbcc11fbbbe301145a87a11fcf0808abaee1167887348c6"

    # Independent verification using hashlib
    indep_l0 = hashlib.sha256(b"\x00" + c0).hexdigest()
    indep_l1 = hashlib.sha256(b"\x00" + c1).hexdigest()
    indep_l2 = hashlib.sha256(b"\x00" + c2).hexdigest()
    assert indep_l0 == EXPECTED_L0
    assert indep_l1 == EXPECTED_L1
    assert indep_l2 == EXPECTED_L2

    indep_p0 = hashlib.sha256(b"\x01" + bytes.fromhex(indep_l0) + bytes.fromhex(indep_l1)).hexdigest()
    # Odd node duplication: indep_l2 pairs with itself
    indep_p1 = hashlib.sha256(b"\x01" + bytes.fromhex(indep_l2) + bytes.fromhex(indep_l2)).hexdigest()
    assert indep_p0 == EXPECTED_P0
    assert indep_p1 == EXPECTED_P1

    indep_root = hashlib.sha256(b"\x01" + bytes.fromhex(indep_p0) + bytes.fromhex(indep_p1)).hexdigest()
    assert indep_root == EXPECTED_ROOT

    # Run actual implementation
    actual_root, actual_levels = build_merkle_tree(chunks)

    assert actual_root == EXPECTED_ROOT
    assert actual_levels[0] == [EXPECTED_L0, EXPECTED_L1, EXPECTED_L2]
    assert actual_levels[1] == [EXPECTED_P0, EXPECTED_P1]
    assert actual_levels[2] == [EXPECTED_ROOT]


def test_identical_bytes_deterministic():
    """Identical bytes must produce identical file hash, chunks, and Merkle root."""
    csv_bytes = b"col1,col2,col3\n1,alpha,10.5\n2,beta,20.0\n3,gamma,30.2\n"

    hash_a = compute_file_hash(csv_bytes)
    hash_b = compute_file_hash(csv_bytes)
    assert hash_a == hash_b

    chunks_a = split_csv_into_chunks(csv_bytes, chunk_rows=2)
    chunks_b = split_csv_into_chunks(csv_bytes, chunk_rows=2)
    assert chunks_a == chunks_b

    root_a, levels_a = build_merkle_tree(chunks_a)
    root_b, levels_b = build_merkle_tree(chunks_b)
    assert root_a == root_b
    assert levels_a == levels_b


def test_single_byte_mutation_flips_hashes():
    """A one-byte modification flips both the file hash and the Merkle root."""
    original = b"id,val\n1,100\n2,200\n3,300\n"
    # Flip '1' to '9' in the first data row
    mutated = b"id,val\n9,100\n2,200\n3,300\n"

    orig_file_hash = compute_file_hash(original)
    mut_file_hash = compute_file_hash(mutated)
    assert orig_file_hash != mut_file_hash

    orig_chunks = split_csv_into_chunks(original, chunk_rows=1)
    mut_chunks = split_csv_into_chunks(mutated, chunk_rows=1)

    orig_root, _ = build_merkle_tree(orig_chunks)
    mut_root, _ = build_merkle_tree(mut_chunks)
    assert orig_root != mut_root


def test_cell_modification_localizes_chunk():
    """Modifying a single cell affects only its target chunk index."""
    # Header + 10 rows; chunk_rows=2 means:
    # chunk 0: header
    # chunk 1: rows 1, 2
    # chunk 2: rows 3, 4
    # chunk 3: rows 5, 6
    # chunk 4: rows 7, 8
    # chunk 5: rows 9, 10
    lines = [f"{i},value_{i}" for i in range(1, 11)]
    csv_text = "id,name\n" + "\n".join(lines) + "\n"
    orig_bytes = csv_text.encode("utf-8")

    # Mutate row 5 (0-indexed data line 4, which falls in chunk 3)
    mutated_lines = list(lines)
    mutated_lines[4] = "5,MODIFIED_VAL"
    mutated_csv_text = "id,name\n" + "\n".join(mutated_lines) + "\n"
    mut_bytes = mutated_csv_text.encode("utf-8")

    orig_chunks = split_csv_into_chunks(orig_bytes, chunk_rows=2)
    mut_chunks = split_csv_into_chunks(mut_bytes, chunk_rows=2)

    assert len(orig_chunks) == len(mut_chunks) == 6

    _, orig_levels = build_merkle_tree(orig_chunks)
    _, mut_levels = build_merkle_tree(mut_chunks)

    diff_indices = find_modified_chunks(orig_levels[0], mut_levels[0])
    # Exactly chunk index 3 should be flagged
    assert diff_indices == [3]


def test_odd_duplication_root_collision_and_disambiguation():
    """Verify that [a, b, c] and [a, b, c, c] share a Merkle root, and num_chunks disambiguates them."""
    a = b"chunk_a\n"
    b = b"chunk_b\n"
    c = b"chunk_c\n"

    tree_3 = [a, b, c]
    tree_4 = [a, b, c, c]

    root_3, _ = build_merkle_tree(tree_3)
    root_4, _ = build_merkle_tree(tree_4)

    # Roots are identical due to odd-node duplication in tree_3
    assert root_3 == root_4

    # Disambiguation: num_chunks differ
    assert len(tree_3) == 3
    assert len(tree_4) == 4

    meta_3 = {"merkle_root": root_3, "num_chunks": len(tree_3)}
    meta_4 = {"merkle_root": root_4, "num_chunks": len(tree_4)}

    # Canonical metadata digest protects against the root collision
    digest_3 = compute_canonical_metadata_digest(meta_3)
    digest_4 = compute_canonical_metadata_digest(meta_4)
    assert digest_3 != digest_4


def test_row_insertion_and_deletion_shifting():
    """Verify detection when rows are inserted or deleted, and document the cascading shift effect."""
    header = "id,val\n"
    lines = [f"{i},{i*10}" for i in range(1, 7)]  # 6 rows
    orig_bytes = (header + "\n".join(lines) + "\n").encode("utf-8")

    # Original with chunk_rows=2:
    # chunk 0: header
    # chunk 1: rows 1, 2
    # chunk 2: rows 3, 4
    # chunk 3: rows 5, 6
    orig_chunks = split_csv_into_chunks(orig_bytes, chunk_rows=2)
    _, orig_levels = build_merkle_tree(orig_chunks)

    # 1. Row insertion in the middle (insert after row 2)
    inserted_lines = lines[:2] + ["99,990"] + lines[2:]
    ins_bytes = (header + "\n".join(inserted_lines) + "\n").encode("utf-8")
    ins_chunks = split_csv_into_chunks(ins_bytes, chunk_rows=2)
    _, ins_levels = build_merkle_tree(ins_chunks)

    diff_ins = find_modified_chunks(orig_levels[0], ins_levels[0])
    # Chunks 0 and 1 are untouched; chunk 2, chunk 3, and newly created chunk 4 differ
    assert 0 not in diff_ins
    assert 1 not in diff_ins
    assert 2 in diff_ins
    assert 3 in diff_ins
    assert 4 in diff_ins  # Extra chunk

    # 2. Row deletion in the middle (delete row 3)
    deleted_lines = lines[:2] + lines[3:]  # Removes row 3
    del_bytes = (header + "\n".join(deleted_lines) + "\n").encode("utf-8")
    del_chunks = split_csv_into_chunks(del_bytes, chunk_rows=2)
    _, del_levels = build_merkle_tree(del_chunks)

    diff_del = find_modified_chunks(orig_levels[0], del_levels[0])
    # Chunks 0 and 1 match; chunk 2 matches shifted rows; chunk 3 is missing
    assert 0 not in diff_del
    assert 1 not in diff_del
    assert 2 in diff_del
    assert 3 in diff_del


def test_canonical_metadata_digest():
    """Canonical metadata digest must be insensitive to key insertion order."""
    meta_a = {"dataset_id": "abc", "num_chunks": 10, "merkle_root": "0123"}
    meta_b = {"merkle_root": "0123", "dataset_id": "abc", "num_chunks": 10}

    digest_a = compute_canonical_metadata_digest(meta_a)
    digest_b = compute_canonical_metadata_digest(meta_b)

    assert digest_a == digest_b
