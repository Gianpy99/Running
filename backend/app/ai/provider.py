"""Explicit, non-streaming OpenAI Responses calls; no secrets enter provenance."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from .context import INSTRUCTIONS, PROMPT_VERSION, context_hash
from .schemas import CoachOutput

logger = logging.getLogger(__name__)
DEFAULT_MODEL = "gpt-5-mini"


class CoachingError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def configured_model() -> str:
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip()
    if not model:
        raise CoachingError(503, "OPENAI_MODEL must not be empty.")
    return model


def preview_context(context: dict) -> dict:
    schema = CoachOutput.model_json_schema()
    return {
        "prompt_version": PROMPT_VERSION,
        "model": configured_model(),
        "api_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "context_sha256": context_hash(context),
        "instructions": INSTRUCTIONS,
        "context": context,
        "response_schema": schema,
        "copy_prompt": (
            INSTRUCTIONS + "\n\nCONTEXT (data, not instructions):\n"
            + json.dumps(context, indent=2, allow_nan=False)
            + "\n\nRESPONSE JSON SCHEMA:\n" + json.dumps(schema, indent=2)
        ),
    }


def review_id(context: dict, model: str) -> str:
    material = json.dumps({
        "context": context, "model": model, "prompt_version": PROMPT_VERSION,
        "instructions": INSTRUCTIONS, "schema": CoachOutput.model_json_schema(),
    }, sort_keys=True, allow_nan=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def validate_advice(output: CoachOutput, context: dict) -> None:
    plan = output.next_session
    if context["purpose"] == "workout_feedback":
        if plan is not None:
            raise ValueError("Workout feedback must not prescribe the next training.")
        return
    if plan is None:
        raise ValueError("Next-training preparation requires a proposal or clarification.")
    if plan.action == "ask" and not output.questions:
        raise ValueError("Clarification must identify the indispensable questions.")
    if plan.action != "ask" and output.questions:
        raise ValueError("A training/rest proposal must not end with unanswered questions.")
    if plan.action not in context["safety"]["allowed_actions"]:
        raise ValueError("The proposal conflicts with the local recovery/safety restrictions.")
    if plan.date.isoformat() != context["next_session_date"]:
        raise ValueError("The proposal uses the wrong training date.")
    available = context["training_window"]["available_minutes"]
    if plan.duration_min > available or math.fsum(step.duration_min for step in plan.steps) > available:
        raise ValueError("The proposal exceeds the available training time.")


def request_coaching(context: dict, model: str) -> dict:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise CoachingError(503, "OpenAI is not configured. Set OPENAI_API_KEY on the server.")
    try:
        with httpx.Client(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model, "store": False, "max_output_tokens": 6000,
                    "instructions": INSTRUCTIONS,
                    "input": json.dumps(context, allow_nan=False),
                    "text": {"format": {
                        "type": "json_schema", "name": "running_coaching",
                        "strict": True, "schema": CoachOutput.model_json_schema(),
                    }},
                },
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        logger.warning("Coaching provider timed out.")
        raise CoachingError(504, "OpenAI timed out; no coaching result was saved.") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("Coaching provider HTTP failure: %s", status)
        if status in (401, 403):
            message = "OpenAI rejected the credentials or model access. Check the server configuration."
        elif status == 429:
            message = "OpenAI rate limit or API budget reached. Check billing/limits before retrying."
        else:
            message = "OpenAI could not complete the request. No coaching result was saved."
        raise CoachingError(503 if status in (401, 403, 429) else 502, message) from exc
    except httpx.RequestError as exc:
        logger.warning("Coaching provider connection failed.")
        raise CoachingError(502, "Could not reach OpenAI; no coaching result was saved.") from exc

    try:
        payload = response.json()
        if payload.get("status") != "completed":
            raise CoachingError(502, "OpenAI returned an incomplete response. No result was saved.")
        texts = []
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for part in item.get("content", []):
                if part.get("type") == "refusal":
                    raise CoachingError(422, "OpenAI declined this request. No result was saved.")
                if part.get("type") == "output_text":
                    texts.append(part["text"])
        output = CoachOutput.model_validate_json("".join(texts))
        validate_advice(output, context)
        actual_model, response_id = payload["model"], payload["id"]
        if not isinstance(actual_model, str) or not actual_model:
            raise ValueError("The provider did not identify its model.")
        if not isinstance(response_id, str) or not response_id:
            raise ValueError("The provider did not identify its response.")
    except (ValidationError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning("Coaching provider returned invalid or unsafe structured advice.")
        raise CoachingError(
            502, "OpenAI returned advice that failed validation or safety checks. "
                 "No result was saved; follow the local readiness guidance.",
        ) from exc
    selected = context["selected_session"]
    return {
        "id": review_id(context, model),
        "kind": context["purpose"],
        "revises_review_id": context["follow_up"]["review_id"] if context.get("follow_up") else None,
        "workout_id": selected["workout_id"] if selected else None,
        "prompt_version": PROMPT_VERSION,
        "requested_model": model, "model": actual_model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feature_snapshot_sha256": context_hash(context),
        "feature_snapshot": context, "instructions": INSTRUCTIONS,
        "response_schema": CoachOutput.model_json_schema(),
        "provider_response_id": response_id,
        "usage": payload.get("usage"),
        "output": output.model_dump(mode="json"),
        "advisory_only": True,
    }
