

## 概述

Lido 协议 oracle 是一个复杂的状态机，主要由三个核心模块组成：`HashConsensus`、`BaseOracle`、`AccountingOracle` 组成。oracle committee 成员将报告上传到 `HashConsensus`，对达成共识，且在规定时间范围内提交报告，`BaseOracle` 负责记录和管理当前已达成共识的报告， `AccountingOracle`负责处理报告，为 Lido 合约提供状态更新的数据参数。


*==HashConsensus：管理 frame 和 hash 共识==*

>  oracle committee member 成员
>  quorum（最少多少成员支持同一个 hash 才算达成共识）
>  frame 的时间切分
>  每个 frame 对应的 `refSlot` 和 `deadline`
>  成员在某个 frame 上提交的 report hash

所以 `HashConsensus` 合约不处理业务数据本身，也不做 rebase。它只做一件事：为每个 frame 选出一份达成共识的 report hash。


*==BaseOracle：接收 consensus report，并管理 processing 状态==*

`BaseOracle` 合约是一个“异步处理基类“。它负责：

>  接收 HashConsensus 推送过来的 `(hash, refSlot, deadline)`
>  记录当前已共识但尚未处理的 report
>  在真正开始处理前，允许共识被替换或丢失
>  在开始处理后，锁定当前 `refSlot`

所以它是共识结果的缓冲层和 processing 状态机。它本身不需要理解 `report data` 的业务含义。


*==AccountingOracle：提交完整数据并执行业务==*

`AccountingOracle` 在 `BaseOracle` 之上增加了真正的业务语义。它负责：

>  接收完整 `ReportData`
>  计算 `keccak256(abi.encode(data))`
>  校验它是否与当前共识 hash 一致
>  调用 `Lido.handleOracleReport()`
>  同步 legacy oracle / staking router / withdrawal queue
>  初始化 extraData 状态
>  分批处理 extraData item

所以 `HashConsensus` 解决哪份 hash 被认可，`BaseOracle` 解决什么时候开始处理，`AccountingOracle` 解决“怎么处理完整业务数据”。

```Plain text
HashConsensus
	-> 管理委员会 member、frame、quorum、report hash 共识


BaseOracle
	-> 接收共识后的 hash，记录当前 frame 可处理的 consensus report
	-> 负责 processing 状态机（什么时候开始处理、是否已开始）


AccountingOracle
	-> 提交完整 ReportData
	-> 校验完整数据的 hash 是否等于已共识的 hash
	-> 执行主报告（rebase / vault / withdrawal / module exited validators）
	-> 初始化并分批处理 extraData
```

整条链路是先对 `hash` 达成共识，再提交完整 `ReportData`，再开始 `processing`，最后再处理 `extraData`。这样的好处是，完整报告很大，先共识 `hash` 更便宜，只有与共识 `hash` 匹配的完整报告才能被处理，`extraData` 可以拆成多批提交，降低 gas 压力。


## 1. 时间模型：report 提交如何划分时间周期

在每次 `member` 提交报告，在合约中有特定限制的时间窗口`slot`、`epoch`、`frame`。顾名思义，报告提交是分阶段提交的，且每个阶段最终达成共识被处理的报告只有一个。那么，这个以时间窗口为基础的阶段是如何划分？

Oracle 的时间模型建立在 Beacon Chain 的 slot / epoch 基础上，其中包括：

### **1.1 `slot`**

slot 是最小时间单位

`timestamp = genesisTime + slot * secondsPerSlot`


### **1.2 `epoch`**

一个 epoch 由固定数量的 slot 组成

`epoch = slot / slotsPerEpoch`

例如：
```Plain
slotsPerEpoch = 32

slot 0   ~ 31   -> epoch 0
slot 32  ~ 63   -> epoch 1
slot 64  ~ 95   -> epoch 2
```


### **1.3 `frame`**

`frame` 是 `HashConsensus` 合约用来组织 oracle 报告的时间窗口，一个 `frame` 包含固定数量的 epoch。

例如：
```Plain
epochsPerFrame = 225
```

那么每个 frame 就是 225 个 epoch。如果每个 `epoch` 都有 32 个 slot，那么每个 `frame` 有 225 * 32 = 7200 个 `slot`。


