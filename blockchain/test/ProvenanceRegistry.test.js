const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("ProvenanceRegistry", function () {
  let registry;
  let owner;
  let unauthorized;

  const datasetA = ethers.keccak256(ethers.toUtf8Bytes("dataset_A"));
  const datasetB = ethers.keccak256(ethers.toUtf8Bytes("dataset_B"));

  const version1 = ethers.keccak256(ethers.toUtf8Bytes("version_1"));
  const version2 = ethers.keccak256(ethers.toUtf8Bytes("version_2"));
  const version3 = ethers.keccak256(ethers.toUtf8Bytes("version_3"));
  const versionB1 = ethers.keccak256(ethers.toUtf8Bytes("version_B1"));

  const fileHash1 = ethers.keccak256(ethers.toUtf8Bytes("file_content_1"));
  const merkleRoot1 = ethers.keccak256(ethers.toUtf8Bytes("merkle_tree_1"));
  const metadataDigest1 = ethers.keccak256(ethers.toUtf8Bytes("metadata_digest_1"));

  const fileHash2 = ethers.keccak256(ethers.toUtf8Bytes("file_content_2"));
  const merkleRoot2 = ethers.keccak256(ethers.toUtf8Bytes("merkle_tree_2"));
  const metadataDigest2 = ethers.keccak256(ethers.toUtf8Bytes("metadata_digest_2"));

  const runId1 = ethers.keccak256(ethers.toUtf8Bytes("run_001"));
  const experimentDigest1 = ethers.keccak256(ethers.toUtf8Bytes("model_seed_config_1"));

  const ZERO_BYTES32 = ethers.ZeroHash;

  const gasTable = [];

  beforeEach(async function () {
    [owner, unauthorized] = await ethers.getSigners();
    const Factory = await ethers.getContractFactory("ProvenanceRegistry");
    registry = await Factory.deploy();
    await registry.waitForDeployment();
  });

  after(function () {
    console.log("\n==================== PHASE 3 GAS CONSUMPTION ====================");
    console.table(gasTable);
    console.log("=================================================================\n");
  });

  describe("Deployment & Access Control", function () {
    it("sets the deployer as owner", async function () {
      expect(await registry.owner()).to.equal(owner.address);
    });

    it("verifies the ABI contains no update or delete functions (append-only guarantee)", function () {
      const functionNames = registry.interface.fragments
        .filter((f) => f.type === "function")
        .map((f) => f.name);

      const forbiddenKeywords = ["update", "modify", "delete", "remove", "clear", "transferownership"];

      for (const name of functionNames) {
        const lower = name.toLowerCase();
        for (const kw of forbiddenKeywords) {
          expect(lower).to.not.include(kw, `Forbidden mutator function detected: ${name}`);
        }
        expect(lower.startsWith("set")).to.be.false;
      }
    });

    it("rejects unauthorized caller on registerVersion", async function () {
      await expect(
        registry.connect(unauthorized).registerVersion(
          datasetA,
          version1,
          ZERO_BYTES32,
          fileHash1,
          merkleRoot1,
          5,
          metadataDigest1
        )
      ).to.be.revertedWithCustomError(registry, "UnauthorizedCaller");
    });

    it("rejects unauthorized caller on recordTrainingRun", async function () {
      await expect(
        registry.connect(unauthorized).recordTrainingRun(runId1, version1, experimentDigest1)
      ).to.be.revertedWithCustomError(registry, "UnauthorizedCaller");
    });
  });

  describe("Version Registration", function () {
    it("successfully registers a root version and emits VersionRegistered", async function () {
      const tx = await registry.registerVersion(
        datasetA,
        version1,
        ZERO_BYTES32,
        fileHash1,
        merkleRoot1,
        10,
        metadataDigest1
      );
      const receipt = await tx.wait();

      gasTable.push({
        Function: "registerVersion",
        Scenario: "Root Version",
        GasUsed: receipt.gasUsed.toString(),
      });

      await expect(tx)
        .to.emit(registry, "VersionRegistered")
        .withArgs(datasetA, version1, ZERO_BYTES32, merkleRoot1, 10, owner.address, await getBlockTimestamp(receipt));

      expect(await registry.versionExists(version1)).to.be.true;

      const record = await registry.getVersion(version1);
      expect(record.datasetId).to.equal(datasetA);
      expect(record.versionId).to.equal(version1);
      expect(record.parentVersionId).to.equal(ZERO_BYTES32);
      expect(record.fileHash).to.equal(fileHash1);
      expect(record.merkleRoot).to.equal(merkleRoot1);
      expect(record.numChunks).to.equal(10);
      expect(record.metadataDigest).to.equal(metadataDigest1);
      expect(record.submitter).to.equal(owner.address);
    });

    it("successfully registers a child version linked to parent", async function () {
      // Register root
      await registry.registerVersion(
        datasetA,
        version1,
        ZERO_BYTES32,
        fileHash1,
        merkleRoot1,
        10,
        metadataDigest1
      );

      // Register child
      const tx = await registry.registerVersion(
        datasetA,
        version2,
        version1,
        fileHash2,
        merkleRoot2,
        12,
        metadataDigest2
      );
      const receipt = await tx.wait();

      gasTable.push({
        Function: "registerVersion",
        Scenario: "Child Version",
        GasUsed: receipt.gasUsed.toString(),
      });

      const record = await registry.getVersion(version2);
      expect(record.parentVersionId).to.equal(version1);
      expect(record.datasetId).to.equal(datasetA);

      const history = await registry.getDatasetVersions(datasetA);
      expect(history).to.deep.equal([version1, version2]);
    });

    it("rejects zero datasetId", async function () {
      await expect(
        registry.registerVersion(
          ZERO_BYTES32,
          version1,
          ZERO_BYTES32,
          fileHash1,
          merkleRoot1,
          10,
          metadataDigest1
        )
      ).to.be.revertedWithCustomError(registry, "ZeroIdentifier");
    });

    it("rejects zero versionId", async function () {
      await expect(
        registry.registerVersion(
          datasetA,
          ZERO_BYTES32,
          ZERO_BYTES32,
          fileHash1,
          merkleRoot1,
          10,
          metadataDigest1
        )
      ).to.be.revertedWithCustomError(registry, "ZeroIdentifier");
    });

    it("rejects zero fileHash, merkleRoot, or metadataDigest", async function () {
      await expect(
        registry.registerVersion(
          datasetA,
          version1,
          ZERO_BYTES32,
          ZERO_BYTES32,
          merkleRoot1,
          10,
          metadataDigest1
        )
      ).to.be.revertedWithCustomError(registry, "ZeroHash");

      await expect(
        registry.registerVersion(
          datasetA,
          version1,
          ZERO_BYTES32,
          fileHash1,
          ZERO_BYTES32,
          10,
          metadataDigest1
        )
      ).to.be.revertedWithCustomError(registry, "ZeroHash");

      await expect(
        registry.registerVersion(
          datasetA,
          version1,
          ZERO_BYTES32,
          fileHash1,
          merkleRoot1,
          10,
          ZERO_BYTES32
        )
      ).to.be.revertedWithCustomError(registry, "ZeroHash");
    });

    it("rejects zero numChunks", async function () {
      await expect(
        registry.registerVersion(
          datasetA,
          version1,
          ZERO_BYTES32,
          fileHash1,
          merkleRoot1,
          0,
          metadataDigest1
        )
      ).to.be.revertedWithCustomError(registry, "ZeroChunks");
    });

    it("rejects duplicate versionId", async function () {
      await registry.registerVersion(
        datasetA,
        version1,
        ZERO_BYTES32,
        fileHash1,
        merkleRoot1,
        10,
        metadataDigest1
      );

      await expect(
        registry.registerVersion(
          datasetA,
          version1,
          ZERO_BYTES32,
          fileHash2,
          merkleRoot2,
          15,
          metadataDigest2
        )
      ).to.be.revertedWithCustomError(registry, "VersionAlreadyExists").withArgs(version1);
    });

    it("rejects second root version for the same dataset", async function () {
      await registry.registerVersion(
        datasetA,
        version1,
        ZERO_BYTES32,
        fileHash1,
        merkleRoot1,
        10,
        metadataDigest1
      );

      // Attempt second root for datasetA
      await expect(
        registry.registerVersion(
          datasetA,
          version2,
          ZERO_BYTES32,
          fileHash2,
          merkleRoot2,
          10,
          metadataDigest2
        )
      ).to.be.revertedWithCustomError(registry, "DatasetAlreadyInitialized").withArgs(datasetA);
    });

    it("rejects child version with nonexistent parent", async function () {
      const nonExistentParent = ethers.keccak256(ethers.toUtf8Bytes("phantom_parent"));

      await expect(
        registry.registerVersion(
          datasetA,
          version1,
          nonExistentParent,
          fileHash1,
          merkleRoot1,
          10,
          metadataDigest1
        )
      ).to.be.revertedWithCustomError(registry, "ParentVersionNotFound").withArgs(nonExistentParent);
    });

    it("rejects child version whose parent belongs to a different dataset", async function () {
      // Register version1 under datasetA
      await registry.registerVersion(
        datasetA,
        version1,
        ZERO_BYTES32,
        fileHash1,
        merkleRoot1,
        10,
        metadataDigest1
      );

      // Attempt to register versionB1 under datasetB pointing to parent from datasetA
      await expect(
        registry.registerVersion(
          datasetB,
          versionB1,
          version1,
          fileHash2,
          merkleRoot2,
          8,
          metadataDigest2
        )
      ).to.be.revertedWithCustomError(registry, "ParentDatasetMismatch").withArgs(datasetB, datasetA);
    });

    it("maintains strict registration order in getDatasetVersions", async function () {
      await registry.registerVersion(datasetA, version1, ZERO_BYTES32, fileHash1, merkleRoot1, 1, metadataDigest1);
      await registry.registerVersion(datasetA, version2, version1, fileHash2, merkleRoot2, 2, metadataDigest2);
      await registry.registerVersion(datasetA, version3, version2, fileHash1, merkleRoot1, 3, metadataDigest1);

      const list = await registry.getDatasetVersions(datasetA);
      expect(list).to.deep.equal([version1, version2, version3]);
    });
  });

  describe("Training Run Recording", function () {
    beforeEach(async function () {
      // Register version1 under datasetA as prerequisite
      await registry.registerVersion(
        datasetA,
        version1,
        ZERO_BYTES32,
        fileHash1,
        merkleRoot1,
        10,
        metadataDigest1
      );
    });

    it("records training run and emits TrainingRunRecorded", async function () {
      const tx = await registry.recordTrainingRun(runId1, version1, experimentDigest1);
      const receipt = await tx.wait();

      gasTable.push({
        Function: "recordTrainingRun",
        Scenario: "Valid Run",
        GasUsed: receipt.gasUsed.toString(),
      });

      await expect(tx)
        .to.emit(registry, "TrainingRunRecorded")
        .withArgs(runId1, version1, experimentDigest1, owner.address, await getBlockTimestamp(receipt));

      expect(await registry.runExists(runId1)).to.be.true;

      const run = await registry.getRun(runId1);
      expect(run.runId).to.equal(runId1);
      expect(run.datasetVersionId).to.equal(version1);
      expect(run.experimentDigest).to.equal(experimentDigest1);
      expect(run.submitter).to.equal(owner.address);
    });

    it("rejects training run with zero runId or zero experimentDigest", async function () {
      await expect(
        registry.recordTrainingRun(ZERO_BYTES32, version1, experimentDigest1)
      ).to.be.revertedWithCustomError(registry, "ZeroIdentifier");

      await expect(
        registry.recordTrainingRun(runId1, version1, ZERO_BYTES32)
      ).to.be.revertedWithCustomError(registry, "ZeroHash");
    });

    it("rejects duplicate runId", async function () {
      await registry.recordTrainingRun(runId1, version1, experimentDigest1);

      await expect(
        registry.recordTrainingRun(runId1, version1, experimentDigest1)
      ).to.be.revertedWithCustomError(registry, "RunAlreadyExists").withArgs(runId1);
    });

    it("rejects training run for unregistered dataset version", async function () {
      const phantomVersion = ethers.keccak256(ethers.toUtf8Bytes("phantom_version"));

      await expect(
        registry.recordTrainingRun(runId1, phantomVersion, experimentDigest1)
      ).to.be.revertedWithCustomError(registry, "VersionNotFound").withArgs(phantomVersion);
    });
  });

  describe("Reverts on Unknown IDs", function () {
    it("getVersion reverts with VersionNotFound for unregistered ID", async function () {
      const unknownId = ethers.keccak256(ethers.toUtf8Bytes("unknown_v"));
      await expect(registry.getVersion(unknownId))
        .to.be.revertedWithCustomError(registry, "VersionNotFound")
        .withArgs(unknownId);
    });

    it("getRun reverts with RunNotFound for unregistered ID", async function () {
      const unknownId = ethers.keccak256(ethers.toUtf8Bytes("unknown_r"));
      await expect(registry.getRun(unknownId))
        .to.be.revertedWithCustomError(registry, "RunNotFound")
        .withArgs(unknownId);
    });

    it("versionExists returns false for zero or unregistered ID", async function () {
      expect(await registry.versionExists(ZERO_BYTES32)).to.be.false;
      expect(await registry.versionExists(version1)).to.be.false;
    });

    it("runExists returns false for zero or unregistered ID", async function () {
      expect(await registry.runExists(ZERO_BYTES32)).to.be.false;
      expect(await registry.runExists(runId1)).to.be.false;
    });
  });
});

async function getBlockTimestamp(receipt) {
  const block = await ethers.provider.getBlock(receipt.blockNumber);
  return block.timestamp;
}
