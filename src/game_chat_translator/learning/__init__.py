"""Evidence-gated, local-only glossary learning."""

from game_chat_translator.learning.domain import (
    Candidate,
    CandidateStatus,
    Evidence,
    LearningDecision,
    LearningPolicy,
    Observation,
    OverlayExport,
)
from game_chat_translator.learning.learner import GlossaryLearner
from game_chat_translator.learning.repository import InMemoryLearningRepository, LearningRepository

__all__ = [
    "Candidate",
    "CandidateStatus",
    "Evidence",
    "GlossaryLearner",
    "InMemoryLearningRepository",
    "LearningDecision",
    "LearningPolicy",
    "LearningRepository",
    "Observation",
    "OverlayExport",
]
