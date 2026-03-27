

## 概述

Lido 的 withdrawal 流程并不是“用户发起 unstake 后立刻拿回 ETH”，而是先进入 `WithdrawalQueue` 排队，随后由 `AccountingOracle` 在 oracle report 中对一批请求做 finalization，最后用户再调用 `claimWithdrawal()` 领取已经锁定好的 ETH。WithdrawalQueue 也是一个 `unstETH` ERC-721 NFT 合约，NFT 代表用户在队列中的提款权利，请求创建时 mint，claim 时 burn。


---
## 1. 用户入口

用户申请提取的流程如下：

```Plain text
用户 requestWithdrawals(...)
    -> 校验每笔 amount
    -> 把 stETH / wstETH 转入 WithdrawalQueue
    -> 为每个请求分配新的 requestId
    -> 写入 queue[requestId]
    -> 记录 owner -> requestIds
    -> mint 对应的 unstETH NFT
```

生成的 `requestId` 是作为后面整个提取链路的锚点，并且会承上启下的作用：

- `calculateFinalizationBatches` 是按 `requestId` 顺序扫队列
- `finalize` 是推进 `lastFinalizedRequestId`
- `claimWithdrawal` 也是按 `requestId` 领钱

### 1.1 `unstETH` NFT：提款权凭证

用户调用 `requestWithdrawals*()` 后，WithdrawalQueue  还会 mint 一个对应 `requestId` 的 `unstETH` ERC-721 NFT。这个 NFT 的含义不是“已经可提取的 ETH”，而是：

- 代表该 withdrawal request 在队列中的所有权  
- 代表未来对该 request 执行 `claimWithdrawal` 的权利  
- 其 `tokenId` 与 `requestId` 一一对应

也就是说，谁持有这个 NFT，谁就拥有该 request 对应的提款权。

### 1.2 NFT 可转让

`WithdrawalQueueERC721` 实现了标准 ERC-721 的核心接口，包括：  
  
- `ownerOf`  
- `approve`  
- `setApprovalForAll`  
- `transferFrom`  
- `safeTransferFrom`

因此，在 request 创建之后、claim 之前，这个 `unstETH` NFT 是可以被转移和交易的，这意味：  
  
- 用户可以自己持有直到 finalization 后 claim  
- 也可以把该 NFT 转给别人  
- claim 权利会随着 NFT 所有权一起转移  
  
当 NFT 被转移时，合约内部也会同步更新该 request 的 `owner`，因此后续真正能 claim 的人是当前 NFT owner。

### 1.3 NFT 何时消失

当 request 被成功 claim 后：  
  
- request 会被标记为 `claimed`  
- 对应的 `unstETH` NFT 会被 burn  
  
因此，`unstETH` NFT 只在 request 的生命周期中存在：

```Plain text
request 创建  
	-> mint unstETH NFT  
	-> 可转移 / 可交易  
	-> finalized 后可 claim  
	-> claim 成功后 burn NFT
```


---
## 2. 用户开始等待 finalization

请求进入 FIFO 队列，用户还不能立刻 claim。只有在 finalization 发生之后，用户才可以 claim。同时，排队期间用户不再享受这部分 `stETH` 的后续收益。

```Plain text
用户发起 request
    -> request 进入 FIFO queue
    -> 用户持有 unstETH NFT
    -> 此时还不能 claim
    -> 需要等待后续 oracle report finalize
```


---
## 3. `calculateFinalizationBatches`：批次规划

然后 Oracle daemon 通过调用 `calculateFinalizationBatches`接口，用来在预算、时间、share rate 限制下，计算本轮能 finalize 到哪些 request，并按 batch 划分。

```Plain text
Oracle daemon
    -> 调用 calculateFinalizationBatches(...)
    -> 输入：
        - remainingEthBudget
        - _maxTimestamp
        - _maxShareRate
        - _maxRequestsPerCall
    -> 输出：
        - withdrawalFinalizationBatches
```

核心逻辑：

- 从 `lastFinalizedRequestId + 1` 开始扫
    
- 检查 `timestamp <= _maxTimestamp`
    
- 计算 request share rate / ethToFinalize
    
- 检查 `remainingEthBudget`
    
- 按“同 report / 同侧（高于或低于 `_maxShareRate`）”合并 batch
    
- 返回 `batches` 和更新后的 state
	例如 `batches = [5, 9, 12]` 表示：
	    `batch1 : request 1 ~ 5`
		`batch2 : request 6 ~ 9`
		`batch3 : request 10 ~ 12`


