"""Shared test fixtures for the test suite."""

import json
import os
from pathlib import Path
import subprocess

import pytest
from web3 import Web3

from backend.chain import ChainClient, default_chain_client


@pytest.fixture(scope="module")
def deployed_fresh_contract():
    """Deploy an isolated fresh contract instance for tests to the running Hardhat node.
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

    old_env = os.environ.get("PROVENANCE_CONTRACT_ADDRESS")
    os.environ["PROVENANCE_CONTRACT_ADDRESS"] = fresh_address
    default_chain_client._custom_contract_address = fresh_address
    default_chain_client._custom_deployment_block = receipt.blockNumber
    default_chain_client._contract = None

    yield fresh_address

    if old_env is not None:
        os.environ["PROVENANCE_CONTRACT_ADDRESS"] = old_env
        default_chain_client._custom_contract_address = old_env
    else:
        os.environ.pop("PROVENANCE_CONTRACT_ADDRESS", None)
        default_chain_client._custom_contract_address = None
    default_chain_client._custom_deployment_block = None
    default_chain_client._contract = None


@pytest.fixture(scope="module")
def fresh_contract_chain_client(deployed_fresh_contract):
    """Provide a ChainClient configured with the fresh contract."""
    return default_chain_client
