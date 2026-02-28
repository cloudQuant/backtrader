- --

name: 'step-04-evaluate-and-score'
description: 'Orchestrate parallel NFR domain assessments (4 subprocesses)'
nextStepFile: './step-04e-aggregate-nfr.md'

- --

# Step 4: Orchestrate Parallel NFR Assessment

## STEP GOAL

Launch 4 parallel subprocesses to assess independent NFR domains simultaneously for maximum performance.

## MANDATORY EXECUTION RULES

- 📖 Read the entire step file before acting
- ✅ Speak in `{communication_language}`
- ✅ Launch FOUR subprocesses in PARALLEL
- ✅ Wait for ALL subprocesses to complete
- ❌ Do NOT assess NFRs sequentially (use subprocesses)

- --

## EXECUTION PROTOCOLS:

- 🎯 Follow the MANDATORY SEQUENCE exactly
- 💾 Wait for subprocess outputs
- 📖 Load the next step only when instructed

- --

## MANDATORY SEQUENCE

### 1. Prepare Subprocess Inputs

- *Generate unique timestamp:**

```javascript
const timestamp = new Date().toISOString().replace(/[:.]/g, '-');

```bash

- *Prepare context:**

```javascript
const subprocessContext = {
  system_context: /*from Step 1*/,
  nfr_thresholds: /*from Step 2*/,
  evidence_gathered: /*from Step 3*/,
  timestamp: timestamp
};

```bash

- --

### 2. Launch 4 Parallel NFR Subprocesses

- *Subprocess A: Security Assessment**

- File: `./step-04a-subprocess-security.md`
- Output: `/tmp/tea-nfr-security-${timestamp}.json`
- Status: Running... ⟳

- *Subprocess B: Performance Assessment**

- File: `./step-04b-subprocess-performance.md`
- Output: `/tmp/tea-nfr-performance-${timestamp}.json`
- Status: Running... ⟳

- *Subprocess C: Reliability Assessment**

- File: `./step-04c-subprocess-reliability.md`
- Output: `/tmp/tea-nfr-reliability-${timestamp}.json`
- Status: Running... ⟳

- *Subprocess D: Scalability Assessment**

- File: `./step-04d-subprocess-scalability.md`
- Output: `/tmp/tea-nfr-scalability-${timestamp}.json`
- Status: Running... ⟳

- --

### 3. Wait for All Subprocesses

```bash
⏳ Waiting for 4 NFR subprocesses to complete...
  ├── Subprocess A (Security): Running... ⟳
  ├── Subprocess B (Performance): Running... ⟳
  ├── Subprocess C (Reliability): Running... ⟳
  └── Subprocess D (Scalability): Running... ⟳

[... time passes ...]

✅ All 4 NFR subprocesses completed!

```bash

- --

### 4. Performance Report

```bash
🚀 Performance Report:

- Execution Mode: PARALLEL (4 NFR domains)
- Total Elapsed: ~max(all subprocesses) minutes
- Sequential Would Take: ~sum(all subprocesses) minutes
- Performance Gain: ~67% faster!

```bash

- --

### 5. Proceed to Aggregation

Load next step: `{nextStepFile}`

The aggregation step will:

- Read all 4 NFR domain outputs
- Calculate overall risk level
- Aggregate compliance status
- Identify cross-domain risks
- Generate executive summary

- --

## EXIT CONDITION

Proceed when all 4 subprocesses completed and outputs exist.

- --

## 🚨 SYSTEM SUCCESS METRICS

### ✅ SUCCESS:

- All 4 NFR subprocesses completed
- Parallel execution achieved ~67% performance gain

### ❌ FAILURE:

- One or more subprocesses failed
- Sequential assessment instead of parallel
