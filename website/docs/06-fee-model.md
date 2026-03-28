## Overview

Lido charges a protocol fee for staking income, not directly from the principal deposited by users. It is a protocol fee charged for staking rewards, which is distributed between node operators and staking modules, as well as the DAO treasury. This rate can be modified by the Lido DAO through governance.

> [!NOTE]
> The protocol fee is usually represented as a portion of the fee for staking rewards; on the Router side, the final total rate depends on the sum of the `module fee`, `treasury fee` and their `active validators` weights of each module. The current common governance configuration is 10%, but from a mechanism perspective, the Router aggregation result is not a hard-coded constant in the code.

This means that what users receive is the net staking income after deducting the protocol fee; the protocol fee will be distributed to relevant parties through the issuance of additional shares/stETH.

<br />

- module fee module fee

The fees allocated to the staking module are used to compensate the module and its node operators for providing verifier operation, infrastructure maintenance, operation and maintenance management and other services.

- treasury fee treasury fee

Fees allocated to the Lido DAO Treasury are used for protocol-level governance, development, risk control, emergencies and other DAO expenses.

Therefore, the fee composition of a single module is: the total rate of the module = module fee + treasury fee.

<br />

## Calculation formula

Calculated according to the proportion of active validators of the module × the fee rate set by the module

1. The module’s validator weight in the protocol

Proportion of module validators = module active validators / full protocol active validators

2. The module fee actually received by the module

The final reward share obtained by the module = Proportion of module verifiers × module fee

3. Module share allocated to Treasury

The Treasury share corresponding to this module = Proportion of module validators × treasury fee

4. Summarize total agreement fee

totalFee = sum of all modules (module fee share + treasury fee share)

```solidity
uint256 stakingModuleValidatorsShare =
    (stakingModulesCache[i].activeValidatorsCount * precisionPoints) / totalActiveValidators;

address recipient =
    address(stakingModulesCache[i].stakingModuleAddress);

uint96 stakingModuleFee =
    uint96((stakingModuleValidatorsShare * stakingModulesCache[i].stakingModuleFee) / TOTAL_BASIS_POINTS);

if (stakingModulesCache[i].status != StakingModuleStatus.Stopped) {
    stakingModuleFees[rewardedStakingModulesCount] = stakingModuleFee;
}

totalFee +=
    uint96((stakingModuleValidatorsShare * stakingModulesCache[i].treasuryFee) / TOTAL_BASIS_POINTS)
    + stakingModuleFee;
```

<br />

> Give an example 🌰
>
> Assume that there are 1000 active validators in the entire protocol, among which:
>
> Module A: 500 active validators, accounting for 50%
>
> Module B: 300 active validators, accounting for 30%
>
> Module C: 200 active validators, accounting for 20%

> [!NOTE]
> 1. If the module is `activeValidatorsCount = 0`, the module will not receive module fee, nor will it contribute part of the module income to the total fee distribution of this round.
>
> 2. The Stopped module will not get its own module fee, but its corresponding part of the fee will still be included in `totalFee`.

> Suppose further:
>
> A's module fee = 8%, treasury fee = 2%
>
> B’s module fee = 6%, treasury fee = 3%
>
> C's module fee = 10%, treasury fee = 2%
>
> So:
>
> Module A
>
> Module revenue = 50% × 8% = **4%**
> Treasury income = 50% × 2% = **1%**
>
> Module B
>
> Module revenue = 30% × 6% = **1.8%**
> Treasury income = 30% × 3% = **0.9%**
>
> Module C
>
> Module revenue = 20% × 10% = **2%**
> Treasury income = 20% × 2% = **0.4%**

The final total agreement fee is: 4% + 1% + 1.8% + 0.9% + 2% + 0.4% = 10.1%

<br />
<br />

## `activeValidators` and `exitedValidators` synchronization mechanism

As mentioned in the previous example, when the Router calculates the fee allocation, the weight of the module depends on its `activeValidators` amount.

`module weight = activeValidators / totalActiveValidators`

```solidity
activeValidators =
    totalDepositedValidators
    - max(moduleSummaryExited, routerExited)
```

The `exitedValidators` here is not a single source, but relies on the status of the `Router`/ `Module exited` data after synchronization is completed. Therefore, it is coupled with the exited validators reporting chain of `AccountingOracle`, but it is not the same synchronization chain as the triggering of `ExitBus` itself. `exitedValidators` The synchronization process is as follows:

```
Oracle reports module exited count
After counting the validator status from the consensus layer, report the exit number of a certain module
  ↓
Router updates module level exited ledger
1. Verify that the number of exited cannot be reduced
2. Verify that the number of exited cannot exceed deposited
3.Update
  ↓
Module updates node operator exited details
Router will:
a. Check encoding format
b. Forward exit information to the module
  ↓
Inside the module there will be:
c. Update the exited validators of each node operator
d. Re-summarize the number of module exited
  ↓
Finish hook confirms that the module summary status is consistent
1. Traverse all modules
2. Read exitedValidators in module summary
3. Compare with exitedValidators recorded by Router
  ↓
Confirm synchronization moduleSummaryExited == routerExited
Router exited General Ledger
Module exited details
Synchronization has been completed
  ↓
Router/Lido subsequent logic reads the final status
```

