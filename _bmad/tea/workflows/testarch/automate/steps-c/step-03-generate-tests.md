- --

name: 'step-03-generate-tests'
description: 'Orchestrate parallel test generation via subprocesses'
nextStepFile: './step-03c-aggregate.md'

- --

# Step 3: Orchestrate Parallel Test Generation

## STEP GOAL

Launch parallel subprocesses to generate tests simultaneously for maximum performance. Subprocess selection depends on `{detected_stack}`.

## MANDATORY EXECUTION RULES

- 📖 Read the entire step file before acting
- ✅ Speak in `{communication_language}`
- ✅ Launch subprocesses in PARALLEL based on `{detected_stack}`
- ✅ Wait for ALL launched subprocesses to complete
- ❌ Do NOT generate tests sequentially (use subprocesses)
- ❌ Do NOT proceed until all subprocesses finish

- --

## EXECUTION PROTOCOLS:

- 🎯 Follow the MANDATORY SEQUENCE exactly
- 💾 Wait for subprocess outputs
- 📖 Load the next step only when instructed

## CONTEXT BOUNDARIES:

- Available context: config, coverage plan from Step 2, knowledge fragments
- Focus: subprocess orchestration only
- Limits: do not generate tests directly (delegate to subprocesses)
- Dependencies: Step 2 outputs (coverage plan, target features)

- --

## MANDATORY SEQUENCE

- *CRITICAL:** Follow this sequence exactly. Do not skip, reorder, or improvise.

### 1. Prepare Subprocess Inputs

- *Generate unique timestamp** for temp file naming:

```javascript
const timestamp = new Date().toISOString().replace(/[:.]/g, '-');

```bash

- *Prepare input context for subprocesses:**

```javascript
const subprocessContext = {
  features: /*from Step 2 coverage plan*/,
  knowledge_fragments_loaded: /*list of fragments*/,
  config: {
    test_framework: config.test_framework,
    use_playwright_utils: config.tea_use_playwright_utils,
    browser_automation: config.tea_browser_automation,  // "auto" | "cli" | "mcp" | "none"

    detected_stack: '{detected_stack}'  // "frontend" | "backend" | "fullstack"

  },
  timestamp: timestamp
};

```bash

- --

### 2. Subprocess Dispatch Matrix

- *Select subprocesses based on `{detected_stack}`:**

| `{detected_stack}` | Subprocess A (API) | Subprocess B (E2E) | Subprocess B-backend |

| ------------------ | ------------------ | ------------------ | -------------------- |

| `frontend`         | Launch             | Launch             | Skip                 |

| `backend`          | Launch             | Skip               | Launch               |

| `fullstack`        | Launch             | Launch             | Launch               |

- --

### 3. Launch Subprocess A: API Test Generation (always)

- *Launch subprocess in parallel:**

- **Subprocess File:**`./step-03a-subprocess-api.md`
- **Output File:**`/tmp/tea-automate-api-tests-${timestamp}.json`
- **Context:**Pass `subprocessContext`
- **Execution:** PARALLEL (non-blocking)

- *System Action:**

```bash
🚀 Launching Subprocess A: API Test Generation
📝 Output: /tmp/tea-automate-api-tests-${timestamp}.json
⏳ Status: Running in parallel...

```bash

- --

### 4. Launch Subprocess B: E2E Test Generation (frontend/fullstack only)

- *If {detected_stack} is `frontend` or `fullstack`:**

- *Launch subprocess in parallel:**

- **Subprocess File:**`./step-03b-subprocess-e2e.md`
- **Output File:**`/tmp/tea-automate-e2e-tests-${timestamp}.json`
- **Context:**Pass `subprocessContext`
- **Execution:** PARALLEL (non-blocking)

- *System Action:**

```bash
🚀 Launching Subprocess B: E2E Test Generation
📝 Output: /tmp/tea-automate-e2e-tests-${timestamp}.json
⏳ Status: Running in parallel...

```bash

- *If {detected_stack} is `backend`:** Skip this subprocess.

- --

### 5. Launch Subprocess B-backend: Backend Test Generation (backend/fullstack only)

- *If {detected_stack} is `backend` or `fullstack`:**

- *Launch subprocess in parallel:**

- **Subprocess File:**`./step-03b-subprocess-backend.md`
- **Output File:**`/tmp/tea-automate-backend-tests-${timestamp}.json`
- **Context:**Pass `subprocessContext`
- **Execution:** PARALLEL (non-blocking)

- *System Action:**

