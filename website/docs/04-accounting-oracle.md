## Overview

The Lido protocol oracle is a complex state machine, mainly composed of three core modules: `HashConsensus`, `BaseOracle`, and `AccountingOracle`. The oracle committee members upload the report to `HashConsensus`, reach a consensus, and submit the report within the specified time range. `BaseOracle` is responsible for recording and managing the current consensus report, and `AccountingOracle` is responsible for processing the report and providing status update data parameters for the Lido contract.

<br />

*HashConsensus: Manage frame and hash consensus*
---

> oracle committee member<br />
> quorum (the minimum number of members supporting the same hash is considered a consensus)<br />
> Time segmentation of frame<br />
> Each frame corresponds to `refSlot` and `deadline`<br />
> Report hash submitted by members on a certain frame<br />

Therefore, the `HashConsensus` contract does not process the business data itself, nor does it rebase. It only does one thing: select a consensus report hash for each frame.

<br />

*BaseOracle: receive consensus report and manage processing status*
---

The `BaseOracle` contract is an "asynchronous processing base class". It is responsible for:

> Receive `(hash, refSlot, deadline)` pushed by HashConsensus<br />
> Record the reports that are currently agreed upon but not yet processed<br />
> Allow consensus to be replaced or lost before actual processing begins<br />
> After starting processing, lock the current `refSlot`<br />

So it's the buffering layer and processing state machine for consensus results. It does not require understanding the business meaning of `report data` per se.

<br />

*AccountingOracle: Submit complete data and perform business*
---
`AccountingOracle` adds real business semantics on top of `BaseOracle`. It is responsible for:

> Receive complete `ReportData`<br />
> Calculate `keccak256(abi.encode(data))`<br />
> Verify whether it is consistent with the current consensus hash<br />
> Call `Lido.handleOracleReport()`<br />
> Synchronize legacy oracle / staking router / withdrawal queue<br />
> Initialize extraData state<br />
> Batch processing extraData item<br />

So `HashConsensus` solves which hash is recognized, `BaseOracle` solves when to start processing, and `AccountingOracle` solves "how to process complete business data".

<br />

```text
HashConsensus
-> Management committee member, frame, quorum, report hash consensus

BaseOracle
-> Receive the hash after consensus and record the consensus report that can be processed by the current frame
-> Responsible for the processing state machine (when to start processing, whether it has started)

AccountingOracle
-> Submit complete ReportData
-> Verify whether the hash of the complete data is equal to the consensus hash
-> Execute main report (rebase/vault/withdrawal/module exited validators)
-> Initialize and process extraData in batches
```

The entire link first reaches consensus on `hash`, then submits the complete `ReportData`, then starts `processing`, and finally processes `extraData`. The advantage of this is that the complete report is large and it is cheaper to consensus `hash` first. Only the complete report matching the consensus `hash` can be processed. `extraData` can be split into multiple batches for submission, reducing gas pressure. <br /><br />

## 1. Time model: How to divide the time period for report submission

Reports are submitted each time `member`, within the time windows `slot`, `epoch`, `frame` specified in the contract. As the name suggests, report submission is submitted in stages, and only one report in each stage reaches consensus and is processed. So, how are the stages based on time windows divided?

Oracle's time model is based on Beacon Chain's slot/epoch, including:

### 1.1 `slot`

slot is the minimum time unit

`timestamp = genesisTime + slot * secondsPerSlot`

<br />

### 1.2 `epoch`

An epoch consists of a fixed number of slots

`epoch = slot / slotsPerEpoch`

For example:
```text
slotsPerEpoch = 32

slot 0   ~ 31   -> epoch 0
slot 32  ~ 63   -> epoch 1
slot 64  ~ 95   -> epoch 2
```

<br />

### 1.3 `frame`

`frame` is the time window used by the `HashConsensus` contract to organize oracle reporting, and a `frame` contains a fixed number of epochs.

For example:
```text
epochsPerFrame = 225
```

Then each frame is 225 epochs. If each `epoch` has 32 slots, then each `frame` has 225 * 32 = 7200 `slot`.

