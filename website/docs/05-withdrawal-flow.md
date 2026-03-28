## Overview

Lido's withdrawal process is not "the user immediately gets back the ETH after initiating the unstake". Instead, it first enters the `WithdrawalQueue` queue, and then `AccountingOracle` finalizes a batch of requests in the oracle report. Finally, the user calls `claimWithdrawal()` to receive the locked ETH. WithdrawalQueue is also a `unstETH` ERC-721 NFT contract. NFT represents the user's withdrawal rights in the queue. It mints when requesting creation and burns when claiming.

<br />
<br />
    
## 1. User entrance

The process for users to apply for withdrawal is as follows:

```text
user requestWithdrawals(...)
-> Verify each amount
-> Transfer stETH / wstETH into WithdrawalQueue
-> Assign new requestId to each request
-> write queue[requestId]
-> record owner -> requestIds
-> unstETH NFT corresponding to mint
```

The generated `requestId` is used as the anchor point for the entire subsequent extraction link, and will serve as a link between the previous and the following:

- `calculateFinalizationBatches` scans the queue in the order of `requestId`
- `finalize` is advancement `lastFinalizedRequestId`
- `claimWithdrawal` is also paid according to `requestId`

<br />

### 1.1 `unstETH` NFT: Withdrawal rights certificate

After the user calls `requestWithdrawals*()`, WithdrawalQueue will also mint a `unstETH` ERC-721 NFT corresponding to `requestId`. The meaning of this NFT is not "already extractable ETH", but rather:

- Represents the ownership of the withdrawal request in the queue
- Represents the right to execute `claimWithdrawal` on this request in the future
- Its `tokenId` has a one-to-one correspondence with `requestId`

In other words, whoever holds this NFT will have the withdrawal rights corresponding to the request.

<br />

### 1.2 NFT is transferable

`WithdrawalQueueERC721` implements the core interface of standard ERC-721, including:

- `ownerOf`
- `approve`
- `setApprovalForAll`
- `transferFrom`
- `safeTransferFrom`

Therefore, after the request is created and before the claim is made, this `unstETH` NFT can be transferred and traded, which means:

- Users can hold the claim until finalization.
- You can also transfer the NFT to others
- The claim rights will be transferred together with the NFT ownership

When the NFT is transferred, the `owner` of the request will also be updated synchronously within the contract, so the person who can actually claim it later is the current NFT owner.

<br />

### 1.3 When will NFT disappear?

When the request is successfully claimed:

- request will be marked as `claimed`
- The corresponding `unstETH` NFT will be burned

Therefore, `unstETH` NFT only exists during the life cycle of request:

```text
request create
	-> mint unstETH NFT
-> Transferable / Tradeable
-> can be claimed after finalized
-> burn NFT after claim is successful
```
<br />
<br />
    
## 2. The user starts waiting for finalization

The request enters the FIFO queue and the user cannot claim immediately. Only after finalization occurs can the user claim. At the same time, users will no longer enjoy the subsequent benefits of this part of `stETH` during the queue period.

```text
User initiates request
-> request enters FIFO queue
-> User holds unstETH NFT
-> Cannot claim at this time
-> Need to wait for subsequent oracle report finalize
```

<br />
<br />
    
## 3. `calculateFinalizationBatches`: Batch planning

Then the Oracle daemon calls the `calculateFinalizationBatches` interface to calculate which requests can be finalized in this round under the constraints of budget, time, and share rate, and divide them into batches.

```text
Oracle daemon
-> Call calculateFinalizationBatches(...)
->Input:
        - remainingEthBudget
        - _maxTimestamp
        - _maxShareRate
        - _maxRequestsPerCall
-> Output:
        - withdrawalFinalizationBatches
```

Core logic:

- Start scanning from `lastFinalizedRequestId + 1`

- Check `timestamp <= _maxTimestamp`

- Calculate request share rate / ethToFinalize

- Check `remainingEthBudget`

- Merge batches by "same report / same side (above or below `_maxShareRate`)"

- Return `batches` and updated state
For example `batches = [5, 9, 12]` means:
`batch1 : request 1 ~ 5`
`batch2 : request 6 ~ 9`
`batch3 : request 10 ~ 12`

