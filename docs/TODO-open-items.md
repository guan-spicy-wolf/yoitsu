# Open Items (2026-03-27)

## From ADR Implementation

1. **ADR-0005**: Extract intake/execution into separate supervisor loop components
   - Current: cursor timing fixed, but intake and execution still share the same loop
   - Priority: P2 (structural cleanup, no correctness impact)

2. **ADR-0006**: Evaluator-specific default role/prompt tuning
   - Current: eval job falls back to `default` role when `eval_spec.role` is omitted
   - Priority: P1 (directly affects eval output quality)

3. **ADR-0014**: Hard timeout for in-process evo Python tools
   - Current: `tool_timeout_seconds` is only a hard guarantee for timeout-capable paths (for example subprocess-backed tools like `bash`)
   - Gap: generic Python evo tools still execute in-process with no reliable interruption boundary
   - Priority: P1 (requires separate isolation/execution design)

4. **ADR-0014**: Update example task specs and smoke fixtures to require explicit root budgets
   - Current: the runtime now expects root-task budget as a first-class field, but examples and ad hoc smoke inputs are not all updated
   - Priority: P1 (operator ergonomics, prevents confusing failed root tasks)

5. **ADR-0014**: Clarify join-job budget policy
   - Current: join jobs inherit the parent task's budget defaults, which effectively gives the continuation/join path a fresh per-job budget rather than a strict "remaining task budget"
   - Gap: this is a policy choice but not yet documented or explicitly accepted
   - Priority: P2 (architecture clarity)

## From Original Issue List

6. **Issue 5**: Verify `publication.py:56` `result.get("status") == "failed"` branch
   - ADR-0006 implemented status propagation; confirm this guard now triggers correctly
   - File: `palimpsest/palimpsest/stages/publication.py:56`
   - Priority: P2 (verify, likely already working)
