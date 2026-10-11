import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from web3 import Web3

def get_rpc_url() -> str:
    # 1. Try loading from .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    
    # 2. Try loading from .env.example if RPC_URL not in env
    if not os.getenv("RPC_URL"):
        env_example_path = Path(__file__).resolve().parent.parent / ".env.example"
        if env_example_path.exists():
            load_dotenv(dotenv_path=env_example_path)

    # 3. Default fallback
    return os.getenv("RPC_URL", "http://127.0.0.1:8545")

def check_connection():
    rpc_url = get_rpc_url()
    print(f"[Web3 Check] Attempting connection to RPC: {rpc_url}")

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
        if not w3.is_connected():
            print(
                f"\n[ERROR] Failed to connect to blockchain node at {rpc_url}.\n"
                f"Reason: Node is not responding.\n"
                f"Remedy: Ensure the Hardhat node is running (e.g., 'npm run node' in /blockchain).\n",
                file=sys.stderr,
            )
            sys.exit(1)

        chain_id = w3.eth.chain_id
        latest_block = w3.eth.block_number
        accounts = w3.eth.accounts

        print("\n========================================")
        print("  BLOCKCHAIN NODE CONNECTION: SUCCESS   ")
        print("========================================")
        print(f" RPC Endpoint   : {rpc_url}")
        print(f" Chain ID       : {chain_id}")
        print(f" Latest Block   : {latest_block}")
        print(f" Available Accts: {len(accounts)}")
        if accounts:
            print(f" Default Account: {accounts[0]}")
        print("========================================\n")
        return True

    except Exception as exc:
        print(
            f"\n[ERROR] Exception connecting to blockchain node at {rpc_url}:\n"
            f"{exc}\n"
            f"Remedy: Ensure the Hardhat node is running and accessible at {rpc_url}.\n",
            file=sys.stderr,
        )
        sys.exit(1)

if __name__ == "__main__":
    check_connection()
