// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice Destination-specific adapter. It must be independently audited.
interface IJuncaBridgeAssetAdapter {
    function releaseOrMint(
        bytes32 assetType,
        bytes32 destinationAsset,
        bytes32 recipient,
        uint256 value,
        uint256 tokenId
    ) external;
}

/// @title JUNCA Social Ecosystem Chain Testnet Bridge
/// @notice Public Testnet / No Monetary Value.
/// @dev Governance display: JAIOS Institutional Governance.
contract JuncaTestnetBridge {
    string public constant GOVERNANCE_DISPLAY = "JAIOS Institutional Governance";
    string public constant TESTNET_NOTICE = "Public Testnet / No Monetary Value";

    bytes32 public constant MESSAGE_TYPEHASH = keccak256(
        "BridgeMessage(bytes32 routeDigest,bytes32 direction,bytes32 sourceNetwork,bytes32 destinationNetwork,uint256 nonce,bytes32 sourceTransaction,uint256 sourceBlock,bytes32 assetType,bytes32 sourceAsset,bytes32 destinationAsset,bytes32 sender,bytes32 recipient,uint256 value,uint256 tokenId,uint256 deadline)"
    );
    uint256 private constant SECP256K1N_HALF =
        0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0;

    struct BridgeMessage {
        bytes32 routeDigest;
        bytes32 direction;
        bytes32 sourceNetwork;
        bytes32 destinationNetwork;
        uint256 nonce;
        bytes32 sourceTransaction;
        uint256 sourceBlock;
        bytes32 assetType;
        bytes32 sourceAsset;
        bytes32 destinationAsset;
        bytes32 sender;
        bytes32 recipient;
        uint256 value;
        uint256 tokenId;
        uint256 deadline;
    }

    address public institutionalGovernance;
    address public pendingInstitutionalGovernance;
    address public guardian;
    IJuncaBridgeAssetAdapter public immutable assetAdapter;
    bytes32 public immutable routeDigest;

    bool public paused = true;
    uint256 public relayerCount;
    uint256 public signatureThreshold;
    uint256 public perTransactionLimit;
    uint256 public dailyLimit;
    uint256 public currentDay;
    uint256 public executedToday;

    mapping(address => bool) public isRelayer;
    mapping(bytes32 => bool) public processedMessage;
    mapping(bytes32 => bool) public processedSourceTransaction;
    mapping(bytes32 => bool) public processedSourceNonce;

    uint256 private locked = 1;

    event MessageExecuted(
        bytes32 indexed messageDigest,
        bytes32 indexed sourceTransaction,
        bytes32 indexed destinationNetwork,
        uint256 nonce,
        uint256 value,
        uint256 tokenId
    );
    event PauseChanged(bool paused);
    event RelayerChanged(address indexed relayer, bool active);
    event ThresholdChanged(uint256 threshold);
    event LimitsChanged(uint256 perTransactionLimit, uint256 dailyLimit);
    event GuardianChanged(address indexed guardian);
    event GovernanceTransferProposed(address indexed pendingGovernance);
    event GovernanceTransferred(address indexed previousGovernance, address indexed newGovernance);

    error Unauthorized();
    error InvalidConfiguration();
    error InvalidMessage();
    error InvalidSignature();
    error InsufficientSignatures();
    error Replay();
    error Expired();
    error RoutePaused();
    error RateLimitExceeded();
    error ReentrantCall();

    modifier onlyGovernance() {
        if (msg.sender != institutionalGovernance) revert Unauthorized();
        _;
    }

    modifier nonReentrant() {
        if (locked != 1) revert ReentrantCall();
        locked = 2;
        _;
        locked = 1;
    }

    constructor(
        address governance_,
        address guardian_,
        address adapter_,
        bytes32 routeDigest_,
        address[] memory relayers_,
        uint256 threshold_,
        uint256 perTransactionLimit_,
        uint256 dailyLimit_
    ) {
        if (
            governance_ == address(0) ||
            guardian_ == address(0) ||
            adapter_ == address(0) ||
            routeDigest_ == bytes32(0) ||
            relayers_.length < 3 ||
            threshold_ < 2 ||
            threshold_ > relayers_.length ||
            perTransactionLimit_ == 0 ||
            dailyLimit_ < perTransactionLimit_
        ) revert InvalidConfiguration();

        institutionalGovernance = governance_;
        guardian = guardian_;
        assetAdapter = IJuncaBridgeAssetAdapter(adapter_);
        routeDigest = routeDigest_;
        signatureThreshold = threshold_;
        perTransactionLimit = perTransactionLimit_;
        dailyLimit = dailyLimit_;

        for (uint256 i; i < relayers_.length; ++i) {
            address relayer = relayers_[i];
            if (relayer == address(0) || isRelayer[relayer]) revert InvalidConfiguration();
            isRelayer[relayer] = true;
            emit RelayerChanged(relayer, true);
        }
        relayerCount = relayers_.length;
    }

    function hashMessage(BridgeMessage calldata message) public pure returns (bytes32) {
        // The explicit type hash domain-separates this tuple from other ABI
        // encodings while keeping compiler stack usage bounded.
        return keccak256(abi.encode(MESSAGE_TYPEHASH, message));
    }

    function execute(
        BridgeMessage calldata message,
        bytes[] calldata signatures
    ) external nonReentrant {
        if (paused) revert RoutePaused();
        if (
            message.routeDigest != routeDigest ||
            message.sourceNetwork == bytes32(0) ||
            message.destinationNetwork == bytes32(0) ||
            message.sourceNetwork == message.destinationNetwork ||
            message.sourceTransaction == bytes32(0) ||
            message.destinationAsset == bytes32(0) ||
            message.recipient == bytes32(0) ||
            message.value == 0
        ) revert InvalidMessage();
        if (block.timestamp > message.deadline) revert Expired();

        bytes32 digest = hashMessage(message);
        bytes32 nonceKey = keccak256(abi.encode(message.sourceNetwork, message.nonce));
        if (
            processedMessage[digest] ||
            processedSourceTransaction[message.sourceTransaction] ||
            processedSourceNonce[nonceKey]
        ) revert Replay();

        _verifySignatures(digest, signatures);
        _consumeRateLimit(message.value);

        processedMessage[digest] = true;
        processedSourceTransaction[message.sourceTransaction] = true;
        processedSourceNonce[nonceKey] = true;

        assetAdapter.releaseOrMint(
            message.assetType,
            message.destinationAsset,
            message.recipient,
            message.value,
            message.tokenId
        );

        emit MessageExecuted(
            digest,
            message.sourceTransaction,
            message.destinationNetwork,
            message.nonce,
            message.value,
            message.tokenId
        );
    }

    function setPaused(bool paused_) external {
        if (msg.sender != institutionalGovernance) {
            if (msg.sender != guardian || paused_ == false) revert Unauthorized();
        }
        paused = paused_;
        emit PauseChanged(paused_);
    }

    function setRelayer(address relayer, bool active) external onlyGovernance {
        if (relayer == address(0) || isRelayer[relayer] == active) revert InvalidConfiguration();
        uint256 nextCount = active ? relayerCount + 1 : relayerCount - 1;
        if (nextCount < 3 || signatureThreshold > nextCount) revert InvalidConfiguration();
        isRelayer[relayer] = active;
        relayerCount = nextCount;
        emit RelayerChanged(relayer, active);
    }

    function setSignatureThreshold(uint256 threshold_) external onlyGovernance {
        if (threshold_ < 2 || threshold_ > relayerCount) revert InvalidConfiguration();
        signatureThreshold = threshold_;
        emit ThresholdChanged(threshold_);
    }

    function setLimits(uint256 perTransactionLimit_, uint256 dailyLimit_) external onlyGovernance {
        if (perTransactionLimit_ == 0 || dailyLimit_ < perTransactionLimit_) {
            revert InvalidConfiguration();
        }
        perTransactionLimit = perTransactionLimit_;
        dailyLimit = dailyLimit_;
        emit LimitsChanged(perTransactionLimit_, dailyLimit_);
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

    function _consumeRateLimit(uint256 value) private {
        if (value > perTransactionLimit) revert RateLimitExceeded();
        uint256 day = block.timestamp / 1 days;
        if (day != currentDay) {
            currentDay = day;
            executedToday = 0;
        }
        if (executedToday + value > dailyLimit) revert RateLimitExceeded();
        executedToday += value;
    }

    function _verifySignatures(bytes32 digest, bytes[] calldata signatures) private view {
        if (signatures.length < signatureThreshold) revert InsufficientSignatures();
        bytes32 signedDigest = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", digest)
        );
        address[] memory seen = new address[](signatures.length);
        uint256 valid;
        for (uint256 i; i < signatures.length; ++i) {
            address signer = _recover(signedDigest, signatures[i]);
            if (!isRelayer[signer]) revert InvalidSignature();
            for (uint256 j; j < valid; ++j) {
                if (seen[j] == signer) revert InvalidSignature();
            }
            seen[valid] = signer;
            ++valid;
        }
        if (valid < signatureThreshold) revert InsufficientSignatures();
    }

    function _recover(bytes32 digest, bytes calldata signature) private pure returns (address) {
        if (signature.length != 65) revert InvalidSignature();
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (uint256(s) > SECP256K1N_HALF || (v != 27 && v != 28)) {
            revert InvalidSignature();
        }
        address signer = ecrecover(digest, v, r, s);
        if (signer == address(0)) revert InvalidSignature();
        return signer;
    }
}