<br />

### 1.4 `reference slot (refSlot)`

A `frame` does not produce separate reports for each `slot` in `frame`, but only produces a report around a fixed `refSlot`.

- `refSlot` is the last `slot` of the previous `frame` and serves as the observation base of the current `frame`
- `processing deadline` is the end time of `frame` (calculated by time, not specific slot)
-  member can submit hash (fast lane + slow lane) within the current reporting window of `frame`

```Solidity
prev frame        current frame
|..............|.................................|
               refSlot                       deadline

// refSlot = last slot of prev frame
// deadline = end timestamp of current frame
```

The significance of this design is:

- The current report of `frame` is based on the Beacon Chain status snapshot corresponding to `refSlot` and is guaranteed to be consistent with the consensus layer.
- The processing result of current `frame` will be observed in `refSlot` of next `frame`, forming a closed loop
- Different `frame` are isolated by `refSlot` to avoid mutual interference between status observation and processing.

<br />
<br />

## 2. Hash mechanism: how to generate, report and reach consensus on report hash

The `HashConsensus` contract doesn't know what the full report looks like, it only handles `bytes32 reportHash` . For the `AccountingOracle` contract, this `hash` comes from `keccak256(abi.encode(ReportData))`. In other words, the report member should calculate the same hash based on the same complete `ReportData` off-chain.

`ReportData` includes:

- `consensusVersion`
- `refSlot`
- `numValidators`
- `clBalanceGwei`
- `stakingModuleIdsWithNewlyExitedValidators`
- `numExitedValidatorsByStakingModule`
- `withdrawalVaultBalance`
- `elRewardsVaultBalance`
- `sharesRequestedToBurn`
- `withdrawalFinalizationBatches`
- `simulatedShareRate`
- `isBunkerMode`
- `extraDataFormat`
- `extraDataHash`
- `extraDataItemsCount`

Therefore, the essence of the consensus of `HashConsensus` is that members agree on a complete ABI encoded hash of `ReportData`, because the parameters in it will be used as input parameters in the Lido contract to modify the ledger state.

<br />

### 2.1 How member uploads hash

The member will call: `HashConsensus.submitReport(refSlot, reportHash, consensusVersion)` on the same `refSlot` in the current frame.

`HashConsensus` The contract will check:

- Whether it is currently within the frame window that allows submission (*fast channel/normal channel*)
- Is `consensusVersion` equal to the version currently required by the processor?
- `refSlot` is the reference slot of the current frame
- Whether the submitter is a committee member

If passed, the member's vote for the frame is recorded.

<br />

### 2.2 `quorum` consensus threshold

`quorum` is the threshold for voting statistics for a certain hash. If the number of votes for a certain hash is greater than this value, it means that a consensus has been reached on this hash. The rules are as follows:

- `quorum` must be strictly greater than half the number of members (greater than `totalMembers` / 2)
- Minimum `quorum = floor(totalMembers / 2) + 1  `

for example:
```text
committee = 5 people
quorum = 3
```

Then if three members all submit the same `reportHash = H1`, it means that H1 has reached consensus.

```text
member1 -> H1
member2 -> H1
member3 -> H1
member4 -> H2
member5 -> not submitted
```

At this time: H1 has 3 votes and is greater than or equal to `quorum(3)`, and H1 becomes the current consensus report of `frame`.

<br />

### 2.3 Submit consensus report

Once a hash reaches quorum, `HashConsensus` will call `report processor` in the contract
`submitConsensusReport(reportHash, refSlot, deadline)`. This action does not start processing the business immediately, but submits the `(hash, refSlot, deadline)` that has reached consensus to the `BaseOracle` contract and records it as the pending consensus result of the current `frame`. As mentioned at the beginning, the `BaseOracle` contract is only responsible for receiving the consensus report and managing the processing status. It is not responsible for processing the data in the report.

<br />

### 2.4 Consensus invalidation and restoration

`quorum` is used as the threshold for reaching consensus, and this value can be modified by the administrator in real time. Then each modification may have an impact (void/restore) on the consensus report submitted to the `BaseOracle` contract. For example:

current

```text
quorum = 3
```

Member support:

```text
H1 = 3 votes
```

So H1 was originally agreed upon.

If an administrator raises the quorum to:

```text
quorum = 4
```

It turned out that those 3 votes were not enough, so:

```text
H1 is no longer a consensus report
```

If this H1 has not started processing, HashConsensus can notify the processor:

```Solidity
discardConsensusReport(refSlot)
```

This means that the consensus report H1 previously submitted to `BaseOracle` has been invalidated.

If another member adds H1 later, or the quorum is set back to 3 by the administrator, or the member changes, this H1 reaches `quorum` again. Then HashConsensus will be called again:

```Solidity
submitConsensusReport(reportHash, refSlot, deadline)
```

That is, the consensus is mutable before processing begins. In the same `frame`, the current consensus hash can be replaced, lost, and restored. Once a certain `refSlot` enters `processing`, that is: the consensus phase ends and enters the execution phase. The current consensus hash of `frame` is locked:

> 1. The current consensus hash of `frame` is locked
> 2. `HashConsensus` will no longer accept any new votes for this `refSlot`
> 3. Can no longer trigger `discardConsensusReport` and invalidate the consensus report provided.
> 4. Can no longer be replaced with a new consensus hash
> 5. `submitReportData` can only be executed once

Next, let's look at how the consensus report enters the `processing` stage.

<br />
<br />

## 3. Report hash processing: How to start the main report `processing`

Before the main report starts `processing`, there is actually one more step after the `HashConsensus` contract uploads the consensus report to the `BaseOracle` contract. That is: `submitReportData`, which is triggered in the `BaseOracle` contract, and the entire sequence is as follows:

> 1. members submit `report hash`
> 2. `HashConsensus` achieved `quorum`
> 3. `HashConsensus` calls `BaseOracle.submitConsensusReport()`
> 4. `BaseOracle` save `_storageConsensusReport`
> 5. Then the administrator `SUBMIT_DATA_ROLE` calls `submitReportData(fullReport)`

Therefore, there must be a consensus hash before the complete `ReportData` can be submitted.

We mentioned earlier that the `HashConsensus` contract will call the `submitConsensusReport` interface of the `BaseOracle` contract and upload the consensus report to `BaseOracle`, so the `BaseOracle` contract will save a current consensus report, including: `hash`, `refSlot`, `processingDeadlineTime`.

This status means that the current frame already has a main report candidate that has reached consensus and can enter subsequent processing. It is not until the administrator calls `submitReportData(data, version)` in the `AccountingOracle` contract that the main report is allowed to begin entering the `processing` process. But before starting to process the report, the `submitReportData` function will verify the report data uploaded by the administrator and the consensus report stored in `BaseOracle`:

- Whether there is indeed a `consensus report` currently
- Is `data.refSlot` equal to the consensus `refSlot`
- Does `consensusVersion` match
- Is `keccak256(abi.encode(data))` equal to the consensus hash?

Only if all are passed will processing be allowed to continue. Therefore, the role of `ConsensusReport` is not to participate in business calculations, but as the access verification threshold for complete `ReportData`.

Once the consensus check is passed, the main report will enter the `processing` stage:

```text
_startProcessing()
-> Mark the current refSlot to start processing
-> Update lastProcessingRefSlot
    -> emit ProcessingStarted(refSlot, ...)
```

At this point, the main report of the current frame is officially locked and processing begins. From now on, the same `refSlot` cannot be adjusted again. `submitReportData`, `HashConsensus` can no longer replace the consensus hash of this frame (mentioned earlier).

To achieve:

```text
1 frame -> 1 refSlot -> 1 main report processing
```

<br />
<br />

## 4. `ReportData` Data processing

Earlier we talked about calling the `_startProcessing()` interface in the `submitReportData` function, and the main report enters the `processing` stage. Next, we will continue to talk about how the `_handleConsensusReportData` function in the `submitReportData` function processes the data in the main report. This is also the trigger point for the entire Oracle mechanism to rewrite different contract ledgers.

