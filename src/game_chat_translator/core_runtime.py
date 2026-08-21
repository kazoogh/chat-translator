from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from game_chat_translator.learning import GlossaryLearner
from game_chat_translator.model_management import (
    DownloadCommand,
    HardwareProfile,
    ModelLifecycleManager,
    ModelOutcome,
    ModelSource,
    UrllibModelSource,
    probe_hardware,
    recommend_model,
)
from game_chat_translator.resource_paths import bundled_resource_root
from game_chat_translator.settings import default_data_dir
from game_chat_translator.storage import (
    HistoryRepository,
    SqliteLearningRepository,
    SqliteModelStateStore,
)
from game_chat_translator.storage.database import Database
from game_chat_translator.storage.repositories import SqliteStateRepository
from game_chat_translator.translation import (
    ArgosProviderFactory,
    BuiltinCorpusTranslationProvider,
    IsolatedTranslationProvider,
    LlamaCppProviderFactory,
    TranslationPipeline,
    TranslationProvider,
    TranslationRouter,
)
from game_chat_translator.validation.schemas import ModelEntry
from game_chat_translator.validation.validators import validate_model_manifest


@dataclass(frozen=True, slots=True)
class ModelOption:
    model_id: str
    provider: str
    languages: tuple[str, ...]
    hardware_tier: str
    size_bytes: int
    license_id: str
    installed: bool


ContextualFactory = Callable[[ModelEntry, Path], TranslationProvider]
LightweightFactory = Callable[[], TranslationProvider]


