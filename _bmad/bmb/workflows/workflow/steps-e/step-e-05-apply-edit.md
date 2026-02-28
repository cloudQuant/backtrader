- --

name: 'step-e-05-apply-edit'
description: 'Offer validation after edits, complete or continue editing'

# File References

nextStepFile: './step-e-06-validate-after.md'
completeStep: './step-e-07-complete.md'
editPlan: '{bmb_creations_output_folder}/edit-plan-{workflow_name}.md'
targetWorkflowPath: '{targetWorkflowPath}'
validationWorkflow: '../steps-v/step-01-validate.md'

- --

# Edit Step 5: Post-Edit Options

## STEP GOAL:

Present options after edits are applied: run validation, make more edits, or complete.

## MANDATORY EXECUTION RULES (READ FIRST):

### Universal Rules:

- 📖 CRITICAL: Read the complete step file before taking any action
- 📋 YOU ARE A FACILITATOR, not an autonomous editor
- ✅ YOU MUST ALWAYS SPEAK OUTPUT In your Agent communication style with the config `{communication_language}`

### Step-Specific Rules:

- 🎯 Focus on next steps after edits
- 💬 Present clear options
- 🚪 Route based on user choice

## EXECUTION PROTOCOLS:

- 🎯 Present post-edit options
- 💾 Update edit plan if needed
- 📖 Route to appropriate next step

## CONTEXT BOUNDARIES:

- Edits have been applied (validation fixes, direct changes, or both)
- Focus: What's next?
- This is a routing step

## MANDATORY SEQUENCE

- *CRITICAL:** Follow this sequence exactly. Do not skip or shortcut.

### 1. Read Edit Plan

- *Load the editPlan:**

Read `{editPlan}` to understand what edits were applied.

### 2. Present Edit Summary

"**Edit Session Summary:**

- *Workflow:** {workflow_name}
- *Path:** {targetWorkflowPath}

- *Edits Applied:**

{Summarize from edit plan}

- *Files Modified:**

{List files changed}

- *Compliance Status:**

{Any compliance issues found and fixed}

- --

- *What would you like to do next?**

- *[V]alidate** - Run comprehensive validation to verify all changes
- *[M]ore edits** - Make additional changes
- *[C]omplete** - Finish editing (without validation)
- *[R]eview changes**- See detailed change log"

### 3. Menu Handling Logic

- **IF V:**Load, read entirely, then execute {validationWorkflow}. After validation completes, return to this step.
- **IF M:**Route to step-e-02-discover-edits.md for more changes
- **IF C:**Load, read entirely, then execute {completeStep}
- **IF R:**Present detailed edit log from editPlan, then redisplay this menu
- **IF Any other:** help user respond, then redisplay menu

### 4. Update Edit Plan (If Completing Without Validation)

- *IF user selects [C] Complete:**

Update editPlan frontmatter:

```yaml
completionDate: '{current-date}'
validationAfterEdit: skipped
completionStatus: complete_without_validation

```bash
Document in editPlan:

```markdown

## Completion

- *Completed:** {current-date}
- *Validation:** Skipped per user request
- *Recommendation:** Run validation before using workflow in production

```bash

### 5. Handle Validation Return

- *IF validation was run and completed:**

Load and review validation report. Present findings:

"**Validation Complete:**

- *Overall Status:** {status}
- *New Issues:** {count}
- *Remaining Issues:** {count}

- *Would you like to:**

1. **[F]ix new issues**- Return to fix-validation step

2.**[M]ore edits**- Make additional changes
3.**[C]omplete** - Finish with current validation status"

#### Menu Handling Logic:

- IF F: Route to step-e-03-fix-validation.md
- IF M: Route to step-e-02-discover-edits.md
- IF C: Load, read entirely, then execute {completeStep}
- IF Any other: help user, then redisplay menu

## CRITICAL STEP COMPLETION NOTE

This is a routing step. Route user to appropriate next step based on their choice. Always offer validation before completing.

- --

## 🚨 SYSTEM SUCCESS/FAILURE METRICS

### ✅ SUCCESS:

- Edit summary presented clearly
- All options explained
- User routed to appropriate next step
- Validation offered before completion
- Edit plan updated if completing

### ❌ SYSTEM FAILURE:

- Not offering validation
- Routing to wrong step
- Not updating edit plan when completing

- *Master Rule:** Always offer validation after edits. Route correctly based on user choice.
