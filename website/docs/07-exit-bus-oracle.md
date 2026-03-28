## Overview

The mechanism of the `AccountingOracle` series contracts is mainly responsible for synchronizing the `validator` data exited at the `Module` and `node operator` levels. The `ValidatorsExitBusOracle` series of contracts actually triggers the CL layer "which validators should exit now". So `AccountingOracle` is mainly responsible for state synchronization, it is a state machine. `ValidatorsExitBusOracle` is the trigger that actually goes to the CL layer to control and execute `validator` exit. The former is the effect, and the latter is the cause.

<br />

You may have doubts as to why you need the `ValidatorsExitBusOracle` series of contracts, and what is its connection with the `WithdrawalQueue` series of contracts? In fact, the user will not directly trigger the validator exit of the CL layer through the `WithdrawalQueue` contract `withdrawal request`, it only records the extraction requirements. In order for the CL layer validator to actually exit, a separate exit command system is required. This is the role of `ValidatorsExitBusOracle`.

<br />

There are two other differences between `ValidatorsExitBusOracle` and `AccountingOracle`. First, it is not the only `HashConsensus -> BaseOracle -> submitReportData` path; in addition, `ValidatorsExitBus` also provides an auxiliary two-stage path of `submitExitRequestsHash -> submitExitRequestsData`. Second, it does not handle the `ReportData` main report and the `extrData` data separately. In fact, `ValidatorsExitBusOracle` has two commit paths:

<br />

*Oracle consensus path (main path)*

`HashConsensus -> BaseOracle -> submitReportData`

- Requires `quorum`
- Check `report hash`
- Belongs to standard Oracle process

<br />

*Bus two-stage path (auxiliary path)*

`submitExitRequestsHash(hash) -> submitExitRequestsData(data)`

- commit → reveal model
- Not dependent on `HashConsensus`
- Used to flexibly submit exit requests

Additionally, `ValidatorsExitBusOracle` processes the `ReportData` main report and `ExitRequestsData` data is processed within a single function call, to `emit event`.

<br />
<br />

## 1. Oracle consensus path

`ValidatorsExitBusOracle` also supports the standard Oracle consensus process. Its overall structure is consistent with `AccountingOracle` and is still based on:

```
HashConsensus -> BaseOracle -> ValidatorsExitBusOracle
```

But its `report` data is simpler and does not contain logic such as `rebase / vault / withdrawal`, only exit requests.

<br />

### 1.1 Report hash generation and submission

Like `AccountingOracle`, the oracle committee member constructs the complete `ReportData` off-chain:

```
struct ReportData {
    uint256 refSlot;
    uint256 requestsCount;
    uint256 dataFormat;
    bytes data;
}
```

in:

- `refSlot`: `reference slot(refSlot)` of the current frame
- `requestsCount`: The number of validators that need to exit this round
- `data`: packed exit request list

`member` is executed off-chain:

```
keccak256(abi.encode(reportData))
```

Get `reportHash` and call it within the current `frame`:

```
HashConsensus.submitReport(refSlot, reportHash, consensusVersion)
```

<br />

### 1.2 `quorum` Consensus Mechanism

Exactly the same as `AccountingOracle`:

- Each `member` votes for `(refSlot, reportHash)`
- If the number of votes of a certain `hash` is greater than or equal to `quorum`, a consensus is reached

For example:

```
member1 -> H1
member2 -> H1
member3 -> H1
member4 -> H2
```

If `quorum = 3`, then:

```
H1 becomes consensus report
```

<br />

### 1.3 Submit consensus report to BaseOracle

When a certain `reportHash` reaches `quorum`:

```
HashConsensus.submitConsensusReport(reportHash, refSlot, deadline)
```

`BaseOracle` will log:

```
_storageConsensusReport = {
    hash,
    refSlot,
    deadline
}
```

At this time, there is only "an exit request hash that can be processed", and the exit has not yet been executed.

<br />

### 1.4 Submit complete exit request data

Then called by a role with permissions:

```
submitReportData(ReportData data)
```

Strict verification will be done before entering `processing`:

