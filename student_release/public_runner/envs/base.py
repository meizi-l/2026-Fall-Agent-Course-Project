from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


def _finite_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _binary_grading_score(value: Any, min_value: Any = 0.0, max_value: Any = 1.0) -> float:
    raw_value = _finite_float(value, 0.0)
    raw_min = _finite_float(min_value, 0.0)
    raw_max = _finite_float(max_value, 1.0)
    if raw_max <= raw_min:
        return 0.0
    return 1.0 if raw_value >= raw_max else 0.0


def _score_status(status: str, grading_score: float) -> str:
    if status in {"scored_success", "scored_failure"}:
        return "scored_success" if grading_score >= 1.0 else "scored_failure"
    return status


def _raw_score_details(
    *,
    raw_grading_score: float,
    raw_analysis_score: float,
    raw_min_score: float,
    raw_max_score: float,
    grading_score: float,
    analysis_score: float,
) -> dict[str, Any]:
    if (
        raw_grading_score == grading_score
        and raw_analysis_score == analysis_score
        and raw_min_score == 0.0
        and raw_max_score == 1.0
    ):
        return {}
    return {
        "grading_score_binary": True,
        "raw_grading_score": raw_grading_score,
        "raw_analysis_score": raw_analysis_score,
        "raw_min_score": raw_min_score,
        "raw_max_score": raw_max_score,
    }


@dataclass(frozen=True)
class BackendCaseResult:
    status: str
    reward: float
    max_reward: float
    events: list[dict[str, Any]]
    grading_score: float | None = None
    analysis_score: float | None = None
    max_score: float | None = None
    min_score: float | None = None

    def __post_init__(self) -> None:
        raw_min_score = _finite_float(self.min_score, 0.0)
        raw_max_score = _finite_float(self.max_score if self.max_score is not None else self.max_reward, 1.0)
        raw_grading_score = _finite_float(self.grading_score if self.grading_score is not None else self.reward, 0.0)
        raw_analysis_score = _finite_float(
            self.analysis_score if self.analysis_score is not None else raw_grading_score,
            raw_grading_score,
        )
        grading_score = _binary_grading_score(raw_grading_score, raw_min_score, raw_max_score)
        analysis_score = raw_analysis_score
        status = _score_status(self.status, grading_score)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "grading_score", grading_score)
        object.__setattr__(self, "analysis_score", analysis_score)
        object.__setattr__(self, "max_score", 1.0)
        object.__setattr__(self, "min_score", 0.0)
        object.__setattr__(self, "reward", grading_score)
        object.__setattr__(self, "max_reward", 1.0)


@dataclass(frozen=True)
class CaseScore:
    status: str
    reward: float
    max_reward: float
    details: dict[str, Any]
    grading_score: float | None = None
    analysis_score: float | None = None
    max_score: float | None = None
    min_score: float | None = None

    def __post_init__(self) -> None:
        raw_min_score = _finite_float(self.min_score, 0.0)
        raw_max_score = _finite_float(self.max_score if self.max_score is not None else self.max_reward, 1.0)
        raw_grading_score = _finite_float(self.grading_score if self.grading_score is not None else self.reward, 0.0)
        raw_analysis_score = _finite_float(
            self.analysis_score if self.analysis_score is not None else raw_grading_score,
            raw_grading_score,
        )
        grading_score = _binary_grading_score(raw_grading_score, raw_min_score, raw_max_score)
        analysis_score = raw_analysis_score
        status = _score_status(self.status, grading_score)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "grading_score", grading_score)
        object.__setattr__(self, "analysis_score", analysis_score)
        object.__setattr__(self, "max_score", 1.0)
        object.__setattr__(self, "min_score", 0.0)
        object.__setattr__(self, "reward", grading_score)
        object.__setattr__(self, "max_reward", 1.0)
        raw_details = _raw_score_details(
            raw_grading_score=raw_grading_score,
            raw_analysis_score=raw_analysis_score,
            raw_min_score=raw_min_score,
            raw_max_score=raw_max_score,
            grading_score=grading_score,
            analysis_score=analysis_score,
        )
        if raw_details:
            object.__setattr__(self, "details", {**self.details, **raw_details})


class TaskEnvironment:
    benchmark: str

    def __init__(self, benchmark: str, case: dict[str, Any]) -> None:
        self.benchmark = benchmark
        self.case = case
        self.case_id = str(case["case_id"])
        self._started = False
        self._done = False
        self._tool_results: list[dict[str, Any]] = []
        self.limits: dict[str, Any] = {}

    @property
    def done(self) -> bool:
        return self._done

    def start(self) -> None:
        self._started = True

    def configure_limits(self, limits: dict[str, Any]) -> None:
        self.limits = dict(limits)

    def observe(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "description": self.case.get("description", ""),
            "tool_results": self._tool_results,
        }

    def tools(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def score(self, final_content: str) -> CaseScore:
        reward = 1.0 if self._tool_results or final_content else 0.0
        status = "scored_success" if reward else "scored_failure"
        return CaseScore(status=status, reward=reward, max_reward=1.0, details={"score_source": "simplified_contract"})

    def close(self) -> None:
        return None
