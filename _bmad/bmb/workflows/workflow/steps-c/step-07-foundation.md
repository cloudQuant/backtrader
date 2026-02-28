- --

name: 'step-07-foundation'
description: 'Create workflow folder structure, workflow.md, and main output template(s)'

nextStepFile: './step-08-build-step-01.md'
targetWorkflowPath: '{bmb_creations_output_folder}/workflows/{new_workflow_name}'
workflowPlanFile: '{targetWorkflowPath}/workflow-plan-{new_workflow_name}.md'
workflowTemplate: '../templates/workflow-template.md'
outputFormatStandards: '../data/output-format-standards.md'
minimalOutputTemplate: '../templates/minimal-output-template.md'
advancedElicitationTask: '{project-root}/_bmad/core/workflows/advanced-elicitation/workflow.xml'
partyModeWorkflow: '{project-root}/_bmad/core/workflows/party-mode/workflow.md'

- --

# Step 7: Foundation Build

## STEP GOAL:

To create the workflow folder structure, the main workflow.md file, and the primary output template(s) that step files will reference.

## MANDATORY EXECUTION RULES (READ FIRST):

### Universal Rules:

- 🛑 NEVER generate content without user input
- 📖 CRITICAL: Read the complete step file before taking any action
- 🔄 CRITICAL: When loading next step with 'C', ensure entire file is read
- 📋 YOU ARE A FACILITATOR, not a content generator
- ✅ YOU MUST ALWAYS SPEAK OUTPUT In your Agent communication style with the config `{communication_language}`

### Role Reinforcement:

- ✅ You are a workflow architect and systems designer
- ✅ If you already have been given communication or persona patterns, continue to use those while playing this new role
- ✅ We engage in collaborative dialogue, not command-response
- ✅ You bring implementation expertise and best practices
- ✅ User brings their specific requirements and design approvals

### Step-Specific Rules:

- 🎯 Focus ONLY on creating foundation elements (folder, workflow.md, main template)
- 🚫 FORBIDDEN to create step files yet - that comes next
- 💬 Get confirmation before creating each foundation element
- 🚪 CREATE files in the correct target location

## EXECUTION PROTOCOLS:

- 🎯 Create foundation systematically from approved design
- 💾 Document what was created in the plan
- 📖 Update frontmatter stepsCompleted to add this step when completed
- 🚫 FORBIDDEN to load next step until user selects 'C'

## CONTEXT BOUNDARIES:

- Approved plan from step 6 guides implementation
- Design specifies: workflow name, continuable or not, document output type, step count
- Load templates and documentation as needed during build
- Follow step-file architecture principles

## MANDATORY SEQUENCE

- *CRITICAL:** Follow this sequence exactly. Do not skip, reorder, or improvise unless user explicitly requests a change.

### 1. Confirm Foundation Readiness

Based on the approved design from step 6, confirm:

"**I have your approved design and I'm ready to create the workflow foundation.**

From your design, I'll be creating:

- *Workflow:** {new_workflow_name}
- *Location:** {targetWorkflowPath}
- *Type:** [continuable/single-session]
- *Document Output:** [yes/no - template type if yes]
- *Estimated Steps:** [number from design]

Ready to proceed with creating the folder structure?"

### 2. Create Folder Structure

Create the workflow folder structure:

```bash
{targetWorkflowPath}/
├── workflow.md                    # To be created

├── steps-c/                       # Create flow steps

│   ├── step-01-init.md
│   ├── step-01b-continue.md      # If continuable

│   └── [remaining steps]
├── steps-v/                       # Validate flow steps (to be created later)

├── data/                          # Shared reference data

└── templates/                     # Output templates

```bash

- *For BMB module workflows:** The target will be `_bmad/custom/src/workflows/{workflow_name}/`
- *For other modules:** Check module's custom_workflow_location

Create the folders and confirm structure.

### 3. Generate workflow.md

Load {workflowTemplate} and create workflow.md with:

- *Frontmatter:**

```yaml

- --

name: '{workflow-name-from-design}'
description: '{description-from-design}'
web_bundle: true

- --

```bash

- *Content:**
- Workflow name and description
- Goal statement
- Role definition
- Meta-context (if applicable)
- Initialization sequence pointing to steps-c/step-01-init.md
- Configuration loading instructions

- *If tri-modal (Create + Edit + Validate):**

Add mode routing logic to workflow.md:

- IF invoked with -c: Load ./steps-c/step-01-init.md
- IF invoked with -v: Load ./steps-v/step-01-validate.md
- IF invoked with -e: Load ./steps-e/step-01-edit.md

### 4. Create Main Output Template

- *Load {outputFormatStandards} to determine template type.**

- *From the design, determine:**
- Free-form (recommended) - Minimal frontmatter + progressive append
- Structured - Required sections with flexible content
- Semi-structured - Core sections + optional additions
- Strict - Exact format (rare, compliance/legal)

- *For Free-form (most common):**

Create `templates/output-template.md`:

```yaml

- --

stepsCompleted: []
lastStep: ''
date: ''
user_name: ''

- --

```bash
If the workflow produces a document with sections:

```markdown

# {{document_title}}

[Content appended progressively by workflow steps]

```bash

- *For Structured/Semi-structured:**

Create template with section placeholders based on design:

```markdown

# {{title}}

## {{section_1}}

[Content to be filled]

## {{section_2}}

[Content to be filled]

```bash

- *For Non-Document Workflows:**

No output template needed. Document this in the plan.

### 5. Document Foundation in Plan

Append to {workflowPlanFile}:

```markdown

## Foundation Build Complete

- *Created:**
- Folder structure at: {targetWorkflowPath}
- workflow.md
- Main template: [template-name]

- *Configuration:**
- Workflow name: {name}
- Continuable: [yes/no]
- Document output: [yes/no - type]
- Mode: [create-only or tri-modal]

- *Next Steps:**
- Step 8: Build step-01 (and step-01b if continuable)
- Step 9: Build remaining steps (repeatable)

```bash

### 6. Present MENU OPTIONS

Display: **Foundation Complete - Select an Option:** [A] Advanced Elicitation [P] Party Mode [C] Continue to Step 01 Build

#### EXECUTION RULES:

- ALWAYS halt and wait for user input after presenting menu
- ONLY proceed to next step when user selects 'C'
- After other menu items execution, return to this menu
- User can chat or ask questions - always respond and then redisplay menu

#### Menu Handling Logic:

- IF A: Execute {advancedElicitationTask}, and when finished redisplay the menu
- IF P: Execute {partyModeWorkflow}, and when finished redisplay the menu
- IF C: Save foundation summary to {workflowPlanFile}, update frontmatter stepsCompleted, then load, read entire file, then execute {nextStepFile}
- IF Any other comments or queries: help user respond then [Redisplay Menu Options](#6-present-menu-options)

## CRITICAL STEP COMPLETION NOTE

ONLY WHEN C is selected and foundation is saved to plan will you load {nextStepFile} to begin building step-01.

- --

## 🚨 SYSTEM SUCCESS/FAILURE METRICS

### ✅ SUCCESS:

- Folder structure created in correct location
- workflow.md created with proper frontmatter and initialization
- Main output template created (if document-producing workflow)
- Foundation documented in {workflowPlanFile}
- Frontmatter updated with stepsCompleted

### ❌ SYSTEM FAILURE:

- Creating folders without user confirmation
- Missing mode routing for tri-modal workflows
- Wrong template type for output format
- Not documenting what was created

- *Master Rule:** Skipping steps, optimizing sequences, or not following exact instructions is FORBIDDEN and constitutes SYSTEM FAILURE.
