"""Integration tests for blockchain client, on-chain provenance, lineage, and multi-version APIs."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from web3 import Web3

from backend.chain import (
    ChainClient,
    ChainUnavailable,
    ContractRevert,
    bytes32_to_uuid,
    default_chain_client,
    uuid_to_bytes32,
)
from backend.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def deployed_fresh_contract():
    """Deploy a fresh contract to the running Hardhat node for test isolation.
    Does NOT modify backend/contracts/deployment.json.
    """
    rpc_url = os.getenv("RPC_URL", "http://127.0.0.1:8545")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        pytest.skip(f"Hardhat node not running at {rpc_url}")

    artifact_path = Path("blockchain/artifacts/contracts/ProvenanceRegistry.sol/ProvenanceRegistry.json")
    if not artifact_path.exists():
        subprocess.run(["npx", "hardhat", "compile"], cwd="blockchain", check=True)

    with open(artifact_path, "r", encoding="utf-8") as f:
        artifact = json.load(f)

    deployer = w3.eth.accounts[0]
    Factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
    tx_hash = Factory.constructor().transact({"from": deployer})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=10)
    fresh_address = receipt.contractAddress

    # Point global chain client and environment to this fresh instance
    old_env = os.environ.get("PROVENANCE_CONTRACT_ADDRESS")
    os.environ["PROVENANCE_CONTRACT_ADDRESS"] = fresh_address
    default_chain_client._custom_contract_address = fresh_address
    default_chain_client._contract = None

    yield fresh_address

    if old_env is not None:
        os.environ["PROVENANCE_CONTRACT_ADDRESS"] = old_env
        default_chain_client._custom_contract_address = old_env
    else:
        os.environ.pop("PROVENANCE_CONTRACT_ADDRESS", None)
        default_chain_client._custom_contract_address = None
    default_chain_client._contract = None


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Ensure every test uses a temporary directory for off-chain storage."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    yield tmp_path


# -----------------------------------------------------------------------------
# Unit Tests: UUID <-> bytes32 Round Trip
# -----------------------------------------------------------------------------

def test_uuid_bytes32_round_trip():
    """Verify reversible conversion between UUID4 and bytes32."""
    for _ in range(50):
        original_uuid = str(uuid.uuid4())
        b32 = uuid_to_bytes32(original_uuid)

        assert len(b32) == 32
        # First 16 bytes must be zero padding
        assert b32[:16] == b"\x00" * 16
        # Trailing 16 bytes match the raw UUID
        assert b32[16:] == uuid.UUID(original_uuid).bytes

        recovered_uuid = bytes32_to_uuid(b32)
        assert recovered_uuid == original_uuid

    # Zero bytes32 maps to None
    zero_b32 = b"\x00" * 32
    assert bytes32_to_uuid(zero_b32) is None
    assert uuid_to_bytes32(None) == zero_b32


# -----------------------------------------------------------------------------
# Integration Tests: Contract & API
# -----------------------------------------------------------------------------

@pytest.mark.chain
def test_root_registration_and_on_chain_record(deployed_fresh_contract, isolated_storage):
    """Root version registration via API anchors correct values on-chain."""
    csv_bytes = b"id,val\n1,100\n2,200\n"
    res = client.post(
        "/datasets",
        files={"file": ("root.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={"chunk_rows": "10"},
    )
    assert res.status_code == 201
    payload = res.json()
    metadata = payload["metadata"]
    receipt = payload["receipt"]

    dataset_id = metadata["dataset_id"]
    version_id = metadata["version_id"]

    assert receipt["block_number"] >= 1
    assert receipt["gas_used"] > 0

    # Query on-chain record directly
    on_chain = default_chain_client.get_version(version_id)
    assert on_chain["dataset_id"] == dataset_id
    assert on_chain["version_id"] == version_id
    assert on_chain["parent_version_id"] is None
    assert on_chain["num_chunks"] == metadata["num_chunks"]

    # Normalize hex digests (strip leading 0x)
    assert on_chain["file_hash"].lower().replace("0x", "") == metadata["file_hash"].lower()
    assert on_chain["merkle_root"].lower().replace("0x", "") == metadata["merkle_root"].lower()
    assert on_chain["metadata_digest"].lower().replace("0x", "") == metadata["metadata_digest"].lower()


@pytest.mark.chain
def test_canonical_metadata_digest_independent_verification(deployed_fresh_contract, isolated_storage):
    """Verify that stored metadata_digest matches independent SHA-256 over canonical JSON."""
    csv_bytes = b"feature,target\n0.5,1\n"
    res = client.post(
        "/datasets",
        files={"file": ("data.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert res.status_code == 201
    meta = res.json()["metadata"]
    version_id = meta["version_id"]

    # Recompute independently using hashlib and canonical json
    meta_without_digest = {k: v for k, v in meta.items() if k != "metadata_digest"}
    canonical_bytes = json.dumps(meta_without_digest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    indep_digest = hashlib.sha256(canonical_bytes).hexdigest()

    assert meta["metadata_digest"] == indep_digest

    # Verify on-chain record also matches independent digest
    on_chain = default_chain_client.get_version(version_id)
    assert on_chain["metadata_digest"].lower().replace("0x", "") == indep_digest.lower()


@pytest.mark.chain
def test_linear_lineage_and_immutability(deployed_fresh_contract, isolated_storage):
    """Create 3-version chain v1->v2->v3; verify lineage in order and older versions untouched."""
    # 1. Root version v1
    v1_res = client.post(
        "/datasets",
        files={"file": ("v1.csv", io.BytesIO(b"id,x\n1,10\n2,20\n"), "text/csv")},
    )
    assert v1_res.status_code == 201
    v1_data = v1_res.json()["metadata"]
    dataset_id = v1_data["dataset_id"]
    v1_id = v1_data["version_id"]

    v1_file_on_disk = isolated_storage / "uploads" / dataset_id / v1_id / "v1.csv"
    assert v1_file_on_disk.exists()

    # 2. Derived version v2 (parent=v1)
    v2_res = client.post(
        f"/datasets/{dataset_id}/versions",
        files={"file": ("v2.csv", io.BytesIO(b"id,x\n1,10\n"), "text/csv")},
        data={
            "parent_version_id": v1_id,
            "operation_type": "filter_rows",
            "operation_params": json.dumps({"threshold": 15}),
        },
    )
    assert v2_res.status_code == 201
    v2_data = v2_res.json()["metadata"]
    v2_id = v2_data["version_id"]

    # 3. Derived version v3 (parent=v2)
    v3_res = client.post(
        f"/datasets/{dataset_id}/versions",
        files={"file": ("v3.csv", io.BytesIO(b"id,x\n1,1.0\n"), "text/csv")},
        data={
            "parent_version_id": v2_id,
            "operation_type": "normalize",
            "operation_params": json.dumps({"method": "minmax"}),
        },
    )
    assert v3_res.status_code == 201
    v3_data = v3_res.json()["metadata"]
    v3_id = v3_data["version_id"]

    # Lineage check for v3
    lineage_res = client.get(f"/versions/{v3_id}/lineage")
    assert lineage_res.status_code == 200
    lineage = lineage_res.json()

    assert len(lineage) == 3
    assert lineage[0]["version_id"] == v1_id
    assert lineage[1]["version_id"] == v2_id
    assert lineage[2]["version_id"] == v3_id
    assert lineage[0]["parent_version_id"] is None
    assert lineage[1]["parent_version_id"] == v1_id
    assert lineage[2]["parent_version_id"] == v2_id

    # Immutability: v1 files and on-chain records remain intact
    assert v1_file_on_disk.exists()
    assert v1_file_on_disk.read_bytes() == b"id,x\n1,10\n2,20\n"
    v1_chain = default_chain_client.get_version(v1_id)
    assert v1_chain["version_id"] == v1_id


@pytest.mark.chain
def test_branching_lineage(deployed_fresh_contract, isolated_storage):
    """Test branching: two distinct children v2a and v2b branching from root v1."""
    v1_res = client.post(
        "/datasets",
        files={"file": ("v1.csv", io.BytesIO(b"id,val\n1,A\n2,B\n"), "text/csv")},
    )
    assert v1_res.status_code == 201
    v1_data = v1_res.json()["metadata"]
    dataset_id = v1_data["dataset_id"]
    v1_id = v1_data["version_id"]

    # Child Branch A
    v2a_res = client.post(
        f"/datasets/{dataset_id}/versions",
        files={"file": ("v2a.csv", io.BytesIO(b"id,val\n1,A\n"), "text/csv")},
        data={"parent_version_id": v1_id, "operation_type": "branch_a"},
    )
    assert v2a_res.status_code == 201
    v2a_id = v2a_res.json()["metadata"]["version_id"]

    # Child Branch B
    v2b_res = client.post(
        f"/datasets/{dataset_id}/versions",
        files={"file": ("v2b.csv", io.BytesIO(b"id,val\n2,B\n"), "text/csv")},
        data={"parent_version_id": v1_id, "operation_type": "branch_b"},
    )
    assert v2b_res.status_code == 201
    v2b_id = v2b_res.json()["metadata"]["version_id"]

    # Verify both lineages branch from v1
    lineage_a = client.get(f"/versions/{v2a_id}/lineage").json()
    assert [x["version_id"] for x in lineage_a] == [v1_id, v2a_id]

    lineage_b = client.get(f"/versions/{v2b_id}/lineage").json()
    assert [x["version_id"] for x in lineage_b] == [v1_id, v2b_id]


@pytest.mark.chain
def test_rejections_and_error_mappings(deployed_fresh_contract, isolated_storage):
    """Test validation and custom error mappings: unknown parent, cross-dataset parent, duplicate ID."""
    # 1. Ingest dataset 1
    d1_res = client.post(
        "/datasets",
        files={"file": ("d1.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
    )
    d1_meta = d1_res.json()["metadata"]
    d1_id = d1_meta["dataset_id"]
    v1_id = d1_meta["version_id"]

    # 2. Ingest dataset 2
    d2_res = client.post(
        "/datasets",
        files={"file": ("d2.csv", io.BytesIO(b"c,d\n3,4\n"), "text/csv")},
    )
    d2_meta = d2_res.json()["metadata"]
    d2_id = d2_meta["dataset_id"]

    # 3. Reject unknown parent version in API
    unknown_uuid = str(uuid.uuid4())
    bad_parent_res = client.post(
        f"/datasets/{d1_id}/versions",
        files={"file": ("bad.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
        data={"parent_version_id": unknown_uuid, "operation_type": "clean"},
    )
    assert bad_parent_res.status_code == 404

    # 4. Reject parent belonging to different dataset in API
    mismatch_res = client.post(
        f"/datasets/{d2_id}/versions",
        files={"file": ("cross.csv", io.BytesIO(b"c,d\n3,4\n"), "text/csv")},
        data={"parent_version_id": v1_id, "operation_type": "clean"},
    )
    assert mismatch_res.status_code == 409

    # 5. Direct call to chain.register_version: assert decoded custom errors
    with pytest.raises(ContractRevert) as exc_info1:
        default_chain_client.register_version(
            dataset_id=d2_id,
            version_id=str(uuid.uuid4()),
            parent_version_id=v1_id,  # from d1
            file_hash="0x" + "11" * 32,
            merkle_root="0x" + "22" * 32,
            num_chunks=2,
            metadata_digest="0x" + "33" * 32,
        )
    assert exc_info1.value.error_name == "ParentDatasetMismatch"

    with pytest.raises(ContractRevert) as exc_info2:
        default_chain_client.register_version(
            dataset_id=d1_id,
            version_id=str(uuid.uuid4()),
            parent_version_id=unknown_uuid,
            file_hash="0x" + "11" * 32,
            merkle_root="0x" + "22" * 32,
            num_chunks=2,
            metadata_digest="0x" + "33" * 32,
        )
    assert exc_info2.value.error_name == "ParentVersionNotFound"

    # 6. Duplicate versionId directly to chain: assert VersionAlreadyExists
    with pytest.raises(ContractRevert) as exc_info3:
        default_chain_client.register_version(
            dataset_id=d1_id,
            version_id=v1_id,  # duplicate
            parent_version_id=None,
            file_hash="0x" + "11" * 32,
            merkle_root="0x" + "22" * 32,
            num_chunks=2,
            metadata_digest="0x" + "33" * 32,
        )
    assert exc_info3.value.error_name == "VersionAlreadyExists"


@pytest.mark.chain
def test_input_validation_rules():
    """Verify operation_type constraints and malformed JSON parameter handling."""
    dummy_csv = ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")
    d_id = str(uuid.uuid4())

    # Invalid operation_type: empty
    r1 = client.post(
        f"/datasets/{d_id}/versions",
        files={"file": dummy_csv},
        data={"parent_version_id": str(uuid.uuid4()), "operation_type": "   "},
    )
    assert r1.status_code == 400

    # Invalid operation_type: too long (> 64 chars)
    r2 = client.post(
        f"/datasets/{d_id}/versions",
        files={"file": dummy_csv},
        data={"parent_version_id": str(uuid.uuid4()), "operation_type": "x" * 65},
    )
    assert r2.status_code == 400

    # Invalid operation_type: derived using 'ingest'
    r3 = client.post(
        f"/datasets/{d_id}/versions",
        files={"file": dummy_csv},
        data={"parent_version_id": str(uuid.uuid4()), "operation_type": "ingest"},
    )
    assert r3.status_code == 400

    # Malformed operation_params JSON
    r4 = client.post(
        f"/datasets/{d_id}/versions",
        files={"file": dummy_csv},
        data={
            "parent_version_id": str(uuid.uuid4()),
            "operation_type": "normalize",
            "operation_params": "{bad-json:",
        },
    )
    assert r4.status_code == 400


@pytest.mark.chain
def test_metadata_digest_tampering_and_missing_handling(deployed_fresh_contract, isolated_storage):
    """Test metadata_digest_matches_chain returns True untouched, False when edited, and False when missing."""
    res = client.post(
        "/datasets",
        files={"file": ("orig.csv", io.BytesIO(b"col\n100\n"), "text/csv")},
    )
    v_id = res.json()["metadata"]["version_id"]

    # 1. Untouched
    check_1 = client.get(f"/versions/{v_id}").json()
    assert check_1["metadata_digest_matches_chain"] is True

    # 2. Tampered metadata file
    meta_path = isolated_storage / "metadata" / f"{v_id}.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        meta_content = json.load(f)
    meta_content["provenance"]["operation_params"]["tampered"] = True
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_content, f)

    check_2 = client.get(f"/versions/{v_id}").json()
    assert check_2["metadata_digest_matches_chain"] is False

    # 3. Missing metadata file (must return False and NOT crash)
    meta_path.unlink()
    check_3 = client.get(f"/versions/{v_id}").json()
    assert check_3["metadata_digest_matches_chain"] is False
    assert check_3["off_chain_metadata"] is None


@pytest.mark.chain
def test_lineage_works_without_off_chain_files(deployed_fresh_contract, isolated_storage):
    """Lineage reconstruction operates purely from blockchain even if all off-chain files are deleted."""
    # Root
    r1 = client.post("/datasets", files={"file": ("f.csv", io.BytesIO(b"a\n1\n"), "text/csv")})
    d_id = r1.json()["metadata"]["dataset_id"]
    v1_id = r1.json()["metadata"]["version_id"]

    # Derived
    r2 = client.post(
        f"/datasets/{d_id}/versions",
        files={"file": ("f2.csv", io.BytesIO(b"a\n2\n"), "text/csv")},
        data={"parent_version_id": v1_id, "operation_type": "scale"},
    )
    v2_id = r2.json()["metadata"]["version_id"]

    # Wipe out all off-chain storage directories
    for sub in ["uploads", "metadata", "trees", "receipts"]:
        target_dir = isolated_storage / sub
        if target_dir.exists():
            shutil.rmtree(target_dir)

    # Lineage must still succeed with 2 items from chain
    lineage_res = client.get(f"/versions/{v2_id}/lineage")
    assert lineage_res.status_code == 200
    lineage = lineage_res.json()
    assert len(lineage) == 2
    assert lineage[0]["version_id"] == v1_id
    assert lineage[1]["version_id"] == v2_id


@pytest.mark.chain
def test_atomicity_failed_chain_leaves_no_orphans(deployed_fresh_contract, isolated_storage, monkeypatch):
    """Failed on-chain transaction cleans up all files (uploads, trees, metadata, receipts)."""
    # Create valid root
    r1 = client.post("/datasets", files={"file": ("ok.csv", io.BytesIO(b"a\n1\n"), "text/csv")})
    d_id = r1.json()["metadata"]["dataset_id"]
    v1_id = r1.json()["metadata"]["version_id"]

    # Force chain client register_version to fail
    def mock_fail(*args, **kwargs):
        raise ContractRevert("SimulatedFailure")

    monkeypatch.setattr(default_chain_client, "register_version", mock_fail)

    fail_res = client.post(
        f"/datasets/{d_id}/versions",
        files={"file": ("fail.csv", io.BytesIO(b"a\n2\n"), "text/csv")},
        data={"parent_version_id": v1_id, "operation_type": "transform"},
    )
    assert fail_res.status_code == 409

    # Assert no files exist for any version other than v1
    uploads_dataset = isolated_storage / "uploads" / d_id
    existing_version_folders = [p.name for p in uploads_dataset.iterdir() if p.is_dir()]
    assert existing_version_folders == [v1_id]

    trees = list((isolated_storage / "trees").glob("*.json"))
    assert [p.stem for p in trees] == [v1_id]

    meta = list((isolated_storage / "metadata").glob("*.json"))
    assert [p.stem for p in meta] == [v1_id]

    receipts = list((isolated_storage / "receipts").glob("*.json"))
    assert [p.stem for p in receipts] == [v1_id]


def test_chain_down_returns_503(monkeypatch):
    """Simulate chain down with unreachable RPC (NEVER stopping the local node)."""
    bad_client = ChainClient(rpc_url="http://127.0.0.1:9999")
    monkeypatch.setattr("backend.main.default_chain_client", bad_client)

    res = client.post(
        "/datasets",
        files={"file": ("test.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
    )
    assert res.status_code == 503
    assert "cannot connect" in res.json()["detail"].lower()
