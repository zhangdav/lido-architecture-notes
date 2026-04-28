---
title: "02 Module Lifecycle"
sidebar_label: "02 Module Lifecycle"
---

## Overview

`StakingRouter` is the core Lido contract responsible for managing the lifecycle and status of `StakingModule`. It sits between the `Lido` contract and each `StakingModule` and handles module registration, configuration management, runtime status control, and validator exit status synchronization.

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

This document mainly covers:

- Registration and initialization process of StakingModule
- Module parameters and configuration updates
- Module runtime status management
- Validator exit related events and delay monitoring
- Synchronization mechanism for Oracle to report exited validator status
- Status recovery process under abnormal circumstances

This document only focuses on module lifecycle and state management. The ETH deposit process, validator allocation strategy, and reward distribution mechanism are covered in other documents.

<br />
<br />
   
## 1. Module Registration

The module admin first adds a module by calling `addStakingModule`.

<br />

**Validation**

- Verify module address is not 0
- Verify that the name does not exceed the allowed length
- Verify that the module count has not exceeded the 32-module limit
- Make sure the module address is not repeated

<br />

**Initialization**

- Assign `module id` auto-increment
- Initialize `module state`
- Set parameters
- `share limit`
- `fee`
- `deposit block` Limitations

<br />

**Storage Structure**

The module uses an **Onbase dual-index mapping mechanism** for efficient lookup and lower gas usage.

<br />
<br />
   
## 2. Module Configuration Updates

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
   
## 3. Module Runtime Management

Router will also adjust the module's running status during operation.

### 3.1 Adjust Vetted Signing Keys

`decreaseStakingModuleVettedKeysCountByNodeOperator()`

- Function: Reduce the number of validator keys

<br />

### 3.2 Pause or Stop Module

`setStakingModuleStatus()`

state:

| Status | Deposit | Rewards |
| :------------- | :-: | :-: |
| Active | ✅ | ✅ |
| DepositsPaused | ❌ | ✅ |
| Stopped | ❌ | ❌ |

<br />
<br />

## 4. Validator Exits

When a validator's triggerable exit request is activated, the Router forwards the notification to the corresponding module.

### 4.1 exit request is triggered

`onValidatorExitTriggered()`

- Function: Notify module that a certain validator has been triggered to exit the request

<br />

### 4.2 Exit Delay Reporting

`reportValidatorExitDelay()`

- Function: Report how long a validator has been eligible to exit but has not yet exited after the exit request was triggered.

> [!NOTE]
>4.1 and 4.2 are `ExitBus / Triggerable exit` related running state events
>

<br />
<br />
   
## 5. Oracle Synchronizes Exit Status

When the validator actually exits the Beacon chain, Oracle will synchronize the status.

### 5.1 Sync the Module-Level Exit Total First

`updateExitedValidatorsCountByStakingModule()`

effect:

- Oracle reports the total number of exited validators for each staking module to the Router

- Router saves this module level total

- Router will later use it to participate in the calculation of active validators / deposit allocation / fee distribution.

<br />

### 5.2 Sync Node Operator Exit Details

`reportStakingModuleExitedValidatorsCountByNodeOperator`
	↓
`module.updateExitedValidatorsCount()`

- Sync node operator exited validators

effect:

- Oracle completes the exited validators subdivision data of each node operator under a module to the internal state of the module.

- This stage can be submitted in batches and multiple times

> [!NOTE]
5.1 and 5.2 are exited validators after `AccountingOracle`, resulting in synchronization

<br />
<br />
   
## 6. Exit Status Synchronization Complete

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
   
## 7. Abnormal Status Repair

If oracle reports an error, the administrator can fix it.

**Repair entry: `unsafeSetExitedValidatorsCount()`**

1. Check current status
2. Modify module exitedValidatorsCount
3. Modify node operator exited count
4. Can trigger sync completion

<br />
<br />
   
## Summary

```text
Module lifecycle

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
