Project: Lightweight Blockchain Framework for Data Provenance and Integrity in ML Pipelines.
Source of truth: PLAN.md. Work only on the phase I name; do not skip or reorder steps.
Stack: Python (FastAPI, Web3.py, pandas, scikit-learn, pytest), Hardhat/Solidity, React + Vite.
Rules:
- Never store datasets on-chain; only hashes, Merkle roots, and digests.
- Verification must read from the blockchain, never from an editable local hash file.
- Every step needs a test or a runnable check. Show the command and its output.
- Never hardcode or invent experiment results; all metrics must come from scripts in /experiments with fixed seeds.
- Do not touch secrets or .env files; keep generated data out of Git.
- At the end of each phase, report: steps completed, validation result, open issues.