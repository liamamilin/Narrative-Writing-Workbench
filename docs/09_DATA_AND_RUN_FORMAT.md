# 09 — Data and Run Format

## 1. Principle

Every run must preserve its intermediate trajectory.

The final text alone is insufficient.

## 2. Run Directory

```text
runs/
└── 000001/
    ├── input.json
    ├── wir.json
    ├── draft.md
    ├── critique.json
    ├── final.md
    ├── metadata.json
    └── raw/
        ├── architect.txt
        ├── critic.txt
        └── errors.txt
```

`raw/` may be omitted when no raw diagnostics are needed, but raw invalid outputs should be saved.

## 3. input.json

Suggested shape:

```json
{
  "material": "...",
  "instruction": "...",
  "task_type": "...",
  "constraints": {}
}
```

## 4. metadata.json

Suggested fields:

```json
{
  "run_id": "000001",
  "timestamp": "",
  "architect_model": "",
  "writer_model": "",
  "critic_model": "",
  "patcher_model": "",
  "architect_temperature": 0.2,
  "writer_temperature": 0.7,
  "critic_temperature": 0.1,
  "patcher_temperature": 0.3,
  "input_tokens": 0,
  "output_tokens": 0,
  "estimated_cost": 0.0,
  "latency_seconds": 0.0,
  "patched": false,
  "status": "success"
}
```

## 5. Why Preserve Trajectories

A run contains:

```text
Material
→ WIR
→ Draft
→ Critique
→ Final
```

This is potentially valuable future training data.

It preserves process supervision rather than only final answers.

## 6. Benchmark Output

Recommended:

```text
benchmarks/results/<experiment_id>/
├── config.json
├── outputs.jsonl
├── judgments.jsonl
└── summary.json
```

## 7. Reproducibility

Each benchmark experiment should preserve:

- prompt version/hash
- model names
- model parameters
- benchmark case IDs
- code version if available
- timestamp