---
## 4. Oracle report

Oracle 在提取链路下的总体流程如下：

```Solidity
Oracle daemon 调用 calculateFinalizationBatches(...)  
	-> 计算本轮可 finalize 的 request batches

Oracle report
    -> AccountingOracle.submitReportData(...)
    -> WithdrawalQueue.onOracleReport(...)
        -> 同步 report timestamp
        -> 同步 bunker mode
    -> Accounting.handleOracleReport(...)
        -> 模拟 report
        -> 调用 WithdrawalQueue.prefinalize(...)
        -> 后续执行 withdrawals/rewards 处理
```

Oracle 会先同步 `WithdrawalQueue` 状态，调用 `onOracleReport` 接口。它的作用不是直接 finalize，而是先把 oracle report 的上下文同步到 `WithdrawalQueue`，主要包括：

- 更新最新 report timestamp
- 同步 bunker mode 状态


---
## 5. `prefinalize` 预计算 withdrawal 成本

在 oracle report 的 accounting 阶段，`WithdrawalQueue.prefinalize()` 会被调用。`prefinalize` 是对上一步 `calculateFinalizationBatches` 已经选出的批次做预计算，包括：

- 校验 `withdrawalFinalizationBatches` 是否合法、递增、连续
    
- 逐 batch 预计算：
    - 要 finalize 的 ETH
    - 要 burn 的 shares
        
- 把这些值返回给 accounting 流程，用于后续 sanity check 和真正执行

### 5.1 收集 rewards 和执行 finalization

完成 prefinalize 以后，需要 oracle 合约调用 `_handleOracleReport` 接口进行账本状态的同步更新。其中会根据提取的 ETH 数量进行 `smoothenTokenRebase` 让提取的过程更加平滑，这样的好处是让 share 价值不会出现很大的波动。然后会从 `elRewardsVault` 和 `withdrawalVault` 中取出奖励，奖励分为两个部分。

==ExecutionLayerRewardsVault==

接收执行层的 priority fee / MEV 收益，然后在 oracle report 里被 `Lido` 调 `withdrawRewards()` 拉回 buffer，更新 Lido 合约中的 `BufferedEther` 账本。

==WithdrawalVault==

接收来自共识层 withdrawal credentials 的 ETH，然后在 oracle report 期间被 `Lido` 拉回 buffer，更新 Lido 合约中的 `BufferedEther` 账本。共识层提取的是质押的 ETH 本金而非奖励，提取的过程如下：

>        ***==Triggerable Withdrawals / EIP-7002 路径**==*
> 
> `gate` 合约支付提取 fee
> 	↓  
> `WithdrawalVault.addWithdrawalRequests()`
> 	↓  
> 提取 fee 转入共识层 `predeploy` 合约 提取请求加入  queue
> 	↓  
> 共识层（`Beacon chain`）按照 queue 执行提取质押的 ETH
> 				 |
	    **==*WithdrawalVault 资金接收路径***==									
> 				↓ 
> ETH 转入 `withdrawal_credentials`指定地址
> 	↓  
> `Lido` 合约调用 `WithdrawalVault.withdrawWithdrawals()`
> 	↓  
> ETH 到 Lido 合约

然后 `finalize` 接口会为 request **确定最终价值**，**在合约余额中锁定 ETH**，并烧掉底层 `stETH`。

```Solidity
WithdrawalQueue.finalize(...)
    -> 锁定本批 request 对应 ETH
    -> 推进 last finalized request 边界
    -> 写入 checkpoint
    -> 更新 request 的 finalized 状态
```

### 5.2 burn 链路

withdrawal 请求对应的 stETH / shares 并不是在用户发起请求时立刻 burn，它发生在 oracle report 的 accounting 流程中：

```Solidity
WithdrawalQueue.prefinalize(...)
    -> 预计算本轮 withdrawal batches 需要 burn 的 sharesToBurn

Lido._handleOracleReport(...)
    -> 调用 Burner.requestBurnShares(withdrawalQueue, sharesToBurnFromWithdrawalQueue)
    -> Burner 先接收 / 记账这部分待 burn shares

    -> OracleReportSanityChecker.smoothenTokenRebase(...)
        -> 计算本轮实际允许 burn 的 sharesToBurn

    -> Burner.commitSharesToBurn(sharesToBurn)
    -> Lido._burnShares(burner, sharesToBurn)
```

