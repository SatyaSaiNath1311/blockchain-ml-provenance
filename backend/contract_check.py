import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from web3 import Web3

def get_rpc_url() -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    if not os.getenv("RPC_URL"):
        env_example_path = Path(__file__).resolve().parent.parent / ".env.example"
        if env_example_path.exists():
            load_dotenv(dotenv_path=env_example_path)
    return os.getenv("RPC_URL", "http://127.0.0.1:8545")

def check_contract():
    contracts_dir = Path(__file__).resolve().parent / "contracts"
    abi_path = contracts_dir / "ProvenanceRegistry.abi.json"
    deployment_path = contracts_dir / "deployment.json"

    # 1. Verify existence of contract deployment files
    if not deployment_path.exists():
        print(
            f"[ERROR] Contract deployment file not found: {deployment_path}\n"
            f"Remedy: Deploy the smart contract first by running:\n"
            f"  npm --prefix blockchain run deploy:local\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if not abi_path.exists():
        print(
            f"[ERROR] Contract ABI file not found: {abi_path}\n"
            f"Remedy: Compile and deploy the contract by running:\n"
            f"  npm --prefix blockchain run deploy:local\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # 2. Parse ABI and deployment information
    try:
        with open(abi_path, "r", encoding="utf-8") as f:
            abi = json.load(f)
        with open(deployment_path, "r", encoding="utf-8") as f:
            deployment = json.load(f)
    except Exception as exc:
        print(f"[ERROR] Failed to parse contract artifacts: {exc}", file=sys.stderr)
        sys.exit(1)

    contract_address = deployment.get("contractAddress")
    expected_chain_id = deployment.get("chainId")

    if not contract_address or expected_chain_id is None:
        print(
            f"[ERROR] Invalid deployment.json content. Missing contractAddress or chainId.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. Connect to the blockchain RPC node
    rpc_url = get_rpc_url()
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
        if not w3.is_connected():
            print(
                f"[ERROR] Cannot connect to blockchain node at {rpc_url}.\n"
                f"Remedy: Ensure the Hardhat node is running (e.g., 'npm run node' in /blockchain).\n",
                file=sys.stderr,
            )
            sys.exit(1)

        current_chain_id = w3.eth.chain_id

        # 4. Detect stale deployment (node restart or chain ID mismatch)
        if current_chain_id != expected_chain_id:
            print(
                f"\n[ERROR] deployment.json is stale: the node was restarted.\n"
                f"Expected Chain ID: {expected_chain_id}, Current Chain ID: {current_chain_id}.\n"
                f"Run npm --prefix blockchain run deploy:local\n",
                file=sys.stderr,
            )
            sys.exit(1)

        checksum_address = Web3.to_checksum_address(contract_address)
        code = w3.eth.get_code(checksum_address)
        if not code or code == b"" or code.hex() == "0x":
            print(
                f"\n[ERROR] deployment.json is stale: the node was restarted.\n"
                f"No bytecode found at address {checksum_address}.\n"
                f"Run npm --prefix blockchain run deploy:local\n",
                file=sys.stderr,
            )
            sys.exit(1)

        # 5. Contract instance and calls
        contract = w3.eth.contract(address=checksum_address, abi=abi)
        contract_owner = contract.functions.owner().call()

        # 6. Read-only smoke check: versionExists(bytes32(0)) must be False
        zero_bytes32 = b"\x00" * 32
        version_zero_exists = contract.functions.versionExists(zero_bytes32).call()
        if version_zero_exists:
            print(
                f"[ERROR] Smoke check failed: versionExists(bytes32(0)) returned True (expected False).",
                file=sys.stderr,
            )
            sys.exit(1)

        latest_block = w3.eth.block_number

        print("\n==================================================")
        print("     SMART CONTRACT DEPLOYMENT VERIFICATION       ")
        print("==================================================")
        print(f" RPC Endpoint       : {rpc_url}")
        print(f" Chain ID           : {current_chain_id}")
        print(f" Contract Address   : {checksum_address}")
        print(f" Contract Owner     : {contract_owner}")
        print(f" Deployed at Block  : {deployment.get('blockNumber')}")
        print(f" Current Block      : {latest_block}")
        print(f" Smoke Check Result : versionExists(bytes32(0)) == False [PASSED]")
        print("==================================================\n")
        return True

    except Exception as exc:
        print(f"[ERROR] Exception during contract verification: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    check_contract()
