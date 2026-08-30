# 07 — Benchmark Specification

## 1. Purpose

The benchmark tests whether architectural decomposition improves writing quality.

It must not be designed only around one preferred style.

## 2. V1 Dataset

Target: 50 cases.

Five task families:

| Task | Cases |
|---|---:|
| Narrative Commentary | 10 |
| Character Analysis | 10 |
| Fiction Scene | 10 |
| Concept Essay | 10 |
| Emotional Retelling | 10 |

## 3. Task Definitions

### Narrative Commentary
Analyze a narrative mechanism, theme, or story effect.

### Character Analysis
Explain a character's motive, contradiction, transformation, or appeal.

### Fiction Scene
Generate or rewrite an actual scene with actions, dialogue, and perspective.

### Concept Essay
Explain an abstract idea with controlled argument and prose.

### Emotional Retelling
Reorder and frame fixed facts to create emotional weight without inventing facts.

## 4. Benchmark Case Format

```json
{
  "id": "ER_001",
  "task_type": "emotional_retelling",
  "difficulty": 3,
  "material": "...",
  "instruction": "...",
  "target_length": 800,
  "requires_reversal": false,
  "requires_character_perspective": true,
  "primary_metric": "immersion"
}
```

## 5. Baselines

### B0 — Direct
A minimal quality instruction.

### B1 — Strong Prompt
A detailed writing prompt describing desired qualities.

### B2 — Few-Shot
Strong prompt plus representative examples.

### B3 — WIR Workflow
Architect → WIR → Writer → Critic → Patch.

## 6. Important Rule

The WIR system must not be judged only against a weak prompt.

The meaningful question is:

> Does architecture outperform a strong prompt or few-shot baseline?

## 7. Smoke Benchmark

Before the full 50-case benchmark, implement 10 smoke cases:

- 2 Narrative Commentary
- 2 Character Analysis
- 2 Fiction Scene
- 2 Concept Essay
- 2 Emotional Retelling

## 8. Later Ablations

Not required for first implementation, but benchmark design should support:

- Direct
- Direct + Critic
- Outline + Writer + Critic
- WIR without reader-state fields
- Full WIR

## 9. Data Integrity

Benchmark cases must remain fixed during model comparison.

Do not tune prompts directly on the final benchmark set.
