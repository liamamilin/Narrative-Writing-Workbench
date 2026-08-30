# 00 — Project Overview

## 1. Project Name

**Narrative Writing Harness**

Working abbreviation: **NWH**

## 2. Problem

Large language models can produce fluent prose, but direct generation often exhibits:

- premature explanation
- weak information sequencing
- repeated meaning
- generic abstraction
- fake depth
- mechanical rhetorical patterns
- weak endings
- excessive rewriting during self-critique

The core hypothesis is that writing quality improves when writing is decomposed into explicit cognitive stages rather than executed as one generation step.

## 3. Core Model

```text
Material
  ↓
Meaning Selection
  ↓
Reader-State Design
  ↓
Writing Intermediate Representation (WIR)
  ↓
Language Realization
  ↓
Audit
  ↓
Minimal Patch
```

## 4. V1 Pipeline

```text
Input
  ↓
Architect
  ↓
WIR
  ↓
Writer
  ↓
Draft
  ↓
Critic
  ├─ PASS → Final
  └─ PATCH_REQUIRED
         ↓
      Patcher
         ↓
       Final
```

## 5. V1 Hypotheses

### H1
A WIR-guided workflow produces higher-quality writing than direct generation.

### H2
Reader-State WIR produces better progression and immersion than a conventional outline.

### H3
Critic + Patch improves quality while preserving successful passages better than full regeneration.

## 6. V1 Scope

V1 must support:

- one input request
- one Architect pass
- one Writer pass
- one Critic pass
- zero or one Patch pass
- structured run persistence
- benchmark execution
- provider-independent LLM interface

## 7. Non-Goals

V1 does not include:

- fine-tuning
- LoRA
- RAG
- style cloning
- author fingerprinting
- dynamic writing-pattern retrieval
- automatic multi-round agent debate
- autonomous prompt optimization
- production UI (superseded: the desktop web workbench is now specified in
  `docs/narrative-writing-product-v0-spec/`, authoritative for the product layer)
- vector databases
- distributed workers

## 8. Core Design Principle

The system does not ask:

> What sentence should come next?

It asks:

> What should change in the reader's knowledge, belief, expectation, or emotion next?

The language is then generated to realize that transition.

## 9. Success Condition

V1 is successful if benchmark results show that the WIR workflow reliably improves at least the intended structural dimensions:

- immersion
- progression
- meaning density
- restraint
- coherence

while not materially degrading naturalness.