Because the link involved is relatively long, we will split it into 6 steps to introduce:

### 4.1 Check whether the `extraData` header is legal

if:

```text
extraDataFormat = EMPTY
```

Then require:

- `extraDataHash == 0`
- `extraDataItemsCount == 0`

Indicates that no `extraData` needs to be processed, and `extraData` data is used to update `node operator` data under specific `module`.

if:

```text
extraDataFormat = LIST
```

Then require:

- `extraDataHash != 0`
- `extraDataItemsCount > 0`

Indicates that `extraData` needs to be processed later and the relevant data in `node operator` under `module` is updated.

<br />

### 4.2 Synchronize CL summary data to legacy oracle

The `AccountingOracle` contract will call the compatible interface of the legacy oracle contract to:

- `refSlot`
- `clBalanceGwei * 1e9`
- `numValidators`

Synchronize the past, this step is mainly to migrate the compatibility layer logic.

<br />

### 4.3 Update module-level exited validators

There are two sets of summary-level fields in the main report:

- `stakingModuleIdsWithNewlyExitedValidators`
- `numExitedValidatorsByStakingModule`

The `AccountingOracle` contract will synchronize them to the `StakingRouter` contract. Here is the `module` level summary, not the `node operator` level details.

<br />

### 4.4 Notify WithdrawalQueue that a new report has arrived

Call:

```text
withdrawalQueue.onOracleReport(
    isBunkerMode,
    prevReportTimestamp,
    currentReportTimestamp
)
```

The function is to update the report time boundary and synchronize the bunker mode status.

<br />

### 4.5 Adjust the `handleOracleReport()` interface in the `Lido` contract

This is the core business action of the main report.

Here will be:

- `report timestamp`
- `time elapsed`
- `numValidators`
- `clBalance`
- `withdrawalVaultBalance`
- `elRewardsVaultBalance`
- `sharesRequestedToBurn`
- `withdrawalFinalizationBatches`
- `simulatedShareRate`

Hand it off to Lido, thus pushing completion in the `Lido` contract:

- rebase
- Withdrawal finalization
- vault balance collection
- burn treatment

<br />

### 4.6 Initialize extraData processing state

The main report will not process the extraData directly at the end, but instead:

- `refSlot`
- `dataFormat`
- `dataHash`
- `itemsCount`
- `itemsProcessed = 0`
- `lastSortingKey = 0`
- `submitted = false`

Write `ExtraDataProcessingState` in the `AccountingOracle` contract. This means: the extraData task has been registered, but has not yet started processing.

At this point, you may be wondering: What are `Report Data` and `extraData`? What are they responsible for? What is the relationship between them?

In fact, we have briefly introduced it before. `Report Data` is summary-level data:

The main report deals with:

- Total number of validators
- Total CL balance
- vault balance
- module level exited validators
- withdrawal finalization decision
- simulatedShareRate

That is to say, update the core status of the protocol first.

Now that the core status has been updated, the remaining detail-level data has not been updated, so `extraData` is mainly responsible for processing:

> **node operator level exited validators detailed status update**

That is to say:

```text
module A total exited = 50
```

further broken down into:

```text
module A:
  operator id 10 -> exited validator num 25
  operator id 11 -> exited validator num 20
  operator id 12 -> exited validator num 5
```

So the order must be:

```text
First submitReportData
-> rebase first / process the main report first

Then submitReportExtraDataList
->Add node operator level details
```

In addition, you may wonder: Why not put both `Report Data` and `extra Data` in the main report? Wouldn't it be better to upload the consensus hash uniformly, verify the legality of the hash, and process it uniformly?

In fact, the main reason is that the amount of data that needs to be updated in the `node operator` details is very large, because there are so many `staking module` in the `Lido` ecosystem, there are a large number of `node operator` under each `module`, and the `exited validators` count under each `node operator` must be synchronized. (You can check the "Module Life Cycle and Status Management" chapter for details). Therefore, if all are crammed into the main report: `calldata` will be very large, and a single transaction may exceed the gas limit.

Thus, it is finally separated and designed as:

