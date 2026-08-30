# 11 — Acceptance Criteria

## 1. Functional Acceptance

V1 must satisfy:

- [ ] input enters full pipeline
- [ ] Architect returns schema-valid WIR
- [ ] Writer consumes WIR
- [ ] Critic returns schema-valid critique
- [ ] PASS skips Patcher
- [ ] PATCH_REQUIRED triggers exactly one patch
- [ ] final text is returned
- [ ] all intermediate artifacts are persisted
- [ ] invalid structured output is handled explicitly
- [ ] at least 10 smoke benchmark cases run end-to-end

## 2. Architecture Acceptance

- [ ] agent responsibilities are separated
- [ ] prompts are externalized
- [ ] schemas are externalized
- [ ] model provider is replaceable
- [ ] orchestration does not depend on a heavy agent framework
- [ ] WIR is immutable after Architect stage unless the run fails
- [ ] configuration is not hardcoded into business logic

## 3. Quality Acceptance

The system must demonstrate that it is more than a prompt wrapper.

At minimum, manual inspection of smoke cases should confirm:

- [ ] WIR contains explicit reader-state transitions
- [ ] reveal timing is actually reflected in drafts
- [ ] Critic identifies specific failures
- [ ] preserve list affects patch behavior
- [ ] patched output is not simply a full regeneration

## 4. Benchmark Acceptance

Before claiming V1 effectiveness:

- compare against at least B0 and B1
- use anonymous pairwise evaluation
- report per-dimension results
- preserve all raw benchmark outputs

## 5. V1 Research Acceptance

The strongest acceptance evidence is:

- WIR improves progression/immersion against Direct
- Reader-State representation adds value beyond a normal outline
- Patch preserves strong passages better than full rewrite

These are research claims and must be supported by benchmark data, not intuition alone.

## 6. Explicit Non-Acceptance

The following do not count as completion:

- "the code runs"
- one impressive example
- subjective developer preference
- a prompt that merely mentions immersion and literary quality
- adding more agents without measurement
