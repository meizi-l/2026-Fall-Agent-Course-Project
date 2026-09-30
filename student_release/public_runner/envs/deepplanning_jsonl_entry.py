from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, TextIO
import uuid


@dataclass(frozen=True)
class ShoppingCaseId:
    level: int
    sample_id: str
    case_dir_name: str


def parse_shopping_case_id(case_id: str) -> ShoppingCaseId:
    parts = case_id.split("/")
    if len(parts) != 3 or parts[0] != "shopping" or not parts[1].startswith("level_") or not parts[2].startswith("case_"):
        raise ValueError("DeepPlanning Shopping case_id must be shopping/level_<1|2|3>/case_<id>")
    try:
        level = int(parts[1].removeprefix("level_"))
    except ValueError as exc:
        raise ValueError("DeepPlanning Shopping case_id must be shopping/level_<1|2|3>/case_<id>") from exc
    if level not in {1, 2, 3}:
        raise ValueError("DeepPlanning Shopping level must be 1, 2, or 3")
    sample_id = parts[2].removeprefix("case_")
    if not sample_id:
        raise ValueError("DeepPlanning Shopping case id cannot be empty")
    return ShoppingCaseId(level=level, sample_id=sample_id, case_dir_name=parts[2])


class DeepPlanningShoppingSession:
    def __init__(self, benchmark_root: Path, work_root: Path | None = None) -> None:
        self.benchmark_root = benchmark_root
        self.work_root = work_root or Path(tempfile.mkdtemp(prefix="course_deepplanning_"))
        self.case: ShoppingCaseId | None = None
        self.case_dir: Path | None = None
        self.database_base_path: Path | None = None
        self.query = ""
        self.tools_schema: list[dict[str, Any]] = []
        self.tool_instances: dict[str, Any] = {}
        self.messages: list[dict[str, Any]] = []

    def start(self, case_id: str) -> dict[str, Any]:
        self.case = parse_shopping_case_id(case_id)
        self.query = self._load_query(self.case)
        source_case_dir = self.benchmark_root / f"database_level{self.case.level}" / self.case.case_dir_name
        if not source_case_dir.exists():
            raise FileNotFoundError(f"DeepPlanning case directory not found: {source_case_dir}")

        self.database_base_path = self.work_root / f"database_level{self.case.level}"
        self.database_base_path.mkdir(parents=True, exist_ok=True)
        self.case_dir = self.database_base_path / self.case.case_dir_name
        if not self.case_dir.exists():
            shutil.copytree(source_case_dir, self.case_dir)

        self.tools_schema = self._load_tool_schema()
        self.tool_instances = self._load_tool_instances(self.case_dir)
        self.messages = [{"role": "user", "content": self.query}]
        self._write_messages("Initial query")
        return self.observe()

    def tools(self) -> list[dict[str, Any]]:
        return self.tools_schema

    def observe(self) -> dict[str, Any]:
        self._require_started()
        return {
            "case_id": f"shopping/level_{self.case.level}/{self.case.case_dir_name}",
            "level": self.case.level,
            "shopping_case_id": self.case.sample_id,
            "query": self.query,
            "cart": self._load_cart(),
        }

    def execute_tool(self, tool_name: str, tool_arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_started()
        tool = self.tool_instances.get(tool_name)
        if tool is None:
            raise KeyError(f"unknown DeepPlanning tool: {tool_name}")
        tool_call_id = f"call_{uuid.uuid4().hex[:24]}"
        self.messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": json.dumps(tool_arguments, ensure_ascii=False)},
                    }
                ],
            }
        )
        with contextlib.redirect_stdout(sys.stderr):
            raw_result = tool.call(json.dumps(tool_arguments, ensure_ascii=False))
        self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": raw_result})
        self._write_messages(f"Executed {tool_name}")
        if isinstance(raw_result, str):
            try:
                parsed = json.loads(raw_result)
            except json.JSONDecodeError:
                parsed = {"raw": raw_result}
        elif isinstance(raw_result, dict):
            parsed = raw_result
        else:
            parsed = {"raw": raw_result}
        if isinstance(parsed, dict) and "error" in parsed:
            raise RuntimeError(str(parsed["error"]))
        return parsed if isinstance(parsed, dict) else {"result": parsed}

    def score(self, final_content: str) -> dict[str, Any]:
        self._require_started()
        self.messages.append({"role": "assistant", "content": final_content})
        self._write_messages("Final answer")
        evaluation_result = self._evaluate()
        grading_score = float(evaluation_result.get("case_score", 0.0) or 0.0)
        match_score = float(evaluation_result.get("score", 0.0) or 0.0)
        status = "scored_success" if grading_score >= 1.0 else "scored_failure"
        return {
            "status": status,
            "grading_score": grading_score,
            "analysis_score": match_score,
            "min_score": 0.0,
            "max_score": 1.0,
            "reward": grading_score,
            "max_reward": 1.0,
            "details": {
                "score_source": "deepplanning_official",
                "deepplanning_match_score": match_score,
                "matched_count": evaluation_result.get("matched_count", 0),
                "expected_count": evaluation_result.get("expected_count", 0),
                "extra_products_count": evaluation_result.get("extra_products_count", 0),
                "is_completed": evaluation_result.get("is_completed", False),
                "work_dir": str(self.work_root),
            },
        }

    def _load_query(self, case: ShoppingCaseId) -> str:
        metadata_path = self.benchmark_root / "data" / f"level_{case.level}_query_meta.json"
        samples = json.loads(metadata_path.read_text(encoding="utf-8"))
        for sample in samples:
            if str(sample.get("id")) == case.sample_id:
                return str(sample.get("query", ""))
        validation_path = self.benchmark_root / f"database_level{case.level}" / case.case_dir_name / "validation_cases.json"
        if validation_path.exists():
            return str(json.loads(validation_path.read_text(encoding="utf-8")).get("query", ""))
        raise ValueError(f"DeepPlanning query metadata not found for case {case.case_dir_name}")

    def _load_tool_schema(self) -> list[dict[str, Any]]:
        schema_path = self.benchmark_root / "tools" / "shopping_tool_schema.json"
        value = json.loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise RuntimeError("DeepPlanning shopping tool schema must be a list")
        return value

    def _load_tool_instances(self, case_dir: Path) -> dict[str, Any]:
        tools_dir = self.benchmark_root / "tools"
        for path in (str(tools_dir), str(self.benchmark_root)):
            if path not in sys.path:
                sys.path.insert(0, path)
        with contextlib.redirect_stdout(sys.stderr):
            import tools  # noqa: F401
            import base_shopping_tool  # type: ignore

        registry = getattr(base_shopping_tool, "TOOL_REGISTRY", {})
        return {name: tool_cls(cfg={"database_path": str(case_dir)}) for name, tool_cls in registry.items()}

    def _load_cart(self) -> dict[str, Any]:
        if self.case_dir is None:
            return {}
        cart_path = self.case_dir / "cart.json"
        if not cart_path.exists():
            return {}
        return json.loads(cart_path.read_text(encoding="utf-8"))

    def _write_messages(self, description: str) -> None:
        if self.case_dir is None:
            return
        payload = {"step": len(self.messages), "description": description, "messages": self.messages}
        (self.case_dir / "messages.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _evaluate(self) -> dict[str, Any]:
        if self.case_dir is None:
            raise RuntimeError("DeepPlanning session has not started")
        if str(self.benchmark_root) not in sys.path:
            sys.path.insert(0, str(self.benchmark_root))
        with contextlib.redirect_stdout(sys.stderr):
            from evaluation.evaluation_pipeline import evaluate_single_case

            result = evaluate_single_case(self.case_dir)
        return result

    def _require_started(self) -> None:
        if self.case is None or self.case_dir is None:
            raise RuntimeError("DeepPlanning session has not started")


def handle_request(session: DeepPlanningShoppingSession, request: dict[str, Any]) -> Any:
    command = request.get("command")
    if command == "start":
        return session.start(str(request["case_id"]))
    if command == "tools":
        return session.tools()
    if command == "observe":
        return session.observe()
    if command == "execute_tool":
        arguments = request.get("tool_arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("tool_arguments must be an object")
        return session.execute_tool(str(request["tool_name"]), arguments)
    if command == "score":
        return session.score(str(request.get("final_content", "")))
    if command == "close":
        return {"closed": True}
    raise ValueError(f"unknown DeepPlanning adapter command: {command!r}")


def serve(session: DeepPlanningShoppingSession, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    for line in stdin:
        if not line.strip():
            continue
        request: dict[str, Any] | None = None
        try:
            request = json.loads(line)
            result = handle_request(session, request)
            response = {"ok": True, "result": result}
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            response = {"ok": False, "error_type": type(exc).__name__, "message": str(exc) or type(exc).__name__}
        stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        stdout.flush()
        if request is not None and request.get("command") == "close":
            break
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeepPlanning Shopping course adapter")
    parser.add_argument("command", choices=["serve"])
    parser.add_argument("--benchmark-root", required=True)
    parser.add_argument("--work-root")
    args = parser.parse_args(argv)

    work_root = Path(args.work_root) if args.work_root else None
    session = DeepPlanningShoppingSession(Path(args.benchmark_root), work_root)
    return serve(session)


if __name__ == "__main__":
    raise SystemExit(main())
