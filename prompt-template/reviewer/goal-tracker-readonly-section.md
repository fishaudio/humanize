## Goal Tracker Corrections (Read-Only Reviewer)

You cannot edit files in this review. The coding agent keeps the **mutable section** of `goal-tracker.md` up to date. Read @{{GOAL_TRACKER_FILE}} and check that it still matches the Ultimate Goal and the real progress against the acceptance criteria.

If Claude's summary contains a "Goal Tracker Update Request" section, or you find tracker drift, add a section named `Goal Tracker Corrections` to your review that lists each change the coding agent must make:

- tasks to move between Active, Completed, and Deferred;
- entries to add to the "Plan Evolution Log", with the round number and your assessment;
- new items for "Blocking Side Issues" or "Queued Side Issues";
- requested changes you reject, and why.

The **IMMUTABLE SECTION** (Ultimate Goal and Acceptance Criteria) must never change. Deferrals need strong justification.
