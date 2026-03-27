

## 概述

Lido 的 ETH staking 流程从用户提交 ETH 开始，最终通过 Oracle 报告同步 Beacon Chain 状态并触发 `stETH` rebase。  
  
在整个流程中，协议涉及多个核心组件：  
  
- Lido：用户入口，负责接收 ETH 并 mint `stETH`  
- DepositSecurityModule (DSM)：负责 deposit 安全校验  
- StakingRouter：负责选择 staking module 并执行 validator deposit  
- StakingModule：管理 node operator 和 validator keys  
- Beacon DepositContract：以太坊官方 deposit 合约  
- AccountingOracle：同步 Consensus Layer 状态并更新协议 accounting  


---
## 1. 用户入口

用户与 `Lido` 合约 `submit()` 交互，而不是直接与 `StakingRouter` 交互；`Lido` 负责接收 ETH，给用户 mint `stETH`；并将 ETH 暂时放入 buffer，buffer 里的 ETH 后续才会被继续分配。


---
## 2. stETH 的铸造

用户提交 ETH 后，会立刻拿到 `stETH`。
这一步发生在 `Lido.submit()` 中，并不要求 ETH 当场完成 Beacon deposit。

`stETH` share 计算公式：

$$
shares = \frac{ethAmount \times totalShares}{totalPooledEther}
$$

```soldiity
User stake
  -> Lido 收 ETH
  -> Lido mint stETH
  -> ETH 先在 buffer
  -> 后续再由 Lido 往 StakingRouter 送
```


---
## 3. 存款分配策略 (Router allocation)

当 buffer 中积累了足够 ETH 后，协议需要决定：

- 本轮可以执行多少个 validator deposit
- deposit 应该分配到哪个 `StakingModule`

通过调用`StakingRouter` 合约中的 `getDepositsAllocation()`，计算：

- 每个 module 当前 `activeValidatorsCount`
- 每个 module 可提供的 `availableValidatorsCount`
- module 的 `stakeShareLimit`    
- module 的当前 `status`

Router 会加载所有 module 的状态，并调用 `MinFirstAllocationStrategy.allocate()`，计算出本轮 deposit 在各 module 之间的分配比例。

> [!NOTE]
> 这个函数只负责 **计算 allocation**，并不会真正执行存款。


---
## 4. DSM 发起存款

guardian 调用 `depositBufferedEther()` 指定目标 `StakingModuleId`，并附带本次 deposit 的相关参数与签名。`DepositSecurityModule` 会先校验签名、模块状态、nonce、block 条件等，再调用 `Lido.deposit()`。


---
## 5. Lido deposit

Lido 合约中的 `deposit()` 会验证 `msg.sender` 是否为 DSM，然后计算本次真正执行的 `depositsCount`。随后从 buffer 中扣除 `depositsCount * 32 ETH`，并调用 `StakingRouter.deposit()`。

> [!NOTE]
> 
> Lido 不会盲信 _maxDepositsCount，  而是结合：  
> 1. 当前 buffer 里可用于存款的 ETH  
> 2. 当前目标模块允许的最大 deposit 数量
> 
> 来计算本次真正执行的 depositsCount。


---
## 6. StakingRouter deposit

`StakingRouter` 会检查 `msg.sender` 是否是 Lido 合约，并检查：

- `withdrawal_credentials`
- 目标 `StakingModule` 是否处于 `Active`
- `msg.value == depositsCount * 32 ETH`

随后向目标 module 调用 `obtainDepositData()`，取出对应 validator 的公钥和签名。


---
## 7. Beacon deposit

`StakingRouter` 通过 `BeaconChainDepositor._makeBeaconChainDeposits32ETH()`，将：

- ETH
- `withdrawal credentials`
- `validator pubkeys`
- `signatures`

一起提交到 Beacon DepositContract，完成底层质押。


---
## 8. Oracle 同步协议状态

当 validator 开始运行后，其余额和状态变化发生在 Consensus Layer (Beacon Chain) ，这些状态不会自动同步到 Lido 合约，需要通过 Oracle 报告更新。Lido 通过 `AccountingOracle` 周期性提交报告，更新协议的关键状态。

Oracle 报告包含以下信息：

- **CL balance**  
    所有 Lido validators 在 Beacon Chain 上的总余额。
    
- **CL validators**  
    当前 validator 数量以及 exited validator 数量。
    
- **Withdrawal vault balance**  
    执行层 withdrawal vault 中可领取的 ETH。
    
- **Execution layer rewards**  
    来自 MEV 和 priority fees 的执行层奖励。
    
- **Withdrawal finalization**  
    Oracle 会根据报告数据 finalize withdrawal requests，并计算需要销毁的 stETH shares。
    
- **Share burn**  
    处理 withdrawal，需要销毁的 shares。
    
- **Protocol fee 分配**  
    Oracle 计算 validator 收益后，会分配 protocol fee：
    
    - staking module fee
    - treasury fee
    
- **stETH rebase**  
    在 accounting 完成后，Lido 更新：
    
    - `totalPooledEther`
    - `totalShares`
    
    从而触发 **stETH 的 rebase**，用户持有的 stETH 数量会自动增加。


---
## 9. Rewards 计算与分配

在 Oracle 报告过程中，协议会计算 validator 收益。`StakingRouter` 合约负责计算各 staking module 的 reward 分配比例：`getStakingRewardsDistribution()`

计算依据：

- module `activeValidatorsCount`
- module `stakingModuleFee`
- module `treasuryFee`

Router 会返回：

- rewards recipient
- module fee
- treasury fee


---
## 10. Protocol fee shares mint

Oracle 计算 protocol fee 后，`Lido` 会 mint stETH shares，分配给 staking modules 和 treasury。


---
## 11. Router 通知 module rewards

在 rewards mint 完成后，Oracle 调用：

- `StakingRouter.reportRewardsMinted()`
	 ↓     *Router 逐个调用 module，通知 module 更新其内部 accounting*
- `module.onRewardsMinted()`


---
## 12. stETH rebase

Oracle accounting 完成后，Lido 更新 `totalPooledEther` 和 `totalShares`，从而触发 stETH rebase；用户钱包中的 `stETH` 数量会自动增加。


---
## Summary

```Solidity
用户调用 Lido.submit()
    -> 用户马上拿到 stETH
    -> ETH 进入 Lido buffer

Later:

    -> Router.getDepositsAllocation()
    -> DSM 触发 Lido.deposit()
    -> Lido 调用 StakingRouter.deposit()
    -> Router 获取 validator keys
    -> Router 执行 Beacon deposit

Validator running...

Oracle report
    -> AccountingOracle.report()

    -> Lido.handleOracleReport()
        -> update CL balance
        -> update validator state
        -> process withdrawals
        -> calculate rewards

	-> Router.getStakingRewardsDistribution()
        -> mint protocol fee shares
	-> Router.reportRewardsMinted()
        -> stETH rebase
```