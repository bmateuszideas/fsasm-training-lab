# Systematic Debugging

Use whenever a test fails, a workflow behaves unexpectedly, a regression appears, or a fix would otherwise be guesswork.

## Core rule

Do not propose a fix until you can state:

1. what is failing
2. where the state/value first becomes wrong
3. what contract or invariant is violated
4. why the proposed change fixes that cause

## Loop

### 1. Reproduce

Run the narrowest command that demonstrates the failure.

Capture the exact failing assertion/error, state, and stack location.

### 2. Trace the boundary path

Follow the relevant value/state through boundaries such as:

```text
input
→ domain transition
→ workflow/activity
→ serialization boundary
→ persistence
→ reload
→ verification
→ final result
```

At each boundary ask:

- what entered?
- what returned?
- what was persisted?
- what is authoritative?
- was in-memory mutation incorrectly assumed to propagate?

### 3. Find the first invalid state

Fix the earliest causal violation, not the latest symptom.

### 4. Confirm the contract

Read the authoritative source: transition rules, model schema, brief, tests, framework docs, or project instructions.

Do not derive the contract from buggy code.

### 5. Apply the smallest causal fix

Change the layer that owns the responsibility.

Avoid broad refactors unless the root cause requires them.

### 6. Add regression proof

Add a test that would have failed before the fix at the correct level:

- pure domain
- activity/persistence
- real worker/integration

### 7. Re-run outward

Run:

1. failing test
2. related module tests
3. milestone tests
4. full suite
5. required checks

## Anti-patterns

Do not:

- randomly change multiple layers
- loosen assertions to hide the bug
- widen accepted states when only one state is correct
- replace a required integration proof with a mock
- assume mutation crosses serialization boundaries
- reset unrelated completed work because one edit failed
