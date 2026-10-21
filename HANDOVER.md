# Project Handover: Blockchain Data Provenance for ML Pipelines

**Repo:** https://github.com/SatyaSaiNath1311/blockchain-ml-provenance
**Full title:** A Lightweight Blockchain Framework for Data Provenance and Integrity in Machine Learning Pipelines

Read this top to bottom. It explains what the system does, how to run it,
what the results mean, and what the honest limitations are. Everything here
has been verified by running it, not assumed.

---

## 1. The problem in one paragraph

A model gets trained on a dataset. Six months later somebody asks: was that
really the data? Normally you cannot prove it. Files get edited, overwritten,
or silently corrupted, and nothing records what the file looked like at
training time. A checksum file helps only until the attacker updates the
checksum file too.

## 2. What this system does

It computes a fingerprint of the dataset and writes that fingerprint to a
blockchain. The dataset itself stays on local disk. Only the fingerprint goes
on-chain, where nobody can rewrite it afterwards.

Three things are fingerprinted and anchored:

1. **The file hash** (SHA-256 of the exact bytes) proves the whole file is unchanged.
2. **A Merkle root** built from fixed-size row chunks. This is the interesting
   part: if the file changes, comparing chunk hashes tells you *which* chunks
   changed, not just that something changed.
3. **A metadata digest** covering filename, size, chunk size, timestamps,
   preprocessing operations and parent version, so the provenance record itself
   cannot be forged.

Each new version (for example raw to cleaned) is a new on-chain record linked
to its parent, so the lineage is traceable and earlier versions are never
overwritten.

## 3. The two things worth demonstrating

**The pre-training verification gate.** Before training runs, the system
recomputes the fingerprint and compares it with the chain. If they do not
match, training is blocked. After training, a digest of the run (dataset
version, seed, hyperparameters, metrics, model file hash) is anchored on-chain
too. So the model is cryptographically tied to the exact data it saw.

**Chunk-level localization.** Change one cell in a 600-row CSV and the system
reports exactly one changed chunk. This has been verified in the running UI,
not just in the benchmark.

---

## 4. How to run it

Requirements: Python 3.14 (3.11+ should work), Node.js, and the repo cloned.

Four terminals. Order matters.

```bash
# Terminal 1 - blockchain node. Leave running. Do NOT restart it later.
cd blockchain
npx hardhat node
```

```bash
# Terminal 2 - deploy contract, then start backend
cd blockchain
npx hardhat run scripts/deploy.js --network localhost
cd ..
venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
# Terminal 3 - frontend
cd frontend
npm install        # first time only
npm run dev        # http://localhost:5173
```

```bash
# Terminal 4 - for commands
# (the project root)
```

If the venv does not exist: `python3 -m venv venv && venv/bin/pip install -r requirements.txt`

**Check it works:**

```bash
venv/bin/pytest -q                      # expect 90 passed
cd blockchain && npx hardhat test       # expect 23 passing
```

**Important:** restarting the Hardhat node wipes the chain. Everything
registered before the restart becomes unverifiable. Redeploy the contract and
re-upload your test data if you restart it.

## 5. A 5-minute test run

1. Open http://localhost:5173. Header should say "Chain connected".
2. **Upload page.** Click the "Loan approval" sample card. Set rows per chunk
   to **100**. Click upload. You get a dataset ID, version ID, SHA-256, Merkle
   root, transaction hash, block number, and gas used (253,568).
3. **Prove it is on-chain.** Copy the transaction hash, then in Terminal 4:
   ```bash
   ./scripts/show_chain.sh 0x<paste the hash>
   ```
   This queries the node directly, bypassing the application. It prints the
   same file hash and Merkle root the UI showed.
4. **Verification page.** Pick the dataset, click "Verify stored file".
   Six checks pass in about 20 ms.
5. **Tampering lab.** Pick the same version, attack `modify cells`, fraction
   1%, seed 42. Result: FAIL, with the changed chunks listed. The attack runs
   on a temporary copy; the stored file is never modified (there is a test
   asserting its SHA-256 is unchanged).
6. **Single-cell localization.** Make an edited copy:
   ```bash
   venv/bin/python -c "
   import pandas as pd
   df = pd.read_csv('frontend/public/samples/loan_approval.csv')
   df.at[250, 'income'] = 999999
   df.to_csv('/tmp/edited.csv', index=False)
   "
   ```
   On the Verification page choose "Upload file to compare", select
   `/tmp/edited.csv`, run. Result: FAIL with exactly one changed chunk.
7. **ML experiments page.** Select the dataset. The gate shows PASS. Click
   train. You get accuracy and an on-chain receipt (gas 139,607).
8. **Analytics page.** All the benchmark results, read from
   `docs/results-final/`.

---

## 6. The results (all verified, 30 trials per condition)

