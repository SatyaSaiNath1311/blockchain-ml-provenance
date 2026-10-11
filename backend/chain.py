"""Web3 client and reversible UUID<->bytes32 conversion for ProvenanceRegistry."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from eth_utils import keccak
from web3 import Web3
from web3.exceptions import ContractCustomError, ContractLogicError, Web3Exception

load_dotenv()

ZERO_BYTES32 = b"\x00" * 32
ZERO_HEX32 = "0x" + "00" * 32


# -----------------------------------------------------------------------------
# Reversible UUID <-> bytes32 Helpers
# -----------------------------------------------------------------------------

def uuid_to_bytes32(u: str | uuid.UUID | None) -> bytes:
    """Convert a UUID into bytes32 by left-padding its 16 raw bytes with 16 zeros.

    If None or empty string, returns 32 zero bytes (ZERO_BYTES32).
    """
    if u is None or u == "":
        return ZERO_BYTES32

    if isinstance(u, str):
        # Validate and convert UUID
        u_obj = uuid.UUID(u)
    elif isinstance(u, uuid.UUID):
        u_obj = u
    else:
        raise ValueError(f"Expected str or UUID, got {type(u)}")

    return b"\x00" * 16 + u_obj.bytes


def bytes32_to_uuid(b: bytes | str | None) -> str | None:
    """Recover standard hyphenated UUID string from the trailing 16 bytes of bytes32.

    Returns None if b is None, all zeros, or empty.
    """
    if b is None:
        return None

    if isinstance(b, str):
        if b.startswith("0x"):
            raw = bytes.fromhex(b[2:])
        else:
            raw = bytes.fromhex(b)
    elif isinstance(b, (bytes, bytearray)):
        raw = bytes(b)
    else:
        raise ValueError(f"Expected bytes or str, got {type(b)}")

    if len(raw) != 32:
        raise ValueError(f"Expected 32 bytes, got {len(raw)}")

    if raw == ZERO_BYTES32:
        return None

    uuid_bytes = raw[-16:]
    return str(uuid.UUID(bytes=uuid_bytes))


def ensure_bytes32(val: str | bytes) -> bytes:
    """Ensure a hash (hex string or bytes) is formatted as exact 32 bytes."""
    if isinstance(val, str):
        clean = val[2:] if val.startswith("0x") else val
        raw = bytes.fromhex(clean)
    elif isinstance(val, (bytes, bytearray)):
        raw = bytes(val)
    else:
        raise ValueError(f"Expected hex string or bytes, got {type(val)}")

    if len(raw) != 32:
        raise ValueError(f"Expected 32 bytes, got {len(raw)}")
    return raw


# -----------------------------------------------------------------------------
# Custom Exceptions
# -----------------------------------------------------------------------------

class ChainError(Exception):
    """Base exception for blockchain interactions."""


class ChainUnavailable(ChainError):
    """Raised when the blockchain RPC node is unreachable."""


class StaleDeployment(ChainError):
    """Raised when the contract address has no deployed bytecode."""


class ContractRevert(ChainError):
    """Raised when a contract execution reverts with a decoded error."""

    def __init__(self, error_name: str, message: str = "", raw_data: str | None = None):
        super().__init__(f"Contract reverted with {error_name}: {message}".strip())
        self.error_name = error_name
        self.message = message
        self.raw_data = raw_data


# -----------------------------------------------------------------------------
# Blockchain Client
# -----------------------------------------------------------------------------

class ChainClient:
    """Web3 client communicating with ProvenanceRegistry smart contract."""

    def __init__(
        self,
        rpc_url: str | None = None,
        contract_address: str | None = None,
        abi_path: Path | str | None = None,
        deployment_path: Path | str | None = None,
    ):
        self.rpc_url = rpc_url or os.getenv("RPC_URL", "http://127.0.0.1:8545")
        self._custom_contract_address = contract_address or os.getenv("PROVENANCE_CONTRACT_ADDRESS")

        base_contracts_dir = Path(__file__).resolve().parent / "contracts"
        self.abi_path = Path(abi_path) if abi_path else base_contracts_dir / "ProvenanceRegistry.abi.json"
        self.deployment_path = (
            Path(deployment_path) if deployment_path else base_contracts_dir / "deployment.json"
        )

        self._w3: Web3 | None = None
        self._contract = None
        self._error_selectors: dict[str, str] = {}  # 4-byte selector hex -> error name

    @property
    def w3(self) -> Web3:
        if self._w3 is None:
            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 5}))
        return self._w3

    def _load_abi(self) -> list[dict[str, Any]]:
        if not self.abi_path.exists():
            raise StaleDeployment(f"Contract ABI file missing: {self.abi_path}")
        with open(self.abi_path, "r", encoding="utf-8") as f:
            abi = json.load(f)

        # Build selector mapping for custom error decoding
        self._error_selectors.clear()
        for item in abi:
            if item.get("type") == "error":
                name = item["name"]
                param_types = ",".join(inp["type"] for inp in item.get("inputs", []))
                sig = f"{name}({param_types})"
                selector = keccak(text=sig)[:4].hex()
                self._error_selectors[selector] = name

        return abi

    def _resolve_contract_address(self) -> str:
        # 1. Direct override
        if self._custom_contract_address:
            return self._custom_contract_address

        env_override = os.getenv("PROVENANCE_CONTRACT_ADDRESS")
        if env_override:
            return env_override

        # 2. Deployment artifact
        if not self.deployment_path.exists():
            raise StaleDeployment(
                f"Deployment file not found at {self.deployment_path}. "
                "Run npm --prefix blockchain run deploy:local"
            )

        with open(self.deployment_path, "r", encoding="utf-8") as f:
            deployment = json.load(f)

        addr = deployment.get("contractAddress")
        if not addr:
            raise StaleDeployment("Invalid deployment.json: missing contractAddress")
        return addr

    def get_contract(self):
        """Get or initialize the contract instance with connectivity and bytecode validation."""
        try:
            if not self.w3.is_connected():
                raise ChainUnavailable(f"Cannot connect to blockchain RPC node at {self.rpc_url}")
        except Exception as exc:
            raise ChainUnavailable(f"Cannot connect to blockchain RPC node at {self.rpc_url}: {exc}") from exc

        addr = self._resolve_contract_address()
        checksum_addr = Web3.to_checksum_address(addr)

        try:
            code = self.w3.eth.get_code(checksum_addr)
        except Exception as exc:
            raise ChainUnavailable(f"RPC query get_code failed: {exc}") from exc

        if not code or code == b"" or code.hex() == "0x":
            raise StaleDeployment(
                f"deployment.json is stale: no bytecode found at address {checksum_addr}. "
                "The node was restarted. Run npm --prefix blockchain run deploy:local"
            )

        abi = self._load_abi()
        return self.w3.eth.contract(address=checksum_addr, abi=abi)

    def _decode_revert(self, exc: Exception) -> ContractRevert:
        """Decode Web3 revert exception into custom error name if available."""
        # Try finding 4-byte selector in data or message
        revert_data = None
        if hasattr(exc, "data"):
            revert_data = str(exc.data)
        elif hasattr(exc, "args") and exc.args:
            for arg in exc.args:
                if isinstance(arg, dict) and "data" in arg:
                    revert_data = str(arg["data"])
                    break
                elif isinstance(arg, str) and ("0x" in arg or "revert" in arg):
                    revert_data = arg

        if revert_data:
            for selector, error_name in self._error_selectors.items():
                if selector in revert_data or f"0x{selector}" in revert_data:
                    return ContractRevert(error_name, raw_data=revert_data)

        # Fallback inspection of string representations
        msg = str(exc)
        for error_name in self._error_selectors.values():
            if error_name in msg:
                return ContractRevert(error_name, raw_data=msg)

        return ContractRevert("UnknownRevert", message=msg)

    # -------------------------------------------------------------------------
    # Contract Interactions
    # -------------------------------------------------------------------------

    def register_version(
        self,
        dataset_id: str | uuid.UUID,
        version_id: str | uuid.UUID,
        parent_version_id: str | uuid.UUID | None,
        file_hash: str | bytes,
        merkle_root: str | bytes,
        num_chunks: int,
        metadata_digest: str | bytes,
    ) -> dict[str, Any]:
        """Send registerVersion transaction from owner account."""
        contract = self.get_contract()
        d_b32 = uuid_to_bytes32(dataset_id)
        v_b32 = uuid_to_bytes32(version_id)
        p_b32 = uuid_to_bytes32(parent_version_id)
        fh_b32 = ensure_bytes32(file_hash)
        mr_b32 = ensure_bytes32(merkle_root)
        md_b32 = ensure_bytes32(metadata_digest)

        accounts = self.w3.eth.accounts
        if not accounts:
            raise ChainUnavailable("No unlocked accounts available on blockchain node")
        owner_account = accounts[0]

        try:
            # 1. Dry run via eth_call to detect reverts early and decode custom errors
            contract.functions.registerVersion(
                d_b32,
                v_b32,
                p_b32,
                fh_b32,
                mr_b32,
                int(num_chunks),
                md_b32,
            ).call({"from": owner_account})

            # 2. Send transaction
            tx_hash = contract.functions.registerVersion(
                d_b32,
                v_b32,
                p_b32,
                fh_b32,
                mr_b32,
                int(num_chunks),
                md_b32,
            ).transact({"from": owner_account})

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=10)
            if receipt.status != 1:
                raise ContractRevert("TransactionFailed", message="Transaction status was 0")

            return {
                "tx_hash": receipt.transactionHash.hex(),
                "block_number": receipt.blockNumber,
                "gas_used": receipt.gasUsed,
            }

        except ContractRevert:
            raise
        except (ContractLogicError, ContractCustomError) as exc:
            raise self._decode_revert(exc) from exc
        except Exception as exc:
            # Check if underlying cause is a revert
            decoded = self._decode_revert(exc)
            if decoded.error_name != "UnknownRevert":
                raise decoded from exc
            raise ChainError(f"registerVersion failed: {exc}") from exc

    def get_version(self, version_id: str | uuid.UUID) -> dict[str, Any]:
        """Retrieve full on-chain VersionRecord struct."""
        contract = self.get_contract()
        v_b32 = uuid_to_bytes32(version_id)

        try:
            raw = contract.functions.getVersion(v_b32).call()
            # Struct: (datasetId, versionId, parentVersionId, fileHash, merkleRoot, numChunks, metadataDigest, submitter, timestamp)
            return {
                "dataset_id": bytes32_to_uuid(raw[0]),
                "version_id": bytes32_to_uuid(raw[1]),
                "parent_version_id": bytes32_to_uuid(raw[2]),
                "file_hash": "0x" + raw[3].hex() if isinstance(raw[3], bytes) else str(raw[3]),
                "merkle_root": "0x" + raw[4].hex() if isinstance(raw[4], bytes) else str(raw[4]),
                "num_chunks": raw[5],
                "metadata_digest": "0x" + raw[6].hex() if isinstance(raw[6], bytes) else str(raw[6]),
                "submitter": raw[7],
                "timestamp": raw[8],
            }
        except (ContractLogicError, ContractCustomError) as exc:
            raise self._decode_revert(exc) from exc
        except Exception as exc:
            decoded = self._decode_revert(exc)
            if decoded.error_name != "UnknownRevert":
                raise decoded from exc
            raise ChainError(f"getVersion failed: {exc}") from exc

    def version_exists(self, version_id: str | uuid.UUID) -> bool:
        """Check if versionId exists on-chain."""
        contract = self.get_contract()
        v_b32 = uuid_to_bytes32(version_id)
        try:
            return bool(contract.functions.versionExists(v_b32).call())
        except Exception as exc:
            raise ChainError(f"versionExists failed: {exc}") from exc

    def get_dataset_versions(self, dataset_id: str | uuid.UUID) -> list[str]:
        """Retrieve ordered list of version UUIDs for a dataset."""
        contract = self.get_contract()
        d_b32 = uuid_to_bytes32(dataset_id)
        try:
            raw_list = contract.functions.getDatasetVersions(d_b32).call()
            return [bytes32_to_uuid(item) for item in raw_list if bytes32_to_uuid(item) is not None]
        except Exception as exc:
            raise ChainError(f"getDatasetVersions failed: {exc}") from exc

    def get_lineage(self, version_id: str | uuid.UUID) -> list[dict[str, Any]]:
        """Walk on-chain parentVersionId links backwards to root and return ordered lineage."""
        lineage: list[dict[str, Any]] = []
        current_id: str | None = str(version_id)

        visited = set()
        while current_id:
            if current_id in visited:
                break
            visited.add(current_id)

            rec = self.get_version(current_id)
            lineage.append(rec)
            current_id = rec.get("parent_version_id")

        lineage.reverse()  # Root to target
        return lineage

    @property
    def deployment_block(self) -> int:
        """Resolve contract deployment block number."""
        if hasattr(self, "_custom_deployment_block") and self._custom_deployment_block is not None:
            return self._custom_deployment_block
        if self.deployment_path.exists():
            try:
                with open(self.deployment_path, "r", encoding="utf-8") as f:
                    return int(json.load(f).get("blockNumber", 0))
            except Exception:
                return 0
        return 0

    def record_training_run(
        self,
        run_id: str | uuid.UUID,
        dataset_version_id: str | uuid.UUID,
        experiment_digest: str | bytes,
    ) -> dict[str, Any]:
        """Send recordTrainingRun transaction from owner account."""
        contract = self.get_contract()
        r_b32 = uuid_to_bytes32(run_id)
        dv_b32 = uuid_to_bytes32(dataset_version_id)
        ed_b32 = ensure_bytes32(experiment_digest)

        accounts = self.w3.eth.accounts
        if not accounts:
            raise ChainUnavailable("No unlocked accounts available on blockchain node")
        owner_account = accounts[0]

        try:
            # 1. Dry run via eth_call to detect reverts early and decode custom errors
            contract.functions.recordTrainingRun(r_b32, dv_b32, ed_b32).call({"from": owner_account})

            # 2. Send transaction
            tx_hash = contract.functions.recordTrainingRun(r_b32, dv_b32, ed_b32).transact({"from": owner_account})
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=10)
            if receipt.status != 1:
                raise ContractRevert("TransactionFailed", message="Transaction status was 0")

            return {
                "tx_hash": receipt.transactionHash.hex(),
                "block_number": receipt.blockNumber,
                "gas_used": receipt.gasUsed,
            }
        except ContractRevert:
            raise
        except (ContractLogicError, ContractCustomError) as exc:
            raise self._decode_revert(exc) from exc
        except Exception as exc:
            decoded = self._decode_revert(exc)
            if decoded.error_name != "UnknownRevert":
                raise decoded from exc
            raise ChainError(f"recordTrainingRun failed: {exc}") from exc

    def get_run(self, run_id: str | uuid.UUID) -> dict[str, Any]:
        """Fetch full on-chain TrainingRunRecord struct."""
        contract = self.get_contract()
        r_b32 = uuid_to_bytes32(run_id)

        try:
            raw = contract.functions.getRun(r_b32).call()
            # Struct: (runId, datasetVersionId, experimentDigest, submitter, timestamp)
            return {
                "run_id": bytes32_to_uuid(raw[0]),
                "dataset_version_id": bytes32_to_uuid(raw[1]),
                "experiment_digest": "0x" + raw[2].hex() if isinstance(raw[2], bytes) else str(raw[2]),
                "submitter": raw[3],
                "timestamp": raw[4],
            }
        except (ContractLogicError, ContractCustomError) as exc:
            raise self._decode_revert(exc) from exc
        except Exception as exc:
            decoded = self._decode_revert(exc)
            if decoded.error_name != "UnknownRevert":
                raise decoded from exc
            raise ChainError(f"getRun failed: {exc}") from exc

    def run_exists(self, run_id: str | uuid.UUID) -> bool:
        """Check if runId exists on-chain."""
        contract = self.get_contract()
        r_b32 = uuid_to_bytes32(run_id)
        try:
            return bool(contract.functions.runExists(r_b32).call())
        except Exception as exc:
            raise ChainError(f"runExists failed: {exc}") from exc

    def get_runs_for_version(
        self,
        version_id: str | uuid.UUID,
        from_block: int | None = None,
    ) -> list[str]:
        """Query TrainingRunRecorded events filtered by indexed datasetVersionId starting from deployment block."""
        contract = self.get_contract()
        v_b32 = uuid_to_bytes32(version_id)
        start_block = from_block if from_block is not None else self.deployment_block

        try:
            event_filter = contract.events.TrainingRunRecorded.create_filter(
                from_block=start_block,
                to_block="latest",
                argument_filters={"datasetVersionId": v_b32},
            )
            entries = event_filter.get_all_entries()
            run_ids: list[str] = []
            for entry in entries:
                run_b32 = entry["args"]["runId"]
                run_uuid = bytes32_to_uuid(run_b32)
                if run_uuid and run_uuid not in run_ids:
                    run_ids.append(run_uuid)
            return run_ids
        except Exception as exc:
            # Fallback using direct eth.get_logs
            try:
                event_sig = self.w3.keccak(text="TrainingRunRecorded(bytes32,bytes32,bytes32,address,uint64)").hex()
                topic_v = "0x" + v_b32.hex()
                logs = self.w3.eth.get_logs({
                    "fromBlock": start_block,
                    "toBlock": "latest",
                    "address": contract.address,
                    "topics": [event_sig, None, topic_v],
                })
                run_ids = []
                for log in logs:
                    run_b32_hex = log["topics"][1].hex()
                    run_b32 = bytes.fromhex(run_b32_hex[2:] if run_b32_hex.startswith("0x") else run_b32_hex)
                    run_uuid = bytes32_to_uuid(run_b32)
                    if run_uuid and run_uuid not in run_ids:
                        run_ids.append(run_uuid)
                return run_ids
            except Exception as e2:
                raise ChainError(f"get_runs_for_version failed: {exc} / fallback: {e2}") from exc


# Default global instance
default_chain_client = ChainClient()
