- --

name: 'step-05-confirm'
description: 'Confirm completion and offer next steps'

validationWorkflow: '../steps-v/step-01-load-target.md'

- --

# Step 5: Confirm Completion

## STEP GOAL:

Confirm edit completion and offer next steps including validation.

## MANDATORY EXECUTION RULES:

### Universal Rules:

- 📖 CRITICAL: Read the complete step file before taking any action
- ✅ Speak in `{communication_language}`

### Role Reinforcement:

- ✅ You are the **Module Editor** — completing the job
- ✅ Guide next steps

- --

## MANDATORY SEQUENCE

### 1. Summary of Changes

"**✓ Edit complete!**"

- *File edited:** {file_path}
- *Edit type:** {edit_type}
- *Summary:** {summary_of_change}

### 2. Offer Next Actions

"**What would you like to do next?**"

- **[V]alidate**— Run validation to check for issues
- **[E]dit more**— Make additional changes
- **[D]one** — Complete edit session

### 3. Handle Response

- *IF Validate:**

"**Loading validation workflow...**"
Load `{validationWorkflow}`

- *IF Edit more:**

"**Loading edit selection...**"
Return to step 1

- *IF Done:**

"**Edit session complete!**"
Summary of what was accomplished.

### 4. Complete Session

If Done selected:

"**Thanks for using the Module Edit workflow!**"

"**Summary:**"

- Files edited: {count}
- Changes made: {summary}

- --

## Success Metrics

✅ Edit confirmed complete
✅ Next actions offered
✅ Validation accessible
✅ Session properly closed
