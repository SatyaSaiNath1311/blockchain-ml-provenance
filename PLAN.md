# PLAN: A Lightweight Blockchain Framework for Data Provenance and Integrity in Machine Learning Pipelines

## Phase 0: Scope and evaluation protocol
- [ ] Step 1. Write the threat model: attacks in scope (cell edits, row insert/delete, label flips, column swap, file replacement, version rollback, preprocessing-output tampering, metadata forgery) and out of scope (original data quality, off-chain storage availability, compromised writer key).
- [ ] Step 2. Fix the evaluation protocol now: metrics (detection rate, false-positive rate, localization accuracy, verification time, storage and gas overhead), modification intensities (0.1%, 1%, 10% of rows), dataset sizes, 30 trials per condition, report mean ± std.
Validation: One-page threat model and protocol sheet exist before any code.

## Phase 1: Environment and project foundation
- [ ] Step 3. Verify Python, Node.js, npm and Git installations.
- [ ] Step 4. Create the project root with frontend, backend, blockchain, storage, tests, docs and experiments folders.
- [ ] Step 5. Create a Python virtual environment and install FastAPI, Uvicorn, pandas, NumPy, scikit-learn, Web3.py, pytest.
- [ ] Step 6. Initialize the React frontend with Vite and install routing, HTTP client and charting libraries.
- [ ] Step 7. Initialize the Solidity project with Hardhat.
- [ ] Step 8. Start the local blockchain and verify Python can connect.
- [ ] Step 9. Create environment config files; exclude secrets, uploaded datasets and generated artifacts from Git.
Validation: Frontend runs, backend health check responds, Python connects to the local chain.

## Phase 2: Dataset ingestion and fingerprinting
- [ ] Step 10. Create a small synthetic CSV dataset for initial testing.
- [ ] Step 11. Implement dataset upload and file validation.
- [ ] Step 12. Save the dataset off-chain with a unique dataset ID.
- [ ] Step 13. Generate a SHA-256 hash of the exact file bytes.
- [ ] Step 14. Split the file into fixed-size chunks, hash each chunk, build a Merkle tree, and store the full tree off-chain. Only the root is anchored on-chain.
- [ ] Step 15. Capture metadata: filename, size, type, dataset ID, chunk size, creation time, file hash, Merkle root.
- [ ] Step 16. Store metadata in the off-chain metadata store.
- [ ] Step 17. Test fingerprinting on unchanged and modified files, including that a one-byte change flips the file hash and the Merkle root, and points to the right chunk.
Validation: Identical bytes give identical hashes; a changed byte gives a different hash and identifies the affected chunk.

## Phase 3: Smart contract
- [ ] Step 18. Define the provenance record in Solidity: dataset ID, version ID, parent version, file hash, Merkle root, metadata digest, submitter, timestamp.
- [ ] Step 19. Implement dataset and version registration.
- [ ] Step 20. Add registration events.
- [ ] Step 21. Implement read functions for versions and provenance records.
- [ ] Step 22. Implement `recordTrainingRun` storing the run ID, dataset version ID, and an experiment digest.
- [ ] Step 23. Restrict writes to an authorized owner address, reject duplicate version IDs, and require the parent version to exist.
- [ ] Step 24. Write contract tests: valid registration, duplicate IDs, unauthorized calls, missing parent, version relationships, run recording.
- [ ] Step 25. Deploy to the local Hardhat network.
- [ ] Step 26. Export the ABI and address to the backend config.
Validation: Valid fingerprints and runs are recorded; invalid operations are rejected.

## Phase 4: Versioning and provenance
- [ ] Step 27. Register the original dataset as Version 1.
- [ ] Step 28. Create new versions without overwriting earlier ones.
- [ ] Step 29. Link each new version to its parent.
- [ ] Step 30. Record preprocessing operations, parameters, software versions, code commit hash, and timestamps.
- [ ] Step 31. Compute a digest of the provenance metadata and anchor it on-chain.
- [ ] Step 32. Implement lineage retrieval from the original through all later versions.
- [ ] Step 33. Implement dataset and version lookup APIs.
Validation: The full version history and the origin of any version can be reconstructed.

