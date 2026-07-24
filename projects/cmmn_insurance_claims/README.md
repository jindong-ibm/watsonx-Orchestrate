# CMMN Insurance Claims — watsonx Orchestrate

A production-grade implementation of **Case Management Model and Notation (CMMN)**
for insurance claims processing, built with IBM watsonx Orchestrate ADK.

---

## Overview

CMMN models processes where the sequence of tasks is **not fixed in advance**.
Unlike BPMN (where the flow is prescribed), CMMN gives knowledge workers the
power to activate tasks based on judgment, incoming evidence, and sentry conditions.

| CMMN Concept | Insurance Claims Mapping |
|---|---|
| **Case** | An insurance claim instance — uniquely identified, opened until resolved |
| **Stage** | Logical grouping: INTAKE → ASSESSMENT → INVESTIGATION → DECISION → CLOSURE |
| **Task** | A unit of work: AUTOMATED, HUMAN, or DISCRETIONARY |
| **Sentry** | Entry/exit guard: "fraud score ≥ 0.65 → open INVESTIGATION stage" |
| **Milestone** | Named checkpoint: M1 Claim Registered … M6 Case Closed |
| **Discretionary** | Optional task the case worker may invoke based on judgment |

---

## CMMN vs BPMN vs MDP — Key Differences

| Dimension | BPMN | CMMN | MDP |
|---|---|---|---|
| **Flow type** | Prescribed sequence | Judgment-driven, emergent | Policy-driven, optimised |
| **Who controls next step** | The process model | The knowledge worker | The learned policy π(s) |
| **Branching mechanism** | Gateways (XOR/AND) | Sentry conditions | State-action value function Q |
| **Best for** | Repeatable, structured processes | Complex, unpredictable cases | Optimisation under uncertainty |
| **Example** | Invoice processing | Insurance claim, medical treatment | Patient monitoring, risk pricing |

---

## Architecture Diagram

```mermaid
graph TB
    User(["👤 Claims Staff"])

    subgraph WxO["watsonx Orchestrate"]
        Coord["🎯 CMMN Claims Coordinator\n(Coordinator Agent)"]

        subgraph Agents["Specialist Agents"]
            Worker["📋 CMMN Case Worker\n(Intake + Assessment + Decision)"]
            Super["🔍 Claims Supervisor\n(Reserve + Fraud + SLA)"]
        end

        subgraph Flow["CMMN Claims Flow  (Agentic Workflow)"]
            IntakeN["📥 process_case_intake\nINTAKE stage"]
            SentryN{"🔀 evaluate_sentries\ncoverage confirmed?"}
            AssessN["🔬 run_damage_assessment\nASSESSMENT + FRAUD_SCREENING"]
            FraudN{"⚠️ Branch\nfraud score high?"}
            SentryInv["🔎 evaluate_sentries\n(INVESTIGATION open)"]
            SentryDec["✅ evaluate_sentries\n(pre-DECISION)"]
            DecN["⚖️ make_settlement_decision\nDECISION stage"]
            CloseN["📁 close_case\nCLOSURE + M6"]
            DenyN["🚫 close_case (DENIED)\nCoverage not confirmed"]
        end

        subgraph Tools["Python Tools"]
            T1["cmmn_case_intake"]
            T2["cmmn_sentry_evaluator"]
            T3["cmmn_assessment"]
            T4["cmmn_settlement_decision"]
            T5["cmmn_case_closer"]
        end

        subgraph Config["Config Layer (no redeploy)"]
            C1["cmmn_config.yaml\nStages · Tasks · Sentries\nOwner: Engineering"]
            C2["case_plan_table.csv\nThresholds · Limits · SLA\nOwner: Business Analysts"]
        end
    end

    User -->|"Claim details"| Coord
    Coord --> Worker
    Coord --> Super
    Worker -->|"Invoke flow"| Flow

    IntakeN --> T1
    AssessN --> T3
    SentryN --> T2
    SentryInv --> T2
    SentryDec --> T2
    DecN --> T4
    CloseN --> T5
    DenyN --> T5

    T1 -.->|reads| C1
    T1 -.->|reads| C2
    T2 -.->|reads| C1
    T2 -.->|reads| C2
    T3 -.->|reads| C2
    T4 -.->|reads| C2
    T5 -.->|reads| C1

    style WxO fill:#f0f4ff,stroke:#3b82d4
    style Flow fill:#e8f5e9,stroke:#43a047
    style Agents fill:#fff3e0,stroke:#fb8c00
    style Tools fill:#fce4ec,stroke:#e91e63
    style Config fill:#f3e5f5,stroke:#7b1fa2
    style Coord fill:#e3f2fd,stroke:#1565c0
    style Worker fill:#fff9c4,stroke:#f9a825
    style Super fill:#fff9c4,stroke:#f9a825
```

