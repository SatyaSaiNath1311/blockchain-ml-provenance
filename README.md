# Lightweight Blockchain Framework for Data Provenance and Integrity in ML Pipelines

A framework combining off-chain storage (Merkle-tree chunking, streaming SHA-256 fingerprinting, canonical metadata digestion) with on-chain Ethereum smart contract state anchoring (`ProvenanceRegistry.sol`) to guarantee data integrity, lineage tracking, and pre-training verification gating in machine learning pipelines.

**New here?** Read [HANDOVER.md](HANDOVER.md) first. It explains the system in plain terms, walks through a 5-minute test run, and summarises every result.

## Architecture

- **Off-Chain Storage**: Raw datasets, Merkle tree structures, and metadata JSON files are kept off-chain in storage volumes. Never store raw datasets on-chain.
- **On-Chain Anchoring**: The Ethereum smart contract anchors dataset IDs, version IDs, parent version links, file hashes, Merkle roots, chunk counts, and canonical metadata digests.
- **Verification Gate**: Prior to model training, datasets are verified against immutable on-chain records (`fileHash` and `merkleRoot`) using isolated temporary copies to prevent Time-of-Check to Time-of-Use (TOCTOU) tampering.
- **Lineage & Training Provenance**: Training runs record dataset version IDs and experiment digests on-chain (`recordTrainingRun`), binding model artifacts to the exact verified data version.

## Setup

Requires Python 3.11+ (developed on 3.14) and Node.js.

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cd blockchain && npm install && cd ..
cd frontend && npm install && cd ..
```

## Running

Four terminals. Order matters.

```bash
# Terminal 1 - blockchain node. Leave running.
cd blockchain
npx hardhat node
```

```bash
# Terminal 2 - deploy the contract, then start the API
cd blockchain
npx hardhat run scripts/deploy.js --network localhost
cd ..
venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
# Terminal 3 - web UI at http://localhost:5173
cd frontend
npm run dev
```

The deploy script writes the ABI and contract address into `backend/contracts/`,
so the backend picks them up automatically.

**Restarting the Hardhat node wipes the chain.** Every dataset registered
before a restart becomes unverifiable. Redeploy the contract and re-register
your test data afterwards.

### Verify the install

```bash
venv/bin/pytest -q                      # 90 passed
cd blockchain && npx hardhat test       # 23 passing
```

The Python tests need the Hardhat node running; without it most will skip.

## Web interface

Seven pages, all backed by real API calls and real chain state:

| Page | Purpose |
|---|---|
| Upload dataset | Ingest a CSV, fingerprint it, anchor it on-chain |
| Dataset explorer | Browse datasets, version history and lineage graphs |
| Verification | Verify a stored file, or upload a file to compare against the chain |
| Tampering lab | Run controlled attacks on a temporary copy and observe detection |
| ML experiments | Pre-training gate, deterministic cleaning, training, reproduce |
| Analytics | Benchmark results read from `docs/results-final/` |

Three sample datasets ship under `frontend/public/samples/`, generated
deterministically by `frontend/scripts/generate_samples.py` (seed 42).

### Inspecting the chain directly

To confirm the UI reads real chain state rather than its own database, query
the node directly with a transaction hash from any upload:

```bash
./scripts/show_chain.sh 0x<transaction hash>
```

This prints the block number, contract address, sender, file hash, Merkle root
and chunk count straight from the node, bypassing the application.

## Comparative Benchmarks (Phase 7)

The evaluation benchmarks compare:
- **Approach A**: Flat files with adjacent editable `manifest.json`.
- **Approach B**: Local Git repository tracking `.dvc` pointer files.
- **Approach C (Proposed)**: Merkle-tree chunking + off-chain storage + Ethereum smart contract anchoring.

Ten attack types are evaluated (cell modification, row insertion and deletion,
label flipping, column swapping, file replacement, version rollback,
preprocessing-output tampering, metadata forgery, and a metadata-aware "smart
attacker"), at three modification intensities (0.1%, 1%, 10%), across three
dataset sizes, with 30 trials per condition.

### Running benchmarks

Requires the node running with the contract deployed. Takes about 8 minutes
for the full profile.

```bash
# Quick smoke test
venv/bin/python -m experiments.eval.run_all --profile quick --allow-dirty

# Full benchmark (30 trials per condition)
venv/bin/python -m experiments.eval.run_all --profile full