## Phase 5: Integrity verification and tampering
- [ ] Step 34. Retrieve the expected fingerprint (file hash and Merkle root) from the blockchain.
- [ ] Step 35. Recompute the file hash and Merkle root of the selected dataset.
- [ ] Step 36. Compare actual and registered values; return VERIFIED or TAMPERING DETECTED.
- [ ] Step 37. On mismatch, walk the Merkle tree and report which chunks changed.
- [ ] Step 38. Check lineage consistency: parent chain intact, timestamps monotonic, rollback to an older version detected.
- [ ] Step 39. Run controlled tampering tests: modify a cell, delete a row, insert a row, flip a label, swap a column, replace the file, roll back a version, modify preprocessing output, forge off-chain metadata.
- [ ] Step 40. Preserve the original record and create a new version when a legitimate change is intended.
- [ ] Step 41. Add tests for missing files, invalid dataset IDs, and unregistered versions.
Validation: Unmodified data passes, every modification fails, and results rely on the on-chain record, not an editable local hash file.

## Phase 6: ML pipeline integration
- [ ] Step 42. Build the preprocessing pipeline with pandas and scikit-learn.
- [ ] Step 43. Record missing-value handling, encoding, scaling, and other transformations.
- [ ] Step 44. Register the processed dataset as a new version.
- [ ] Step 45. Add a pre-training verification gate: training aborts if the dataset fails verification against the chain.
- [ ] Step 46. Train a baseline model (Random Forest) on the selected version.
- [ ] Step 47. Record the dataset version, preprocessing config, model parameters, random seed, and code revision.
- [ ] Step 48. Store the model artifact and evaluation results off-chain.
- [ ] Step 49. Anchor the experiment digest (config plus model hash) on-chain via `recordTrainingRun`.
- [ ] Step 50. Implement experiment lookup and a reproducibility-check workflow.
- [ ] Step 51. Test that the gate blocks training on tampered data and allows it on verified data.
Validation: Every experiment identifies the exact dataset version and configuration, and tampered data cannot reach training.

## Phase 7: Conventional versus blockchain evaluation
- [ ] Step 52. Implement baseline A: files with editable metadata and checksums.
- [ ] Step 53. Implement baseline B: Git/DVC-style versioning.
- [ ] Step 54. Run identical registration, verification and tampering experiments on all three approaches.
- [ ] Step 55. Measure hashing and verification time separately from blockchain transaction latency.
- [ ] Step 56. Measure off-chain metadata storage, on-chain storage, and gas per transaction.
- [ ] Step 57. Test multiple dataset sizes and the 0.1%, 1%, 10% modification intensities; compute detection rate, false-positive rate, and localization accuracy per attack type.
- [ ] Step 58. Evaluate lineage reconstruction and reproducibility.
- [ ] Step 59. Run 30 trials per condition; report mean ± std.
- [ ] Step 60. Generate comparison charts and summary tables.
Validation: Results tables cover all three approaches, with variability reported.

## Phase 8: React UI
- [ ] Step 61. Build the app shell, navigation, header, and layout.
- [ ] Step 62. Build the upload page with progress, metadata, and fingerprint display.
- [ ] Step 63. Build the dataset explorer with version history and an interactive lineage graph.
- [ ] Step 64. Build the verification page: expected vs. actual hash, PASS/FAIL, changed chunks.
- [ ] Step 65. Build the tampering lab with controlled modifications and before/after comparison.
- [ ] Step 66. Build the ML experiment page with preprocessing history and dataset-version links.
- [ ] Step 67. Build the analytics page using the Phase 7 results.
- [ ] Step 68. Connect all pages to the real FastAPI endpoints; add loading, validation, error, and empty states.
- [ ] Step 69. Test the full user journey in the browser.
- Optional if time allows: overview dashboard and blockchain explorer.
Validation: Upload, register, modify, verify, trace, and inspect experiments entirely through the UI.

## Phase 9: Analysis and writing
- [ ] Step 70. Analyze results and trade-offs: blockchain write latency and gas vs. removing a single trusted record keeper.
- [ ] Step 71. Write the limitations section (trust boundary, off-chain availability, key compromise).
- [ ] Step 72. Draft the paper: Abstract, Introduction, Related Work, Architecture, Implementation, Experiments, Results, Limitations, Conclusion.
- [ ] Step 73. Prepare the repo README and a reproducibility package (configs, seeds, scripts).
Validation: Paper draft and a repo anyone can rerun end to end.