### **1.4 `reference slot 简称：refSlot`**

一个 `frame` 并不是对 `frame` 内每个 `slot` 都分别出报告，而是只围绕一个固定的 `refSlot` 出一份报告。

- `refSlot` 是上一个 `frame` 的最后一个 `slot`，作为当前 `frame` 的观察基准 
- `processing deadline` 是该 `frame` 的结束时间（按时间计算，而非具体 slot）
-  member 可以在当前 `frame` 的 reporting 窗口内提交 hash（fast lane + slow lane）

```Solidity
prev frame        current frame
|..............|.................................|
               refSlot                       deadline
               
// refSlot = last slot of prev frame
// deadline = end timestamp of current frame
```

这样设计的意义在于：

- 当前 `frame` 的 report 基于 `refSlot` 对应的 Beacon Chain 状态快照，保证与共识层一致   
- 当前 `frame` 的处理结果，会在下一个 `frame` 的 `refSlot` 被观测到，形成闭环  
- 不同 `frame` 之间通过 `refSlot` 隔离，避免状态观测与处理相互干扰


---
## 2. Hash 机制：report hash 如何产生、上报、达成共识

`HashConsensus` 合约并不知道完整报告长什么样，它只处理 `bytes32 reportHash` 。对于 `AccountingOracle` 合约来说，这个 `hash` 来自 `keccak256(abi.encode(ReportData))`。也就是说，report member 在链下都应该基于同一份完整 `ReportData` 计算出同一个 hash。

`ReportData` 里包括：

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

所以 `HashConsensus` 的共识本质是，member 对一整份 `ReportData` 的 ABI 编码 hash 达成一致，因为其中的参数将在 Lido 合约中作为入参修改账本状态。


### **2.1 member 如何上传 hash**

成员会在当前 frame 内，对同一个 `refSlot` 调用：`HashConsensus.submitReport(refSlot, reportHash, consensusVersion)`。

`HashConsensus` 合约会检查：

- 当前是否在允许提交的 frame 窗口内（*快速通道/普通通道*）
- `consensusVersion` 是否等于 processor 当前要求的版本
- `refSlot` 是否是当前 frame 的 reference slot
- 提交者是否是 committee member

如果通过，就把该成员对该 frame 的投票记下来。


### **2.2  `quorum` 共识阈值**

`quorum` 是对某个 hash 投票统计的阈值，某个 hash 投票数大于该值则表示对此 hash 达成共识，其规则如下：

- `quorum` 必须严格大于成员数量的一半（大于 `totalMembers` / 2）  
- 最小 `quorum = floor(totalMembers / 2) + 1  `

比如：
```Plain
committee = 5 人
quorum = 3
```

那如果 3 个成员都提交了相同的 `reportHash = H1`，就说明 H1 达成共识。

```Plain
member1 -> H1
member2 -> H1
member3 -> H1
member4 -> H2
member5 -> 未提交
```

此时：H1 票数为 3票，且大于或等于 `quorum(3)`，H1 成为当前 `frame` 的 consensus report。


### **2.3 提交共识报告**

一旦某个 hash 达到 quorum，`HashConsensus` 会调用 `report processor` 合约中的
`submitConsensusReport(reportHash, refSlot, deadline)`。这个动作不是立刻开始处理业务，而是把已达成共识的 `(hash, refSlot, deadline)` 提交到 `BaseOracle` 合约，记录为当前 `frame` 的待处理共识结果。开篇提到过 `BaseOracle` 合约只负责接收 consensus report 和管理 processing 状态，它不负责处理报告中的数据。


### **2.4 共识作废和恢复**

`quorum` 作为是否达成共识的阈值，而这个值管理员可以实时修改，那么每次修改都可能对已提交到 `BaseOracle` 合约中的共识报到存在影响（作废/恢复），举个例子：

当前

```Plain
quorum = 3
```

成员支持情况：

```Plain
H1 = 3 票
```

所以 H1 原本已共识。

如果管理员把 quorum 提高到：

```Plain
quorum = 4
```

那原来那 3 票就不够了，于是：

```Plain
H1 不再是共识报告
```

如果这个 H1 还没开始 processing，HashConsensus 就可以通知 processor：

