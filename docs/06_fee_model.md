## 概述

Lido 对质押收益收取协议费，不是从用户存入的本金直接收费。而是对 staking rewards 收取的协议费，这部分费用在 node operators 和 staking modules，以及 DAO treasury 之间分配。该费率可由 Lido DAO 通过治理修改。

> [!NOTE]
> 协议费通常表现为对 staking rewards 抽取的一部分费用；在 Router 侧，最终总费率取决于各模块的 `module fee`、`treasury fee` 以及它们的 `active validators` 权重加总。当前治理配置常见为 10%，但从机制上看，Router 聚合结果不是代码里硬编码死的常数。

这意味，用户获得的是扣除协议费之后的净质押收益；协议费会通过 增发 shares / stETH 的方式分配给相关方。

<br>

- 模块费 module fee

	分给 staking module 的费用，用于补偿模块及其节点运营者提供验证者运行、基础设施维护、运维管理等服务。

- 国库费 treasury fee

	分给 Lido DAO Treasury 的费用，用于协议层面的治理、开发、风控、应急和其他 DAO 支出。

所以，单个模块的收费组成是：该模块的总费率 = 模块费 + 国库费。

<br>

## 计算公式

按模块 active validators 占比 × 该模块设置的 fee rate 来计算

1. 模块在协议中的验证者权重

	模块验证者占比 = 模块 active validators / 全协议 active validators

2. 模块实际拿到的模块费

	模块最终获得的 rewards 份额  = 模块验证者占比 × module fee

3. 模块分给 Treasury 的份额

	该模块对应的 Treasury 份额  = 模块验证者占比 × treasury fee

4. 汇总总协议费

	totalFee  = 所有模块 (module fee 份额 + treasury fee 份额) 之和

```solidity
uint256 stakingModuleValidatorsShare =
    (stakingModulesCache[i].activeValidatorsCount * precisionPoints) / totalActiveValidators;

address recipient =
    address(stakingModulesCache[i].stakingModuleAddress);

uint96 stakingModuleFee =
    uint96((stakingModuleValidatorsShare * stakingModulesCache[i].stakingModuleFee) / TOTAL_BASIS_POINTS);

if (stakingModulesCache[i].status != StakingModuleStatus.Stopped) {
    stakingModuleFees[rewardedStakingModulesCount] = stakingModuleFee;
}

totalFee +=
    uint96((stakingModuleValidatorsShare * stakingModulesCache[i].treasuryFee) / TOTAL_BASIS_POINTS)
    + stakingModuleFee;
```

<br>

> 举个例子 🌰
>
> 假设全协议共有 1000 个 active validators，其中：
>
> 模块 A：500 个 active validators，占 50%
>
> 模块 B：300 个 active validators，占 30%
>
> 模块 C：200 个 active validators，占 20%

> [!NOTE]
> 1. 若模块 `activeValidatorsCount = 0`，则该模块不会获得 module fee，也不会对本轮总 fee 分布产生模块收入部分贡献。
>
> 2. Stopped 模块不会拿到自己的 module fee，但它对应那部分 fee 仍会计入 `totalFee`。

> 再假设：
>
> A 的 module fee = 8%，treasury fee = 2%
>
> B 的 module fee = 6%，treasury fee = 3%
>
> C 的 module fee = 10%，treasury fee = 2%
>
> 那么：
>
> 模块 A
>
> 模块收入 = 50% × 8% = **4%**
> Treasury 收入 = 50% × 2% = **1%**
>
> 模块 B
>
> 模块收入 = 30% × 6% = **1.8%**
> Treasury 收入 = 30% × 3% = **0.9%**
>
> 模块 C
>
> 模块收入 = 20% × 10% = **2%**
> Treasury 收入 = 20% × 2% = **0.4%**

最后总协议费为： 4% + 1% + 1.8% + 0.9% + 2% + 0.4% = 10.1%

<br>
<br>

## `activeValidators` 与 `exitedValidators` 同步机制

前面的例子中提到，在 Router 计算手续费分配时，模块的权重取决于其 `activeValidators` 数量。

`模块权重 = activeValidators / totalActiveValidators`

```solidity
activeValidators =
    totalDepositedValidators
    - max(moduleSummaryExited, routerExited)
```

这里的 `exitedValidators` 不是单一来源，而是依赖的是 `Router`/ `Module exited` 数同步完成后的状态，因此它与 `AccountingOracle` 的 exited validators 上报链是耦合的，但与 `ExitBus` 的触发本身不是同一条同步链。`exitedValidators` 同步流程如下：

```
Oracle 报告模块 exited 数量
从共识层统计 validator 状态后，报告某个模块的退出数量
  ↓
Router 更新模块级 exited 总账
 1.校验 exited 数量不能减少
 2.校验 exited 数量不能超过 deposited
 3.更新
  ↓
Module 更新 node operator exited 明细
Router 会：
  a. 校验编码格式
  b. 将退出信息转发给模块
  ↓
模块内部会：
  c. 更新每个 node operator 的 exited validators
  d. 重新汇总模块 exited 数量
  ↓
Finish hook 确认模块汇总状态一致
  1.遍历所有模块
  2.读取模块 summary 中的 exitedValidators
  3.与 Router 记录的 exitedValidators 对比
  ↓
确认同步 moduleSummaryExited == routerExited
 Router exited 总账
 Module exited 明细
 已经同步完成
  ↓
Router / Lido 后续逻辑读取最终状态
```

