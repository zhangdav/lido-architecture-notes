## 概述

`AccountingOracle` 系列合约的机制主要是负责同步 `Module` 和 `node operator` 级退出的 `validator`数据。而 `ValidatorsExitBusOracle` 系列合约则是真正触发 CL 层“哪些 validator 现在应该退出”。所以 `AccountingOracle` 主要负责状态同步，它是一个状态机。`ValidatorsExitBusOracle` 则是真正去 CL 层控制和执行 `validator` 退出的触发器，前者是果，后者是因。

<br />

或许大家会存在疑惑，为什么需要 `ValidatorsExitBusOracle` 系列合约，它到底和 `WithdrawalQueue` 系列合约存在什么联系？其实用户通过 `WithdrawalQueue` 合约 `withdrawal request` 不会直接触发 CL 层的 validator exit，它只是记录提取的需求。为了让 CL 层 validator 真正退出，需要单独的退出指令系统，这就是 `ValidatorsExitBusOracle` 的作用。

<br />

`ValidatorsExitBusOracle` 和 `AccountingOracle` 不同的还有两点。第一，它不是只有 `HashConsensus -> BaseOracle -> submitReportData` 路径；除此之外，`ValidatorsExitBus` 还提供了 `submitExitRequestsHash -> submitExitRequestsData` 的辅助两阶段路径。第二，它不是将 `ReportData` 主报告和 `extrData` 数据分开处理。实际上，`ValidatorsExitBusOracle` 有两条提交路径：

<br />

*Oracle 共识路径（主路径）*

`HashConsensus -> BaseOracle -> submitReportData`

- 需要 `quorum`
- 校验 `report hash`
- 属于标准 Oracle 流程

<br />

*Bus 两阶段路径（辅助路径）*

`submitExitRequestsHash(hash) -> submitExitRequestsData(data)`

- commit → reveal 模型
- 不依赖 `HashConsensus`
- 用于灵活提交 exit request

此外，`ValidatorsExitBusOracle` 处理 `ReportData` 主报告和 `ExitRequestsData` 数据是在一个函数调用内处理，进行 `emit event`。

<br />
<br />    

## 1. Oracle 共识路径

`ValidatorsExitBusOracle` 同样支持标准的 Oracle 共识流程，其整体结构与 `AccountingOracle` 一致，依然基于：

```
HashConsensus -> BaseOracle -> ValidatorsExitBusOracle
```

但它的 `report` 数据更简单，不包含 `rebase / vault / withdrawal` 等逻辑，只包含 exit requests

<br />

### 1.1 Report hash 产生与提交

与 `AccountingOracle` 一样，oracle committee member 在链下构造完整的 `ReportData`：

```
struct ReportData {
    uint256 refSlot;
    uint256 requestsCount;
    uint256 dataFormat;
    bytes data;
}
```

其中：

- `refSlot`：当前 frame 的 `reference slot(refSlot)`
- `requestsCount`：本轮需要 exit 的 validator 数量
- `data`：packed 的 exit request 列表

`member` 在链下执行：

```
keccak256(abi.encode(reportData))
```

得到 `reportHash`，并在当前 `frame` 内调用：

```
HashConsensus.submitReport(refSlot, reportHash, consensusVersion)
```

<br />

### 1.2 `quorum` 共识机制

与 `AccountingOracle` 完全一致：

- 每个 `member` 对 `(refSlot, reportHash)` 投票
- 某个 `hash` 投票数大于等于 `quorum`，则达成共识

例如：

```
member1 -> H1
member2 -> H1
member3 -> H1
member4 -> H2
```

若 `quorum = 3`，则：

```
H1 成为 consensus report
```

<br />

### 1.3 提交共识报告到 BaseOracle

当某个 `reportHash` 达到 `quorum` 后：

```
HashConsensus.submitConsensusReport(reportHash, refSlot, deadline)
```

`BaseOracle` 会记录：

```
_storageConsensusReport = {
    hash,
    refSlot,
    deadline
}
```

此时只是“有了一份可以处理的 exit request hash”，还没有执行 exit。

<br />

### 1.4 提交完整 exit request 数据

之后由拥有权限的角色调用：

```
submitReportData(ReportData data)
```