class CoreRuntime:
    """Slice-4 composition root used by setup CLI now and desktop UI in Slice 5."""

    def __init__(
        self,
        *,
        resource_root: Path | None = None,
        state_path: Path | None = None,
        model_root: Path | None = None,
        source: ModelSource | None = None,
        model_health_check: Callable[[ModelEntry, Path], bool] | None = None,
        contextual_factory: ContextualFactory | None = None,
        lightweight_factory: LightweightFactory | None = None,
    ) -> None:
        self.resource_root = (resource_root or bundled_resource_root()).resolve()
        app_data = default_data_dir()
        self._database = Database(state_path or app_data / "state.sqlite3")
        self._database.open()
        self._manifest = validate_model_manifest(
            self.resource_root / "data" / "models" / "manifest.v1.json"
        )
        self._contextual_factory = contextual_factory or _contextual_provider
        self._lightweight_factory = lightweight_factory or _argos_provider
        self._model_manager = ModelLifecycleManager(
            model_root or app_data / "models",
            source or UrllibModelSource(),
            model_health_check or _model_health_check,
            allowed_entries=self._manifest.models,
            store=SqliteModelStateStore(self._database),
        )
        self._pipelines: list[TranslationPipeline] = []
        self._pipeline_models: dict[int, str] = {}
        self._compute_closed = False
        self._storage_closed = False
        self._closed = False
        self._layout_generation = 0

    @property
    def manifest_entries(self) -> tuple[ModelEntry, ...]:
        return self._manifest.models

    @property
    def active_pipeline_count(self) -> int:
        return len(self._pipelines)

    def model_options(self) -> tuple[ModelOption, ...]:
        return tuple(
            ModelOption(
                entry.model_id,
                entry.provider,
                entry.languages,
                entry.hardware_tier,
                entry.size_bytes,
                entry.license_id,
                self._model_manager.active_path(entry.model_id) is not None
                or self._model_manager.restore(entry),
            )
            for entry in self._manifest.models
        )

    def recommended_model(
        self, hardware: HardwareProfile | None = None, *, override: str | None = None
    ) -> ModelEntry | None:
        return recommend_model(
            self._manifest.models, hardware or probe_hardware(), override_model_id=override
        )

    def download_model(
        self,
        model_id: str,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        progress: Callable[[int, int], None] | None = None,
    ) -> ModelOutcome:
        entry = self._entry(model_id)
        return self._model_manager.download(
            DownloadCommand(entry), cancelled=cancelled, progress=progress
        )

    def remove_model(self, model_id: str) -> ModelOutcome:
        entry = self._entry(model_id)
        self._model_manager.restore(entry)
        self._model_manager.deactivate(model_id)
        return self._model_manager.remove(model_id)

    def build_translation_pipeline(
        self,
        *,
        model_id: str | None = None,
        initial_generations: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0),
    ) -> TranslationPipeline:
        entry = self._entry(model_id) if model_id else self.recommended_model()
        contextual: TranslationProvider | None = None
        if entry is not None:
            path = self._model_manager.active_path(entry.model_id)
            if path is None and self._model_manager.restore(entry):
                path = self._model_manager.active_path(entry.model_id)
            if path is not None:
                contextual = self._contextual_factory(entry, path)
                self._model_manager.mark_in_use(entry.model_id, True)
        router = TranslationRouter(
            contextual,
            self._lightweight_factory(),
            additional_fallbacks=(BuiltinCorpusTranslationProvider(),),
        )
        pipeline = TranslationPipeline(router, initial_generations=initial_generations)
        self._pipelines.append(pipeline)
        if contextual is not None and entry is not None:
            self._pipeline_models[id(pipeline)] = entry.model_id
        return pipeline

    def release_pipeline(self, pipeline: TranslationPipeline) -> None:
        pipeline.close()
        model_id = self._pipeline_models.pop(id(pipeline), None)
        if model_id is not None:
            self._model_manager.mark_in_use(model_id, False)
        with suppress(ValueError):
            self._pipelines.remove(pipeline)

    def glossary_learner(
        self,
        profile_id: str,
        *,
        known_aliases: dict[str, str] | None = None,
        existing_canonical_terms: set[str] | frozenset[str] = frozenset(),
        usernames: set[str] | frozenset[str] = frozenset(),
    ) -> GlossaryLearner:
        return GlossaryLearner(
            SqliteLearningRepository(self._database, profile_id),
            known_aliases=known_aliases,
            existing_canonical_terms=existing_canonical_terms,
            usernames=usernames,
        )

    def history_repository(self) -> HistoryRepository:
        return HistoryRepository(self._database)

    def state_repository(self) -> SqliteStateRepository:
        return SqliteStateRepository(self._database)

    def clear_translation_history(self) -> None:
        for pipeline in tuple(self._pipelines):
            pipeline.clear_history()

    def advance_layout_generation(self) -> int:
        self._layout_generation = (
            max(
                (pipeline.generations[1] for pipeline in self._pipelines),
                default=self._layout_generation,
            )
            + 1
        )
        for pipeline in tuple(self._pipelines):
            profile, _layout, context, glossary, model, config = pipeline.generations
            pipeline.advance_generations(
                profile=profile,
                layout=self._layout_generation,
                context=context,
                glossary=glossary,
                model=model,
                config=config,
            )
        return self._layout_generation

    def close_compute(self) -> None:
        if self._compute_closed:
            return
        self._compute_closed = True
        for pipeline in tuple(reversed(self._pipelines)):
            self.release_pipeline(pipeline)

    def close_storage(self) -> None:
        if self._storage_closed:
            return
        self._storage_closed = True
        self._database.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.close_compute()
        self.close_storage()

    def __enter__(self) -> CoreRuntime:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _entry(self, model_id: str | None) -> ModelEntry:
        if model_id is None:
            raise ValueError("model ID is required")
        entry = next((item for item in self._manifest.models if item.model_id == model_id), None)
        if entry is None:
            raise ValueError("model ID is not in the bundled allowlist")
        return entry


def _contextual_provider(entry: ModelEntry, path: Path) -> TranslationProvider:
    return IsolatedTranslationProvider(
        LlamaCppProviderFactory(path, entry.model_id),
        provider_id="llama_cpp",
        model_id=entry.model_id,
    )


def _argos_provider() -> TranslationProvider:
    return IsolatedTranslationProvider(ArgosProviderFactory(), provider_id="argos", model_id=None)


def _model_health_check(entry: ModelEntry, path: Path) -> bool:
    provider = _contextual_provider(entry, path)
    try:
        return provider.health_check()
    finally:
        provider.close()