```text
Main report: summary + extraData in hash/count/format
extraData: subsequent batch asynchronous processing
```

Up to this point, we have introduced the processing flow of the main report `ReportData`. Next, we will introduce in detail how `extraData` is processed asynchronously in batches and in what form efficient gas saving is achieved.

<br />
<br />

## 5. `extraData` Data processing

### 5.1 `extraData` Data classification

`extraData` is the data to update the detail level of `node operator`, mainly the quantity of `exit validator` of `node operator` under a specific `module`. There are two modes of data for `extraData`: `EMPTY` and `LIST`.

`EMPTY` means: This round of report does not have extraData details.

Require:

- `extraDataHash = 0`
- `extraDataItemsCount = 0`

The subsequent batch processing is not performed, but directly:

```text
_submitReportExtraDataEmpty()
```

The function is:

- Mark `submitted = true`
- Adjust `stakingRouter.onValidatorsCountsByNodeOperatorReportingFinished()`
- Send `ExtraDataSubmitted(refSlot, 0, 0)`

In other words: even if there is no extraData, the state machine must be explicitly completed.

 

`LIST` means: This round of report has extraData details and will be submitted in batches later.

Require:

- `extraDataHash != 0`
- `extraDataItemsCount > 0`

Subsequent passes:

```text
submitReportExtraDataList(bytes data)
```

Come and process them batch by batch.

<br />

### 5.2 `extraData` data batching

When processing `extraData`, it is divided into `batch` and `item`. In fact, when seeing these two words, the first thing everyone thinks is to process each set of data in batches.

`batch` means: a whole batch submitted at one time `bytes`

`data` in `submitReportExtraDataList(bytes data)` is not an item, but an entire batch:

```text
| nextHash (32 bytes) | item0 | item1 | item2 | ... |
```

in:

- The first 32 bytes `nextHash` are the hash of the next batch
- followed by multiple items

 

`item` means: a business unit

The header format of each `item` is:

```text
| 3 bytes itemIndex | 2 bytes itemType | itemPayload |
```

The current version only supports:

```text
itemType = EXITED_VALIDATORS
```

`STUCK_VALIDATORS` has been deprecated after the `Triggerable Withdrawals` update.

The values ​​that need to be processed in the `extraData` data are stored in ==`itemPayload`==. The payload format is:

```text
| 3 bytes  | 8 bytes | nodeOpsCount * 8 bytes | nodeOpsCount * 16 bytes |
| moduleId | count   | nodeOperatorIds        | validatorsCounts        |
```

What it means is:

> **Count of exited validators for a group of node operators under a certain module**

For example:

```text
moduleId = 2
nodeOpsCount = 3
nodeOperatorIds = [10, 15, 20]
validatorsCounts = [5, 8, 12]
```

express:

```text
module 2:
  operator id 10 -> exited = 5
  operator id 15 -> exited = 8
  operator id 20 -> exited = 12
```

<br />

### 5.3 `extraData` Data processing

The processing of `extraData` can be understood as a processing process of "submit in batches + each batch contains multiple items + hash chain to ensure order".

Before understanding the code, let’s look at a complete example 🌰:

Assume that in the current report:

```text
extraDataItemsCount = 5
```

Indicates a total of 5 items:

```text
item0, item1, item2, item3, item4
```

📦 We will submit in two batches:

*batch1 (first 3 items)*

```
batch1:
[ nextHash = H2 ]
[ item0 ]
[ item1 ]
[ item2 ]
```

Among them `H2 = keccak256(batch2)`

*batch2 (last 2 items)*

```
batch2:
[ nextHash = 0 ]
[ item3 ]
[ item4 ]
```

In this way, the hash chain relationship between the two `batch` is:

```
ReportData.extraDataHash = H1 = keccak256(batch1)

batch1 → H2 → batch2 → 0
```

The overall process is as follows:

```text
submitReportData
    ↓
procState.dataHash = H1

submit batch1
    ↓
keccak256(batch1) == H1 ✔
    ↓
procState.dataHash = H2

submit batch2
    ↓
keccak256(batch2) == H2 ✔
    ↓
nextHash = 0 → end
```