---

## Workflow Diagram

```mermaid
flowchart TD
    A([START: Claim submitted]) --> B

    subgraph INTAKE["Stage 1 — INTAKE  (auto-activating)"]
        B["REGISTER_CLAIM\nAssign claim ID · Open case record\n🏁 Milestone M1"]
        B --> C["VERIFY_COVERAGE\nCheck policy dates · Covered perils\n🏁 Milestone M2"]
        C --> D["TRIAGE_SEVERITY\nLOW / MEDIUM / HIGH / CRITICAL\nfrom case_plan_table.csv"]
    end

    D --> E{"Coverage\nconfirmed?"}
    E -->|"LAPSED or\nNOT_COVERED"| F1

    subgraph DENY["Immediate Denial"]
        F1["CLOSE_CLAIM\nDisposition: DENIED\nReason: coverage gap\n🏁 Milestone M6"]
    end

    E -->|"CONFIRMED"| G

    subgraph ASSESSMENT["Stage 2 — ASSESSMENT"]
        G["COLLECT_DOCUMENTS\n🧑 Human task\nChecklist validated against claim type"]
        G --> H["ESTIMATE_DAMAGE\nDamage × reserve_multiplier\nfrom case_plan_table.csv\n🏁 Milestone M3"]
        H --> I["FRAUD_SCREENING\nWeighted signal scoring\nfraud_score 0.0 – 1.0"]
    end

    I --> J{"fraud_score\n≥ threshold?"}
    J -->|"YES\n(sentry fired)"| K

    subgraph INVESTIGATION["Stage 3 — INVESTIGATION  (Discretionary)"]
        K["evaluate_sentries\nINVESTIGATION stage open\nCase worker activates SIU_REFERRAL\nand/or LIABILITY_REVIEW\n🏁 Milestone M4"]
    end

    J -->|"NO"| L

    subgraph PRE_DECISION["Sentry Re-evaluation"]
        L["evaluate_sentries\nConfirm DECISION stage available\nCheck SLA status"]
    end

    K --> M
    L --> M

    subgraph DECISION["Stage 4 — DECISION"]
        M["RESERVE_APPROVAL\nAuto-approve if ≤ auto_approve_limit\nOtherwise manager sign-off"]
        M --> N["SETTLEMENT_OFFER\nGenerate offer letter + amount"]
        N --> O{"Claimant\ncountered?"}
        O -->|"YES (Discretionary)"| P["NEGOTIATE_SETTLEMENT\nCase worker activates this task"]
        O -->|"NO"| Q
        P --> Q
        Q["Decision: APPROVED / DENIED / NEGOTIATING\n🏁 Milestone M5"]
    end

    Q --> R

    subgraph CLOSURE["Stage 5 — CLOSURE"]
        R["CLOSE_CLAIM\nFinalise payment · Archive · Notify\n🏁 Milestone M6\nSLA outcome recorded"]
    end

    R --> S([END: Case closed])

    style INTAKE fill:#e3f2fd,stroke:#1976d2
    style ASSESSMENT fill:#e8f5e9,stroke:#388e3c
    style INVESTIGATION fill:#fff3e0,stroke:#f57c00
    style DECISION fill:#f3e5f5,stroke:#7b1fa2
    style CLOSURE fill:#fce4ec,stroke:#c62828
    style DENY fill:#ffebee,stroke:#b71c1c
    style PRE_DECISION fill:#f5f5f5,stroke:#9e9e9e
```

---

## CMMN Sentry Conditions

Sentries are the heart of CMMN — they guard task and stage activation:

| Sentry | Guards | Condition |
|---|---|---|
| Coverage confirmed | ASSESSMENT stage entry | `coverage_status == CONFIRMED` |
| Documents complete | ESTIMATE_DAMAGE entry | `COLLECT_DOCUMENTS completed` |
| Fraud score high | INVESTIGATION stage activation | `fraud_score ≥ fraud_score_flag (CSV)` |
| SIU referral | SIU_REFERRAL task entry | `fraud_score ≥ 0.65` |
| Counter-offer | NEGOTIATE_SETTLEMENT entry | `claimant_counter_offered == true` |
| Reserve approved | SETTLEMENT_OFFER entry | `reserve_approved == true` |
| Auto-approve | Bypass RESERVE_APPROVAL | `damage ≤ auto_approve_limit (CSV)` |

---

## Project Structure

