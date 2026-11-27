---
name: humanize-cancel-rlcr-loop
description: >-
  Cancels the active Humanize RLCR loop in this repository. Use this skill
  only when the user explicitly asks to cancel, stop, or end the RLCR loop.
---

# Cancel the Humanize RLCR Loop

Use this skill only when the user asks for it. Never cancel a loop on your own to get out of a review.

1. Run the cancel script with `run_command`:

   ```bash
   "{{HUMANIZE_RUNTIME_ROOT}}/scripts/cancel-rlcr-loop.sh"
   ```

2. Read the first line of the output:
   - `NO_LOOP` or `NO_ACTIVE_LOOP`: tell the user there is no active loop.
   - `CANCELLED`, `CANCELLED_METHODOLOGY_ANALYSIS`, or `CANCELLED_FINALIZE`: tell the user the loop was cancelled.
   - `FINALIZE_NEEDS_CONFIRM`: the loop is in its last (finalize) round. Go to step 3.

3. Ask the user with `ask_question`: the loop is in its last round, and if they cancel now it ends without finishing that round. Offer two choices: "Cancel now" and "Let it finish".
   - "Cancel now": run `"{{HUMANIZE_RUNTIME_ROOT}}/scripts/cancel-rlcr-loop.sh" --force` and tell the user the loop was cancelled.
   - "Let it finish": tell the user the last round will continue and the loop will end normally.

Explain the result in your own plain words. The loop folder under `.humanize/rlcr/` is kept, with every summary and review, so nothing is deleted.
