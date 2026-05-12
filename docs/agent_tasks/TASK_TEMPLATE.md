# Agent Task Template

## Task name

[short name]

## Task type

Choose one:

- analysis only
- documentation only
- small code change
- test-only change
- refactor
- bug fix

## Goal

[one clear goal]

## Allowed files

List exact files or folders the agent may touch.

## Forbidden files

List files or folders the agent must not touch.

## Out of scope

List what the agent must not do.

## Risk level

Choose one:

- low
- medium
- high

## Reviewer requirement

State whether user review is required before implementation.

## Rules

- Do not rewrite unrelated code.
- Do not change scientific formulas unless explicitly requested.
- Do not change UI layout unless explicitly requested.
- Do not delete files unless explicitly requested.
- Prefer small changes.
- Stop if the task requires a larger architectural decision.

## Expected output

[what file or change should exist after the task]

## Documentation target

The agent must answer:

- Is this task updating an existing document?
- If yes, which one?
- Is a new document necessary?
- If yes, why can this not fit into an existing document?

## Tests to run

[commands]

## Validation evidence

List exact evidence that must exist after the task, such as:

- output file
- test command
- terminal output
- screenshot
- report section
- changed file list

## Rollback / abort plan

Explain how to stop safely if the task becomes risky.

## Stop condition

Stop and ask for review if:

- more than 5 files need to be changed,
- scientific logic needs to be changed,
- the agent finds conflicting assumptions,
- tests fail for unclear reasons.

## Files actually modified

At the end of each task, the agent must list every modified file.
