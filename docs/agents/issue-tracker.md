# Issue tracker: Local Markdown

Issues and PRDs for this repo live as markdown files in `.scratch/`. Do not use the GitHub CLI for issue operations unless the user explicitly asks to publish something remotely.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The PRD is `.scratch/<feature-slug>/PRD.md`
- Implementation issues are `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is recorded as a `Status:` line near the top of each issue file. Use the role strings from `docs/agents/triage-labels.md`.
- Comments and conversation history append to the bottom of the file under a `## Comments` heading.

## Issue File Template

```markdown
# <Issue title>

Status: ready-for-agent
Type: feature

## Problem

## Scope

## Acceptance Criteria

## Testing

## Comments
```

## When a skill says "publish to the issue tracker"

Create or update local markdown files under `.scratch/<feature-slug>/`.

## When a skill says "fetch the relevant ticket"

Read the referenced local markdown file. The user will normally pass the path, feature slug, or issue number.