在进入 `processing` 前会做严格校验：

```
1. data.refSlot == consensus.refSlot
2. keccak256(abi.encode(data)) == consensus.hash
3. dataFormat 合法
4. data.length 与 requestsCount 匹配
```

校验通过后：

```
_startProcessing()
```

进入 `processing` 状态：

```
当前 frame 锁定
该 refSlot 只能处理一次
```

<br />

### 1.5 处理 exit requests

通过调用 `_handleConsensusReportData(data)` 内部函数，其核心逻辑：

```text
1. 校验 dataFormat（必须为 LIST）
2. 校验 data length
3. sanity checker 检查 requestsCount
4. 调用 _processExitRequestsList(data)
5. 更新 processing state
6. 更新 TOTAL_REQUESTS_PROCESSED
```

<br />

### 1.6 解析并 emit exit request

其中 `_processExitRequestsList(data)` 是核心函数，主要负责解析数据并 emit exit request event。

#### 📦 数据结构（packed）

```
| moduleId (24bit) | nodeOpId (40bit) | validatorIndex (64bit) | pubkey (48 bytes) |
```

#### 🔄 处理流程：

```
while(offset < end):
    解析：
        moduleId
        nodeOpId
        validatorIndex
        pubkey

    校验：
        moduleId != 0
        排序严格递增（防重复）

    emit ValidatorExitRequest(...)
```

到目前这里只是 emit event，不会立即触发 exit 动作。

<br />

### 1.7 真正执行 exit

在 report data 已提交之后，调用：

```
triggerExits(exitsData, exitDataIndexes, refundRecipient)
```

执行流程：

```
1. 校验 exitsData hash 已存在（已提交）
2. 校验 exitDataIndexes 合法（递增 / 不越界）
3. 根据 index 选取 validator
4. 调用：
   TriggerableWithdrawalsGateway.triggerFullWithdrawals(...)
```

最终 Beacon Chain validator exit 被触发，这一条路径是标准 Oracle 驱动 exit 的方式。

Oracle 路径总结

```text
member 提交 hash
	↓
HashConsensus 达成 quorum
	↓
BaseOracle 记录 consensus report
	↓
submitReportData 提交完整数据
	↓
_processExitRequestsList emit exit request
	↓
triggerExits 执行 exit
```

<br />
<br />
    
## 2. Bus 两阶段路径

除了标准 Oracle 共识路径外，`ValidatorsExitBus` 还支持一种更轻量的两阶段提交方式：

```
submitExitRequestsHash -> submitExitRequestsData
```

<br />

### 2.1 提交 hash（commit 阶段）

这里的 hash 提交不需要 `quorum`，也不需要调用 `HashConsensus` 合约。首先调用  `submitExitRequestsHash(bytes32 exitRequestsHash)` 记录某份 exit request 数据的 hash（只登记一份 hash）。

存储：

```
requestStatusMap[exitRequestsHash] = {
    contractVersion,
    deliveredExitDataTimestamp
}
```

<br />

### 2.2 提交完整数据（reveal 阶段）

然后调用 `submitExitRequestsData(bytes data)` 接口，具体执行流程如下：

```
1. 计算 keccak256(data) -> hash
2. 检查该 hash 是否已通过 submitExitRequestsHash 提交
3. 校验数据格式 / 长度
4. 调用 _processExitRequestsList(data)
```

也就是说 commit: 记录 hash，reveal: 提交 data 并执行。这种路径不需要 `quorum` 达成共识，也不调用 `HashConsensus`，也不需要 `refSlot`，也没有 `processing` 状态机。所以它是适合用于紧急情况（快速触发 exit），灵活控制 exit request 提交，绕过共识层的快速执行通道。

Bus 两阶段路径总结

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
1. Oracle 路径（主路径）
   HashConsensus 达成 quorum
   -> BaseOracle 记录
   -> submitReportData
   -> processing
   -> emit exit request
   -> triggerExits

2. Bus 路径（辅助路径）
   submitExitRequestsHash
   -> submitExitRequestsData
   -> emit exit request
   -> triggerExits

3. 最终统一执行 ValidatorExitRequest
   -> TriggerableWithdrawalsGateway
   -> Beacon Chain exit
```