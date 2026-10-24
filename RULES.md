# Project and hackathon working rules

## Important event-template distinction

The linked [DevDay Kochi template](https://github.com/anima-regem/devday-kochi-hackathon-template) identifies its event as **DevDay Exchange Community Hackathon: Kochi, 10–11 October 2026**. The event described for this project is **Devin Hacks Kochi, 24–25 October 2026**. These are different event names and dates.

This repository adopts the template's useful development workflow, documentation structure, and simple-coding guidance. Its DevDay-specific venue, timing, credits, and mandatory-Codex rule are **not assumed to be official rules for Devin Hacks**. Follow the actual Devin Hacks organizer announcements for eligibility and submission requirements. If you intend to apply the source template literally as an additional convention, use Codex during implementation and record its actual usage.

## Project implementation

- The current branch contains planning/specification documents and no working runtime implementation yet.
- Build the application implementation from scratch during the event. Do not import a pre-built application or present a prebuilt tool as the hackathon implementation.
- Libraries, SDKs, APIs, and reference documentation may be used subject to the current event's actual rules; document the sources used.
- The goal is one real end-to-end flow, not a collection of incomplete features.
- Use the PRD, TRD, and build plan as the source of project scope. Any change to scope should be documented.

## Development workflow

- Prefer simple, idiomatic code and minimal purposeful dependencies.
- Record every meaningful code or documentation milestone in CHANGELOG.md in the same commit.
- Keep README.md synchronized with the working setup/run/test steps.
- Keep AI_USAGE.md accurate: record tools that actually contributed, what they did, the human review status, and checks performed. Do not fabricate Codex usage or any test result.
- Commit coherent, tested milestones; a useful checkpoint about every 30 minutes is a workflow target, not a reason to create empty commits.
- Do not backdate commits, force-push, or rewrite shared history.
- Preserve the user's worktree and local changes.

## Validation and safety

- Run checks appropriate to the change and document failures or checks that could not be run.
- Do not report planned functionality as implemented.
- Never commit secrets, credentials, access tokens, or private participant data.
- Do not claim an agent hook enforces a rule unless the host behavior has actually been tested.
