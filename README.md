# Lightweight Blockchain Framework for Data Provenance and Integrity in ML Pipelines

A framework combining off-chain storage (Merkle-tree chunking, streaming SHA-256 fingerprinting, canonical metadata digestion) with on-chain Ethereum smart contract state anchoring (`ProvenanceRegistry.sol`) to guarantee data integrity, lineage tracking, and pre-training verification gating in machine learning pipelines.

## Architecture

- **Off-Chain Storage**: Raw datasets, Merkle tree structures, and metadata JSON files are kept off-chain in storage volumes. Never store raw datasets on-chain.
- **On-Chain Anchoring**: The Ethereum smart contract anchors dataset IDs, version IDs, parent version links, file hashes, Merkle roots, chunk counts, and canonical metadata digests.
- **Verification Gate**: Prior to model training, datasets are verified against immutable on-chain records (`fileHash` and `merkleRoot`) using isolated temporary copies to prevent Time-of-Check to Time-of-Use (TOCTOU) tampering.
- **Lineage & Training Provenance**: Training runs record dataset version IDs and experiment digests on-chain (`recordTrainingRun`), binding model artifacts to the exact verified data version.

## Comparative Benchmarks (Phase 7)

The evaluation benchmarks compare:
- **Approach A**: Flat files with adjacent editable `manifest.json`.
- **Approach B**: Local Git repository tracking `.dvc` pointer files.
- **Approach C (Proposed)**: Merkle-tree chunking + off-chain storage + Ethereum smart contract anchoring.

### Running Benchmarks

```bash
# Quick profile smoke test
./venv/bin/python experiments/eval/run_all.py --profile quick --allow-dirty
./venv/bin/python experiments/analyze.py experiments/results/<RUN_DIR>

# Full benchmark (30 trials per condition)
./venv/bin/python experiments/eval/run_all.py --profile full
./venv/bin/python experiments/analyze.py experiments/results/<RUN_DIR>
```

## Limitations

- **Approach B has no remote and no signed commits, so the smart attacker evades it.** Baseline B has no remote repository and no cryptographic commit signing configured in this local evaluation. Under these conditions, the local smart attacker evades verification via `git commit --amend`. In production, a protected remote with signed commits would provide stronger guarantees, but requires network infrastructure and external access management.
- **Approach C assumes the attacker has no chain write access or registrar key.** Approach C assumes the attacker does not have write access to the Ethereum blockchain and does not possess the private key of the contract owner / registrar. If the registrar private key is compromised, an attacker could register forged versions directly on-chain.
- **A local Hardhat automine node gives near-zero tx latency and is not truly immutable.** The benchmarks run against a local Hardhat node in automine mode (`http://127.0.0.1:8545`). This provides near-zero transaction mining latency (~10–30 ms) and is not truly immutable across node restarts. On a public testnet or mainnet, block mining intervals (12s on Ethereum, 2s on Arbitrum/Polygon) and network gas volatility would increase end-to-end registration latency.
