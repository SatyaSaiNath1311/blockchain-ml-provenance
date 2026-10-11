const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const network = await hre.ethers.provider.getNetwork();

  console.log("==================================================");
  console.log("  DEPLOYING PROVENANCE REGISTRY SMART CONTRACT    ");
  console.log("==================================================");
  console.log(` Deployer address: ${deployer.address}`);
  console.log(` Network Name    : ${network.name}`);
  console.log(` Chain ID        : ${network.chainId}`);

  const ProvenanceRegistry = await hre.ethers.getContractFactory("ProvenanceRegistry");
  const registry = await ProvenanceRegistry.deploy();
  await registry.waitForDeployment();

  const contractAddress = await registry.getAddress();
  const deploymentTx = registry.deploymentTransaction();
  const receipt = await deploymentTx.wait();

  console.log(` Contract Address: ${contractAddress}`);
  console.log(` Deployed at block: ${receipt.blockNumber}`);
  console.log("==================================================");

  // Target directory for backend contract integration
  const backendContractsDir = path.resolve(__dirname, "../../backend/contracts");
  if (!fs.existsSync(backendContractsDir)) {
    fs.mkdirSync(backendContractsDir, { recursive: true });
  }

  // 1. Export ABI only (to be committed)
  const artifact = await hre.artifacts.readArtifact("ProvenanceRegistry");
  const abiPath = path.join(backendContractsDir, "ProvenanceRegistry.abi.json");
  fs.writeFileSync(abiPath, JSON.stringify(artifact.abi, null, 2), "utf-8");
  console.log(` [Export] Saved ABI to: ${abiPath}`);

  // 2. Export deployment details (gitignored)
  const deploymentInfo = {
    contractAddress: contractAddress,
    chainId: Number(network.chainId),
    deployer: deployer.address,
    blockNumber: receipt.blockNumber,
    timestamp: Math.floor(Date.now() / 1000),
  };
  const deploymentPath = path.join(backendContractsDir, "deployment.json");
  fs.writeFileSync(deploymentPath, JSON.stringify(deploymentInfo, null, 2), "utf-8");
  console.log(` [Export] Saved deployment details to: ${deploymentPath}`);
  console.log("Deployment completed successfully.\n");
}

main().catch((error) => {
  console.error("Deployment failed:", error);
  process.exitCode = 1;
});
