// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/**
 * @title ProvenanceRegistry
 * @notice Lightweight registry for machine learning dataset and pipeline provenance.
 * @dev Stores only cryptographic hashes, roots, digests, and metadata. No datasets or strings on-chain.
 */
contract ProvenanceRegistry {
    // ------------------------------------------------------------------------
    // Custom Errors
    // ------------------------------------------------------------------------
    error UnauthorizedCaller();
    error ZeroIdentifier();
    error ZeroHash();
    error ZeroChunks();
    error VersionAlreadyExists(bytes32 versionId);
    error VersionNotFound(bytes32 versionId);
    error DatasetAlreadyInitialized(bytes32 datasetId);
    error ParentVersionNotFound(bytes32 parentVersionId);
    error ParentDatasetMismatch(bytes32 expectedDatasetId, bytes32 actualDatasetId);
    error RunAlreadyExists(bytes32 runId);
    error RunNotFound(bytes32 runId);

    // ------------------------------------------------------------------------
    // Data Structures
    // ------------------------------------------------------------------------
    struct VersionRecord {
        bytes32 datasetId;
        bytes32 versionId;
        bytes32 parentVersionId;
        bytes32 fileHash;
        bytes32 merkleRoot;
        uint32 numChunks;
        bytes32 metadataDigest;
        address submitter;
        uint64 timestamp;
    }

    struct TrainingRunRecord {
        bytes32 runId;
        bytes32 datasetVersionId;
        bytes32 experimentDigest;
        address submitter;
        uint64 timestamp;
    }

    // ------------------------------------------------------------------------
    // Events
    // ------------------------------------------------------------------------
    event VersionRegistered(
        bytes32 indexed datasetId,
        bytes32 indexed versionId,
        bytes32 parentVersionId,
        bytes32 merkleRoot,
        uint32 numChunks,
        address submitter,
        uint64 timestamp
    );

    event TrainingRunRecorded(
        bytes32 indexed runId,
        bytes32 indexed datasetVersionId,
        bytes32 experimentDigest,
        address submitter,
        uint64 timestamp
    );

    // ------------------------------------------------------------------------
    // State Variables
    // ------------------------------------------------------------------------
    address public immutable owner;

    mapping(bytes32 => VersionRecord) private versions;
    mapping(bytes32 => bool) private _versionExists;
    mapping(bytes32 => bytes32[]) private datasetVersions;

    mapping(bytes32 => TrainingRunRecord) private runs;
    mapping(bytes32 => bool) private _runExists;

    // ------------------------------------------------------------------------
    // Modifiers
    // ------------------------------------------------------------------------
    modifier onlyOwner() {
        if (msg.sender != owner) revert UnauthorizedCaller();
        _;
    }

    // ------------------------------------------------------------------------
    // Constructor
    // ------------------------------------------------------------------------
    constructor() {
        owner = msg.sender;
    }

    // ------------------------------------------------------------------------
    // Write Functions
    // ------------------------------------------------------------------------

    /**
     * @notice Registers a new dataset version record in an append-only structure.
     * @param datasetId Unique identifier for the dataset family.
     * @param versionId Unique identifier for this specific version.
     * @param parentVersionId Identifier of direct parent version (bytes32(0) for root version).
     * @param fileHash SHA-256 digest of exact file bytes.
     * @param merkleRoot Domain-separated Merkle root of row chunks.
     * @param numChunks Total number of chunks in the Merkle tree (required for collision disambiguation).
     * @param metadataDigest SHA-256 digest of canonical off-chain metadata JSON.
     */
    function registerVersion(
        bytes32 datasetId,
        bytes32 versionId,
        bytes32 parentVersionId,
        bytes32 fileHash,
        bytes32 merkleRoot,
        uint32 numChunks,
        bytes32 metadataDigest
    ) external onlyOwner {
        if (datasetId == bytes32(0) || versionId == bytes32(0)) revert ZeroIdentifier();
        if (_versionExists[versionId]) revert VersionAlreadyExists(versionId);
        if (fileHash == bytes32(0) || merkleRoot == bytes32(0) || metadataDigest == bytes32(0)) revert ZeroHash();
        if (numChunks == 0) revert ZeroChunks();

        if (parentVersionId == bytes32(0)) {
            // Root version: dataset must not have any registered versions yet
            if (datasetVersions[datasetId].length != 0) revert DatasetAlreadyInitialized(datasetId);
        } else {
            // Child version: parent must exist and belong to the same dataset
            if (!_versionExists[parentVersionId]) revert ParentVersionNotFound(parentVersionId);
            bytes32 parentDataset = versions[parentVersionId].datasetId;
            if (parentDataset != datasetId) revert ParentDatasetMismatch(datasetId, parentDataset);
        }

        uint64 currentTime = uint64(block.timestamp);

        versions[versionId] = VersionRecord({
            datasetId: datasetId,
            versionId: versionId,
            parentVersionId: parentVersionId,
            fileHash: fileHash,
            merkleRoot: merkleRoot,
            numChunks: numChunks,
            metadataDigest: metadataDigest,
            submitter: msg.sender,
            timestamp: currentTime
        });

        _versionExists[versionId] = true;
        datasetVersions[datasetId].push(versionId);

        emit VersionRegistered(
            datasetId,
            versionId,
            parentVersionId,
            merkleRoot,
            numChunks,
            msg.sender,
            currentTime
        );
    }

    /**
     * @notice Records an ML training run linking an experiment digest to a dataset version.
     * @param runId Unique experiment run identifier.
     * @param datasetVersionId Registered dataset version used for training.
     * @param experimentDigest Digest of training config and model artifact.
     */
    function recordTrainingRun(
        bytes32 runId,
        bytes32 datasetVersionId,
        bytes32 experimentDigest
    ) external onlyOwner {
        if (runId == bytes32(0)) revert ZeroIdentifier();
        if (experimentDigest == bytes32(0)) revert ZeroHash();
        if (_runExists[runId]) revert RunAlreadyExists(runId);
        if (!_versionExists[datasetVersionId]) revert VersionNotFound(datasetVersionId);

        uint64 currentTime = uint64(block.timestamp);

        runs[runId] = TrainingRunRecord({
            runId: runId,
            datasetVersionId: datasetVersionId,
            experimentDigest: experimentDigest,
            submitter: msg.sender,
            timestamp: currentTime
        });

        _runExists[runId] = true;

        emit TrainingRunRecorded(
            runId,
            datasetVersionId,
            experimentDigest,
            msg.sender,
            currentTime
        );
    }

    // ------------------------------------------------------------------------
    // Read Functions
    // ------------------------------------------------------------------------

    /**
     * @notice Fetches the full version record for a given version ID.
     */
    function getVersion(bytes32 versionId) external view returns (VersionRecord memory) {
        if (!_versionExists[versionId]) revert VersionNotFound(versionId);
        return versions[versionId];
    }

    /**
     * @notice Checks whether a version ID has been registered.
     */
    function versionExists(bytes32 versionId) external view returns (bool) {
        return _versionExists[versionId];
    }

    /**
     * @notice Returns all version IDs registered under a dataset in order.
     */
    function getDatasetVersions(bytes32 datasetId) external view returns (bytes32[] memory) {
        return datasetVersions[datasetId];
    }

    /**
     * @notice Fetches a training run record by run ID.
     */
    function getRun(bytes32 runId) external view returns (TrainingRunRecord memory) {
        if (!_runExists[runId]) revert RunNotFound(runId);
        return runs[runId];
    }

    /**
     * @notice Checks whether a training run ID has been recorded.
     */
    function runExists(bytes32 runId) external view returns (bool) {
        return _runExists[runId];
    }
}