```Solidity
discardConsensusReport(refSlot)
```

这意味，之前提交给 `BaseOracle` 的共识报告 H1 被作废了。

如果后来又有成员补投 H1，或 quorum 又被管理员设置降回到 3，或 member 发生变化后，这个 H1 再次达到 `quorum`。那么 HashConsensus 会再次调用：

```Solidity
submitConsensusReport(reportHash, refSlot, deadline)
```

也就是说，在开始 processing 之前，共识是可变的。同一个 `frame` 里，当前共识 hash 可以被替换、丢失、再恢复。一旦某个 `refSlot` 进入 `processing`，即：共识阶段结束，进入执行阶段。当前 `frame` 的共识 hash 被锁定：

> 1. 当前 `frame` 的共识 hash 被锁定
> 2. `HashConsensus` 不再接受该 `refSlot` 的任何新投票  
> 3. 无法再触发 `discardConsensusReport`  作废已提供的共识报告
> 4. 无法再替换为新的共识 hash  
> 5. `submitReportData` 只能执行一次

接下来，我们来看一下共识报告如何进入 `processing` 阶段。


---
## 3. Report hash 处理：主报告如何开始 `processing`

在主报告开始 `processing` 之前，在 `HashConsensus` 合约向 `BaseOracle` 合约上传完达成共识的报告之后，其实还有一个步骤。即：`submitReportData` ，它是在 `BaseOracle` 合约中触发的，整个顺序如下：

> 1. members 提交 `report hash`
> 2. `HashConsensus` 达成 `quorum`
> 3. `HashConsensus` 调用 `BaseOracle.submitConsensusReport()`
> 4. `BaseOracle` 存下 `_storageConsensusReport`
> 5. 之后才由管理员 `SUBMIT_DATA_ROLE` 调用 `submitReportData(fullReport)`

所以必须先有共识 hash，才能提交完整的 `ReportData`。

前面我们提到 `HashConsensus` 合约会调用 `BaseOracle` 合约的 `submitConsensusReport` 接口，将达成共识报告上传到 `BaseOracle` 中，所以 `BaseOracle` 合约中会保存一个当前共识报告，包括：`hash`、`refSlot`、`processingDeadlineTime`。

这个状态代表，当前 frame 已经有一份达成共识、可以进入后续处理的主报告候选。直到管理员调用`AccountingOracle`合约中的 `submitReportData(data, version)`才允许主报告开始进入 `processing` 流程。但在开始处理报告前，`submitReportData` 函数会对管理员上传的报告数据与 `BaseOracle` 中存储的共识报告进行校验：

- 当前是否确实有一个 `consensus report`
- `data.refSlot` 是否等于共识的 `refSlot`
- `consensusVersion` 是否匹配
- `keccak256(abi.encode(data))` 是否等于共识 hash

只有都通过，才允许继续处理。所以`ConsensusReport` 的作用不是参与业务计算，而是作为完整 `ReportData` 的准入校验门槛。

一旦通过共识校验，主报告就会进入 `processing` 阶段：

```Plain
_startProcessing()
    -> 标记当前 refSlot 开始 processing
    -> 更新 lastProcessingRefSlot
    -> emit ProcessingStarted(refSlot, ...)
```

此时，当前 frame 的主报告正式锁定，并开始处理。从这之后不能再次对同一个 `refSlot` 调 `submitReportData`，`HashConsensus` 也不能再替换这一帧的共识 hash（前面提到过）。

从而实现：

```Plain
1 frame -> 1 refSlot -> 1 main report processing
```


---
## 4. `ReportData` 数据处理

前面我们讲到了 `submitReportData` 函数中调用 `_startProcessing()` 接口，主报告进入 `processing` 阶段。接下来，我们要继续讲 `submitReportData` 函数中 `_handleConsensusReportData` 函数是如何处理主报告中的数据，这也是整个 Oracle 机制改写不同合约账本的触发点。

因为涉及到的链路比较长，我们将其拆成 6 步进行介绍：


### **4.1 检查 `extraData` 头部是否合法** 

如果：

```Plain
extraDataFormat = EMPTY
```

那么要求：

- `extraDataHash == 0`
- `extraDataItemsCount == 0`

