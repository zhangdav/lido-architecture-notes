---
title: "01 Deposit Flow"
sidebar_label: "01 Deposit Flow"
---

## Overview

Lido's ETH staking flow starts when the user submits ETH and ends when Oracle reporting synchronizes Beacon Chain state and triggers `stETH` rebase.

Throughout the process, the protocol involves several core components:

- Lido: User entry point; receives ETH and mints `stETH`
- DepositSecurityModule (DSM): Performs deposit safety checks
- StakingRouter: Selects a staking module and executes validator deposits
- StakingModule: Manages node operators and validator keys
- Beacon DepositContract: Ethereum’s official deposit contract
- AccountingOracle: synchronize Consensus Layer status and update protocol accounting

<br />
   
## 1. User Entry

The user interacts with `Lido.submit()` rather than calling `StakingRouter` directly. `Lido` receives ETH, mints `stETH` for the user, and places the ETH into the buffer for later allocation.

<br />
   
## 2. Minting `stETH`

After the user submits ETH, `stETH` is minted immediately.
This happens in `Lido.submit()` and does not require an immediate Beacon deposit.

`stETH` share calculation formula:

```text
shares = \frac{ethAmount \times totalShares}{totalPooledEther}
```

```solidity
User stake
-> Lido receives ETH
  -> Lido mint stETH
-> ETH first in buffer
-> Later, Lido will send it to StakingRouter.
```
<br />
   
## 3. Deposit Allocation Strategy (Router allocation)

When enough ETH has accumulated in the buffer, the protocol must decide:

- How many validator deposits can be executed in this round?
- Which `StakingModule` should the deposit be allocated to?

By calling `StakingRouter.getDepositsAllocation()`, the protocol calculates:

- Each module currently has `activeValidatorsCount`
- Each module can provide `availableValidatorsCount`
- module's `stakeShareLimit`
- module's current `status`

The Router loads the status of all modules and calls `MinFirstAllocationStrategy.allocate()` to calculate the deposit split for this round.

> [!NOTE]
> This function only **calculates allocation**; it does not execute deposits.

<br />
   
## 4. DSM Initiates Deposit

The guardian calls `depositBufferedEther()` to specify the target `StakingModuleId` together with the parameters and signature for the deposit. `DepositSecurityModule` first verifies the signature, module status, nonce, block conditions, and related constraints, then calls `Lido.deposit()`.

<br />
   
## 5. Lido Deposit

`deposit()` in the Lido contract will verify whether `msg.sender` is DSM, and then calculate the `depositsCount` actually executed this time. Then `depositsCount * 32 ETH` is deducted from buffer and `StakingRouter.deposit()` is called.

> [!NOTE]
>
> Lido does not blindly rely on _maxDepositsCount, but combines:
> 1. The ETH available for deposit in the current buffer
> 2. The maximum number of deposits allowed by the current target module
>
> To calculate the depositsCount actually executed this time.

<br />

## 6. StakingRouter deposit

`StakingRouter` verifies that `msg.sender` is the Lido contract and checks:

- `withdrawal_credentials`
- Is target `StakingModule` in `Active`
- `msg.value == depositsCount * 32 ETH`

It then calls `obtainDepositData()` on the target module to retrieve the validator public key and signature.

<br />

## 7. Beacon Deposit

`StakingRouter` through `BeaconChainDepositor._makeBeaconChainDeposits32ETH()` will:

- ETH
- `withdrawal credentials`
- `validator pubkeys`
- `signatures`

Submit them to the Beacon DepositContract to complete the underlying stake.

<br />
   
## 8. Oracle Synchronizes Protocol State

When validators start running, their balance and status changes occur on the Consensus Layer (Beacon Chain). These changes are not automatically reflected in the Lido contract and must be updated through Oracle reports. Lido periodically submits reports through `AccountingOracle` to update the protocol state.

Oracle reports contain the following information:

- **CL balance**
The total balance of all Lido validators on Beacon Chain.

- **CL validators**
The current number of validators and the number of exited validators.

- **Withdrawal vault balance**
The ETH that can be withdrawn from the execution layer withdrawal vault.

- **Execution layer rewards**
Execution layer rewards from MEV and priority fees.

- **Withdrawal finalization**
Oracle will finalize withdrawal requests based on the report data and calculate the stETH shares that need to be destroyed.

- **Share burn**
To handle withdrawal, shares need to be destroyed.

- **Protocol fee allocation**
After Oracle calculates the validator income, it will allocate the protocol fee:

    - staking module fee
    - treasury fee

- **stETH rebase**
After accounting completes, Lido updates:

    - `totalPooledEther`
    - `totalShares`

This triggers the rebase of **stETH**, and the amount of stETH held by the user will automatically increase.

<br />
   
## 9. Rewards Calculation and Distribution

During Oracle reporting, the protocol calculates validator earnings. The `StakingRouter` contract is responsible for calculating the reward distribution ratio of each staking module via `getStakingRewardsDistribution()`.

Calculation basis:

- module `activeValidatorsCount`
- module `stakingModuleFee`
- module `treasuryFee`

Router will return:

- rewards recipient
- module fee
- treasury fee

<br />
   
## 10. Protocol Fee Share Minting

After Oracle calculates the protocol fee, `Lido` will mint stETH shares and allocate them to staking modules and treasury.

<br />
   
## 11. Router Notifies Module Rewards

After rewards mint completes, Oracle calls:

- `StakingRouter.reportRewardsMinted()`
↓ *Router calls the module one by one to notify the module to update its internal accounting*
- `module.onRewardsMinted()`

<br />

## 12. `stETH` Rebase

After Oracle accounting is completed, Lido updates `totalPooledEther` and `totalShares`, thereby triggering stETH rebase; the amount of `stETH` in the user's wallet will automatically increase.

<br />
   
## Summary

```Solidity
User calls Lido.submit()
-> Users get stETH immediately
-> ETH enters Lido buffer

Later:

    -> Router.getDepositsAllocation()
-> DSM triggers Lido.deposit()
-> Lido calls StakingRouter.deposit()
-> Router gets validator keys
-> Router executes Beacon deposit

Validator running...

Oracle report
    -> AccountingOracle.report()

    -> Lido.handleOracleReport()
        -> update CL balance
        -> update validator state
        -> process withdrawals
        -> calculate rewards

	-> Router.getStakingRewardsDistribution()
        -> mint protocol fee shares
	-> Router.reportRewardsMinted()
        -> stETH rebase
```
