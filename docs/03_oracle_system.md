## 概述

Lido 的 Oracle 体系本质上是一个 **分层 + 解耦的状态同步与执行系统**，由三类核心组件组成：

```
HashConsensus -> BaseOracle -> 具体 Oracle（Accounting / ExitBus）
```

其中：

- `HashConsensus`：负责对 report hash 达成共识
- `BaseOracle`：负责管理 processing 状态机
- 各类 Oracle：负责具体业务执行

在 Lido 中，Oracle 并不是单一模块，而是拆分为两条核心链路：

> 🔥 **AccountingOracle（状态同步） + ValidatorsExitBusOracle（退出触发）**

<br>
<br>

## 1. Oracle 分层架构

### 1.1 `HashConsensus`：只做“选 hash“

职责：

- 管理 oracle committee 成员
- 管理 frame / refSlot / deadline
- 收集 member 提交的 report hash
- 达成 quorum 共识

特点：

```
只处理 hash，不处理业务数据
```

<br>

### 1.2 BaseOracle： processing 状态机

职责：

- 接收已达成共识的 `(hash, refSlot)`
- 存储当前可处理的 report
- 控制 processing 生命周期：
    - 是否可以开始处理
    - 是否已经处理过
    - 是否锁定当前 frame

特点：

```
只管理“什么时候处理”，不关心“处理什么”
```

<br>

### 1.3 业务 Oracle：执行真实逻辑

在 BaseOracle 之上，Lido 实现了两类 Oracle：

#### ✅ AccountingOracle（状态同步）

负责：

- 同步 CL balance / validators
- 同步 module exited validators（汇总 + 明细）
- 处理 withdrawal finalization
- 归集 vault ETH（EL rewards + withdrawals）
- 计算 rewards / fee 并分配
- 执行 stETH rebase

本质：

```
一个“状态机 + 结算引擎”
```

#### ✅ ValidatorsExitBusOracle（退出触发）

负责：

- 决定哪些 validator 应该 exit
- emit exit request
- 调用 Gateway 触发 CL exit

本质：

```
一个“执行触发器”
```

<br>
<br>

## 2. 两条 Oracle 主链路

Lido Oracle 实际运行中存在两条**完全独立的链路**：

### 2.1 AccountingOracle（状态同步链）

```text
HashConsensus
	↓
BaseOracle
	↓
AccountingOracle.submitReportData
	↓
Lido.handleOracleReport
	↓
更新状态：
  - CL balance
  - validators
  - exited validators
  - withdrawal finalization
  - rewards / fee - rebase
```

特点：

- 周期性执行（每个 frame）
- 驱动整个协议账本更新
- 不触发 validator exit

<br>

### 2.2 ValidatorsExitBusOracle（退出触发链）

```text
HashConsensus / 或 Bus路径
	↓
submitReportData / submitExitRequestsData
	↓
emit ValidatorExitRequest
	↓
triggerExits
	↓
TriggerableWithdrawalsGateway
	↓
Beacon Chain exit
```

特点：

- 负责“让 validator 退出”
- 不处理资金结算
- 不更新 Lido accounting

<br>
<br>

## 3. Withdrawal 与 Oracle 的关系

很多人容易误解：

> ❗ **用户提现 ≠ 触发 validator exit**

正确关系如下：

### 3.1 WithdrawalQueue 的作用

```
requestWithdrawals()
    -> 记录请求
    -> mint unstETH NFT
```

只是表达需求，不做任何执行

<br>

### 3.2 exit 由 ExitBusOracle 触发

```
ValidatorsExitBusOracle
    -> 决定哪些 validator exit
```

与用户 request 解耦

<br>

### 3.3 ETH 回流由 Oracle 同步

```
CL withdrawal
	↓
WithdrawalVault
	↓
AccountingOracle report
	↓
Lido buffer 更新
```

<br>

### 3.4 finalize + claim

```
AccountingOracle
	-> finalize withdrawal

用户
	-> claimWithdrawal()
```

完整链路：

```
用户 request
	↓
 （等待）
	↓
ExitBus 触发 validator exit
	↓
CL 执行 withdrawal
	↓
ETH 到 WithdrawalVault
	↓
AccountingOracle finalize
	↓
用户 claim
```

<br>
<br>

## 4. 解耦设计

Lido Oracle 的设计关键在于三条链路完全解耦。

```
1. 用户链路（request / claim）
2. exit 链路（ExitBusOracle）
3. accounting 链路（AccountingOracle）

用户 request ≠ 立即
exit exit ≠ 立即到账
到账 ≠ 立即 claim
```

Oracle 是“周期驱动”，不是“用户驱动”，Oracle 每个 frame 执行 不是用户触发。Lido 是“pull-based + oracle-driven system”，不是同步执行系统。

总体调用关系：

```
用户
	-> submit / requestWithdrawals

Oracle（周期运行）
	-> AccountingOracle（同步状态）
	-> ExitBusOracle（触发 exit）

系统执行
	-> CL exit
	-> ETH 回流 vault

Oracle
	-> finalize withdrawal

用户
	-> claimWithdrawal
```

<br>
<br>

### Summary

```
1. Oracle 分三层：
    HashConsensus -> BaseOracle -> 业务 Oracle

2. 两条核心链路：
    - AccountingOracle：状态同步 + 结算
    - ExitBusOracle：触发 validator exit

3. Withdrawal 是独立系统：
   request ≠ exit ≠ finalize ≠ claim

4. 所有流程由 Oracle 周期驱动，而不是用户触发

5. 核心设计思想：
   解耦 + 分层 + 异步执行
```
