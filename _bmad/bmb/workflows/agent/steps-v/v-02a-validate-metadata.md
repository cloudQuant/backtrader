- --

name: 'v-02a-validate-metadata'
description: 'Validate metadata and append to report'

nextStepFile: './v-02b-validate-persona.md'
validationReport: '{bmb_creations_output_folder}/validation-report-{agent-name}.md'
agentMetadata: ../data/agent-metadata.md
agentFile: '{agent-file-path}'

- --

# Validate Step 2a: Validate Metadata

## STEP GOAL

Validate the agent's metadata properties against BMAD standards as defined in agentMetadata.md. Append findings to validation report and auto-advance.

## MANDATORY EXECUTION RULES

- 📖 CRITICAL: Read the complete step file before taking any action
- 🔄 CRITICAL: Read validationReport and agentMetadata first
- 🔄 CRITICAL: Load the actual agent file to validate metadata
- 🚫 NO MENU - append findings and auto-advance
- ✅ YOU MUST ALWAYS SPEAK OUTPUT In your Agent communication style with the config `{communication_language}`

### Step-Specific Rules:

- 🎯 Validate metadata against agentMetadata.md rules
- 📊 Append findings to validation report
- 🚫 FORBIDDEN to present menu

## EXECUTION PROTOCOLS

- 🎯 Load agentMetadata.md reference
- 🎯 Load the actual agent file for validation
- 📊 Validate all metadata fields
- 💾 Append findings to validation report
- ➡️ Auto-advance to next validation step

## MANDATORY SEQUENCE

- *CRITICAL:**Follow this sequence exactly. Do not skip, reorder, or improvise unless user explicitly requests a change.

### 1. Load References

Read `{agentMetadata}`, `{validationReport}`, and `{agentFile}`.

### 2. Validate Metadata

Perform these checks systematically - validate EVERY rule specified in agentMetadata.md:

1.**Required Fields Existence**

   - [ ] id: Present and non-empty
   - [ ] name: Present and non-empty (display name)
   - [ ] title: Present and non-empty
   - [ ] icon: Present (emoji or symbol)
   - [ ] module: Present and valid format
   - [ ] hasSidecar: Present (boolean, if applicable)

1. **Format Validation**
   - [ ] id: Uses kebab-case, no spaces, unique identifier
   - [ ] name: Clear display name for UI
   - [ ] title: Concise functional description
   - [ ] icon: Appropriate emoji or unicode symbol
   - [ ] module: Either a 3-4 letter module code OR 'stand-alone'
   - [ ] hasSidecar: Boolean value, matches actual agent structure

1. **Content Quality**
   - [ ] id: Unique and descriptive
   - [ ] name: Clear and user-friendly
   - [ ] title: Accurately describes agent's function
   - [ ] icon: Visually representative of agent's purpose
   - [ ] module: Correctly identifies module membership
   - [ ] hasSidecar: Correctly indicates if agent uses sidecar files

1. **Agent Type Consistency**
   - [ ] If hasSidecar: true, sidecar folder path must be specified
   - [ ] If module is a module code, agent is a module agent
   - [ ] If module is 'stand-alone', agent is not part of a module
   - [ ] No conflicting type indicators

### 3. Append Findings to Report

Append to `{validationReport}`:

```markdown

### Metadata Validation

- *Status:** {✅ PASS / ⚠️ WARNING / ❌ FAIL}

- *Checks:**
- [ ] id: kebab-case, no spaces, unique
- [ ] name: clear display name
- [ ] title: concise function description
- [ ] icon: appropriate emoji/symbol
- [ ] module: correct format (code or stand-alone)
- [ ] hasSidecar: matches actual usage

- *Detailed Findings:**

- PASSING:*

{List of passing checks}

- WARNINGS:*

{List of non-blocking issues}

- FAILURES:*

{List of blocking issues that must be fixed}

```bash

### 4. Auto-Advance

Load and execute `{nextStepFile}` immediately.

- --

- *Validating persona...**