表示没有 `extraData` 需要被处理，`extraData`数据是用来更新特定 `module` 下 `node operator` 数据的。

如果：

```Plain
extraDataFormat = LIST
```

那么要求：

- `extraDataHash != 0`
- `extraDataItemsCount > 0`

表示有 `extraData` 需要在后续被处理，及更新 `module` 下 `node operator` 中的相关数据。


### **4.2 同步 CL 汇总数据到 legacy oracle**

`AccountingOracle` 合约会调用 legacy oracle 合约的兼容接口，把：

- `refSlot`
- `clBalanceGwei * 1e9`
- `numValidators`

同步过去，这一步主要是迁移兼容层逻辑。


### **4.3 更新 module 级 exited validators**

主报告里有两组汇总级字段：

- `stakingModuleIdsWithNewlyExitedValidators`
- `numExitedValidatorsByStakingModule`

`AccountingOracle` 合约会把它们同步到 `StakingRouter` 合约中，这里是 `module` 级别的汇总，不是 `node operator` 级明细。


### **4.4 通知 WithdrawalQueue 新的 report 到了**

调用：

```Plain
withdrawalQueue.onOracleReport(
    isBunkerMode,
    prevReportTimestamp,
    currentReportTimestamp
)
```

作用是更新 report 时间边界，同步 bunker mode 状态。


### **4.5 调 `Lido` 合约中 `handleOracleReport()`接口

这是主报告最核心的业务动作。

这里会把：

- `report timestamp`
- `time elapsed`
- `numValidators`
- `clBalance`
- `withdrawalVaultBalance`
- `elRewardsVaultBalance`
- `sharesRequestedToBurn`
- `withdrawalFinalizationBatches`
- `simulatedShareRate`

交给 Lido，从而推动 `Lido` 合约中完成：

- rebase
- 提现 finalization
- vault 余额归集
- burn 处理


### **4.6 初始化 extraData processing state**

主报告最后不会直接处理 extraData，而是把：

- `refSlot`
- `dataFormat`
- `dataHash`
- `itemsCount`
- `itemsProcessed = 0`
- `lastSortingKey = 0`
- `submitted = false`

写入 `AccountingOracle` 合约中 的`ExtraDataProcessingState`。这表示：extraData 的任务已经被登记，但还没开始处理。

讲到这里可能大家会疑惑：到底什么是 `Report Data`，`extraData`又是什么，它们分别负责什么，它们之间有什么关联？

其实我们在前面已经简单介绍了，`Report Data` 是汇总级的数据：

主报告里处理的是：

- 总 validator 数
- 总 CL balance
- vault 余额
- module 级 exited validators
- withdrawal finalization 决策
- simulatedShareRate

也就是先把协议核心状态更新掉。

既然核心状态更新了，那么还剩下明细级的数据没有更新，所以 `extraData` 主要负责处理：

> **node operator 级别的 exited validators 明细状态更新**

也就是把：

```Plain
module A total exited = 50
```

进一步拆成：

```Plain
module A:
  operator id 10 -> exited validator num 25
  operator id 11 -> exited validator num 20
  operator id 12 -> exited validator num 5
```

所以顺序一定是：

```Plain
先 submitReportData
    -> 先 rebase / 先处理主报告

再 submitReportExtraDataList
    -> 再补 node operator 级明细
```

另外大家可能会疑问：为什么不将 `Report Data` 和 `extra Data` 都放在主报告中？这样统一上传共识 hash，统一验证 hash 的合法性，并且也能统一处理不是更好吗？

其实，主要是因为 `node operator` 明细需要更新的数据量非常大，因为在 `Lido` 生态中 `staking module` 非常多，每个 `module` 下有大量的 `node operator`，每个 `node operator` 下的 `exited validators` 计数都要同步。（可以详细查阅《Module 生命周期与状态管理》章节）。所以，如果全部塞进主报告：`calldata` 会非常大，单笔交易可能超 gas limit。

从而最终将其分离设计为：

```Plain
主报告：汇总 + extraData 的 hash / count / format
extraData：后续分批异步处理
```