First let's look at how `batch` is processed, and then we'll look at how `item` under `batch` is processed.

 
**`batch` processing logic**

The function `_submitReportExtraDataList()` is the master scheduler for batch processing of `extraData`. It will take `ExtraDataProcessingState` first and know the current:

- Looking forward to `dataHash`
- Total number of items
- Number of items processed
- Previous sort position

To check whether the hash of the current batch of data is correct, the contract first does:

```Solidity
keccak256(data) == procState.dataHash
```

If not equal, revert directly. This ensures that the batch that should be submitted now is the one that should be submitted now, and not another batch.

It should be noted that the `procState.dataHash` here is not the hash value reached by the consensus of the main report `reportData` we discussed before. It is the `dataHash` in the main report, or the subsequent chained hash.

> 1. The HashConsensus consensus is the overall hash of the main report
> 	↓
> 2. The main report contains extraDataHash
> 	↓
> 3. After submitReportData is successful
> 	↓
> 4. extraDataHash is written to procState.dataHash
> 	↓
> 5. submitReportExtraDataList uses keccak256(data) to match it

Next, read `nextHash` starting with `batch` (the first 32 bytes of `data` are: `nextHash`)

```solidity
assembly {
    dataHash := calldataload(data.offset)
}

// Get the first 32 bytes: nextHash
```

Determine if:

```text
nextHash == 0
```

It means this is the last batch, otherwise it means there will be the next batch later.

 
**`item` processing logic**

Parse `item` starting from `offset=32` (because the first 32 bytes are nextHash). Then call `_processExtraDataItems(data, iter)` to process items one by one: `item0 → item1 → item2 → ...`.

The data in each `item` is the `exitedValidatorsCount` value in which `node operator id` under which `module id` needs to be updated.

Then call:

```solidity
stakingRouter.reportStakingModuleExitedValidatorsCountByNodeOperator()
```

After processing this batch:

- If `nextHash == 0`: the last batch

    - Request `itemsProcessed == itemsCount`
    - Mark `submitted = true`
    - Adjust `stakingRouter.onValidatorsCountsByNodeOperatorReportingFinished()`

- If `nextHash != 0`: There is another batch

    - Request `itemsProcessed < itemsCount`
    - Put `procState.dataHash = nextHash`
    - Wait for the next batch of submissions

So the whole mechanism is essentially hash chain batch submission.

Finally, let's look at how a single `item` is handled. The specific logic is in the `_processExtraDataItem()` function. This function is responsible for parsing a `item`'s `payload` and actually reporting the data to the `StakingRouter` contract.

The specific process is as follows:

> *The first step: parse the payload first and read it from the current `dataOffset`*
>
> - `moduleId`
> - `nodeOpsCount`
> - `nodeOpIds` byte slice
> - `valuesCounts` byte slice
>
> Then calculate the total length of this item based on `nodeOpsCount` and update `dataOffset` to the beginning of the next item.
>
>
> *Step 2: Sorting Check*
>
> The system requires that the global order is strictly increasing according to the following key:
>
> `(itemType, moduleId, nodeOperatorId)`
>
> Therefore, two levels of checks will be done:
>
> 1. The first `(type, moduleId, nodeOpId)` of the current `item` must be greater than the last key of the previous `item`
> 2. The current `item` internal `nodeOperatorIds` must also be strictly incremented
>
> This ensures no duplication, no disorder, and no jumps.
>
>
> *Step 3: Call StakingRouter to implement the business*
>
> After both parsing and verification pass, it will be called:
>
> `reportStakingModuleExitedValidatorsCountByNodeOperator(moduleId, nodeOpIds, valuesCounts)`
>
> This step is to truly synchronize the `node operator` level `exited validators` details to `StakingRouter`.

<br />

### 5.4 `extraData` packed efficient gas mechanism

Seeing this, some people may have questions. Since the `reportStakingModuleExitedValidatorsCountByNodeOperator()` interface is ultimately called to update the `node operator` level data, why not pass the array directly? Is the previous method of packaging and unpacking redundant?

