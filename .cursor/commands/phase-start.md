# /phase-start

Begin work on a numbered build phase from `SETUP_PROMPT.md`.

**Usage:** `/phase-start 3` (or describe the phase)

## Procedure
1. Re-read the relevant phase section in `SETUP_PROMPT.md` and the applicable `.cursor/rules/`.
2. Confirm the previous phase's verification actually passes right now — run it, don't assume.
3. Produce a short plan: files to create/modify, interfaces to define, tests to write, expected risks.
4. **Wait for my approval of the plan before writing code.**
5. Implement, tests first where practical.
6. Run `make check`. Fix everything until green.
7. Run the phase's stated verification and paste the real output.
8. Report using the template below.

## Report template
```
## Phase N — <name>

### Delivered
- <file>: <what it does>

### Interfaces introduced/changed
- <signature> — <why>

### Verification (actual output)
<paste>

### Assumptions made
- <assumption> — <why, and what would change if wrong>

### Deferred / TODO
- <item> — <which phase it belongs to>

### Risks I want you to look at
- <risk>
```
