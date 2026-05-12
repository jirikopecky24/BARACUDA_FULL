# BARAKUDA Agent Instructions

## Project identity

BARAKUDA is a scientific research software platform.

## Current checkpoint

The active checkpoint is **CP01 — BARAKUDA v1 laboratory deployment and PhD Talent acceleration**.

## Current goal

The current goal is preparation for safe development, not broad feature expansion.

## Direction for application structure

BARAKUDA Acquisition and BARAKUDA Analysis should become separate launchable application modes in a later step, with minimal-risk transition from the current shared launcher.

## Scientific sensitivity areas

The following areas are scientifically sensitive and must be treated as high-risk:

- timing truth
- effective FPS
- `timestamps.csv` status and semantics
- batch summaries
- report consistency

Agents must never silently change scientific formulas, units, timing assumptions, calibration assumptions, or report values.

## Task granularity rule

One task must have one narrow goal.

Do not combine unrelated refactor, feature, UI redesign, and scientific logic changes in one task.

## Hard stop rule

If more than 5 files need to change, stop and request explicit approval before proceeding.

## Risk-aware execution preference

Prefer documentation updates, diagnostics, and tests before risky refactors.

## Completion reporting requirement

At task end, always summarize:

1. what was changed
2. what was intentionally not changed

## Documentation anti-proliferation rule

- Do not create a new report/audit/status document for every small task.
- If a task belongs to an existing topic, update the existing topic document instead.
- Prefer adding a dated section such as:
  "## Update YYYY-MM-DD — [short topic]"
- Only create a new document when:
  1. the task introduces a genuinely new topic,
  2. no existing document fits,
  3. the user explicitly asks for a new document,
  4. or the task would make an existing document confusingly large.
- Before creating any new docs/agent_tasks/*.md file, check whether one of these existing files should be updated instead:
  - CP01_AGENT_QUEUE.md
  - TASK_TEMPLATE.md
  - GIT_HYGIENE_PLAN.md
  - ACQUISITION_ANALYSIS_SPLIT_PLAN.md
  - STARTUP_CONSTRUCTOR_SEAM_REPORT.md
  - STARTUP_HELPER_IMPLEMENTATION_AUDIT_001.md
  - STARTUP_HELPER_ENV_VALIDATION_001.md
  - ENVIRONMENT_SETUP_PLAN.md if it exists
- For repeated audits/validations of the same topic, append to the existing file instead of creating AUDIT_002, AUDIT_003, etc., unless the user explicitly asks.
- At the end of every task, the agent must say:
  1. whether it created any new document,
  2. why a new document was necessary if it created one,
  3. or which existing document it updated instead.
