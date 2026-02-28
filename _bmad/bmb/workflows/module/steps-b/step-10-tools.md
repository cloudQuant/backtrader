- --

name: 'step-10-tools'
description: 'MCP tools, integrations, external services the module might need'

nextStepFile: './step-11-scenarios.md'
advancedElicitationTask: '../../../../core/workflows/advanced-elicitation/workflow.xml'
partyModeWorkflow: '../../../../core/workflows/party-mode/workflow.md'

- --

# Step 10: Tools

## STEP GOAL:

Identify MCP tools, integrations, and external services the module might need.

## MANDATORY EXECUTION RULES:

### Universal Rules:

- 🛑 NEVER generate content without user input
- 📖 CRITICAL: Read the complete step file before taking any action
- 🔄 CRITICAL: When loading next with 'C', ensure entire file is read
- 📋 YOU ARE A FACILITATOR, not a content generator
- ✅ Speak in `{communication_language}`

### Role Reinforcement:

- ✅ You are the **Module Architect** — integrations thinker
- ✅ Keep it practical — only what's needed
- 💬 Ask "what external capabilities would help?"

- --

## MANDATORY SEQUENCE

### 1. MCP Tools

"**Does your module need any MCP (Model Context Protocol) tools?**"

Explain: MCP tools connect agents to external capabilities.

Common MCP tools:

- Database connectors
- Git integration
- Web automation (Playwright)
- API tools
- Knowledge bases

- *"What would help your module work better?"**

### 2. External Services

"**Any external services or APIs?**"

- Web APIs?
- Cloud services?
- Data sources?
- Third-party tools?

### 3. Module Integrations

"**Does this integrate with other BMAD modules?****

- Uses workflows from other modules?
- Shares agents or extends them?
- Depends on another module's capabilities?

### 4. Capture the List

Document:

- **MCP Tools:**{list or "none"}
- **External Services:**{list or "none"}
- **Module Integrations:** {list or "none"}

Note: These are placeholders for later — the create workflow can implement them.

### 5. MENU OPTIONS

- *Select an Option:** [A] Advanced Elicitation [P] Party Mode [C] Continue

- IF A: Execute `{advancedElicitationTask}`
- IF P: Execute `{partyModeWorkflow}`
- IF C: Load `{nextStepFile}`
- IF Any other: Help, then redisplay

- --

## Success Metrics

✅ MCP tools identified (or "none" decided)
✅ External services documented (or "none")
✅ Module integrations noted (or "none")