<br />
<br />

## 4.Oracle report

Oracle's overall process under the extraction link is as follows:

```Solidity
Oracle daemon calls calculateFinalizationBatches(...)
-> Calculate the request batches that can be finalized in this round

Oracle report
    -> AccountingOracle.submitReportData(...)
    -> WithdrawalQueue.onOracleReport(...)
-> Synchronize report timestamp
-> Sync bunker mode
    -> Accounting.handleOracleReport(...)
-> Simulation report
-> Call WithdrawalQueue.prefinalize(...)
-> Subsequent execution of withdrawals/rewards processing
```

Oracle will first synchronize the `WithdrawalQueue` state and call the `onOracleReport` interface. Its function is not to finalize directly, but to synchronize the context of the oracle report to `WithdrawalQueue` first, mainly including:

- Update the latest report timestamp
- Synchronize bunker mode status

<br />
<br />

## 5. `prefinalize` Precalculate withdrawal cost

During the accounting phase of oracle report, `WithdrawalQueue.prefinalize()` will be called. `prefinalize` is a pre-calculation of the batches selected in the previous step `calculateFinalizationBatches`, including:

- Verify whether `withdrawalFinalizationBatches` is legal, increasing, and continuous

- Precompute batch by batch:
    - ETH to finalize
    - shares to burn

- Return these values ​​to the accounting process for subsequent sanity checks and actual execution

### 5.1 Collect rewards and perform finalization

After completing prefinalize, the oracle contract needs to call the `_handleOracleReport` interface to synchronously update the ledger status. `smoothenTokenRebase` will be carried out based on the amount of ETH withdrawn to make the withdrawal process smoother. This has the advantage that the share value will not fluctuate greatly. The reward is then taken from `elRewardsVault` and `withdrawalVault`, and the reward is divided into two parts.

ExecutionLayerRewardsVault

Receive the priority fee / MEV income of the execution layer, and then call `withdrawRewards()` in the oracle report to pull back the buffer and update the `BufferedEther` ledger in the Lido contract.

WithdrawalVault

Receive ETH from the consensus layer withdrawal credentials, and then be pulled back to the buffer by `Lido` during the oracle report, updating the `BufferedEther` ledger in the Lido contract. The consensus layer withdraws the pledged ETH principal instead of rewards. The withdrawal process is as follows:

> ***Triggerable Withdrawals / EIP-7002 Path***
>
> `gate` Contract payment withdrawal fee
> 	↓
> `WithdrawalVault.addWithdrawalRequests()`
> 	↓
> Withdraw the fee and transfer it to the consensus layer `predeploy` contract. Add the withdrawal request to the queue.
> 	↓
> The consensus layer (`Beacon chain`) executes the extraction of pledged ETH according to the queue
> 				 |
***WithdrawalVault fund receiving path***
> 				↓
> ETH is transferred to the `withdrawal_credentials` specified address
> 	↓
> `Lido` Contract call `WithdrawalVault.withdrawWithdrawals()`
> 	↓
> ETH to Lido Contract

The `finalize` interface will then determine the final value for the request, lock the ETH in the contract balance, and burn the underlying `stETH`.

```Solidity
WithdrawalQueue.finalize(...)
-> Lock this batch of requests corresponding to ETH
-> Push the last finalized request boundary
-> Write checkpoint
-> Update the finalized status of request
```

<br />

### 5.2 burn link

The stETH/shares corresponding to the withdrawal request are not burned immediately when the user initiates the request. It occurs in the accounting process of the oracle report:

```Solidity
WithdrawalQueue.prefinalize(...)
-> Precalculate the sharesToBurn of withdrawal batches that need to be burned in this round

Lido._handleOracleReport(...)
-> Call Burner.requestBurnShares(withdrawalQueue, sharesToBurnFromWithdrawalQueue)
-> Burner first receives/accounts this part and waits for burn shares

    -> OracleReportSanityChecker.smoothenTokenRebase(...)
-> Calculate sharesToBurn that is actually allowed to burn in this round

    -> Burner.commitSharesToBurn(sharesToBurn)
    -> Lido._burnShares(burner, sharesToBurn)
```

