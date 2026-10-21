import pytest
from backend.fingerprint import split_csv_into_chunks, find_modified_chunks


def _make_csv(header: bytes, rows: list[bytes]) -> bytes:
    """Utility to create CSV bytes from header and list of row bytes."""
    return header + b"".join(rows)


@pytest.fixture
def base_csv():
    header = b"a,b\n"
    rows = [f"{i},{i}\n".encode() for i in range(10)]  # rows 0..9
    return header, rows


def test_modify_data_row(base_csv):
    header, rows = base_csv
    original = _make_csv(header, rows)
    modified_rows = rows.copy()
    modified_rows[4] = b"4,XYZ\n"
    modified = _make_csv(header, modified_rows)
    chunk_rows = 3
    orig_chunks = split_csv_into_chunks(original, chunk_rows=chunk_rows)
    mod_chunks = split_csv_into_chunks(modified, chunk_rows=chunk_rows)
    flagged = set(find_modified_chunks(orig_chunks, mod_chunks))
    assert flagged == {2}
    assert 1 + 4 // chunk_rows == 2


def test_insert_row_before_original_row_5(base_csv):
    header, rows = base_csv
    original = _make_csv(header, rows)
    inserted_rows = rows.copy()
    inserted_rows.insert(5, b"5,NEW\n")
    inserted = _make_csv(header, inserted_rows)
    chunk_rows = 3
    orig_chunks = split_csv_into_chunks(original, chunk_rows=chunk_rows)
    ins_chunks = split_csv_into_chunks(inserted, chunk_rows=chunk_rows)
    flagged = set(find_modified_chunks(orig_chunks, ins_chunks))
    assert flagged == {2, 3, 4}


def test_delete_data_row_4(base_csv):
    header, rows = base_csv
    original = _make_csv(header, rows)
    deleted_rows = rows.copy()
    del deleted_rows[4]
    deleted = _make_csv(header, deleted_rows)
    chunk_rows = 3
    orig_chunks = split_csv_into_chunks(original, chunk_rows=chunk_rows)
    del_chunks = split_csv_into_chunks(deleted, chunk_rows=chunk_rows)
    flagged = set(find_modified_chunks(orig_chunks, del_chunks))
    assert flagged == {2, 3, 4}