直到这里，我们介绍完了主报告 `ReportData` 的处理流程，接下来我们将详细介绍 `extraData` 如何分批异步处理的，以及通过何种形式做到了高效的 gas saving。


---
## 5. `extraData` 数据处理

### **5.1 `extraData` 数据分类**

`extraData` 是更新 `node operator` 明细级的数据，主要是特定 `module` 下 `node operator` 的 `exit validator` 数量。`extraData` 的数据有两种模式：`EMPTY` 和 `LIST`。

`EMPTY` 表示：这轮 report 没有 extraData 明细。

要求：

- `extraDataHash = 0`
- `extraDataItemsCount = 0`

后续不走 batch 处理，而是直接走：

```Plain
_submitReportExtraDataEmpty()
```

作用是：

- 标记 `submitted = true`
- 调 `stakingRouter.onValidatorsCountsByNodeOperatorReportingFinished()`
- 发 `ExtraDataSubmitted(refSlot, 0, 0)`

也就是说：即使没有 extraData，也要显式把状态机走完。

---

`LIST` 表示：这轮 report 有 extraData 明细，后续要分批提交。

要求：

- `extraDataHash != 0`
- `extraDataItemsCount > 0`

后续通过：

```Plain
submitReportExtraDataList(bytes data)
```

来一批一批处理。


### **5.2 `extraData` 数据分批**

在处理 `extraData` 时，将其分为了 `batch` 和 `item`。其实看到这两个词，大家第一感觉是分批次处理每组数据。

`batch` 表示：一次提交的一整批 `bytes`

`submitReportExtraDataList(bytes data)` 里的 `data` 不是一个 item，而是一整个 batch：

```Plain
| nextHash (32 bytes) | item0 | item1 | item2 | ... |
```

其中：

- 前 32 字节 `nextHash` 是下一批的 hash
- 后面跟着多个 item

---

`item` 表示：一个业务单元

每个 `item` 的头部格式是：

```Plain
| 3 bytes itemIndex | 2 bytes itemType | itemPayload |
```

当前版本只支持：

```Plain
itemType = EXITED_VALIDATORS
```

`STUCK_VALIDATORS` 在 `Triggerable Withdrawals` 更新后已废弃。

其中`extraData`数据中需要处理的值，存储在 ==`itemPayload`== 中。payload 格式是：

```Plain
| 3 bytes  | 8 bytes | nodeOpsCount * 8 bytes | nodeOpsCount * 16 bytes |
| moduleId | count   | nodeOperatorIds        | validatorsCounts        |
```

它的含义是：

> **某个 module 下，一组 node operators 的 exited validators 计数**

例如：

```Plain
moduleId = 2
nodeOpsCount = 3
nodeOperatorIds = [10, 15, 20]
validatorsCounts = [5, 8, 12]
```

表示：

```Plain
module 2:
  operator id 10 -> exited = 5
  operator id 15 -> exited = 8
  operator id 20 -> exited = 12
```


### **5.3 `extraData` 数据处理**

`extraData` 的处理可以理解为，它是一个“按批次提交 + 每批包含多个 item + hash 链保证顺序”的处理流程。

在理解代码之前，我们先看一个完整例子 🌰：

假设当前 report 中：

```Plain text
extraDataItemsCount = 5
```

表示总共有 5 个 item：

```Plain text
item0, item1, item2, item3, item4
```

📦 我们分成两批提交：

*batch1（前 3 个 item）*

```
batch1:
[ nextHash = H2 ]
[ item0 ]
[ item1 ]
[ item2 ]
```

其中 `H2 = keccak256(batch2)`

*batch2（后 2 个 item）*

```
batch2:
[ nextHash = 0 ]
[ item3 ]
[ item4 ]
```

这样两个 `batch` 的 hash 链关系为：

```
ReportData.extraDataHash = H1 = keccak256(batch1)

batch1 → H2 → batch2 → 0
```

整体流程如下：

```Plain text
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
nextHash = 0 → 结束
```

首先我们来看下 `batch` 是如何被处理的，然后我们再看 `batch` 下的 `item` 是如何被处理的。


---
**`batch` 的处理逻辑**

`_submitReportExtraDataList()`这个函数是 `extraData` 分批处理的总调度器，它会先拿 `ExtraDataProcessingState`，知道当前：