The Burner contract is responsible for hosting the shares prepared for burn, recording the status of these shares to be burned, and updating the internal ledger when the burn actually occurs. The actual action of modifying the totalShares ledger is to call `_burnShares()` in the oracle report of the Lido contract, so that it and the following processes are processed in the same accounting / rebase cycle:

- CL balance update
- withdrawal finalization
- EL rewards / withdrawals collection
- rebase smoothing
- fee minting

Only in this way can stETH's share rate, rebase and withdrawal settlement standards be consistent.

The Burn contract maintains a ledger of shares to be burned, which mainly contains four state variables:

```solidity
coverSharesBurnRequested
nonCoverSharesBurnRequested
totalCoverSharesBurnt
totalNonCoverSharesBurnt
```

When `requestBurnShares()` is called: `nonCoverSharesBurnRequested += shares`, only the state to be burned is recorded, and the total supply of stETH will not be reduced immediately. During the oracle report process, when the number of burns allowed in this round is determined: `commitSharesToBurn(sharesToBurn)`, Burner will update the internal ledger:

```solidity
pending -= sharesToBurn
totalBurnt += sharesToBurn
```

`Lido` then calls `_burnShares()`, truly reducing `totalShares`.

<br />
<br />

## 6. checkpoint mechanism

Before the user claims, the checkpoint mechanism needs to be introduced first, because it will be used in the claim method. In order to reduce storage costs, Lido does not store the final ETH amount on each request, but uses the checkpoint mechanism.

checkpoint records: `fromRequestId`, `shareRate`, `cumulative shares`, `cumulative ETH`. Each checkpoint indicates that the same settlement rules are used from the beginning of fromRequestId to the next checkpoint, for example:

```text
checkpoint1 : fromRequestId = 1
checkpoint2 : fromRequestId = 6
checkpoint3 : fromRequestId = 11
```

Corresponding interval:

```text
request 1  ~ 5   -> checkpoint1
request 6  ~ 10  -> checkpoint2
request 11 ~ ... -> checkpoint3
```

Quickly locate the range through the Binary Search method. There is no need to store the ETH amount on each request. Finalize only needs to write a small number of checkpoints, and the storage and gas costs are significantly reduced. The design of checkpoint + binary search adopts a very classic model: batch settlement + interval compression storage + binary search.

This model can be reused in many scenarios, such as segmented interest rates, segmented rewards, segmented settlement, and batch liquidation.

<br />
<br />
    
## 7. Users receive ETH

After `finalize` is completed, the user enters the real claim path. Users can check the status through `getWithdrawalStatus()`, or know that the request can be claimed through the `WithdrawalsFinalized` event. The end user completes the ETH withdrawal by calling `claimWithdrawal`.

```Solidity
User claimWithdrawal(requestId, hint)
-> Check whether request has been finalized
-> Check whether request has not been claimed
-> Check whether the caller is the current NFT owner/authorized party
-> Use checkpoint hint to find the checkpoint
-> Calculate the request to receive ETH
-> Mark request as claimed
    -> burn unstETH NFT
-> Transfer locked ETH to recipient
```

<br />
<br />
    
## Summary

```text
The user calls WithdrawalQueue.requestWithdrawals(...)
-> stETH / wstETH transfer to WithdrawalQueue
-> Generate WithdrawalRequest
    -> mint unstETH NFT

Later:

-> Oracle daemon calls calculateFinalizationBatches(...)
-> Calculate the request batches that can be finalized in this round

    -> AccountingOracle.submitReportData(...)
        -> WithdrawalQueue.onOracleReport(...)
-> Synchronize report timestamp
-> Sync bunker mode

        -> AccountingOracle.submitReportData(...)
-> Lido.handleOracleReport(...) is called internally in the function
            -> report simulation（WithdrawalQueue.prefinalize(...)）
            -> sanity checks
-> Handle withdrawals / rewards / rebase
-> Complete this round of withdrawal finalization

The user calls claimWithdrawal(requestId, hint)
-> Verify finalized / unclaimed / owner
-> ETH can be collected based on checkpoint calculation
    -> burn unstETH NFT
-> ETH transferred to user
```
