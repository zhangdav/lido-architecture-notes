## 03 Oracle System

Lido's Oracle system is essentially a **layered, decoupled state-synchronization and execution system** composed of three core component layers:

```
HashConsensus -> BaseOracle -> Specific Oracle (Accounting/ExitBus)
```

where:

- `HashConsensus`: Responsible for reaching consensus on report hash
- `BaseOracle`: Responsible for managing the processing state machine
- Various Oracles: Responsible for specific business execution

In Lido, Oracle is not a single module. It is split into two core flows:

> 🔥 **AccountingOracle (status synchronization) + ValidatorsExitBusOracle (exit trigger)**

<br />
<br />

## 1. Oracle layered architecture

### 1.1 `HashConsensus`: Only Select the Hash

Responsibilities:

- Manage oracle committee members
- Manage frame/refSlot/deadline
- Collect report hash submitted by member
- Reach quorum consensus

Features:

```
Only processes hash, not business data
```

<br />

### 1.2 BaseOracle: Processing State Machine

Responsibilities:

- Receive consensus `(hash, refSlot)`
- Stores the reports that can currently be processed
- Controlling the processing lifecycle:
    - Is it possible to start processing
    - Has it been processed
    - Whether to lock the current frame

Features:

```
Only manage "when to process" and don't care about "what to process"
```

<br />

### 1.3 Business Oracle: Execute the Real Logic

On top of BaseOracle, Lido implements two types of Oracle:

#### ✅ AccountingOracle (status synchronization)

Responsible:

- Synchronize CL balance / validators
- Synchronize module exited validators (summary + detail)
- Handling withdrawal finalization
- Collect vault ETH (EL rewards + withdrawals)
- Calculate rewards / fees and distribute
- Execute stETH rebase

nature:

```
A "state machine + settlement engine"
```

#### ✅ ValidatorsExitBusOracle (exit trigger)

Responsible:

- Decide which validators should exit
- emit exit request
- Call Gateway to trigger CL exit

nature:

```
an "execution trigger"
```

<br />
<br />

## 2. Two Primary Oracle Flows

There are two **completely independent links** in the actual operation of Lido Oracle:

### 2.1 AccountingOracle (status-synchronization flow)

```text
HashConsensus
	↓
BaseOracle
	↓
AccountingOracle.submitReportData
	↓
Lido.handleOracleReport
	↓
Update status:
  - CL balance
  - validators
  - exited validators
  - withdrawal finalization
  - rewards / fee - rebase
```

Features:

- Periodic execution (every frame)
- Drive the entire protocol ledger update
- Does not trigger validator exit

<br />

### 2.2 ValidatorsExitBusOracle (exit-trigger flow)

```text
HashConsensus / or Bus path
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

Features:

- Responsible for "letting validator exit"
- Does not handle fund settlement
- Lido accounting not updated

<br />
<br />

## 3. Withdrawal and Oracle

This is often misunderstood:

> ❗ **User withdrawal ≠ trigger validator exit**

The correct relationship is as follows:

### 3.1 The Role of WithdrawalQueue

```
requestWithdrawals()
-> Log request
    -> mint unstETH NFT
```

Just express needs without any execution

<br />

### 3.2 Exit Is Triggered by ExitBusOracle

```
ValidatorsExitBusOracle
-> Determine which validators exit
```

Decoupled from user requests

<br />

### 3.3 ETH Reflow Synchronized by Oracle

```
CL withdrawal
	↓
WithdrawalVault
	↓
AccountingOracle report
	↓
Lido buffer update
```

<br />

### 3.4 Finalize + Claim

```
AccountingOracle
	-> finalize withdrawal

user
	-> claimWithdrawal()
```

Full link:

```
user request
	↓
(wait)
	↓
ExitBus triggers validator exit
	↓
CL execution withdrawal
	↓
ETH to WithdrawalVault
	↓
AccountingOracle finalize
	↓
user claim
```

<br />
<br />

## 4. Decoupled Design

The key to Lido Oracle's design is the complete decoupling of the three links.

```
1. User link (request/claim)
2. exit link (ExitBusOracle)
3. accounting link (AccountingOracle)

User request ≠ immediately
exit exit ≠ Deposit immediately
Receipt ≠ claim immediately
```

Oracle is "cycle-driven", not "user-driven". Oracle's execution of each frame is not triggered by the user. Lido is a "pull-based + oracle-driven system", not a synchronous execution system.

Overall calling relationship:

```
user
	-> submit / requestWithdrawals

Oracle (periodic operation)
-> AccountingOracle (synchronization status)
-> ExitBusOracle (trigger exit)

System execution
	-> CL exit
-> ETH flows back to the vault

Oracle
	-> finalize withdrawal

user
	-> claimWithdrawal
```

<br />
<br />

### Summary

```
1. Oracle is divided into three layers:
HashConsensus -> BaseOracle -> Business Oracle

2. Two core links:
- AccountingOracle: status synchronization + settlement
- ExitBusOracle: trigger validator exit

3. Withdrawal is an independent system:
   request ≠ exit ≠ finalize ≠ claim

4. All processes are driven by Oracle cycles, not user triggered

5. Core design ideas:
Decoupling + layering + asynchronous execution
```