- 期待的 `dataHash`
- 总 item 数
- 已处理 item 数
- 上一个排序位置

检查当前这批 data 的 hash 是否正确，合约先做：

```Solidity
keccak256(data) == procState.dataHash
```

如果不相等，直接 revert。这保证了现在提交的正是当前应该提交的这一批，而不是别的批次。

需要注意的是这里的 `procState.dataHash` 不是之前我们讨论的主报告 `reportData` 达成共识的 hash 值。它是主报告中的 `dataHash`，或后续链式 hash。

> 1. HashConsensus 共识的是主报告整体 hash  
> 	↓  
> 2. 主报告里包含 extraDataHash  
> 	↓  
> 3. submitReportData 成功后  
> 	↓  
> 4. extraDataHash 被写入 procState.dataHash  
> 	↓  
> 5. submitReportExtraDataList 用 keccak256(data) 去匹配它

接着，读取  `batch` 开头的 `nextHash`（`data` 的前 32 字节就是：`nextHash`）

```solidity
assembly {
    dataHash := calldataload(data.offset)
}

// 拿前 32 字节：nextHash
```

判断，如果：

```Plain
nextHash == 0
```

说明这是最后一批，否则说明后面还有下一批。


---
**`item` 的处理逻辑**

从 `offset=32` 开始解析 `item`（因为前 32 字节是 nextHash）。然后调用 `_processExtraDataItems(data, iter)` 逐个处理 item：`item0 → item1 → item2 → ...`。

每个 `item` 中的数据是需要更新哪个 `module id`下的哪个 `node operator id` 中的 `exitedValidatorsCount` 值。

然后调用：

```solidity
stakingRouter.reportStakingModuleExitedValidatorsCountByNodeOperator()
```

处理完本批后：

- 如果 `nextHash == 0`：最后一批
    
    - 要求 `itemsProcessed == itemsCount`
    - 标记 `submitted = true`
    - 调 `stakingRouter.onValidatorsCountsByNodeOperatorReportingFinished()`
    
- 如果 `nextHash != 0`：还有下一批
    
    - 要求 `itemsProcessed < itemsCount`
    - 把 `procState.dataHash = nextHash`
    - 等下一批提交

所以整个机制本质上是哈希链式分批提交。

最后，我们来看下单个 `item` 是如何被处理的。具体的逻辑在 `_processExtraDataItem()`函数中，这个函数负责解析一个 `item` 的 `payload`，并真正把数据上报到 `StakingRouter`合约。

具体流程如下：

> ==*第一步：先解析 payload，从当前 `dataOffset` 读取*==
> 
> - `moduleId`
> - `nodeOpsCount`
> - `nodeOpIds` 字节切片
> - `valuesCounts` 字节切片
> 
> 然后根据 `nodeOpsCount` 算出这个 item 的总长度，更新 `dataOffset` 到下一个 item 开始处。
> 
> 
> ==*第二步：排序检查*==
> 
> 系统要求全局顺序是按下面这个 key 严格递增：
> 
> `(itemType, moduleId, nodeOperatorId)`
> 
> 所以会做两层检查：
> 
> 	1. 当前 `item` 的第一个 `(type, moduleId, nodeOpId)` 必须大于上一个 `item` 的最后一个 key
> 	2. 当前 `item` 内部的 `nodeOperatorIds` 也必须严格递增
> 
> 这样可以保证不重复、不乱序、不跳跃。
> 
> 
> ==*第三步：调用 StakingRouter 落地业务*==
> 
> 解析和校验都通过后，会调用：
> 
> `reportStakingModuleExitedValidatorsCountByNodeOperator(moduleId, nodeOpIds, valuesCounts)`
> 
> 这一步才是真正把 `node operator` 级 `exited validators` 明细同步到 `StakingRouter`。


### 5.4 `extraData` packed 高效 gas 机制

看到这里，或许有的人会有疑问，既然最终是调用 `reportStakingModuleExitedValidatorsCountByNodeOperator()`接口来更新 `node operator`级的数据，为什么不直接传数组？前面通过打包和解包的方式是不是多余？

实际上不多余。因为这套协议额外解决了：

