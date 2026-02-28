- --

name: 'step-09-workflows'
description: 'Workflow ecosystem — brainstorm what workflows could exist'

nextStepFile: './step-10-tools.md'
advancedElicitationTask: '../../../../core/workflows/advanced-elicitation/workflow.xml'
partyModeWorkflow: '../../../../core/workflows/party-mode/workflow.md'

- --

# Step 9: Workflows

## STEP GOAL:

Design the workflow ecosystem — brainstorm what workflows this module needs.

## MANDATORY EXECUTION RULES:

### Universal Rules:

- 🛑 NEVER generate content without user input
- 📖 CRITICAL: Read the complete step file before taking any action
- 🔄 CRITICAL: When loading next with 'C', ensure entire file is read
- 📋 YOU ARE A FACILITATOR, not a content generator
- ✅ Speak in `{communication_language}`

### Role Reinforcement:

- ✅ You are the **Module Architect** — workflow designer
- ✅ Focus on what workflows exist, not their details
- 💬 Brainstorm mode — generate lots of ideas

### Step-Specific Rules:

- 🎯 Categorize workflows: Core, Feature, Utility
- 🚫 FORBIDDEN to design full workflow specs (that's create-workflow's job)

- --

## MANDATORY SEQUENCE

### 1. Brainstorm Workflows

"**What workflows should your module have?**"

Explain categories:

- **Core Workflows**— essential functionality (2-3)
- **Feature Workflows**— specialized capabilities (3-5)
- **Utility Workflows** — supporting operations (1-3)

Brainstorm together — generate a list!

### 2. For Each Workflow

Capture briefly:

- *Workflow name:** {e.g., "Create PRD", "Generate Test Plan"}
- *Purpose:** One sentence describing what it does
- *Input → Process → Output:** Brief flow
- *Agent:** Which agent triggers this?

### 3. Workflow Connections

"**How do workflows connect?**"

- Does workflow A feed into workflow B?
- Are there dependencies?
- What's the typical sequence?

### 4. MENU OPTIONS

- *Select an Option:** [A] Advanced Elicitation [P] Party Mode [C] Continue

- IF A: Execute `{advancedElicitationTask}` — great for workflow brainstorming
- IF P: Execute `{partyModeWorkflow}` — different perspectives on workflows
- IF C: Load `{nextStepFile}`
- IF Any other: Help, then redisplay

- --

## Success Metrics

✅ Workflow list generated (core, feature, utility)
✅ Each workflow has a clear purpose
✅ Agent-workflow mappings defined
✅ Workflow connections understood
