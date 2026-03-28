---
slug: /
---

## Overview

`Lido` is an Ethereum staking protocol that combines "instant liquidity certificates" and "asynchronous underlying pledge settlement". After the user submits ETH, the protocol will immediately mint `stETH` as the equity certificate, allowing the user to maintain on-chain liquidity while the funds have entered the pledge system; and the underlying validator creation, operation, reward accumulation, exit triggering and withdrawal return are completed through the Router, StakingModule, Oracle, Vault and WithdrawalQueue modules. The entire system is not completed synchronously by a single user operation, but relies on Oracle to periodically synchronize the status of Consensus Layer and Execution Layer back to the chain, and then uniformly complete rebase, reward distribution, exit result confirmation and withdrawal settlement.

> *Refer to the official repo version: https://github.com/lidofinance/core/tree/v2.2.0*

![Lido Architecture](/img/diagrams/lido_architecture.png)

  
## 1. Four core links

The Lido protocol can be broken down into four core links, which cooperate with each other but are not executed in the same transaction.

### 1.1 Deposit (pledge link)

```
user
	-> Lido.submit()
	-> mint stETH
-> ETH enters buffer

Follow-up:
-> StakingRouter allocates deposit
-> StakingModule provides validator keys
-> Beacon DepositContract completes the pledge
```

Features:

- Users get stETH immediately
- ETH will not enter CL immediately, but will be deposited in batches by DSM after entering the buffer.

<br />

### 1.2 Validator Lifecycle (validator life cycle)

```
StakingRouter
-> Manage StakingModule
->Manage NodeOperator
->Manage Validator

Life cycle: Create → Deposit → Active → Exit Triggered → Exited → Withdrawn
```

Features:

- Router only manages state and does not run validator
- validator actually runs in Consensus Layer

<br />

### 1.3 Oracle (state synchronization link)

```
HashConsensus
	-> BaseOracle
    -> AccountingOracle
```

Execution content:

```
- Synchronize CL balance
- Update the number of validators
- Synchronize exited validators
- Handle withdrawal finalization
- Collect vault ETH
- Calculate rewards / fees
- Execute stETH rebase
```

Features:

- Periodic execution (frame)
- Drives entire protocol status updates
- It is the “settlement engine” of the system

<br />

### 1.4 Withdrawal (withdrawal link)

```
user
	-> requestWithdrawals()
	-> mint unstETH NFT

wait:
	-> Oracle finalize

user
	-> claimWithdrawal()
```

Features:

- FIFO queue
- request / finalize / claim three stages
- Withdrawal process is completely asynchronous

<br />
<br />
  
## 2. Division of core modules

Lido splits different responsibilities into different contracts through modular design:

  
#### **Lido**

- User portal
- mint/burn stETH
- Manage buffer
- as a settlement center

  
#### **StakingRouter**

- Managing the StakingModule lifecycle
- Determine deposit allocation
- Aggregate validator status

  
#### **StakingModule**

- Management node operator
- Manage validator keys
- Provide deposit data

  
#### **AccountingOracle**

- Sync protocol status
- Process rewards/fees
- trigger rebase
- finalize withdrawal

  

#### **ValidatorsExitBusOracle**

- Decide which validators need to exit
- emit exit request
- Trigger Beacon Chain exit

  

#### **WithdrawalQueue**

- Log withdrawal request
- mint unstETH NFT
- Manage finalize/claim

  

#### **Vault(ExecutionLayer/Withdrawal)**

- Receive EL rewards
- Receive CL withdrawal ETH
- Reflow to Lido in Oracle

<br />
<br />
  
## 3. Key design ideas

### 3.1 Oracle driver (non-user driver)

```
User operation ≠ immediate execution result
```

- User deposits will not be completed immediately CL deposit
- Users who withdraw money will not receive ETH immediately
- All critical status updates are performed by Oracle periodically

<br />

### 3.2 Strong decoupling (core architecture design)

Lido splits the system into three independent links:

```
1. User link (deposit / withdrawal request)
2. exit link (ValidatorsExitBusOracle)
3. accounting link (AccountingOracle)
```

Their relationship:

```
request ≠ exit
exit ≠ arrival
Arrival ≠ claim
```

<br />

### 3.3 Asynchronous settlement system

All operations are "done in stages":

- deposit：buffer → batch → CL
- withdrawal: request → finalize → claim
- exit: trigger → CL → withdrawal → vault

<br />

### 3.4 Layering + state machine design

```
HashConsensus -> BaseOracle -> Business Oracle
```

- Consensus layer (hash)
- State layer (processing)
- Business layer (execution logic)

Improved security + upgradeability

<br />
<br />
  
## 4. Reading path (recommended order)

In order to fully understand the Lido protocol, it is recommended to read in the following order:

```
1. This article: Overview of the Lido protocol (global map)

2. Pledge process
-> Understand how ETH enters CL

3. StakingRouter / Module life cycle
-> Understand the validator management structure

4. Overview of Oracle Mechanism
-> Understand how the system is driven

5. AccountingOracle
-> Understand status synchronization and settlement

6. WithdrawalQueue
-> Understand the withdrawal process

7. ValidatorsExitBusOracle
-> Understand validator exit trigger

8. fee allocation mechanism -> understand the economic model
```
