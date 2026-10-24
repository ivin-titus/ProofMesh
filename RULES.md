# Project and hackathon working rules

## Event guidance and template correction

The original starter files in the [DevDay Kochi template repository](https://github.com/anima-regem/devday-kochi-hackathon-template) identified **DevDay Exchange Community Hackathon: Kochi, 10–11 October 2026**. Its [corrected Devin Hack Kochi branch](https://github.com/anima-regem/devday-kochi-hackathon-template/tree/codex/correct-devin-hack-kochi-cainebenoy) says those details came from an older event template and identifies **Devin Hack Kochi** as the relevant event. That branch says Codex is not required and that there are no major AI-usage constraints.

This correction is maintained in a participant project branch, not an official organizer rules page. Treat it as a reason to remove inherited template assumptions, not as a complete authoritative rulebook. Do not carry forward the older template's dates, venue, registration, team-size limits, credit promises, or Codex/OpenAI-specific requirements. Follow current organizer instructions for eligibility, tracks, logistics, permitted work, and submission. The documentation and commit workflow in this repository are project conventions, not additional eligibility rules.

## Project implementation

- The current branch contains planning/specification documents and no working runtime implementation yet.
- Project plan: implement ProofMesh's core runtime during the event and disclose the provenance of prior planning, code, libraries, AI assistance, and reused components accurately. This is a project commitment, not a claim that the linked template establishes a blanket no-prework event rule.
- Libraries, SDKs, APIs, and reference documentation may be used subject to the current event's actual rules; document the sources used.
- The goal is one real end-to-end flow, not a collection of incomplete features.
- Use the PRD, TRD, and build plan as the source of project scope. Any change to scope should be documented.

## Development workflow

- Prefer simple, idiomatic code and minimal purposeful dependencies.
- Record every meaningful code or documentation milestone in CHANGELOG.md in the same commit.
- Keep README.md synchronized with the working setup/run/test steps.
- Keep AI_USAGE.md accurate: record tools that actually contributed, what they did, the human review status, and checks performed. Do not fabricate tool usage or test results.
- Commit coherent, tested milestones; a useful checkpoint about every 30 minutes is a workflow target, not a reason to create empty commits.
- Do not backdate commits, force-push, or rewrite shared history.
- Preserve the user's worktree and local changes.

## Validation and safety

- Run checks appropriate to the change and document failures or checks that could not be run.
- Do not report planned functionality as implemented.
- Never commit secrets, credentials, access tokens, or private participant data.
- Do not claim an agent hook enforces a rule unless the host behavior has actually been tested.