The final module weight depends on active validators, and the calculation of this value is related to the `routerExited`, `moduleSummaryExited` synchronization results of the above process.

<br />

> Give an example 🌰
>
> Assume two modules:
>
> `Module A deposited = 1000`
> `Module B deposited = 1000`
>
> initial:
>
> `A active = 1000`
> `B active = 1000`
> `weight = 50% / 50%`
>
> If Oracle reports:
>
> `routerExited = 200`
> `moduleSummaryExited = 150`
>
> Router uses: when calculating active validators:
>
> `active = deposited - max(routerExited, moduleSummaryExited)`
>
> get:
>
> `A active = 800`
> `B active = 1000`
>
> New fee weight:
>
> `A = 800 / 1800`
> `B = 1000 / 1800`
>
> Therefore, in the next round of rewards fee distribution: the handling fee weight of Module A will decrease, and the handling fee weight of Module B will increase relatively.

In summary, the synchronization mechanism of `exitedValidators` will ultimately affect: the distribution ratio of rewards fees between modules and the treasury income source structure by changing the amount of `activeValidators`.

<br />
<br />

*Core synchronization interface:*

1. Module level total update

```solidity
updateExitedValidatorsCountByStakingModule(
	uint256[] calldata _stakingModuleIds,
	uint256[] calldata _exitedValidatorsCounts
)
```

<br />

2. nodeOperator level update

```solidity
reportStakingModuleExitedValidatorsCountByNodeOperator(
	uint256 _stakingModuleId,
	bytes calldata _nodeOperatorIds,
	bytes calldata _exitedValidatorsCounts
)
```

<br />

3. All node operators report finish after completion

```solidity
onValidatorsCountsByNodeOperatorReportingFinished()
```

<br />

4. Module closing hook

```solidity
module.onExitedAndStuckValidatorsCountsUpdated()
```

<br />

5. Urgent fix

```solidity
unsafeSetExitedValidatorsCount(...)
```

<br />

## Calling relationship

```text
Oracle submit report
  ↓
Lido.handleOracleReport
  ↓
Calculate _totalRewards
  ↓
Lido._distributeFee
  ↓
StakingRouter.getStakingRewardsDistribution
  ↓
get modulesFees / totalFee
  ↓
Calculate sharesMintedAsFees
  ↓
_mintShares(address(this), sharesMintedAsFees)
  ↓
_transferModuleRewards
  ↓
_transferTreasuryRewards
  ↓
router.reportRewardsMinted

```
> [!NOTE]
> router.reportRewardsMinted does not participate in this round of rate calculation. Instead, after the allocation is completed, the `totalShares` corresponding to each module will be notified synchronously to the module for internal accounting or subsequent processing of the module.

Call the `handleOracleReport` function in the Lido contract and execute to step 7. `_processRewards` internally calls the router contract to call `getStakingRewardsDistribution` to calculate and return the current round of `modulesFees`, `totalFee` and `precisionPoints` based on the current status of staking modules. The key data returned is as follows:

<br />

```text
modulesFees = [4%, 2%, 3%]
treasuryFee = 1%
totalFee = 10%
```

Subsequently used for mint and allocation of fee shares, the steps to calculate mint shares are as follows:

<br />

*Step 1 Define initial state*

- The total ETH in the Lido contract before the reward is generated: preTotalPooledEther = E

- Total Share in the Lido contract before rewards are generated: preTotalShares = S

- Generated in this round: totalRewards = R

*Step 2 Update the amount of ETH after the reward*

- After Oracle reports the reward, the total ETH of the protocol becomes: newTotalPooledEther = E + R

*Step 3 Calculate the fee receivable under the agreement*

- Protocol fee ratio: f = totalFee / precisionPoints

*Step 4 Calculate the share price after mint*

- Let: sharesMintedAsFees = x

- After mint shares: totalShares = S + x

- Generated in this round: totalRewards = R

- The share price is: sharePrice = (E + R) / (S + x)

- The value of shares of protocol new mint is: value = x * sharePrice

- Substitute sharePrice: value = x * (E + R) / (S + x)

- Get the formula:
```text
x = \frac{R f S}{E + R - R f}
```

- $E$: preTotalPooledEther
- $S$: preTotalShares
- $R$: totalRewards
- $f$：fee ratio
- $x$：sharesMintedAsFees

The protocol hopes that the value of the shares from the new mint will be exactly equal to the fee ETH receivable by the protocol. The protocol will not directly deduct rewards ETH from the pool, but dilute and distribute the equity "equal to the protocol fee" to modules and treasury by minting new shares.

```solidity
uint256 totalPooledEtherWithRewards = _preTotalPooledEther.add(_totalRewards);

sharesMintedAsFees =
    _totalRewards.mul(rewardsDistribution.totalFee).mul(_preTotalShares).div(
        totalPooledEtherWithRewards.mul(
            rewardsDistribution.precisionPoints
        ).sub(_totalRewards.mul(rewardsDistribution.totalFee))
    );
```
