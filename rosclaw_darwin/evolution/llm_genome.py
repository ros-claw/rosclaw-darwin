"""LLM-powered Task Genome Engine.

Extends the genetic TaskGenomeEngine with semantic task generation via
Claude/GPT API. Instead of randomly combining primitives, the LLM
understands the task description and generates meaningful variations.

Example:
    Original: "Pick up the milk carton from the counter"
    LLM Mutation: "Pick up the milk carton from the fridge and place it on the counter"

This requires an API key set in the environment:
    ANTHROPIC_API_KEY  for Claude
    OPENAI_API_KEY     for GPT
"""

from __future__ import annotations

import json
import os
from typing import Any

from rosclaw_darwin.tdl.schema import Task, Primitive, Object, Constraint


# Default system prompt for task generation
TASK_GEN_PROMPT = """You are a robotics task generator for embodied AI benchmarking.
Your job is to take a robot task definition and generate meaningful variations.

You will receive a task in JSON format. Generate {n_variations} variations.
Each variation should:
1. Be physically plausible in a household environment
2. Progress logically from the original task (easier or harder)
3. Use valid motor primitives: Pick, Place, Push, Open, Close, Navigate, Observe, Grasp, Rotate, Pour
4. Reference valid objects: cup, plate, bottle, drawer, fridge, table, counter, apple, milk, bowl

Output a JSON array where each element is a task object with:
- name: human-readable task name
- description: what the robot should do
- primitives: list of {name, params, target}
- objects: list of {name, object_type}
- constraints: list of {name, constraint_type, weight}
- difficulty: float 0-10 (higher = harder)
- tags: list of strings

Be creative but physically grounded."""


class LLMTaskGenomeEngine:
    """Generate task variations using LLM API."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        self.provider = provider or self._detect_provider()
        self.model = model or self._default_model()
        self.api_key = api_key or self._get_api_key()
        self._client: Any | None = None

    @staticmethod
    def _detect_provider() -> str:
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        return "none"

    def _default_model(self) -> str:
        if self.provider == "anthropic":
            return "claude-sonnet-4-6"
        if self.provider == "openai":
            return "gpt-4o"
        return "none"

    def _get_api_key(self) -> str | None:
        if self.provider == "anthropic":
            return os.environ.get("ANTHROPIC_API_KEY")
        if self.provider == "openai":
            return os.environ.get("OPENAI_API_KEY")
        return None

    def _lazy_init_client(self) -> bool:
        if self._client is not None:
            return True
        if self.provider == "none" or not self.api_key:
            return False
        try:
            if self.provider == "anthropic":
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self.api_key)
            elif self.provider == "openai":
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            return True
        except ImportError:
            return False

    def generate(self, task: Task, n_variations: int = 3) -> list[Task]:
        """Generate task variations via LLM.

        Falls back to random genetic mutation if LLM is unavailable.
        """
        if not self._lazy_init_client():
            # Fallback: use genetic engine
            from .genome import TaskGenomeEngine
            engine = TaskGenomeEngine()
            return engine.mutate(task, n_variations=n_variations)

        task_json = self._task_to_prompt(task)
        prompt = TASK_GEN_PROMPT.format(n_variations=n_variations)

        response = self._call_llm(prompt, task_json)
        variations = self._parse_response(response, task)
        return variations

    def _task_to_prompt(self, task: Task) -> str:
        return json.dumps(
            {
                "name": task.name,
                "description": task.description,
                "primitives": [
                    {"name": p.name, "params": p.params, "target": p.target}
                    for p in task.primitives
                ],
                "objects": [
                    {"name": o.name, "object_type": o.object_type}
                    for o in task.objects
                ],
                "constraints": [
                    {"name": c.name, "constraint_type": c.constraint_type}
                    for c in task.constraints
                ],
                "difficulty": task.difficulty,
            },
            indent=2,
        )

    def _call_llm(self, system_prompt: str, user_content: str) -> str:
        if self.provider == "anthropic":
            message = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            return message.content[0].text

        if self.provider == "openai":
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            return completion.choices[0].message.content

        return "[]"

    def _parse_response(self, response: str, parent_task: Task) -> list[Task]:
        """Parse LLM JSON response into Task objects."""
        # Extract JSON from markdown code blocks if present
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON array in the text
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                data = json.loads(text[start:end + 1])
            else:
                data = []

        if not isinstance(data, list):
            data = [data]

        tasks: list[Task] = []
        for i, item in enumerate(data):
            try:
                t = Task(
                    id=f"{parent_task.id}_llm_{i}",
                    name=item.get("name", f"LLM Task {i}"),
                    source="rosclaw-tdl",
                    description=item.get("description", ""),
                    primitives=[
                        Primitive(name=p["name"], params=p.get("params", {}), target=p.get("target"))
                        for p in item.get("primitives", [])
                    ],
                    objects=[
                        Object(name=o["name"], object_type=o.get("object_type", "generic"))
                        for o in item.get("objects", [])
                    ],
                    constraints=[
                        Constraint(
                            name=c["name"],
                            constraint_type=c.get("constraint_type", "safety"),
                            weight=c.get("weight", 1.0),
                        )
                        for c in item.get("constraints", [])
                    ],
                    difficulty=item.get("difficulty", parent_task.difficulty),
                    parent_id=parent_task.id,
                    tags=item.get("tags", ["llm_generated"]),
                )
                tasks.append(t)
            except Exception:
                continue

        return tasks
