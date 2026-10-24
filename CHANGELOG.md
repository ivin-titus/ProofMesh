# Change log

## 2026-10-24T22:26:23+05:30 — Organize specifications under docs/

- **Changed:** Moved the PRD to `docs/PRD.md`, the TRD to `docs/TRD.md`, and the event-track PDF to `docs/BUILD_TRACKS.pdf`. Updated README/agent/build-plan links and added a direct link to the track reference. Expanded `AI_USAGE.md` to record the earlier Devin-assisted ideation/specification work, separately from Git commit authorship.
- **Why:** Keep project specifications and supporting event material together under `docs/`, with clear navigation and an honest AI-contribution record.
- **Validation:** Checked all current repository references to the prior filenames; verified the moved spec and PDF paths use the existing blobs so their contents are unchanged; reviewed the updated AI-usage and change records.
- **Test result:** Documentation/file-organization change only; no runtime tests were run because the application implementation has not started.
- **Limitations:** Devin's exact model/version was not recorded; its contribution is described at the project-document level rather than attributing individual lines or Git commits.


## 2026-10-24T22:15:13+05:30 — Correct event-template assumptions

- **Changed:** Updated README.md, AGENTS.md, RULES.md, AI_USAGE.md, SUBMISSION.md, and docs/BUILD_PLAN.md to reflect the corrected Devin Hack Kochi guidance in the linked reference branch. Removed the inherited mandatory-Codex assumption and reframed the from-scratch implementation plan as a ProofMesh project commitment rather than an asserted event rule.
- **Why:** The corrected reference branch says the starter documentation belonged to an older event and that Codex is not required. The reference is participant-maintained, so official organizer instructions remain authoritative.
- **Validation:** Compared the reference repository's `main` branch with `codex/correct-devin-hack-kochi-cainebenoy`; read the corrected RULES.md, AGENTS.md, README.md, AI_USAGE.md, CHANGELOG.md, and SUBMISSION.md; reviewed the affected ProofMesh documentation for consistency.
- **Test result:** Documentation-only change; no runtime tests were run because the ProofMesh implementation has not started.
- **Limitations:** No separate official organizer rules page was included in the supplied reference. Verify event-specific eligibility and submission details against current organizer communications.


Record meaningful project changes newest first. Use the actual timestamp with timezone. Keep this file updated in the same commit as the change being recorded.

## 2026-10-24T22:09:29+05:30 — Adopt template-aligned repository workflow

- **Changed:** Added the project README, agent guidance, project working rules, AI usage record, submission checklist, Git ignore rules, and pull-request template; updated the build plan to use this branch and the current remaining-time window.
- **Why:** Adopt the reusable documentation, review, AI-usage, and commit-cadence practices from the linked participant template while keeping the two different hackathon events distinct.
- **Validation:** Read the reference template README, AGENTS.md, RULES.md, AI_USAGE.md, CHANGELOG.md, SUBMISSION.md, .gitignore, and pull-request template; inspected the current ProofMesh branch and existing PRD/TRD/build plan.
- **Test result:** Documentation-only change; no application tests were run because no runtime implementation exists yet.
- **Limitations:** The linked template describes DevDay Exchange Community Hackathon on 10–11 October 2026, not the Devin Hacks Kochi event described for this project. Current event-specific rules must be confirmed with its organizers.
