// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title JUNCA Testnet Mintable ERC-20
/// @notice Public Testnet / No Monetary Value.
/// @dev Governance display: JAIOS Institutional Governance.
contract JuncaTestnetMintableERC20 {
    string public constant GOVERNANCE_DISPLAY = "JAIOS Institutional Governance";
    string public constant TESTNET_NOTICE = "Public Testnet / No Monetary Value";

    string public name;
    string public symbol;
    uint8 public immutable decimals;
    uint256 public immutable maxSupply;
    address public immutable bridgeAdapter;
    address public institutionalGovernance;
    bool public paused = true;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event PauseChanged(bool paused);
    error Unauthorized();
    error InvalidConfiguration();
    error RoutePaused();
    error SupplyCapExceeded();
    error InsufficientBalance();
    error InsufficientAllowance();

    constructor(
        string memory name_,
        string memory symbol_,
        uint8 decimals_,
        uint256 maxSupply_,
        address bridgeAdapter_,
        address governance_
    ) {
        if (
            bytes(name_).length == 0 ||
            bytes(symbol_).length == 0 ||
            decimals_ > 18 ||
            maxSupply_ == 0 ||
            bridgeAdapter_ == address(0) ||
            governance_ == address(0)
        ) revert InvalidConfiguration();
        name = name_;
        symbol = symbol_;
        decimals = decimals_;
        maxSupply = maxSupply_;
        bridgeAdapter = bridgeAdapter_;
        institutionalGovernance = governance_;
    }

    function bridgeMint(address recipient, uint256 amount) external {
        if (msg.sender != bridgeAdapter) revert Unauthorized();
        if (paused) revert RoutePaused();
        if (recipient == address(0) || amount == 0) revert InvalidConfiguration();
        if (totalSupply + amount > maxSupply) revert SupplyCapExceeded();
        totalSupply += amount;
        balanceOf[recipient] += amount;
        emit Transfer(address(0), recipient, amount);
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        if (spender == address(0)) revert InvalidConfiguration();
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 approved = allowance[from][msg.sender];
        if (approved < amount) revert InsufficientAllowance();
        if (approved != type(uint256).max) {
            allowance[from][msg.sender] = approved - amount;
            emit Approval(from, msg.sender, allowance[from][msg.sender]);
        }
        _transfer(from, to, amount);
        return true;
    }

    function setPaused(bool paused_) external {
        if (msg.sender != institutionalGovernance) revert Unauthorized();
        paused = paused_;
        emit PauseChanged(paused_);
    }

    function _transfer(address from, address to, uint256 amount) private {
        if (paused) revert RoutePaused();
        if (to == address(0) || amount == 0) revert InvalidConfiguration();
        uint256 balance = balanceOf[from];
        if (balance < amount) revert InsufficientBalance();
        balanceOf[from] = balance - amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }
}