Everything below comes from one clean benchmark run at commit `1481f34`,
stored in `docs/results-final/`. The raw CSVs, the generated tables and the
figures are all in that folder, and `run_metadata.json` records the commit,
the software versions and the machine.

Three approaches are compared:

- **A:** file checksums with an editable manifest
- **B:** Git/DVC-style local versioning
- **C:** blockchain-anchored Merkle tree (this work)

### Detection (the main result)

All three approaches catch naive file edits 30/30. The difference appears only
against metadata-aware attackers:

| Attack | A | B | C |
|---|---|---|---|
| forge_metadata | 0/30 | 30/30 | 30/30 |
| smart_attacker | 0/30 | 0/30 | 30/30 |
| all 8 others | 30/30 | 30/30 | 30/30 |

The `smart_attacker` edits the data file *and* updates the local checksum or
amends the git commit, so A and B see a consistent story and pass. C still
fails it, because the attacker cannot rewrite the on-chain record.

**Write it up honestly:** the blockchain's advantage is confined to those two
attacks. Do not claim C detects things the baselines miss across the board.

### False positives

0 out of 100 clean trials for all three approaches (Wilson 95% CI [0%, 3.7%]).

### Localization (approach C only)

Precision 1.0, recall 1.0, exact match 100% across all 12 conditions.

**Caveat to state in the paper:** for row insertions and deletions, the
ground truth is defined as every chunk from the edit point onward, because
fixed-row chunking shifts all later boundaries. So those rows are correct by
construction and are not evidence of precise pinpointing. The meaningful
localization result is for cell modifications and label flips.

### Cost

Gas is constant regardless of dataset size:

| Operation | Measured gas | Slot estimate |
|---|---|---|
| register root version | 253,568 | 242,000 |
| register child version | 260,804 | 247,000 |
| record training run | 139,607 | 131,500 |

Timing (medians, 1MB / 10MB / 100MB):

| | A verify | B verify | C verify | C register |
|---|---|---|---|---|
| 1MB | 0.6 ms | 19.0 ms | 18.6 ms | 53.0 ms |
| 10MB | 6.6 ms | 24.1 ms | 48.4 ms | 133.4 ms |
| 100MB | 50.8 ms | 68.1 ms | 343.4 ms | 990.5 ms |

The blockchain call itself is about 16 ms and does not scale with dataset
size. C's cost is Merkle recomputation (287 ms of the 344 ms at 100MB), not
the chain.

**Unexplained component:** at 100MB, C's registration is about 990 ms, but
hashing + Merkle + transaction only account for about 272 ms. The remaining
~710 ms is file copying, tree construction and metadata serialization. It was
not decomposed further. The `timing_breakdown` table has an `other_ms` column
showing this. Describe it as "I/O, chunking and serialization (not
decomposed)" rather than guessing.

### Storage overhead (approach C)

0.44% at 1MB, 0.27% at 10MB, 0.25% at 100MB. Compare: A is 0.03%, B is 0.11%.
C costs more off-chain metadata because it stores the full Merkle tree.

### Chunk size trade-off (10MB dataset)

| Rows per chunk | Chunks | Tree size | Verify time |
|---|---|---|---|
| 100 | 1,751 | 260 KB | 50.2 ms |
| 1,000 | 176 | 26.5 KB | 46.3 ms |
| 10,000 | 19 | 3.3 KB | 46.3 ms |

Verification time is essentially flat. Smaller chunks buy finer localization
at a storage cost, not a time cost. This is a clean result worth a figure.

### Lineage and reproducibility

All three approaches detect the three structural lineage attacks (forge
parent, delete version, reorder versions) 30/30. Only C blocks the smart
attacker from contaminating training. Reproducibility was tested for approach
C only, 30/30 reproduced.

---

## 7. Limitations (please include these)

These are real and a reviewer will find them. Stating them first is stronger
than being caught.

1. **The local node is not immutable.** Benchmarks ran against a local Hardhat
   node in automine mode. Transaction latency is near zero (about 16 ms) and
   the chain does not survive a restart. On a public chain, block times (12 s
   on Ethereum, about 2 s on L2s) and gas price volatility would dominate
   registration latency. Immutability is a property of a public or permissioned
   deployment; here it is emulated.
2. **Row shifts cannot be pinpointed.** Fixed-row chunking means an insertion
   or deletion changes every later chunk. Detection works; localization
   degrades to "the edit point onward". Content-defined chunking would fix this
   and is good future work.
3. **Integrity is not validity.** A perfectly anchored dataset can still be
   biased, mislabelled or useless. Data quality is explicitly out of scope.
4. **A compromised writer key defeats it.** Whoever holds the key can register
   a tampered file as a legitimate new version. The chain records who and when,
   but cannot prevent it.
