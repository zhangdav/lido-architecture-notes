

## 概述

`StakingRouter` 是 Lido 协议中负责管理 StakingModule 生命周期与状态的核心合约。它在 `Lido` 合约与各个 `StakingModule` 之间，承担模块注册、配置管理、运行状态控制以及 validator 退出状态同步等职责。  
  
在 Lido 的架构中，validator 按照如下层级组织：  
  
- `StakingRouter` 管理多个 `StakingModule`  
- 每个 `StakingModule` 可以包含多个 `NodeOperator`  
- 每个 `NodeOperator` 维护一组 `Validator`  

```Plain text
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

Router 本身并不直接管理 validator 的密钥或节点运行状态，这些逻辑由 `StakingModule` 实现；Router 负责维护模块级别的全局状态与配置，并在需要时将事件或数据转发给对应的 module。  
  
此外，Router 还负责协调 Oracle 上报的 validator 状态，例如 exited validator 数量的同步，并在必要时触发 module 的状态更新回调。  
  
本文档主要描述以下内容：  
  
- StakingModule 的注册与初始化流程  
- Module 参数与配置更新  
- Module 运行期状态管理  
- Validator 退出相关事件与延迟监控  
- Oracle 上报 exited validator 状态的同步机制  
- 异常情况下的状态修复流程  
  
需要注意的是，本文档只关注 Module 生命周期与状态管理逻辑。 关于 ETH deposit 流程、validator 分配策略以及奖励分配机制，会在其他文档中单独介绍。


---
## 1. Module 注册

Module 管理员首先通过调用 `addStakingModule` 添加一个模块。  
  
**校验逻辑**  
  
- 校验 module 地址非 0  
- 校验 name 不能超过规定长度  
- 校验是否已经超过 module 数量 **32 上限**  
- 确保 module 地址不重复  
  
**初始化流程**  
  
- 分配 `module id` 自增  
- 初始化 `module state`  
- 设置参数  
- `share limit`  
- `fee`  
- `deposit block` 限制  
  
**存储结构**
  
Module 的存储方式为 **Onbase 双索引映射机制**，用于高效查找并节省 Gas。


---
## 2. Module 配置更新

运行过程中 Module 管理员可以调整模块参数。  


### 2.1 更新 Router 层配置

`updateStakingModule()`
  
- `stakeShareLimit`  
- `priorityExitShareThreshold`  
- `stakingModuleFee`  
- `treasuryFee`  
- `maxDepositsPerBlock`  
- `minDepositBlockDistance`  


### 2.2 更新 Module 内配置

`updateTargetValidatorsLimits()`

- 作用：node operator validator 上限


---
## 3. Module 运行期管理

运行过程中 Router 还会调整 module 的运行状态。


### 3.1 调整 vetted signing keys

`decreaseStakingModuleVettedKeysCountByNodeOperator()`

- 作用：减少 validator keys  


### 3.2 暂停或停止 module

`setStakingModuleStatus()`
  
状态： 

| 状态             | 存款  | 奖励  |
| :------------- | :-: | :-: |
| Active         |  ✅  |  ✅  |
| DepositsPaused |  ❌  |  ✅  |
| Stopped        |  ❌  |  ❌  |


---
## 4. Validator 退出

某个 validator 的 triggerable exit request 被触发，Router 把这个通知转发给对应 module。  

  
### 4.1 exit request 被触发

`onValidatorExitTriggered()` 
  
- 作用：通知 module 某 validator 已被触发退出请求


### 4.2 exit delay 上报

`reportValidatorExitDelay()`
  
- 作用：上报某 validator 在被请求退出后，已经 eligible to exit 但仍未真正退出多久

> [!NOTE]
>4.1 和 4.2 是 `ExitBus / Triggerable exit` 相关运行态事件
> 


---
## 5. Oracle 同步退出状态

当 validator 真正退出 Beacon chain 后，oracle 会同步状态。


### **5.1 先同步 Module 层退出总数**

`updateExitedValidatorsCountByStakingModule()`

作用：

- Oracle 向 Router 上报每个 staking module 的总 exited validators 数
    
- Router 保存这个模块级总数
    
- Router 后续用它参与 active validators / deposit allocation / fee distribution 的计算


### **5.2 再同步 Node Operator 层退出明细**

`reportStakingModuleExitedValidatorsCountByNodeOperator`  
	↓  
`module.updateExitedValidatorsCount()`  
  
- 同步 node operator exited validators

作用：

- Oracle 将某 module 下各 node operator 的 exited validators 细分数据补齐到 module 内部状态
    
- 这一阶段可以分批、多次提交

> [!NOTE]
5.1 和 5.2 是 `AccountingOracle` 之后的 exited validators 结果同步


---
## 6. 状态同步完成

当 Oracle 完成 node operator 级 exited validators 数据上报后，会调用：

- `onValidatorsCountsByNodeOperatorReportingFinished()`

此时 Router 会遍历每个 module：

- 读取 module 内部聚合出的 `exitedValidatorsCount`
    
- 与 Router 中保存的 module 总 exitedValidatorsCount 比较
    
- **只有两者一致时**  

调用：

- `module.onExitedAndStuckValidatorsCountsUpdated()`

如果不一致，则该 module 本轮不会被标记为完成。


---
## 7. 异常状态修复

如果 oracle 报告出现错误，管理员可以修复。

**修复入口：`unsafeSetExitedValidatorsCount()`**

1. 校验当前状态  
2. 修改 module exitedValidatorsCount  
3. 修改 node operator exited count  
4. 可触发同步完成


---
## Summary

```Plain
Module 生命周期

注册
  addStakingModule
  ↓

配置
  updateStakingModule
  updateTargetValidatorsLimits
  ↓

运行期管理
  decreaseStakingModuleVettedKeysCountByNodeOperator
  setStakingModuleStatus
  ↓

validator exit 相关
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

异常修复
  unsafeSetExitedValidatorsCount
```