```
1. calldata 压缩
    uint64 不再按 32 bytes 编码
    uint128 也不再按 32 bytes 编码
    
2. 多 item 合并成一个 batch
    一个 batch 可以处理多个 module / 多个 item
      
3. 多批次链式续传
    一批处理不完，可以继续下一批
    通过 nextHash 串起来
    
4. 全局顺序与完整性
    不能乱序
    不能替换中间某一批
    不能跳过某些 item
```

所以 packed `batch/item` 解决的是“大规模、可校验、可续传的输入协议。

> 我们回到前面 5.3 开头讲的例子，来展示整个 `extraData` 被处理的过程
> 
> 假如这轮 report 有  5 个 `item`：
> 
> `item0, item1, item2, item3, item4`
> 
> 这时发现太大了，拆成两批（`batch 或者叫 chunk`)

==第二批 batch2==

```solidity
batch2 = | 0x00..00 | item3 | item4 |
hash2 = keccak256(batch2)
```

因为这是最后一批，所以 `nextHash = 0`。

==第一批 batch1==

```solidity
batch1 = | hash2 | item0 | item1 | item2 |
hash1 = keccak256(batch1)
```

主报告里记录：

```solidity
extraDataFormat = LIST
extraDataHash = hash1
extraDataItemsCount = 5
```

处理时：

```solidity
submitReportData(...)
  -> 只初始化 extraData state
  -> itemsProcessed = 0
  -> dataHash = hash1

submitReportExtraDataList(batch1)
  -> keccak256(batch1) == hash1
  -> _processExtraDataItems(...)
      -> 遍历 item0, item1, item2
      -> 对每个 item 调用：
         stakingRouter.reportStakingModuleExitedValidatorsCountByNodeOperator(...)
  -> itemsProcessed = 3
  -> 下一批要求的 hash = hash2

submitReportExtraDataList(batch2)
  -> keccak256(batch2) == hash2
  -> _processExtraDataItems(...)
      -> 遍历 item3, item4
      -> 对每个 item 调用：
         stakingRouter.reportStakingModuleExitedValidatorsCountByNodeOperator(...)
  -> itemsProcessed = 5
  -> nextHash = 0
  -> submitted = true
  -> stakingRouter.onValidatorsCountsByNodeOperatorReportingFinished()
```


---
## 6. 状态机对外暴露

`AccountingOracle`合约对外提供了 `getProcessingState()` 的查询接口，用来回答：

```Plain
当前 frame：
	1. 有没有 consensus hash？
    2. 主报告是否已提交？
    3. extraData 是否已经开始 / 完成？
    4. 已处理了多少 item？
```

它把三层状态拼在一起：

- `HashConsensus`：当前 frame 是否已有共识 hash
- `BaseOracle`：当前 refSlot 是否已经开始 processing
- `AccountingOracle`：extraData 处理进度


---
## Summary

```Plain text
1. 时间切分
   slot -> epoch -> frame
   每个 frame 只有一个 refSlot 和一个 processing deadline

2. HashConsensus
   members 在当前 frame 内对同一个 refSlot 的 report hash 投票
   某个 hash 达到 quorum -> 成为 consensus report

3. BaseOracle
   接收 submitConsensusReport(hash, refSlot, deadline)
   记录当前 frame 已共识但尚未处理的报告

4. submitReportData
   提交完整 ReportData
   重新计算 keccak256(abi.encode(data))
   必须等于当前 consensus hash
   _startProcessing() 后，当前 refSlot 锁定

5. 主报告处理
   _handleConsensusReportData(...)
   -> 校验 extraData 头部
   -> legacy oracle
   -> module 级 exited validators
   -> withdrawal queue
   -> Lido.handleOracleReport(...)
   -> 初始化 extraData processing state

6. extraData
   EMPTY -> 直接收尾
   LIST  -> 分批 submitReportExtraDataList(bytes data)

7. batch / item
   batch = | nextHash | item0 | item1 | ... |
   item  = | index | type | payload |
   当前版本主要处理 EXITED_VALIDATORS

8. item payload
   moduleId + nodeOperatorIds + validatorsCounts
   最终调用 StakingRouter.reportStakingModuleExitedValidatorsCountByNodeOperator(...)
```



