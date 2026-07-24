// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IBridgeMintableERC20 {
    function bridgeMint(address recipient, uint256 amount) external;
}

interface IBridgeMintableERC721 {
    function bridgeMint(address recipient, uint256 tokenId) external;
}

/// @title JUNCA Testnet Bridge Asset Adapter
/// @notice Public Testnet / No Monetary Value.
/// @dev Governance display: JAIOS Institutional Governance.
contract JuncaBridgeAssetAdapter {
    string public constant GOVERNANCE_DISPLAY = "JAIOS Institutional Governance";
    string public constant TESTNET_NOTICE = "Public Testnet / No Monetary Value";
    bytes32 public constant FUNGIBLE = keccak256("fungible");
    bytes32 public constant NFT = keccak256("nft");

    struct AssetPolicy {
        bytes32 assetType;
        bool enabled;
    }

    address public immutable bridge;
    address public institutionalGovernance;
    address public pendingInstitutionalGovernance;
    address public guardian;
    bool public paused = true;

    mapping(address => AssetPolicy) public assetPolicy;

    event AssetPolicyChanged(address indexed asset, bytes32 indexed assetType, bool enabled);
    event AssetMinted(
        address indexed asset,
        address indexed recipient,
        bytes32 indexed assetType,
        uint256 value,
        uint256 tokenId
    );
    event PauseChanged(bool paused);
    event GuardianChanged(address indexed guardian);
    event GovernanceTransferProposed(address indexed pendingGovernance);
    event GovernanceTransferred(address indexed previousGovernance, address indexed newGovernance);

    error Unauthorized();
    error InvalidConfiguration();
    error RoutePaused();
    error UnsupportedAsset();
    error InvalidAddressEncoding();

    modifier onlyGovernance() {
        if (msg.sender != institutionalGovernance) revert Unauthorized();
        _;
    }

    constructor(address bridge_, address governance_, address guardian_) {
        if (
            bridge_ == address(0) ||
            governance_ == address(0) ||
            guardian_ == address(0)
        ) revert InvalidConfiguration();
        bridge = bridge_;
        institutionalGovernance = governance_;
        guardian = guardian_;
    }

    function releaseOrMint(
        bytes32 assetType,
        bytes32 destinationAsset,
        bytes32 recipient,
        uint256 value,
        uint256 tokenId
    ) external {
        if (msg.sender != bridge) revert Unauthorized();
        if (paused) revert RoutePaused();
        address asset = _decodeAddress(destinationAsset);
        address recipientAddress = _decodeAddress(recipient);
        AssetPolicy memory policy = assetPolicy[asset];
        if (!policy.enabled || policy.assetType != assetType) revert UnsupportedAsset();

        if (assetType == FUNGIBLE) {
            if (value == 0 || tokenId != 0) revert InvalidConfiguration();
            IBridgeMintableERC20(asset).bridgeMint(recipientAddress, value);
        } else if (assetType == NFT) {
            if (value != 1) revert InvalidConfiguration();
            IBridgeMintableERC721(asset).bridgeMint(recipientAddress, tokenId);
        } else {
            revert UnsupportedAsset();
        }

        emit AssetMinted(asset, recipientAddress, assetType, value, tokenId);
    }

    function setAssetPolicy(
        address asset,
        bytes32 assetType,
        bool enabled
    ) external onlyGovernance {
        if (
            asset == address(0) ||
            (assetType != FUNGIBLE && assetType != NFT)
        ) revert InvalidConfiguration();
        assetPolicy[asset] = AssetPolicy(assetType, enabled);
        emit AssetPolicyChanged(asset, assetType, enabled);
    }

    function setPaused(bool paused_) external {
        if (msg.sender != institutionalGovernance) {
            if (msg.sender != guardian || paused_ == false) revert Unauthorized();
        }
        paused = paused_;
        emit PauseChanged(paused_);
    }

    function setGuardian(address guardian_) external onlyGovernance {
        if (guardian_ == address(0)) revert InvalidConfiguration();
        guardian = guardian_;
        emit GuardianChanged(guardian_);
    }

    function proposeGovernance(address nextGovernance) external onlyGovernance {
        if (nextGovernance == address(0)) revert InvalidConfiguration();
        pendingInstitutionalGovernance = nextGovernance;
        emit GovernanceTransferProposed(nextGovernance);
    }

    function acceptGovernance() external {
        if (msg.sender != pendingInstitutionalGovernance) revert Unauthorized();
        address previous = institutionalGovernance;
        institutionalGovernance = msg.sender;
        pendingInstitutionalGovernance = address(0);
        emit GovernanceTransferred(previous, msg.sender);
    }

    function _decodeAddress(bytes32 encoded) private pure returns (address) {
        if (uint256(encoded) >> 160 != 0) revert InvalidAddressEncoding();
        address decoded = address(uint160(uint256(encoded)));
        if (decoded == address(0)) revert InvalidAddressEncoding();
        return decoded;
    }
}
