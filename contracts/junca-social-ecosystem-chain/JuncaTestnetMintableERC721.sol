// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title JUNCA Testnet Mintable ERC-721
/// @notice Public Testnet / No Monetary Value.
/// @dev Governance display: JAIOS Institutional Governance.
contract JuncaTestnetMintableERC721 {
    string public constant GOVERNANCE_DISPLAY = "JAIOS Institutional Governance";
    string public constant TESTNET_NOTICE = "Public Testnet / No Monetary Value";

    string public name;
    string public symbol;
    uint256 public immutable collectionCap;
    address public immutable bridgeAdapter;
    address public institutionalGovernance;
    bool public paused = true;
    uint256 public totalSupply;

    mapping(uint256 => address) public ownerOf;
    mapping(address => uint256) public balanceOf;
    mapping(uint256 => address) public getApproved;
    mapping(address => mapping(address => bool)) public isApprovedForAll;

    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event Approval(address indexed owner, address indexed approved, uint256 indexed tokenId);
    event ApprovalForAll(address indexed owner, address indexed operator, bool approved);
    event PauseChanged(bool paused);
    error Unauthorized();
    error InvalidConfiguration();
    error RoutePaused();
    error CollectionCapExceeded();
    error TokenAlreadyExists();
    error TokenDoesNotExist();

    constructor(
        string memory name_,
        string memory symbol_,
        uint256 collectionCap_,
        address bridgeAdapter_,
        address governance_
    ) {
        if (
            bytes(name_).length == 0 ||
            bytes(symbol_).length == 0 ||
            collectionCap_ == 0 ||
            bridgeAdapter_ == address(0) ||
            governance_ == address(0)
        ) revert InvalidConfiguration();
        name = name_;
        symbol = symbol_;
        collectionCap = collectionCap_;
        bridgeAdapter = bridgeAdapter_;
        institutionalGovernance = governance_;
    }

    function bridgeMint(address recipient, uint256 tokenId) external {
        if (msg.sender != bridgeAdapter) revert Unauthorized();
        if (paused) revert RoutePaused();
        if (recipient == address(0)) revert InvalidConfiguration();
        if (ownerOf[tokenId] != address(0)) revert TokenAlreadyExists();
        if (totalSupply >= collectionCap) revert CollectionCapExceeded();
        ownerOf[tokenId] = recipient;
        balanceOf[recipient] += 1;
        totalSupply += 1;
        emit Transfer(address(0), recipient, tokenId);
    }

    function approve(address approved, uint256 tokenId) external {
        address owner = ownerOf[tokenId];
        if (owner == address(0)) revert TokenDoesNotExist();
        if (msg.sender != owner && !isApprovedForAll[owner][msg.sender]) revert Unauthorized();
        getApproved[tokenId] = approved;
        emit Approval(owner, approved, tokenId);
    }

    function setApprovalForAll(address operator, bool approved) external {
        if (operator == address(0) || operator == msg.sender) revert InvalidConfiguration();
        isApprovedForAll[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }

    function transferFrom(address from, address to, uint256 tokenId) external {
        if (paused) revert RoutePaused();
        address owner = ownerOf[tokenId];
        if (owner == address(0)) revert TokenDoesNotExist();
        if (owner != from || to == address(0)) revert InvalidConfiguration();
        if (
            msg.sender != owner &&
            getApproved[tokenId] != msg.sender &&
            !isApprovedForAll[owner][msg.sender]
        ) revert Unauthorized();
        delete getApproved[tokenId];
        ownerOf[tokenId] = to;
        balanceOf[from] -= 1;
        balanceOf[to] += 1;
        emit Transfer(from, to, tokenId);
    }

    function setPaused(bool paused_) external {
        if (msg.sender != institutionalGovernance) revert Unauthorized();
        paused = paused_;
        emit PauseChanged(paused_);
    }
}
