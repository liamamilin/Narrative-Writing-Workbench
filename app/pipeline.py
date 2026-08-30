"""Pipeline: single entry point for the V1 workflow.

    Architect -> WIR -> Writer -> Draft -> Critic -> (optional Patcher) -> Final

All intermediate artifacts are persisted; failed runs preserve diagnostics.
"""

from __future__ import annotations

import logging

from .architect import ArchitectAgent
from .config import Config
from .critic import CriticAgent
from .llm_client import LLMClient, build_client
from .models import RunResult, StageResult, StructuredOutputError, Usage
from .patcher import PatcherAgent
from .persistence import RunStore
from .prompts import prompt_version_info
from .schemas import SchemaSet
from .utils import now_iso
from .writer import WriterAgent

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        config: Config | None = None,
        client: LLMClient | None = None,
        store: RunStore | None = None,
        schemas: SchemaSet | None = None,
    ):
        self.config = config or Config.default()
        self.client = client or build_client(self.config)
        self.schemas = schemas or SchemaSet(self.config.schemas_dir)
        self.store = store or RunStore(self.config.runs_dir, schemas=self.schemas)
        self.architect = ArchitectAgent(self.client, self.config, self.schemas)
        self.writer = WriterAgent(self.client, self.config)
        self.critic = CriticAgent(self.client, self.config, self.schemas)
        self.patcher = PatcherAgent(self.client, self.config)

    # ------------------------------------------------------------------

    def run(
        self,
        material: str,
        instruction: str,
        task_type: str = "narrative_commentary",
        constraints: dict | None = None,
    ) -> RunResult:
        run_id = self.store.create_run()
        usage = Usage()
        warnings: list[str] = []
        self.store.save_input(
            run_id,
            {
                "material": material,
                "instruction": instruction,
                "task_type": task_type,
                "constraints": constraints or {},
            },
        )
        logger.info("run %s: started", run_id)

        try:
            arch = self._stage(run_id, "architect", lambda: self.architect.run(
                material, instruction, task_type, constraints
            ))
            usage = usage.add(arch.usage)
            wir = arch.data
            self.store.save_wir(run_id, wir)
            logger.info("run %s: WIR produced (%d beats)", run_id, len(wir.get("beats", [])))

            wr = self._stage(run_id, "writer", lambda: self.writer.run(material, instruction, wir))
            usage = usage.add(wr.usage)
            draft = wr.data
            self.store.save_draft(run_id, draft)
            logger.info("run %s: draft written (%d chars)", run_id, len(draft))

            cr = self._stage(run_id, "critic", lambda: self.critic.run(
                material, instruction, wir, draft
            ))
            usage = usage.add(cr.usage)
            critique = cr.data
            warnings.extend(cr.warnings)
            self.store.save_critique(run_id, critique)

            decision = critique["decision"]
            patched = False
            if decision == "PASS":
                final = draft
                logger.info("run %s: PASS -> final = draft", run_id)
            else:
                pr = self._stage(run_id, "patcher", lambda: self.patcher.run(
                    material, instruction, wir, draft, critique
                ))
                usage = usage.add(pr.usage)
                final = pr.data
                patched = True
                warnings.extend(self._patch_diagnostics(draft, final, critique))
                logger.info("run %s: PATCH_REQUIRED -> patched (%d chars)", run_id, len(final))

            self.store.save_final(run_id, final)
            self._save_metadata(run_id, usage, patched, "success", warnings)
            logger.info("run %s: success", run_id)
            return RunResult(
                run_id=run_id,
                status="success",
                final_text=final,
                wir=wir,
                draft=draft,
                critique=critique,
                patched=patched,
                usage=usage,
                errors=[],
                run_dir=str(self.store.run_dir_path(run_id)),
            )

        except StructuredOutputError as exc:
            errors = [str(exc)] + [f"schema: {e}" for e in exc.errors]
            self.store.save_raw(run_id, f"{exc.stage}_invalid", exc.raw)
            self.store.append_error(run_id, "\n".join(errors))
            self._save_metadata(run_id, usage, False, "failed", warnings + errors)
            logger.error("run %s: failed at stage '%s'", run_id, exc.stage)
            return self._failed(run_id, errors, usage)

        except Exception as exc:  # provider/network/etc: preserve everything we have
            errors = [f"{type(exc).__name__}: {exc}"]
            self.store.append_error(run_id, "\n".join(errors))
            self._save_metadata(run_id, usage, False, "failed", warnings + errors)
            logger.error(
                "run %s: failed (%s)", run_id, exc,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
            return self._failed(run_id, errors, usage)

    # ------------------------------------------------------------------

    def _stage(self, run_id: str, stage: str, fn) -> StageResult:
        result = fn()
        self.store.save_raw(run_id, stage, result.raw)
        for warning in result.warnings:
            logger.warning("run %s [%s]: %s", run_id, stage, warning)
            self.store.append_error(run_id, f"[warning][{stage}] {warning}")
        return result

    def _patch_diagnostics(self, draft: str, patched: str, critique: dict) -> list[str]:
        """Flag suspicious full-rewrite behavior (docs/06: patch != rewrite)."""
        notes: list[str] = []
        if not draft.strip():
            return notes
        change_ratio = 1.0 - (
            len(set(draft) & set(patched)) / max(1, len(set(draft)))
        )
        # Character-set overlap is a crude diagnostic only; report change size.
        size_delta = abs(len(patched) - len(draft)) / max(1, len(draft))
        if size_delta > 0.6:
            notes.append(
                f"patcher size delta {size_delta:.0%} (>60%): possible full regeneration"
            )
        preserve = critique.get("preserve") or []
        if preserve and patched.strip() == draft.strip():
            notes.append("patcher returned text identical to draft")
        return notes

    def _save_metadata(
        self,
        run_id: str,
        usage: Usage,
        patched: bool,
        status: str,
        warnings: list[str],
    ) -> None:
        roles = self.config.roles
        metadata = {
            "run_id": run_id,
            "timestamp": now_iso(),
            "models": {name: roles[name].model for name in roles},
            "parameters": {
                "provider": self.config.provider,
                "temperatures": {name: roles[name].temperature for name in roles},
                "max_output_tokens": {name: roles[name].max_output_tokens for name in roles},
                "timeouts_seconds": {name: roles[name].timeout_seconds for name in roles},
                "structured_modes": {name: roles[name].structured_mode for name in roles},
                "thresholds": {
                    "max_moderate_issues": self.config.thresholds.max_moderate_issues,
                    "min_writing_quality": self.config.thresholds.min_writing_quality,
                },
                "prompts": prompt_version_info(
                    self.config.prompts_dir, ["architect", "writer", "critic", "patcher"]
                ),
                "warnings": warnings,
            },
            "usage": usage.to_dict(),
            "patched": patched,
            "status": status,
        }
        self.store.save_metadata(run_id, metadata)

    def _failed(self, run_id: str, errors: list[str], usage: Usage) -> RunResult:
        return RunResult(
            run_id=run_id,
            status="failed",
            final_text=None,
            wir=None,
            draft=None,
            critique=None,
            patched=False,
            usage=usage,
            errors=errors,
            run_dir=str(self.store.run_dir_path(run_id)),
        )
