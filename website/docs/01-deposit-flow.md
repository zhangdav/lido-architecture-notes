## Overview

Lido's ETH staking process starts with the user submitting ETH, and finally synchronizes the Beacon Chain status through Oracle reporting and triggers `stETH` rebase.

Throughout the process, the protocol involves several core components:

- Lido: User entrance, responsible for receiving ETH and mint `stETH`
- DepositSecurityModule (DSM): Responsible for deposit security verification
- StakingRouter: Responsible for selecting staking module and executing validator deposit
- StakingModule: manages node operator and validator keys
- Beacon DepositContract: Ethereum’s official deposit contract
- AccountingOracle: synchronize Consensus Layer status and update protocol accounting

<br />
   
## 1. User entrance

The user interacts with the `Lido` contract `submit()` instead of directly interacting with `StakingRouter`; `Lido` is responsible for receiving ETH and mint `stETH` to the user; and temporarily puts the ETH into the buffer, and the ETH in the buffer will be allocated later.

<br />
   
## 2. Minting of stETH

After the user submits ETH, he or she will immediately receive `stETH`.
This step occurs in `Lido.submit()` and does not require ETH to complete the Beacon deposit on the spot.

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
   
## 3. Deposit allocation strategy (Router allocation)

When enough ETH has accumulated in the buffer, the protocol needs to decide:

- How many validator deposits can be executed in this round?
- Which `StakingModule` should the deposit be allocated to?

By calling `getDepositsAllocation()` in the `StakingRouter` contract, calculate:

- Each module currently has `activeValidatorsCount`
- Each module can provide `availableValidatorsCount`
- module's `stakeShareLimit`
- module's current `status`

Router will load the status of all modules and call `MinFirstAllocationStrategy.allocate()` to calculate the distribution ratio of deposits among modules in this round.

> [!NOTE]
> This function is only responsible for **calculating allocation** and will not actually perform deposits.

<br />
   
## 4. DSM initiates deposit

The guardian calls `depositBufferedEther()` to specify the target `StakingModuleId`, along with the relevant parameters and signature of this deposit. `DepositSecurityModule` will first verify the signature, module status, nonce, block conditions, etc., and then call `Lido.deposit()`.

<br />
   
## 5.Lido deposit

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

`StakingRouter` will check whether `msg.sender` is a Lido contract and check:

- `withdrawal_credentials`
- Is target `StakingModule` in `Active`
- `msg.value == depositsCount * 32 ETH`

Then call `obtainDepositData()` on the target module to retrieve the public key and signature of the corresponding validator.

<br />

## 7. Beacon deposit

`StakingRouter` through `BeaconChainDepositor._makeBeaconChainDeposits32ETH()` will:

- ETH
- `withdrawal credentials`
- `validator pubkeys`
- `signatures`

Submit it to Beacon DepositContract together to complete the underlying pledge.

<br />
   
## 8. Oracle Synchronization Protocol Status

When the validator starts running, its balance and status changes occur in the Consensus Layer (Beacon Chain). These statuses are not automatically synchronized to the Lido contract and need to be updated through Oracle reports. Lido periodically submits reports through `AccountingOracle` to update the key status of the protocol.

Oracle reports contain the following information:

- **CL balance**
The total balance of all Lido validators on Beacon Chain.

- **CL validators**
The current number of validators and the number of exited validators.

- **Withdrawal vault balance**
The ETH that can be withdrawn from the execution layer withdrawal vault.

- **Execution layer rewards**
Executive layer rewards from MEV and priority fees.

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
   
## 9. Calculation and distribution of Rewards

During Oracle reporting, the protocol calculates validator earnings. `StakingRouter` The contract is responsible for calculating the reward distribution ratio of each staking module: `getStakingRewardsDistribution()`

Calculation basis:

- module `activeValidatorsCount`
- module `stakingModuleFee`
- module `treasuryFee`

Router will return:

- rewards recipient
- module fee
- treasury fee

<br />
   
## 10. Protocol fee shares mint

After Oracle calculates the protocol fee, `Lido` will mint stETH shares and allocate them to staking modules and treasury.

<br />
   
## 11. Router notification module rewards

After rewards mint completes, Oracle calls:

- `StakingRouter.reportRewardsMinted()`
↓ *Router calls the module one by one to notify the module to update its internal accounting*
- `module.onRewardsMinted()`

<br />

## 12. stETH rebase

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