最终模块权重依赖于 active validators，这个值的计算与上述流程的 `routerExited`, `moduleSummaryExited` 同步结果有关。

<br>

> 举个例子🌰
>
> 假设两个模块：
>
> `Module A deposited = 1000`
> `Module B deposited = 1000`
>
> 初始：
>
> `A active = 1000`
> `B active = 1000`
> `权重 = 50% / 50%`
>
> 如果 Oracle 报告：
>
> `routerExited = 200`
> `moduleSummaryExited = 150`
>
> Router 计算 active validators 时使用：
>
> `active = deposited - max(routerExited, moduleSummaryExited)`
>
> 得到：
>
> `A active = 800`
> `B active = 1000`
>
> 新的手续费权重：
>
> `A = 800 / 1800`
> `B = 1000 / 1800`
>
> 因此在下一轮 rewards fee 分配中：Module A 的手续费权重会下降，Module B 的手续费权重会相对提高。

总结，所以`exitedValidators` 的同步机制会通过改变 `activeValidators` 的数量，最终影响：rewards fee 在模块之间的分配比例和treasury 收入来源结构。

<br>
<br>

*核心同步接口：*

1. Module 级总数更新

```solidity
updateExitedValidatorsCountByStakingModule(
	uint256[] calldata _stakingModuleIds,
	uint256[] calldata _exitedValidatorsCounts
)
```

<br>

2. nodeOperator 级更新

```solidity
reportStakingModuleExitedValidatorsCountByNodeOperator(
	uint256 _stakingModuleId,
	bytes calldata _nodeOperatorIds,
	bytes calldata _exitedValidatorsCounts
)
```

<br>

3. 所有 node operator 上报完成后的 finish

```solidity
onValidatorsCountsByNodeOperatorReportingFinished()
```

<br>

4. Module 收尾 hook

```solidity
module.onExitedAndStuckValidatorsCountsUpdated()
```

<br>

5. 紧急修正

```solidity
unsafeSetExitedValidatorsCount(...)
```

<br>

## 调用关系

```text
Oracle submit report
  ↓
Lido.handleOracleReport
  ↓
计算 _totalRewards
  ↓
Lido._distributeFee
  ↓
StakingRouter.getStakingRewardsDistribution
  ↓
得到 modulesFees / totalFee
  ↓
计算 sharesMintedAsFees
  ↓
_mintShares(address(this), sharesMintedAsFees)
  ↓
_transferModuleRewards
  ↓
_transferTreasuryRewards
  ↓
router.reportRewardsMinted

```
> [!NOTE]
> router.reportRewardsMinted 不参与本轮费率计算，而是在分配完成后，把每个模块对应的 totalShares` 同步通知给模块，用于模块内部记账或后续处理。

在 Lido 合约中调用 `handleOracleReport` 函数，执行到 step 7. `_processRewards` 内部调用 router 合约调用 `getStakingRewardsDistribution` 根据当前 staking modules 状态计算并返回本轮 `modulesFees`、`totalFee` 和 `precisionPoints`，返回的关键数据如：

<br>

```text
modulesFees = [4%, 2%, 3%]
treasuryFee = 1%
totalFee = 10%
```

随后用于 fee shares 的 mint 和分配，计算 mint shares 的步骤如下：

<br>

*Step 1 定义初始状态*

- 产生奖励前 Lido 合约中的总 ETH：preTotalPooledEther = E

- 产生奖励前 Lido 合约中的总 Share：preTotalShares = S

- 本轮产生的：totalRewards = R

*Step 2 更新奖励后的 ETH 数量*

- Oracle 报告奖励后，协议总 ETH 变为：newTotalPooledEther = E + R

*Step 3 计算协议应收的 fee*

- 协议 fee 比例：f = totalFee / precisionPoints

*Step 4 计算 mint 后 share 价格*

- 设：sharesMintedAsFees = x

- mint shares 后：totalShares = S + x

- 本轮产生的：totalRewards = R

- share price 为：sharePrice = (E + R) / (S + x)

- protocol 新 mint 的 shares 价值为：value = x * sharePrice

- 代入 sharePrice：value = x * (E + R) / (S + x)

- 得到公式：
$$
x = \frac{R f S}{E + R - R f}
$$

- $E$：preTotalPooledEther
- $S$：preTotalShares
- $R$：totalRewards
- $f$：fee ratio
- $x$：sharesMintedAsFees

协议希望新 mint 出来的 shares 的价值，恰好等于协议应收的 fee ETH。协议不会直接把 rewards ETH 从池子里扣走，而是通过 mint 新 shares 的方式，把“等值于协议费”的权益稀释并分配给模块和 treasury。

```solidity
uint256 totalPooledEtherWithRewards = _preTotalPooledEther.add(_totalRewards);

sharesMintedAsFees =
    _totalRewards.mul(rewardsDistribution.totalFee).mul(_preTotalShares).div(
        totalPooledEtherWithRewards.mul(
            rewardsDistribution.precisionPoints
        ).sub(_totalRewards.mul(rewardsDistribution.totalFee))
    );
```