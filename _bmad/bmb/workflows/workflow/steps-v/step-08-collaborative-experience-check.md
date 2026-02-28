- --

name: 'step-08-collaborative-experience-check'
description: 'Check collaborative quality - does this workflow facilitate well or just interrogate?'

nextStepFile: './step-08b-subprocess-optimization.md'
targetWorkflowPath: '{workflow_folder_path}'
validationReportFile: '{workflow_folder_path}/validation-report-{datetime}.md'
workflowPlanFile: '{workflow_folder_path}/workflow-plan.md'

- --

# Validation Step 8: Collaborative Experience Check

## STEP GOAL:

To validate that the workflow actually facilitates well - natural conversation, not interrogation. Questions asked progressively, not in laundry lists.

## MANDATORY EXECUTION RULES (READ FIRST):

### Universal Rules:

- 🛑 DO NOT BE LAZY - LOAD AND REVIEW EVERY FILE
- 📖 CRITICAL: Read the complete step file before taking any action
- 🔄 CRITICAL: When loading next step, ensure entire file is read
- ✅ Validation does NOT stop for user input - auto-proceed through all validation steps

### Step-Specific Rules:

- 🎯 Review EVERY step for collaborative quality
- 🚫 DO NOT skip any files or experience checks
- 💬 Append findings to report, then auto-load next step
- 🚪 This is validation - systematic and thorough

## EXECUTION PROTOCOLS:

- 🎯 Walk through the workflow as a user would
- 💾 Check conversation flow in each step
- 📖 Validate facilitation quality
- 🚫 DO NOT halt for user input - validation runs to completion

## CONTEXT BOUNDARIES:

- Good workflows facilitate, don't interrogate
- Questions should be 1-2 at a time
- Conversation should feel natural
- Check EVERY step for collaborative patterns

## MANDATORY SEQUENCE

- *CRITICAL:** Follow this sequence exactly. Do not skip or shortcut.

### 1. Load the Workflow Design

From {workflowPlanFile}, understand:

- What is the workflow's goal?
- Who is the user?
- What interaction style was designed?

### 2. Review EACH Step for Collaborative Quality

- *DO NOT BE LAZY - For EACH step file:**

1. Load the step
2. Read the MANDATORY SEQUENCE section
3. Evaluate against collaborative quality criteria:

- *Good Facilitation Indicators:**
- ✅ "Ask 1-2 questions at a time"
- ✅ "Think about their response before continuing"
- ✅ "Use conversation, not interrogation"
- ✅ "Probe to understand deeper"
- ✅ Natural language in instructions
- ✅ Allows for back-and-forth

- *Bad Interrogation Indicators:**
- ❌ Laundry lists of questions
- ❌ "Ask the following: 1, 2, 3, 4, 5, 6..."
- ❌ Form-filling approach
- ❌ No space for conversation
- ❌ Rigid sequences without flexibility

- *Role Reinforcement Check:**
- ✅ "You are a [role], we engage in collaborative dialogue"
- ✅ "Together we produce something better"
- ❌ "You are a form filler" (obviously bad, but check for patterns)

### 3. Check Progression and Arc

- *Does the workflow have:**
- ✅ Clear progression from step to step?
- ✅ Each step builds on previous work?
- ✅ User knows where they are in the process?
- ✅ Satisfying completion at the end?

- *Or does it:**
- ❌ Feel disjointed?
- ❌ Lack clear progression?
- ❌ Leave user unsure of status?

### 4. Check Error Handling

- *Do steps handle:**
- ✅ Invalid input gracefully?
- ✅ User uncertainty with guidance?
- ✅ Off-track conversation with redirection?
- ✅ Edge cases with helpful messages?

### 5. Document Findings

```markdown

### Collaborative Experience Check Results

- *Overall Facilitation Quality:** [Excellent/Good/Fair/Poor]

- *Step-by-Step Analysis:**

- *step-01-init.md:**
- Question style: [Progressive/Laundry list]
- Conversation flow: [Natural/Rigid]
- Role clarity: ✅/❌
- Status: ✅ PASS / ❌ FAIL

- *step-02-*.md:**
- Question style: [Progressive/laundry list - "Ask 1-2 at a time" / Lists 5+ questions]
- Allows conversation: ✅/❌
- Thinks before continuing: ✅/❌
- Status: ✅ PASS / ❌ FAIL

[Continue for ALL steps...]

- *Collaborative Strengths Found:**
- [List examples of good facilitation]
- [Highlight steps that excel at collaboration]

- *Collaborative Issues Found:**

- *Laundry List Questions:**
- [List steps with question dumps]
- Example: "step-03-*.md asks 7 questions at once"

- *Rigid Sequences:**
- [List steps that don't allow conversation]
- Example: "step-04-*.md has no space for back-and-forth"

- *Form-Filling Patterns:**
- [List steps that feel like form filling]
- Example: "step-05-*.md collects data without facilitation"

- *Progression Issues:**
- [List problems with flow/arc]
- Example: "step-06-*.md doesn't connect to previous step"

- *User Experience Assessment:**

- *Would this workflow feel like:**
- [ ] A collaborative partner working WITH the user
- [ ] A form collecting data FROM the user
- [ ] An interrogation extracting information
- [ ] A mix - depends on step

- *Overall Collaborative Rating:** ⭐⭐⭐⭐⭐ [1-5 stars]

- *Status:** ✅ EXCELLENT / ✅ GOOD / ⚠️ NEEDS IMPROVEMENT / ❌ POOR

```bash

### 6. Append to Report

Update {validationReportFile} - replace "## Collaborative Experience Check *Pending...*" with actual findings.

### 7. Save Report and Auto-Proceed

- *CRITICAL:** Save the validation report BEFORE loading next step.

Then immediately load, read entire file, then execute {nextStepFile}.

- *Display:**

"**Collaborative Experience check complete.** Proceeding to Cohesive Review..."

- --

## 🚨 SYSTEM SUCCESS/FAILURE METRICS

### ✅ SUCCESS:

- EVERY step reviewed for collaborative quality
- Question patterns analyzed (progressive vs laundry list)
- Conversation flow validated
- Issues documented with specific examples
- Findings appended to report
- Report saved before proceeding
- Next validation step loaded

### ❌ SYSTEM FAILURE:

- Not checking every step's collaborative quality
- Missing question pattern analysis
- Not documenting experience issues
- Not saving report before proceeding

- *Master Rule:** Validation is systematic and thorough. DO NOT BE LAZY. Check EVERY step's collaborative quality. Auto-proceed through all validation steps.
