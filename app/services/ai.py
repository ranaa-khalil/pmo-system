"""AI service — LLM-powered suggestions for vision, features, and field filling.

Works with any OpenAI-compatible API (OpenAI, Azure, Ollama, LM Studio, etc.).
Configure via Settings: AI API Key, Base URL, Model.
"""
import json
import re
import httpx
from app.config import settings


from typing import Optional


def is_ai_configured() -> bool:
    """Check if AI is configured (API key set)."""
    return bool(settings.ai_api_key)


def _extract_json(raw: str) -> Optional[dict]:
    """Try every strategy to extract valid JSON from an LLM response."""
    # 1. Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', raw)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Find the outermost { ... } block
    brace_match = re.search(r'\{[\s\S]*\}', raw)
    if brace_match:
        candidate = brace_match.group()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # 4. Try fixing common issues: trailing commas, single quotes
            cleaned = candidate
            cleaned = re.sub(r',\s*}', '}', cleaned)  # trailing comma before }
            cleaned = re.sub(r',\s*]', ']', cleaned)  # trailing comma before ]
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    return None


def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 1500, json_mode: bool = False) -> str:
    """Call the LLM API and return the response text."""
    if not is_ai_configured():
        raise ValueError("AI is not configured. Set the API key in Settings.")

    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.ai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"{settings.ai_base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def suggest_vision_improvements(
    project_name: str,
    project_description: str,
    current_vision: str,
    objectives: str = "",
) -> dict:
    """Suggest improvements to a project vision statement."""
    system = (
        "You are a senior Product Manager and Business Analyst. "
        "You help refine project vision statements to be clear, inspiring, and actionable. "
        "You MUST respond with ONLY valid JSON. No markdown, no code fences, no commentary. "
        "Just the JSON object."
    )
    user = (
        f"Project: {project_name}\n"
        f"Description: {project_description or 'N/A'}\n"
        f"Current Vision: {current_vision or 'N/A'}\n"
        f"Strategic Objectives: {objectives or 'N/A'}\n\n"
        "Analyze the current vision and suggest improvements. Respond as JSON:\n"
        '{\n'
        '  "improved_vision": "A refined, inspiring vision statement (2-3 sentences)",\n'
        '  "strengths": ["What works well in the current vision"],\n'
        '  "improvements": ["Specific suggestions for improvement"],\n'
        '  "suggested_objectives": ["3-5 strategic objectives that align with the vision"]\n'
        '}'
    )
    raw = _call_llm(system, user, json_mode=True)
    parsed = _extract_json(raw)
    if parsed:
        return parsed
    return {"improved_vision": raw, "strengths": [], "improvements": [], "suggested_objectives": []}


def suggest_features(
    project_name: str,
    project_description: str,
    vision: str,
    existing_epics: list,
    existing_features: list,
    personas: list,
) -> dict:
    """Suggest epics and features for a project based on context."""
    system = (
        "You are a senior Product Manager. You help break down project visions into "
        "epics and features. You understand user personas and create features that "
        "serve their needs. You MUST respond with ONLY valid JSON. No markdown, no code fences, "
        "no commentary. Just the JSON object."
    )
    epics_text = "\n".join(f"- {e}" for e in existing_epics) or "None yet"
    features_text = "\n".join(f"- {f}" for f in existing_features[:20]) or "None yet"
    personas_text = "\n".join(f"- {p['name']}: {p.get('role','')}" for p in personas) or "None defined"

    user = (
        f"Project: {project_name}\n"
        f"Description: {project_description or 'N/A'}\n"
        f"Vision: {vision or 'N/A'}\n\n"
        f"Existing Epics:\n{epics_text}\n\n"
        f"Existing Features (first 20):\n{features_text}\n\n"
        f"User Personas:\n{personas_text}\n\n"
        "Based on the project context, suggest 2-3 NEW epics and 3-5 NEW features that don't duplicate existing ones. Keep descriptions concise.\n\n"
        "Each EPIC must include ALL of these fields:\n"
        '- title: Short epic name (e.g. "RBAC & Identity Management")\n'
        '- description: 2-3 sentence description of the epic scope\n'
        '- rationale: Why this epic matters to the project\n'
        '- priority: High, Medium, or Low\n'
        '- primary_actor: Which persona benefits most\n'
        '- story_points: Estimated complexity (1,2,3,5,8,13)\n'
        '- acceptance_criteria: 3-5 testable bullet points (as one string with newlines)\n\n'
        "Each FEATURE must include ALL of these fields:\n"
        '- title: Feature title (e.g. "Role-based access control on project resources")\n'
        '- epic: The epic name it belongs to (must match one of the suggested epics or existing ones)\n'
        '- description: 2-3 sentence description of what it does\n'
        '- priority: High, Medium, or Low\n'
        '- primary_actor: Which persona benefits\n'
        '- story_points: Estimated complexity (1,2,3,5,8,13)\n'
        '- acceptance_criteria: 3-5 testable bullet points (as one string with newlines)\n'
        '- item_type: "Feature", "Enhancement", or "Bug"\n'
        '- rationale: Why this feature is needed\n\n'
        "Respond as JSON:\n"
        '{\n'
        '  "suggested_epics": [\n'
        '    {"title":"...","description":"...","rationale":"...","priority":"...","primary_actor":"...","story_points":N,"acceptance_criteria":"..."}\n'
        '  ],\n'
        '  "suggested_features": [\n'
        '    {"title":"...","epic":"...","description":"...","priority":"...","primary_actor":"...","story_points":N,"acceptance_criteria":"...","item_type":"...","rationale":"..."}\n'
        '  ],\n'
        '  "summary": "Brief overall assessment of what the project needs next"\n'
        '}'
    )
    raw = _call_llm(system, user, max_tokens=6000, json_mode=True)
    parsed = _extract_json(raw)
    if parsed:
        return parsed
    return {"suggested_epics": [], "suggested_features": [], "summary": raw}


def fill_field(
    item_title: str,
    item_type: str,
    field_name: str,
    field_context: str,
    project_name: str,
    vision: str,
    existing_description: str = "",
) -> dict:
    """Fill an empty field on a backlog item using AI."""
    system = (
        "You are a senior Business Analyst. You help write clear, professional "
        "requirements documentation. You MUST respond with ONLY valid JSON. No markdown, "
        "no code fences, no commentary. Just the JSON object."
    )
    user = (
        f"Project: {project_name}\n"
        f"Project Vision: {vision or 'N/A'}\n\n"
        f"Item: {item_title}\n"
        f"Type: {item_type}\n"
        f"Existing Description: {existing_description or 'N/A'}\n\n"
        f"Task: Fill in the '{field_name}' field.\n"
        f"Context: {field_context}\n\n"
        "Respond as JSON:\n"
        '{\n'
        f'  "{field_name}": "Professional, detailed content for this field",\n'
        '  "explanation": "Brief explanation of why this content is appropriate"\n'
        '}'
    )
    raw = _call_llm(system, user, max_tokens=800)
    parsed = _extract_json(raw)
    if parsed:
        return parsed
    return {field_name: raw, "explanation": ""}