```
cmmn_insurance_claims/
├── __init__.py
├── main_flow.py                              # 4-scenario local test harness
├── import-all.sh                             # one-command deploy
│
├── config/                                   # ← no code deploy to tune
│   ├── cmmn_config.yaml                      # Stages, tasks, sentries, milestones
│   │                                         # Owner: Engineering / Business Analysts
│   └── case_plan_table.csv                   # Thresholds, SLA %, reserve multiplier
│                                             # Owner: Claims Operations
│
├── tools/
│   ├── __init__.py
│   ├── config_loader.py                      # Shared YAML+CSV loader (lru_cache)
│   ├── cmmn_case_intake.py                   # INTAKE stage (3 automated tasks)
│   ├── cmmn_sentry_evaluator.py              # Sentry engine: available/blocked/discretionary
│   ├── cmmn_assessment.py                    # ASSESSMENT + FRAUD_SCREENING tasks
│   ├── cmmn_settlement_decision.py           # DECISION stage (auto-approve, negotiate)
│   ├── cmmn_case_closer.py                   # CLOSURE + milestone timeline
│   └── cmmn_claims_flow.py                   # @flow orchestration with branch nodes
│
├── agents/
│   ├── cmmn_case_worker_agent.yaml           # Primary: invokes CMMN flow
│   ├── cmmn_claims_supervisor_agent.yaml     # Reserve/fraud/SLA oversight
│   └── cmmn_claims_coordinator.yaml          # Coordinator + collaborators
│
└── generated/
    └── cmmn_insurance_claims_flow.json       # Compiled flow spec (auto-generated)
```

---

## Milestone Lifecycle

| Milestone | Triggered When | CMMN Role |
|---|---|---|
| M1 Claim Registered | REGISTER_CLAIM completes | Case opened — irrevocable |
| M2 Coverage Confirmed | VERIFY_COVERAGE confirms coverage | Unlocks ASSESSMENT stage |
| M3 Assessment Complete | ESTIMATE_DAMAGE completes | Unlocks DECISION stage |
| M4 Investigation Required | Fraud score ≥ threshold | Signals discretionary stage needed |
| M5 Decision Made | SETTLEMENT_OFFER or denial | Unlocks CLOSURE stage |
| M6 Case Closed | CLOSE_CLAIM completes | Terminal — case archived |

---

## Configuration Ownership

| File | What it controls | Who changes it |
|---|---|---|
| `config/cmmn_config.yaml` | Stage definitions, task types, sentry_in conditions, milestone triggers | Engineering + Business Analysts via PR |
| `config/case_plan_table.csv` | Severity thresholds, fraud cutoffs, auto-approve limits, SLA percentages, reserve multipliers | Claims Operations in Excel — no code deploy |

**The separation is intentional:** a claims ops manager can raise the fraud flag threshold from `0.65` to `0.70` for a specific claim type in one minute, without touching Python or redeploying the flow.

---

## Usage

### Deploy

```bash
cd cmmn_insurance_claims
./import-all.sh
```

### Local Tests (4 scenarios)

```bash
python cmmn_insurance_claims/main_flow.py
```

### Chat

```bash
orchestrate chat start --agent cmmn_claims_coordinator
```

**Example prompts:**

```
> Process a new AUTO claim for Alice Johnson, policy POL-2024-001,
  incident 2024-10-15, rear-end collision, damage $3,800.
  Documents: police report, photos, repair estimate, driver license.

> Bob Martinez filed a PROPERTY claim for $85,000. New policy, filed 2 months in.
  Weekend incident, inconsistent damage photos, multiple prior claims.
  What stage should this case be in?

> Carol Smith's MEDICAL claim — policy expired June 2024, incident July 2024.
  How should this be handled?

> David Chen's LIABILITY claim for $42,000 — he counter-offered at $48,000.
  What are the adjuster's options?
```

---

## Extending to Other Business Domains

The same CMMN architecture applies to any **knowledge-worker-driven case process**:

| Domain | Case | Discretionary Stages | Key Sentries |
|---|---|---|---|
| Healthcare | Patient treatment plan | Specialist referral, surgery | Diagnosis confirmed, lab results |
| Legal | Court case | Expert witness, appeal | Evidence admissible, precedent found |
| HR | Employee grievance | External mediator, tribunal | Escalation threshold, policy breach |
| Banking | Loan default | Debt restructuring, legal action | Payment missed, asset review done |
| Government | Permit application | Site inspection, public hearing | Objection filed, zoning check passed |

---

> ⚖️ **Disclaimer**: This system is a demonstration of CMMN architecture.
> All claim decisions require licensed adjuster review before execution.
> Do not use in production without regulatory and legal validation.
