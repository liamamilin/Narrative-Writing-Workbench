# 01 — Architecture

## 1. System Components

V1 contains four logical agents:

1. Architect
2. Writer
3. Critic
4. Patcher

These may use the same underlying model with different prompts.

## 2. Data Flow

```text
User Input
   │
   ▼
Architect
   │
   ├─ Source Material
   ├─ Writing Instruction
   └─ Task Constraints
   │
   ▼
WIR
   │
   ▼
Writer
   │
   ▼
Draft
   │
   ▼
Critic
   │
   ├─ PASS ────────────────► Final
   │
   └─ PATCH_REQUIRED
              │
              ▼
           Patcher
              │
              ▼
            Final
```

## 3. Architectural Separation

### Architect
Designs meaning progression and reader-state transitions.

### Writer
Renders WIR into prose.

### Critic
Audits WIR fidelity and prose quality.

### Patcher
Makes the smallest necessary revision.

## 4. V1 Constraints

- No graph orchestration framework.
- No recursive agent loops.
- At most one patch pass.
- No hidden mutation of WIR after Architect output.
- All structured outputs must be schema-valid.
- All stages must be persisted.

## 5. Recommended Runtime Modules

```text
app/
├── llm_client.py
├── architect.py
├── writer.py
├── critic.py
├── patcher.py
├── pipeline.py
├── persistence.py
└── models.py
```

## 6. Control Flow

Pseudo-code:

```python
def run(material, instruction, config):
    wir = architect(material, instruction, config)

    draft = writer(
        material=material,
        instruction=instruction,
        wir=wir,
        config=config,
    )

    critique = critic(
        material=material,
        instruction=instruction,
        wir=wir,
        draft=draft,
        config=config,
    )

    if critique.decision == "PASS":
        final = draft
    else:
        final = patcher(
            material=material,
            instruction=instruction,
            wir=wir,
            draft=draft,
            critique=critique,
            config=config,
        )

    persist_all(...)
    return final
```

## 7. Failure Handling

If an agent returns invalid structured output:

1. attempt one structured-output repair call;
2. do not silently guess missing fields;
3. if repair fails, mark run failed;
4. save raw output and validation error.

## 8. Provider Abstraction

Model calls must be accessed through a common interface.

Example:

```python
class LLMClient:
    def generate_text(...)
    def generate_structured(...)
```

No business logic should depend on a specific provider SDK.

## 9. Configuration

Configuration should support per-role:

- model
- temperature
- max output tokens
- timeout
- structured-output mode

Do not hardcode model names inside agent modules.
