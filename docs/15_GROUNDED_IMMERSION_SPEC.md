# Grounded Immersion Specification

Status: normative concept definition for V1.1 (H4). Experimental only: no
production Writer prompt may be replaced by this mechanism until blind-review
data supports it.

## 1. Definition

**Grounded Immersion** = increased experiential presence using only supported
material, without inventing unsupported facts.

Immersion is treated not as "more description" but as *presence within what is
already licensed by the material and the instruction*. Where the V1 Writer
renders meaning progression, the Grounded-Immersion Writer additionally
maximizes the reader's being-inside-the-scene, subject to a hard fact license.

## 2. Licensed techniques (may use)

1. **Perspective proximity** — anchor perception in the licensed viewpoint
   character/voice; stay close to what they can perceive.
2. **Supported sensory detail** — sensory wording for properties already
   stated or entailed by the material (a burned field may be described as
   ash-grey; an unmentioned weather may not).
3. **Action instead of explanation** — render stated behavior as behavior;
   do not annotate it with emotion labels.
4. **Information sequencing** — order sentences so that discovery happens in
   scene-time, not summary-time, without changing what is known when (WIR
   reveal timing remains binding).
5. **Pauses and silence** — ellipsis, short sentences, withheld commentary at
   licensed gaps.
6. **Concrete wording** — prefer the most specific term that the material
   supports.
7. **Sentence rhythm** — vary length to match the tension of the beat.
8. **Semantic echo** — recur key concrete images across beats (not slogans).
9. **Controlled omission** — leave licensed-but-unnecessary facts out to keep
   the experiential line unbroken.

## 3. Prohibited (must not rely on)

- invented biography or past events
- invented dialogue
- invented objects with story significance
- invented character motives
- fabricated memories
- unsupported environmental details that change interpretation

These are the same categories the V1 benchmark review penalized (ER_001,
FS_001: immersion gains bought with fabricated facts). Grounded Immersion is
defined precisely to break that trade-off.

## 4. Precedence

factual fidelity > WIR fidelity > immersion. Immersion never licenses a fact.
When presence would require an unsupported detail, the text stays at the
factual level and uses §2.5 (pause/omission) instead.

## 5. Implementation surface

- `prompts/writer_gi.md`: production writer rules + §2 technique block + §3
  prohibition block + §4 precedence.
- Variants `A2_GI` (and optionally `A3_GI`) per docs/14 §3.
- Hard gates (docs/14 §5) apply unchanged; the `factual_fidelity` gate is one
  enforcement layer, the Critic's fidelity check another.

## 6. Evaluation requirement (H4)

A2_GI vs A2 blind review must show:

- `immersion` win-rate > 0.5 to count as a gain; and
- no regression on `restraint`, `meaning_density`, `coherence` (win-rate ≥ 0.4
  and no statistically obvious loss pattern), and
- zero increase in hard-gate `factual_fidelity` failures.

If immersion gains coincide with fidelity failures, the mechanism is rejected
for production regardless of literary scores.
