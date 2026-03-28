---
slug: /
---

## 概述

GitHub 导航：[zhangdav/lido-architecture-notes](https://github.com/zhangdav/lido-architecture-notes)

`Lido` 是一个将“即时流动性凭证”和“异步底层质押结算”结合起来的以太坊质押协议。用户提交 ETH 后，协议会立即铸造 `stETH` 作为权益凭证，使用户在资金已进入质押体系的同时仍保持链上流动性；而底层的 validator 创建、运行、奖励累积、退出触发以及提款回流，则分别通过 Router、StakingModule、Oracle、Vault 和 WithdrawalQueue 等模块协同完成。整个系统并不是由单次用户操作同步完成，而是依赖 Oracle 周期性地把 Consensus Layer 和 Execution Layer 的状态同步回链上，再统一完成 rebase、奖励分配、退出结果确认和提款结算。

> *参考官方 repo version：https://github.com/lidofinance/core/tree/v2.2.0*

![Lido Architecture](/img/diagrams/lido_architecture.png)

  
## 1. 四条核心链路

Lido 协议可以拆解为四条核心链路，这四条链路相互配合，但并不在同一笔交易中执行。

### 1.1 Deposit（质押链路）

```
用户
	-> Lido.submit()
	-> mint stETH
	-> ETH 进入 buffer

后续：
	-> StakingRouter 分配 deposit
	-> StakingModule 提供 validator keys
	-> Beacon DepositContract 完成质押
```

特点：

- 用户立即获得 stETH
- ETH 不会立即进入 CL，而是进入 buffer 后再由 DSM 分批 deposit

<br />

### 1.2 Validator Lifecycle（validator 生命周期）

```
StakingRouter
	-> 管理 StakingModule
		-> 管理 NodeOperator
			-> 管理 Validator

生命周期：创建 → 存款 → Active → Exit Triggered → Exited → Withdrawn
```

特点：

- Router 只管理状态，不运行 validator
- validator 实际运行在 Consensus Layer

<br />

### 1.3 Oracle（状态同步链路）

```
HashConsensus
	-> BaseOracle
    -> AccountingOracle
```

执行内容：

```
- 同步 CL balance
- 更新 validator 数量
- 同步 exited validators
- 处理 withdrawal finalization
- 归集 vault ETH
- 计算 rewards / fee
- 执行 stETH rebase
```

特点：

- 周期性执行（frame）
- 驱动整个协议状态更新
- 是系统的“结算引擎”

<br />

### 1.4 Withdrawal（提款链路）

```
用户
	-> requestWithdrawals()
	-> mint unstETH NFT

等待：
	-> Oracle finalize

用户
	-> claimWithdrawal()
```

特点：

- FIFO 队列
- request / finalize / claim 三阶段
- 提款过程完全异步

<br />
<br />
  
## 2. 核心模块分工

Lido 通过模块化设计将不同职责拆分到不同合约中：

  
#### **Lido**

- 用户入口
- mint / burn stETH
- 管理 buffer
- 作为结算中心

  
#### **StakingRouter**

- 管理 StakingModule 生命周期
- 决定 deposit 分配
- 汇总 validator 状态

  
#### **StakingModule**

- 管理 node operator
- 管理 validator keys
- 提供 deposit 数据

  
#### **AccountingOracle**

- 同步协议状态
- 处理 rewards / fee
- 触发 rebase
- finalize withdrawal

  

#### **ValidatorsExitBusOracle**

- 决定哪些 validator 需要 exit
- emit exit request
- 触发 Beacon Chain exit

  

#### **WithdrawalQueue**

- 记录提款请求
- mint unstETH NFT
- 管理 finalize / claim

  

#### **Vault（ExecutionLayer / Withdrawal）**

- 接收 EL rewards
- 接收 CL withdrawal ETH
- 在 Oracle 中回流到 Lido

<br />
<br />
  
## 3. 关键设计思想

### 3.1 Oracle 驱动（非用户驱动）

```
用户操作 ≠ 立即执行结果
```

- 用户存款不会立即完成 CL deposit
- 用户提款不会立即拿到 ETH
- 所有关键状态更新由 Oracle 周期执行

<br />

### 3.2 强解耦（核心架构设计）

Lido 将系统拆为三条独立链路：

```
1. 用户链路（deposit / withdrawal request）
2. exit 链路（ValidatorsExitBusOracle）
3. accounting 链路（AccountingOracle）
```

它们的关系：

```
request ≠ exit
exit ≠ 到账
到账 ≠ claim
```

<br />

### 3.3 异步结算系统

所有操作都是“分阶段完成”的：

- deposit：buffer → batch → CL
- withdrawal：request → finalize → claim
- exit：trigger → CL → withdrawal → vault

<br />

### 3.4 分层 + 状态机设计

```
HashConsensus -> BaseOracle -> Business Oracle
```

- 共识层（hash）
- 状态层（processing）
- 业务层（执行逻辑）

 提高安全性 + 可升级性

 <br />
 <br />
  
## 4. 阅读路径（建议顺序）

为了完整理解 Lido 协议，建议按照以下顺序阅读：

```
1. 本文：Lido 协议纵览（全局地图）

2. 质押流程
   -> 理解 ETH 如何进入 CL

3. StakingRouter / Module 生命周期
   -> 理解 validator 管理结构

4. Oracle 机制纵览
   -> 理解系统如何被驱动

5. AccountingOracle
   -> 理解状态同步与结算

6. WithdrawalQueue
   -> 理解提款流程

7. ValidatorsExitBusOracle
   -> 理解 validator exit 触发

8. fee 分配机制 -> 理解经济模型
```