# Generate tables and figures from a run
venv/bin/python -m experiments.analyze experiments/results/<RUN_DIR>
```

The full profile refuses to start on a dirty git tree, so every result can be
traced to exact code. Each run folder is named `<timestamp>_<commit>` and
contains a `run_metadata.json` recording the commit, software versions and
machine.

### Results

The results used for the paper are committed under **`docs/results-final/`**
(tables as `.md` and `.csv`, figures as `.png` and `.pdf`), from a single clean
run at commit `1481f34`. Headline numbers:

- **Detection:** all three approaches detect naive file edits 30/30. Approach A
  misses metadata forgery (0/30); A and B both miss the smart attacker (0/30);
  Approach C detects all ten attack types 30/30.
- **False positives:** 0/100 clean trials for all three approaches
  (Wilson 95% CI [0%, 3.7%]).
- **Localization (C):** precision 1.0, recall 1.0, 100% exact match. For row
  insertions and deletions the ground truth is defined as every chunk from the
  edit point onward, because fixed-row chunking shifts all later boundaries.
- **Gas (constant, independent of dataset size):** 253,568 to register a root
  version, 260,804 for a child version, 139,607 to record a training run.
- **Verification time (median):** 18.6 ms at 1 MB, 48.4 ms at 10 MB, 343.4 ms
  at 100 MB for Approach C. The chain call itself is about 16 ms and does not
  scale with size; the cost is Merkle recomputation.
- **Storage overhead (C):** 0.44% at 1 MB, 0.27% at 10 MB, 0.25% at 100 MB.
- **Chunk size:** verification time is essentially flat (46 to 50 ms) from 100
  to 10,000 rows per chunk, while tree size falls from 260 KB to 3.3 KB.

Benchmarks ran on a MacBook Air (arm64, 8 cores, 8 GB RAM). Detection and
localization were measured on the ~1 MB dataset; timing, gas and storage at
1, 10 and 100 MB.

## Repository layout

```
backend/        FastAPI application, fingerprinting, chain client, verification, ML pipeline
blockchain/     Solidity contract, Hardhat tests, deploy script
frontend/       React UI (Vite), sample datasets
experiments/    Attack implementations, baselines A/B, benchmarks E1-E5, analysis
docs/
  00-threat-model-and-protocol.md    threat model and evaluation protocol
  results-final/                     benchmark results used for the paper
tests/          90 Python tests
scripts/        demo helper scripts
PLAN.md         73-step build plan
HANDOVER.md     plain-language guide to the whole project
```

## Limitations

- **Approach B has no remote and no signed commits, so the smart attacker evades it.** Baseline B has no remote repository and no cryptographic commit signing configured in this local evaluation. Under these conditions, the local smart attacker evades verification via `git commit --amend`. In production, a protected remote with signed commits would provide stronger guarantees, but requires network infrastructure and external access management.
- **Approach C assumes the attacker has no chain write access or registrar key.** Approach C assumes the attacker does not have write access to the Ethereum blockchain and does not possess the private key of the contract owner / registrar. If the registrar private key is compromised, an attacker could register forged versions directly on-chain.
- **A local Hardhat automine node gives near-zero tx latency and is not truly immutable.** The benchmarks run against a local Hardhat node in automine mode (`http://127.0.0.1:8545`). This provides near-zero transaction mining latency (~10–30 ms) and is not truly immutable across node restarts. On a public testnet or mainnet, block mining intervals (12s on Ethereum, 2s on Arbitrum/Polygon) and network gas volatility would increase end-to-end registration latency.
- **Row insertions and deletions cannot be localized precisely.** Fixed-row chunking means an insertion or deletion shifts every subsequent chunk boundary, so detection succeeds but localization degrades to "the edit point onward". Content-defined chunking would address this.
- **Integrity is not validity.** The framework proves a dataset is unchanged since registration. It makes no claim about whether the data is correct, unbiased or fit for purpose; data quality is out of scope.
- **Off-chain availability is a separate concern.** If the stored file is deleted, the chain proves what it was, not where it is.
- **Registration cost is not fully decomposed.** At 100 MB, Approach C registration takes about 990 ms, of which hashing, Merkle construction and the transaction account for roughly 272 ms. The remainder is file I/O, chunking and serialization, reported as `other_ms` in the timing table.
