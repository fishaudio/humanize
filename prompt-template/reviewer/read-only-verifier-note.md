
## Reviewer Mode: Read-Only

You are running as a read-only reviewer: you can read files and run read-only git commands, but you cannot edit or create files.

- Do not try to write @{{REVIEW_RESULT_FILE}} or any other file. Print your complete review to standard output instead; the loop saves it to that file for you.
- The marker rules above still apply: the last line of your output is exactly `COMPLETE` only when every current-scope task is fully done.
