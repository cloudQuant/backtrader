- --

name: 'step-04-review'
description: 'Review changes and offer validation'

nextStepFile: './step-05-confirm.md'
validationWorkflow: '../steps-v/step-01-load-target.md'

- --

# Step 4: Review Changes

## STEP GOAL:

Review the applied changes and offer to run validation.

## MANDATORY EXECUTION RULES:

### Universal Rules:

- 📖 CRITICAL: Read the complete step file before taking any action
- ✅ Speak in `{communication_language}`

### Role Reinforcement:

- ✅ You are the **Module Editor** — confirming changes
- ✅ Ensure user is satisfied

- --

## MANDATORY SEQUENCE

### 1. Show Diff

Display what changed:

"**Here's what changed:**"

- *Before:**

{before_content}

- *After:**

{after_content}

### 2. Confirm Satisfaction

"**Are you happy with this change?**"

- **[Y]es**— Keep the change
- **[N]o**— Revert and redo
- **[M]odify** — Make further adjustments

### 3. Handle Response

- *IF Yes:**
- Mark edit as complete
- Proceed to step 5

- *IF No:**
- Revert the change
- Return to step 2 to gather new edit

- *IF Modify:**
- Make additional adjustments
- Show updated diff
- Ask again

### 4. Offer Validation

"**Would you like to run validation after this edit?**"

- Validation can check for any issues introduced

### 5. Proceed to Confirm

Load `{nextStepFile}` to confirm completion.

- --

## Success Metrics

✅ Changes reviewed
✅ User satisfaction confirmed
✅ Validation offered
