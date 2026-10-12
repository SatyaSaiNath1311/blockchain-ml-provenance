# Phase 7 Evaluation: Conventional vs. Blockchain-Anchored ML Provenance

This directory contains the comparative evaluation benchmarks comparing the proposed blockchain framework (**Approach C**) against two established industry baselines:
1. **Approach A ("Files + editable manifest")**: Flat data files tracked with an adjacent `manifest.json` containing SHA-256 checksums and metadata.
2. **Approach B ("Git/DVC-style")**: Local Git repository tracking `.dvc` pointer files that reference content-addressed files.
3. **Approach C ("Proposed Blockchain Framework")**: Merkle-tree chunking, streaming SHA-256 fingerprinting, canonical metadata digestion, and Ethereum smart contract state anchoring (`registerVersion`, `recordTrainingRun`) with private temp copy TOCTOU-protected verification gates.

---

## 1. How to Run the Evaluation

### Quick Smoke Test (CI / Local Verification)
Executes 3 trials per condition with scaled dataset sizes, N=100 clean verifications, and generates all summary tables and figures:
```bash
./venv/bin/python experiments/eval/run_all.py --profile quick --allow-dirty
./venv/bin/python experiments/analyze.py experiments/results/<TIMESTAMP>_<COMMIT>
```

### Full Benchmark Execution (30 Trials per Condition)
Executes 30 trials per condition across ~1 MB, ~10 MB, and ~100 MB datasets:
```bash
# Ensure working tree is clean
git status --porcelain
./venv/bin/python experiments/eval/run_all.py --profile full
./venv/bin/python experiments/analyze.py experiments/results/<TIMESTAMP>_<COMMIT>
```

---

## 2. Benchmark Experiments Overview

| Experiment | Target Metrics | Key Question Answered |
| :--- | :--- | :--- |
| **E1 Detection** | Detection rate (%) across 14 attack conditions with Wilson 95% CI; False Positive Rate across N=100 clean trials. | Does on-chain anchoring prevent detection evasion by sophisticated local attackers? |
| **E1b Localization** | Chunk-level precision, recall, and exact match for in-place modifications (Approach C only). | Can Merkle trees isolate the exact damaged data chunks without scanning the entire storage? |
| **E2 Latency Breakdown** | Hashing time, Merkle tree construction time, chain read latency, transaction latency, and end-to-end time. | What is the latency overhead of cryptographic verification compared to raw I/O? |
| **E3 Storage & Gas** | Off-chain metadata overhead (bytes and % of raw CSV), on-chain calldata, storage slots, and measured gas consumption. | What is the economic and storage cost of immutable on-chain anchoring? |
| **E4 Chunk Sensitivity** | Trade-off across chunk sizes ({100, 1000, 10000} rows on 10 MB) between tree JSON size and verification latency. | How does Merkle tree granularity influence performance and storage? |
| **E5 Lineage & Contamination**| Lineage corruption detection, pre-training gate silent-contamination blocking (naive vs smart attacker), reproducibility tracking. | Can tampered data silently contaminate training, and can reproducibility be verified without local trust? |

---

## 3. Threat Models

### Baseline A (Files + Editable Manifest)
- **Assumptions**: The system relies on local files accompanied by `manifest.json`.
- **Attacker Capabilities**: The attacker has local filesystem write access.
- **Vulnerability**: While naive file edits are caught because the file hash mismatches the manifest, a sophisticated attacker simply modifies the dataset and recomputes the hash inside `manifest.json`. Because there is no external root of trust, Baseline A cannot detect this consistent local forgery.

### Baseline B (Git/DVC-Style)
- **Assumptions**: The system tracks pointer files in a local Git repository and stores content-addressed chunks in a local cache.
- **Attacker Capabilities**: The attacker has local write access to both the working directory and the `.git` repository folder, but does **not** have write access to any remote Git repository.
- **Vulnerability**: Naive file modifications are caught by checking working tree hashes against `HEAD`. However, an attacker can modify the working file, update the `.dvc` pointer, and rewrite local history via `git commit --amend`. Because `HEAD` now matches the tampered file and `git status` reports a clean working tree, local Git-based verification passes without detection.

### Approach C (Proposed Blockchain Framework)
- **Assumptions**: Dataset hashes, Merkle roots, chunk counts, and metadata digests are anchored immutably in an Ethereum smart contract (`ProvenanceRegistry`).
- **Attacker Capabilities**: The attacker has complete local storage write access (can tamper CSV files, overwrite local Merkle tree JSONs, rewrite metadata JSONs, and re-digest them).
- **Security Guarantee**: Because the smart contract on-chain is append-only and cryptographically secured by consensus, local file manipulations result in hash or Merkle root mismatches against the on-chain record, triggering `TAMPERING_DETECTED` and blocking execution at the pre-training gate.

---

## 4. Limitations and Scope Boundaries

The evaluation explicitly documents the following limitations:
- **Approach B has no remote and no signed commits, so the smart attacker evades it.** Baseline B has no remote repository and no cryptographic commit signing configured in this local evaluation. Under these conditions, the local smart attacker evades verification via `git commit --amend`. In production, a protected remote with signed commits would provide stronger guarantees, but requires network infrastructure and external access management.
- **Approach C assumes the attacker has no chain write access or registrar key.** Approach C assumes the attacker does not have write access to the Ethereum blockchain and does not possess the private key of the contract owner / registrar. If the registrar private key is compromised, an attacker could register forged versions directly on-chain.
- **A local Hardhat automine node gives near-zero tx latency and is not truly immutable.** The benchmarks run against a local Hardhat node in automine mode (`http://127.0.0.1:8545`). This provides near-zero transaction mining latency (~10–30 ms) and is not truly immutable across node restarts. On a public testnet or mainnet, block mining intervals (12s on Ethereum, 2s on Arbitrum/Polygon) and network gas volatility would increase end-to-end registration latency.