```bash
🚀 Launching Subprocess B-backend: Backend Test Generation
📝 Output: /tmp/tea-automate-backend-tests-${timestamp}.json
⏳ Status: Running in parallel...

```bash

- *If {detected_stack} is `frontend`:** Skip this subprocess.

- --

### 6. Wait for All Subprocesses to Complete

- *Monitor subprocess execution based on `{detected_stack}`:**

```bash
⏳ Waiting for subprocesses to complete...
  ├── Subprocess A (API): Running... ⟳
  ├── Subprocess B (E2E): Running... ⟳       [if frontend/fullstack]
  └── Subprocess B-backend: Running... ⟳     [if backend/fullstack]

[... time passes ...]

  ├── Subprocess A (API): Complete ✅
  ├── Subprocess B (E2E): Complete ✅         [if frontend/fullstack]
  └── Subprocess B-backend: Complete ✅       [if backend/fullstack]

✅ All subprocesses completed successfully!

```bash

- *Verify outputs exist (based on `{detected_stack}`):**

```javascript
const apiOutputExists = fs.existsSync(`/tmp/tea-automate-api-tests-${timestamp}.json`);

// Check based on detected_stack
if (detected_stack === 'frontend' || detected_stack === 'fullstack') {

  const e2eOutputExists = fs.existsSync(`/tmp/tea-automate-e2e-tests-${timestamp}.json`);
  if (!e2eOutputExists) throw new Error('E2E subprocess output missing!');
}
if (detected_stack === 'backend' || detected_stack === 'fullstack') {

  const backendOutputExists = fs.existsSync(`/tmp/tea-automate-backend-tests-${timestamp}.json`);
  if (!backendOutputExists) throw new Error('Backend subprocess output missing!');
}
if (!apiOutputExists) throw new Error('API subprocess output missing!');

```bash

- --

### Subprocess Output Schema Contract

Both `step-03b-subprocess-e2e.md` and `step-03b-subprocess-backend.md` MUST write JSON to their output file with identical schema:

```json
{
  "subprocessType": "e2e | backend",

  "testsGenerated": [
    {
      "file": "path/to/test-file",
      "content": "[full test file content]",
      "description": "Test description",
      "priority_coverage": { "P0": 0, "P1": 0, "P2": 0, "P3": 0 }
    }
  ],
  "coverageSummary": {
    "totalTests": 0,
    "testLevels": ["unit", "integration", "api", "e2e"],
    "fixtureNeeds": []
  },
  "status": "complete | partial"

}

```bash
The aggregate step reads whichever output file(s) exist based on `{detected_stack}`.

- --

### 7. Performance Report

- *Display performance metrics:**

```bash
🚀 Performance Report:

- Execution Mode: PARALLEL (subprocesses based on {detected_stack})
- Stack Type: {detected_stack}
- API Test Generation: ~X minutes
- E2E Test Generation: ~Y minutes       [if frontend/fullstack]
- Backend Test Generation: ~Z minutes    [if backend/fullstack]
- Total Elapsed: ~max(X, Y, Z) minutes
- Sequential Would Take: ~(X + Y + Z) minutes
- Performance Gain: ~40-70% faster!

```bash

- --

### 8. Proceed to Aggregation

- *Load aggregation step:**

Load next step: `{nextStepFile}`

The aggregation step (3C) will:

- Read all subprocess outputs (based on `{detected_stack}`)
- Write all test files to disk
- Generate shared fixtures and helpers
- Calculate summary statistics

- --

## EXIT CONDITION

Proceed to Step 3C (Aggregation) when:

- ✅ Subprocess A (API tests) completed successfully
- ✅ Subprocess B (E2E tests) completed successfully [if frontend/fullstack]
- ✅ Subprocess B-backend (Backend tests) completed successfully [if backend/fullstack]
- ✅ All expected output files exist and are valid JSON
- ✅ Performance metrics displayed

- *Do NOT proceed if:**

- ❌ Any launched subprocess failed
- ❌ Output files missing or corrupted
- ❌ Timeout occurred (subprocesses took too long)

- --

## 🚨 SYSTEM SUCCESS/FAILURE METRICS:

### ✅ SUCCESS:

- All required subprocesses launched successfully (based on `{detected_stack}`)
- All subprocesses completed without errors
- Output files generated and valid
- Parallel execution achieved ~40-70% performance gain

### ❌ SYSTEM FAILURE:

- Failed to launch subprocesses
- One or more subprocesses failed
- Output files missing or invalid
- Attempted sequential generation instead of parallel

- *Master Rule:** Parallel subprocess execution is MANDATORY for performance.