Actually not redundant. Because this set of protocols additionally solves:

```
1. calldata compression
uint64 is no longer encoded in 32 bytes
uint128 is no longer encoded in 32 bytes

2. Combine multiple items into one batch
One batch can process multiple modules/multiple items

3. Multi-batch chain resume transfer
If one batch cannot be processed, you can continue to the next batch.
String through nextHash

4. Global order and integrity
Can't be out of order
Cannot replace a certain batch in the middle
Certain items cannot be skipped
```

So packed `batch/item` solves the problem of "large-scale, verifiable, and resumable input protocols."

> Let’s go back to the example mentioned at the beginning of 5.3 to show the entire process of `extraData` being processed.
>
> If this round of report has 5 `item`:
>
> `item0, item1, item2, item3, item4`
>
> At this point, it was too large, so it was split into two batches (`batch`, also called a `chunk`)

The second batch batch2

```solidity
batch2 = | 0x00..00 | item3 | item4 |
hash2 = keccak256(batch2)
```

Since this is the last batch, `nextHash = 0`.

The first batch batch1

```solidity
batch1 = | hash2 | item0 | item1 | item2 |
hash1 = keccak256(batch1)
```

Recorded in the main report:

```solidity
extraDataFormat = LIST
extraDataHash = hash1
extraDataItemsCount = 5
```

When processing:

```solidity
submitReportData(...)
-> Only initialize extraData state
  -> itemsProcessed = 0
  -> dataHash = hash1

submitReportExtraDataList(batch1)
  -> keccak256(batch1) == hash1
  -> _processExtraDataItems(...)
-> Traverse item0, item1, item2
-> Call for each item:
         stakingRouter.reportStakingModuleExitedValidatorsCountByNodeOperator(...)
  -> itemsProcessed = 3
->Next batch of requested hash = hash2

submitReportExtraDataList(batch2)
  -> keccak256(batch2) == hash2
  -> _processExtraDataItems(...)
-> Traverse item3, item4
-> Call for each item:
         stakingRouter.reportStakingModuleExitedValidatorsCountByNodeOperator(...)
  -> itemsProcessed = 5
  -> nextHash = 0
  -> submitted = true
  -> stakingRouter.onValidatorsCountsByNodeOperatorReportingFinished()
```
<br />
<br />
 
## 6. The state machine is exposed to the outside world

The `AccountingOracle` contract provides a query interface of `getProcessingState()` to the outside world, which is used to answer:

```text
Current frame:
1. Is there a consensus hash?
2. Has the main report been submitted?
3. Has extraData been started/completed?
4. How many items have been processed?
```

It puts three levels of states together:

- `HashConsensus`: Whether the current frame already has a consensus hash
- `BaseOracle`: Whether the current refSlot has started processing
- `AccountingOracle`: extraData processing progress

<br />
<br />

## Summary

```text
1. Time segmentation
   slot -> epoch -> frame
Each frame has only one refSlot and one processing deadline

2. HashConsensus
members vote on the report hash of the same refSlot in the current frame
A certain hash reaches quorum -> becomes consensus report

3. BaseOracle
Receive submitConsensusReport(hash, refSlot, deadline)
Record reports that the current frame has been agreed upon but has not yet been processed.

4. submitReportData
Submit complete ReportData
Recalculate keccak256(abi.encode(data))
Must be equal to the current consensus hash
After _startProcessing(), the current refSlot is locked

5. Main report processing
   _handleConsensusReportData(...)
-> Verify extraData header
   -> legacy oracle
-> module level exited validators
   -> withdrawal queue
   -> Lido.handleOracleReport(...)
-> Initialize extraData processing state

6. extraData
EMPTY -> End directly
LIST -> submitReportExtraDataList(bytes data) in batches

7. batch / item
   batch = | nextHash | item0 | item1 | ... |
   item  = | index | type | payload |
The current version mainly deals with EXITED_VALIDATORS

8. item payload
   moduleId + nodeOperatorIds + validatorsCounts
Finally call StakingRouter.reportStakingModuleExitedValidatorsCountByNodeOperator(...)
```