```
1. data.refSlot == consensus.refSlot
2. keccak256(abi.encode(data)) == consensus.hash
3. dataFormat is legal
4. data.length matches requestsCount
```

After passing the verification:

```
_startProcessing()
```

Enter `processing` state:

```
Current frame locked
The refSlot can only be processed once
```

<br />

### 1.5 Handling exit requests

By calling the `_handleConsensusReportData(data)` internal function, its core logic:

```text
1. Verify dataFormat (must be LIST)
2. Verify data length
3. sanity checker checks requestsCount
4. Call _processExitRequestsList(data)
5. Update processing state
6. Update TOTAL_REQUESTS_PROCESSED
```

<br />

### 1.6 Parse and emit exit request

Among them, `_processExitRequestsList(data)` is the core function, mainly responsible for parsing data and emitting exit request event.

#### 📦 Data structure (packed)

```
| moduleId (24bit) | nodeOpId (40bit) | validatorIndex (64bit) | pubkey (48 bytes) |
```

#### 🔄 Processing process:

```
while(offset < end):
Analysis:
        moduleId
        nodeOpId
        validatorIndex
        pubkey

check:
        moduleId != 0
Sort strictly in ascending order (to prevent duplication)

    emit ValidatorExitRequest(...)
```

So far this is just the emit event, and the exit action will not be triggered immediately.

<br />

### 1.7 Actual execution of exit

After the report data has been submitted, call:

```
triggerExits(exitsData, exitDataIndexes, refundRecipient)
```

Execution process:

```
1. Verify that exitsData hash already exists (submitted)
2. Verify that exitDataIndexes is legal (incremental/not out of bounds)
3. Select validator based on index
4. Call:
   TriggerableWithdrawalsGateway.triggerFullWithdrawals(...)
```

Finally, the Beacon Chain validator exit is triggered. This path is the standard Oracle driver exit method.

Oracle Path Summary

```text
member commit hash
	↓
HashConsensus reached quorum
	↓
BaseOracle record consensus report
	↓
submitReportData submits complete data
	↓
_processExitRequestsList emit exit request
	↓
triggerExits execute exit
```

<br />
<br />
    
## 2. Bus two-stage path

In addition to the standard Oracle consensus path, `ValidatorsExitBus` also supports a more lightweight two-phase commit method:

```
submitExitRequestsHash -> submitExitRequestsData
```

<br />

### 2.1 Submit hash (commit phase)

The hash submission here does not require `quorum`, nor does it need to call the `HashConsensus` contract. First call `submitExitRequestsHash(bytes32 exitRequestsHash)` to record the hash of a certain exit request data (only one hash is registered).

storage:

```
requestStatusMap[exitRequestsHash] = {
    contractVersion,
    deliveredExitDataTimestamp
}
```

<br />

### 2.2 Submit complete data (reveal stage)

Then call the `submitExitRequestsData(bytes data)` interface. The specific execution process is as follows:

```
1. Calculate keccak256(data) -> hash
2. Check whether the hash has been submitted through submitExitRequestsHash
3. Verify data format/length
4. Call _processExitRequestsList(data)
```

In other words, commit: record the hash, reveal: submit the data and execute it. This path does not require `quorum` consensus, no calls to `HashConsensus`, no `refSlot`, and no `processing` state machine. Therefore, it is suitable for emergency situations (quickly triggering exit), flexible control of exit request submission, and fast execution channel that bypasses the consensus layer.

Bus two-stage path summary

```text
submitExitRequestsHash(hash)
	↓
submitExitRequestsData(data)
	↓
_processExitRequestsList
	↓
emit ValidatorExitRequest
	↓
triggerExits
	↓
Beacon Chain exit
```

<br />
<br />
    
## Summary

```text
1. Oracle path (main path)
HashConsensus reached quorum
-> BaseOracle record
   -> submitReportData
   -> processing
   -> emit exit request
   -> triggerExits

2. Bus path (auxiliary path)
   submitExitRequestsHash
   -> submitExitRequestsData
   -> emit exit request
   -> triggerExits

3. Finally execute ValidatorExitRequest uniformly
   -> TriggerableWithdrawalsGateway
   -> Beacon Chain exit
```
