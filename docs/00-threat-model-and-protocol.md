# Threat Model and Evaluation Protocol

## 1. Assets
Raw datasets, preprocessed dataset versions, provenance metadata, and experiment (training run) records.

## 2. Adversary model
An insider or attacker who can read and write the off-chain dataset storage and the off-chain metadata store. The attacker cannot modify blockchain state and does not hold the authorized writer's private key.

## 3. Attacks in scope
| ID | Attack | Target | Expected detection |
|----|--------|--------|--------------------|
| A1 | Modify cell values | Dataset file | File hash and Merkle root mismatch |
| A2 | Delete rows | Dataset file | Hash mismatch, changed chunks located |
| A3 | Insert rows | Dataset file | Hash mismatch, changed chunks located |
| A4 | Flip labels | Dataset file | Hash mismatch, changed chunks located |
| A5 | Swap or reorder columns | Dataset file | Hash mismatch |
| A6 | Replace the whole file | Dataset file | Hash mismatch, all chunks differ |
| A7 | Roll back to an older version | Version pointer | Lineage and timestamp consistency check |
| A8 | Modify preprocessing output | Processed version | Hash mismatch vs. registered version |
| A9 | Forge off-chain metadata | Metadata store | Metadata digest mismatch vs. on-chain digest |
| A10 | Train on unverified data | ML pipeline | Pre-training gate blocks the run |

## 4. Out of scope
- Quality or correctness of the original data
- Availability or loss of off-chain storage
- Compromise of the authorized writer's private key
- Attacks on the blockchain consensus itself (local dev chain)
- Malicious data registered by an authorized writer at the source

## 5. Assumptions
- The blockchain record is immutable once written.
- Only one authorized owner address can register versions (prototype).
- The verifier runs trusted code and reads expected hashes from the chain.

## 6. Evaluation protocol
**Approaches compared:** (A) files with editable metadata and checksums, (B) Git/DVC-style versioning, (C) proposed blockchain framework.

**Datasets and sizes:** synthetic CSV, one real tabular dataset (e.g., Adult Income), and synthetic scaled files at ~1 MB, 10 MB, 100 MB.

**Modification intensity:** 0.1%, 1%, and 10% of rows for A1-A4. A5-A10 are applied once per trial.

**Trials:** 30 per condition, fixed random seeds, results reported as mean ± std (and 95% CI).

**Metrics**
- Detection rate = detected tamperings / total tamperings
- False-positive rate = failed verifications on unmodified data / total clean verifications
- Localization accuracy = fraction of modified chunks correctly identified (blockchain approach only)
- Hashing time, verification time (measured separately from blockchain transaction latency)
- Transaction latency and gas per registration
- Storage overhead: off-chain metadata bytes and on-chain bytes, as a percentage of dataset size
- Reproducibility: retrain on the registered version and compare metrics across runs; check that the exact version is retrievable from lineage

**Rules:** all numbers come from scripts in `/experiments`; no hand-entered results.