Burner 合约负责托管准备 burn 的 shares，记录这些 shares 是待 burn 状态，在 burn 真正发生时更新内部账本。真正修改 totalShares 账本的动作，是在 Lido 合约的 oracle report 中调用 `_burnShares()`，这样它和以下过程放在同一个 accounting / rebase 周期里统一处理：

- CL balance 更新
- withdrawal finalization
- EL rewards / withdrawals 归集
- rebase smoothing
- fee minting

这样才能保证 stETH 的 share rate、rebase 和 withdrawal 结算口径保持一致。

Burn 合约维护了一个待 burn shares 的账本，主要包含四个状态变量：

```solidity
coverSharesBurnRequested
nonCoverSharesBurnRequested
totalCoverSharesBurnt
totalNonCoverSharesBurnt
```

当 `requestBurnShares()` 被调用时：`nonCoverSharesBurnRequested += shares`，只记录待 burn 状态，并不会立刻减少 stETH 总 supply。在 oracle report 过程中，当本轮允许 burn 的数量确定后：`commitSharesToBurn(sharesToBurn)`，Burner 会更新内部账本：

```solidity
pending -= sharesToBurn
totalBurnt += sharesToBurn
```

随后 `Lido` 调用 `_burnShares()`，真正减少 `totalShares`。


---
## 6. checkpoint 机制

在用户 claim 前，需要先介绍 checkpoint 机制，因为在 claim 方法中会用到。了减少 storage 成本，Lido 没有在每个 request 上存储最终的 ETH amount，而是使用 **checkpoint 机制**。

checkpoint 记录：`fromRequestId`、`shareRate`、`累计 shares`、`累计 ETH`。每个 checkpoint 表示从 fromRequestId 开始到下一个 checkpoint 之前使用相同的结算规则，例如：

```Plain text
checkpoint1 : fromRequestId = 1
checkpoint2 : fromRequestId = 6
checkpoint3 : fromRequestId = 11
```

对应区间：

```Plain text
request 1  ~ 5   -> checkpoint1
request 6  ~ 10  -> checkpoint2
request 11 ~ ... -> checkpoint3
```

通过 Binary Search 的方法快速定位区间，不需要在每个 request 上存储 ETH amount，finalize 只需写入少量 checkpoint，storage 和 gas 成本都显著降低。checkpoint + binary search 的设计，采用了一种非常经典的模式：批处理结算 + 区间压缩存储 + 二分查找。

这种模式在很多场景都可以复用，例如：分段利率、分段奖励、分段结算、批处理清算。


---
## 7. 用户领取 ETH

`finalize` 完成后，用户才进入真正的 claim 路径。用户可通过 `getWithdrawalStatus()` 检查状态，或通过 `WithdrawalsFinalized` 事件得知 request 已可 claim。最终用户通过调用 `claimWithdrawal` 完成 ETH 提取。

```Solidity
用户 claimWithdrawal(requestId, hint)
    -> 检查 request 是否已 finalized
    -> 检查 request 是否未被 claimed
    -> 检查调用者是否是当前 NFT owner / 被授权方
    -> 使用 checkpoint hint 找到所属 checkpoint
    -> 计算该 request 可领取 ETH
    -> 标记 request 为 claimed
    -> burn unstETH NFT
    -> 向接收者转出已锁定 ETH
```


---
## Summary

```Plain text
用户调用 WithdrawalQueue.requestWithdrawals(...)
    -> stETH / wstETH 转入 WithdrawalQueue
    -> 生成 WithdrawalRequest
    -> mint unstETH NFT

Later:

    -> Oracle daemon 调用 calculateFinalizationBatches(...)
        -> 计算本轮可 finalize 的 request batches

    -> AccountingOracle.submitReportData(...)
        -> WithdrawalQueue.onOracleReport(...)
            -> 同步 report timestamp
            -> 同步 bunker mode

        -> AccountingOracle.submitReportData(...)
	        -> 函数内部调用 Lido.handleOracleReport(...)
            -> report simulation（WithdrawalQueue.prefinalize(...)）
            -> sanity checks
            -> 处理 withdrawals / rewards / rebase
            -> 完成本轮 withdrawal finalization

用户调用 claimWithdrawal(requestId, hint)
    -> 校验 finalized / unclaimed / owner
    -> 根据 checkpoint 计算可领 ETH
    -> burn unstETH NFT
    -> ETH 转给用户
```