5. **Off-chain availability is a separate problem.** If the local file is
   deleted, the chain proves what it was, not where it is.
6. **Detection and localization were benchmarked on the ~1 MB file only.**
   Timing, gas and storage were measured at 1, 10 and 100 MB.
7. **The preprocessing step is dataset-specific.** It has special handling for
   loan-style columns and otherwise falls back to "last column is the target".
   The provenance framework is general; the cleaning step is not.
8. **Hardware:** MacBook Air, arm64, 8 cores, 8 GB RAM. Memory pressure was
   observed during the 100MB runs; some latency figures have high variance
   (approach B at 100MB has a median of 178 ms but a max of 660 ms). Report
   medians for those, not means.

---

## 8. Where everything lives

```
backend/          FastAPI app
  main.py         all HTTP endpoints
  fingerprint.py  chunking, Merkle tree, find_modified_chunks
  chain.py        Web3 client
  verify.py       the verification logic
  ml_pipeline.py  preprocessing, training, the gate, reproduce
blockchain/
  contracts/ProvenanceRegistry.sol    the smart contract
  test/                               23 contract tests
  scripts/deploy.js                   deployment
experiments/
  tamper.py       the 10 attack implementations
  eval/           baselines A and B, experiments E1-E5
  analyze.py      turns raw CSVs into tables and figures
docs/
  00-threat-model-and-protocol.md     threat model, metrics, protocol
  results-final/                      THE RESULTS FOR THE PAPER
    tables/       9 tables as .md and .csv
    figures/      6 figures as .png and .pdf
    run_metadata.json                 commit, versions, machine
frontend/         React UI
tests/            90 Python tests
PLAN.md           73-step build plan, all ticked
```

**For the paper, use `docs/results-final/` only.** It is a single clean
benchmark run from a clean git tree (`git_dirty: false`), so every number
shares one commit hash. Do not mix in numbers from other run folders.

Figures are already generated as PDFs, which should drop straight into LaTeX.

## 9. Reproducing the benchmark

Only if you want to regenerate the numbers. It takes about 8 minutes and needs
the node running with the contract deployed.

```bash
venv/bin/python -m experiments.eval.run_all --profile full
venv/bin/python -m experiments.analyze experiments/results/<new-folder>
```

Results land in a new timestamped folder named after the current commit. The
run refuses to start on a dirty git tree, which is deliberate: it guarantees
results can be traced to exact code.

Note that your numbers will differ slightly from `docs/results-final/` because
timing depends on the machine. Gas and detection rates will be identical, as
they are deterministic.

## 10. Suggested paper structure

1. **Introduction:** the provenance gap in ML pipelines.
2. **Related work:** data versioning (DVC, Git-LFS), blockchain provenance,
   Merkle-tree integrity.
3. **Threat model:** read `docs/00-threat-model-and-protocol.md`. It lists
   what is in and out of scope, which maps directly onto a table.
4. **System design:** chunking and Merkle construction, the contract (append
   only, no update or delete functions, and there is a test asserting the ABI
   contains neither), versioning and lineage, the pre-training gate, the
   experiment digest.
5. **Evaluation protocol:** three approaches, 10 attacks, three modification
   intensities (0.1%, 1%, 10%), three dataset sizes, 30 trials, Wilson
   intervals for proportions and Student's t for timing.
6. **Results:** the tables above.
7. **Discussion and limitations:** section 7 of this document.
8. **Conclusion and future work:** content-defined chunking, a permissioned
   deployment, multi-writer scenarios with key management.

One design detail worth a sentence: the verification gate copies the file to a
private temporary directory, verifies the copy, and then reads only from that
copy. This closes a time-of-check-to-time-of-use gap where an attacker could
swap the file between verification and training.

## 11. If something breaks

| Symptom | Cause | Fix |
|---|---|---|
| Tests skip or return 503 | Node not running | Start Hardhat node |
| "not registered on blockchain" | Node restarted since upload | Redeploy, re-upload |
| Frontend cannot reach backend | Backend not running | Start uvicorn on port 8000 |
| Verification fails on a file you did not touch | Wrong dataset version selected | Check the version ID |

Two known UI bugs at time of writing: the "reproduce run" button on the ML
experiments page may show "Malformed run ID", and the light theme has some
unreadable table text. Use dark mode. Neither affects the backend or the
results.

## 12. Contact points in the code

- The detection and localization logic: `backend/fingerprint.py`
  (`split_csv_into_chunks`, `find_modified_chunks`) and `backend/verify.py`
- The attacks: `experiments/tamper.py`
- How the ground truth for localization is computed:
  `experiments/eval/e1_detection.py`, the `_evaluate_localization` function
- The contract's storage layout and gas: `blockchain/contracts/ProvenanceRegistry.sol`
  and the gas table printed by `npx hardhat test`
