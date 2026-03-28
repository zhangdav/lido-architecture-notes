## Overview

`StakingRouter` is the core contract in the Lido protocol responsible for managing the life cycle and status of StakingModule. It is between the `Lido` contract and each `StakingModule`, and is responsible for module registration, configuration management, running status control, and validator exit status synchronization.

In Lido's architecture, validators are organized as follows:

- `StakingRouter` manages multiple `StakingModule`
- Each `StakingModule` can contain multiple `NodeOperator`
- Each `NodeOperator` maintains a set of `Validator`

```text
StakingRouter
├── StakingModule #1
│   ├── NodeOperator #1
│   │   ├── Validator #1
│   │   ├── Validator #2
│   │   └── Validator #3
│   ├── NodeOperator #2
│   │   ├── Validator #4
│   │   └── Validator #5
│   └── NodeOperator #3
│       └── Validator #6
│
├── StakingModule #2
│   ├── NodeOperator #4
│   │   ├── Validator #7
│   │   └── Validator #8
│   └── NodeOperator #5
│       ├── Validator #9
│       ├── Validator #10
│       └── Validator #11
│
└── StakingModule #3
    └── NodeOperator #6
        └── Validator #12
```

The Router itself does not directly manage the validator's key or node running status. These logics are implemented by `StakingModule`; the Router is responsible for maintaining the global status and configuration at the module level, and forwarding events or data to the corresponding module when needed.

In addition, the Router is also responsible for coordinating the validator status reported by Oracle, such as the synchronization of the number of exited validators, and triggering the module's status update callback when necessary.

This document mainly describes the following contents:

- Registration and initialization process of StakingModule
- Module parameters and configuration updates
- Module runtime status management
- Validator exit related events and delay monitoring
- Synchronization mechanism for Oracle to report exited validator status
- Status recovery process under abnormal circumstances

It should be noted that this document only focuses on the Module life cycle and state management logic. The ETH deposit process, validator distribution strategy, and reward distribution mechanism will be introduced separately in other documents.

<br />
<br />
   
## 1. Module registration

The Module manager first adds a module by calling `addStakingModule`.

<br />

**Verification logic**

- Verify module address is not 0
- Verification name cannot exceed the specified length
- Verify whether the number of modules has exceeded the upper limit of 32**
- Make sure the module address is not repeated

<br />

**Initialization process**

- Assign `module id` auto-increment
- Initialize `module state`
- Set parameters
- `share limit`
- `fee`
- `deposit block` Limitations

<br />

**Storage Structure**

The storage method of Module is **Onbase dual index mapping mechanism**, which is used for efficient search and saving Gas.

<br />
<br />
   
## 2. Module configuration update

Module administrator can adjust module parameters during operation.

### 2.1 Update Router layer configuration

`updateStakingModule()`

- `stakeShareLimit`
- `priorityExitShareThreshold`
- `stakingModuleFee`
- `treasuryFee`
- `maxDepositsPerBlock`
- `minDepositBlockDistance`

<br />

### 2.2 Update configuration in Module

`updateTargetValidatorsLimits()`

- Role: node operator validator upper limit

<br />
<br />
   
## 3. Module runtime management

Router will also adjust the module's running status during operation.

### 3.1 Adjust vetted signing keys

`decreaseStakingModuleVettedKeysCountByNodeOperator()`

- Function: Reduce validator keys

<br />

### 3.2 Pause or stop module

`setStakingModuleStatus()`

state:

| Status | Deposit | Rewards |
| :------------- | :-: | :-: |
| Active | ✅ | ✅ |
| DepositsPaused | ❌ | ✅ |
| Stopped | ❌ | ❌ |

<br />
<br />

## 4. Validator exits

The triggerable exit request of a certain validator is triggered, and the Router forwards this notification to the corresponding module.

### 4.1 exit request is triggered

`onValidatorExitTriggered()`

- Function: Notify module that a certain validator has been triggered to exit the request

<br />

### 4.2 exit delay reporting

`reportValidatorExitDelay()`

- Function: Report how long a validator has been eligible to exit but has not actually exited after being requested to exit.

> [!NOTE]
>4.1 and 4.2 are `ExitBus / Triggerable exit` related running state events
>

<br />
<br />
   
## 5. Oracle synchronization exit status

When the validator actually exits the Beacon chain, Oracle will synchronize the status.

### 5.1 First synchronize the total number of Module layer exits

`updateExitedValidatorsCountByStakingModule()`

effect:

- Oracle reports the total number of exited validators for each staking module to the Router

- Router saves this module level total

- Router will later use it to participate in the calculation of active validators / deposit allocation / fee distribution.

<br />

### 5.2 Resynchronize Node Operator layer exit details

`reportStakingModuleExitedValidatorsCountByNodeOperator`
	↓
`module.updateExitedValidatorsCount()`

- Synchronous node operator exited validators

effect:

- Oracle completes the exited validators subdivision data of each node operator under a module to the internal state of the module.

- This stage can be submitted in batches and multiple times

> [!NOTE]
5.1 and 5.2 are exited validators after `AccountingOracle`, resulting in synchronization

<br />
<br />
   
## 6. Status synchronization completed

When Oracle completes node operator level exited validators data reporting, it will call:

- `onValidatorsCountsByNodeOperatorReportingFinished()`

At this point Router will traverse each module:

- Read the `exitedValidatorsCount` aggregated inside the module

- Compare with the total exitedValidatorsCount of modules saved in Router

- **Only when both are consistent**

Call:

- `module.onExitedAndStuckValidatorsCountsUpdated()`

If inconsistent, the module will not be marked as complete this cycle.

<br />
<br />
   
## 7. Abnormal status repair

If oracle reports an error, the administrator can fix it.

**Repair entrance:`unsafeSetExitedValidatorsCount()`**

1. Check current status
2. Modify module exitedValidatorsCount
3. Modify node operator exited count
4. Can trigger sync completion

<br />
<br />
   
## Summary

```text
Module life cycle

register
  addStakingModule
  ↓

Configuration
  updateStakingModule
  updateTargetValidatorsLimits
  ↓

Runtime management
  decreaseStakingModuleVettedKeysCountByNodeOperator
  setStakingModuleStatus
  ↓

validator exit related
  ├─ onValidatorExitTriggered
  └─ reportValidatorExitDelay
  ↓

Oracle exit report
  Phase 1:
    updateExitedValidatorsCountByStakingModule

  Phase 2:
    reportStakingModuleExitedValidatorsCountByNodeOperator

  Finish:
    onValidatorsCountsByNodeOperatorReportingFinished
      └─ if module exited total == router recorded total
         -> module.onExitedAndStuckValidatorsCountsUpdated()
  ↓

Exception fix
  unsafeSetExitedValidatorsCount
```
