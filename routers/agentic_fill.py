import asyncio
import base64
import json
import logging
import re
from difflib import get_close_matches
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import settings
from db import get_db, SessionLocal
from models.form import Form
from services.nvidia_ai import MaxxieAI, NvidiaAIError, build_maxxie_messages


router = APIRouter(prefix="/api/agentic-fill", tags=["agentic-fill"])
INPUT_AUDIO_RATE = 16000
logger = logging.getLogger(__name__)


class AgenticFillTurnRequest(BaseModel):
    text: str = Field(..., min_length=1)
    draft_answers: Dict[str, Any] = Field(default_factory=dict)
    current_question_id: Optional[str] = None


class AgenticFillTurnResponse(BaseModel):
    assistant_text: str
    answer_patch: Dict[str, Any] = Field(default_factory=dict)
    current_question_id: Optional[str] = None
    next_question_id: Optional[str] = None
    completed: bool = False


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def _option_text(option: Any) -> str:
    if isinstance(option, str):
        return option
    if isinstance(option, dict):
        return str(option.get("label") or option.get("value") or option)
    return str(option)


def _public_form_or_404(db: Session, form_id: str) -> Form:
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    if form.status != "published":
        raise HTTPException(status_code=403, detail="Form is not accepting responses")
    return form


def _form_knowledge(form: Form) -> Dict[str, Any]:
    questions = []
    for index, question in enumerate(form.questions or []):
        questions.append({
            "index": index,
            "id": question.get("id"),
            "label": question.get("label", ""),
            "type": question.get("type", "short_text"),
            "required": bool(question.get("required", False)),
            "options": [_option_text(opt) for opt in question.get("options") or []],
            "condition": question.get("condition"),
        })

    return {
        "id": form.id,
        "title": form.title,
        "description": _strip_html(form.description or ""),
        "branding": form.branding or {},
        "presentation": form.presentation or {},
        "questions": questions,
    }


def _live_form_context(form: Form, answers: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "templateName": form.title,
        "fields": [
            {
                "id": question["id"],
                "label": question["label"],
                "type": question["type"],
                "required": question["required"],
                "current_value": answers.get(question["id"], ""),
                **({"options": question["options"]} if question.get("options") else {}),
            }
            for question in _visible_questions(form, answers)
        ],
    }


def _visible_questions(form: Form, answers: Dict[str, Any]) -> List[Dict[str, Any]]:
    def passes(condition: Optional[Dict[str, Any]]) -> bool:
        if not condition or not condition.get("source_question_id"):
            return True
        source = str(answers.get(condition["source_question_id"]) or "")
        value = str(condition.get("value") or "")
        operator = condition.get("operator")
        if operator == "equals":
            return source == value
        if operator == "not_equals":
            return source != value
        if operator == "contains":
            return value.lower() in source.lower()
        if operator == "not_empty":
            return bool(source.strip())
        return True

    return [q for q in _form_knowledge(form)["questions"] if passes(q.get("condition"))]


def _first_unanswered(form: Form, answers: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for question in _visible_questions(form, answers):
        value = answers.get(question["id"])
        if value in (None, "", []):
            return question
    return None


def _normalize_answer(question: Dict[str, Any], answer: Any) -> Any:
    if answer is None:
        return ""

    text = str(answer).strip()
    question_type = question.get("type")
    options = question.get("options") or []

    if question_type in {"multiple_choice", "dropdown"} and options:
        lower_map = {opt.lower(): opt for opt in options}
        if text.lower() in lower_map:
            return lower_map[text.lower()]
        match = get_close_matches(text.lower(), list(lower_map.keys()), n=1, cutoff=0.6)
        return lower_map[match[0]] if match else text

    if question_type == "checkbox" and options:
        selected = []
        lower_text = text.lower()
        for option in options:
            if option.lower() in lower_text:
                selected.append(option)
        return ", ".join(selected) if selected else text

    if question_type == "email":
        match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
        return match.group(0) if match else text

    if question_type == "number":
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return match.group(0) if match else text

    return text


def _question_for_utterance(form: Form, text: str, answers: Dict[str, Any], current_question_id: Optional[str]) -> Optional[Dict[str, Any]]:
    questions = _visible_questions(form, answers)
    if current_question_id:
        current = next((q for q in questions if q["id"] == current_question_id), None)
        if current:
            return current

    lower = text.lower()
    if "@" in text:
        email_question = next((q for q in questions if q.get("type") == "email" and not answers.get(q["id"])), None)
        if email_question:
            return email_question

    for keyword in ("name", "full name"):
        if keyword in lower:
            named = next((q for q in questions if "name" in q.get("label", "").lower() and not answers.get(q["id"])), None)
            if named:
                return named

    labels = {q["label"].lower(): q for q in questions}
    label_match = get_close_matches(lower, list(labels.keys()), n=1, cutoff=0.45)
    if label_match and not answers.get(labels[label_match[0]]["id"]):
        return labels[label_match[0]]

    return _first_unanswered(form, answers)


def _local_turn(form: Form, data: AgenticFillTurnRequest) -> AgenticFillTurnResponse:
    answers = dict(data.draft_answers or {})
    question = _question_for_utterance(form, data.text, answers, data.current_question_id)
    if not question:
        return AgenticFillTurnResponse(
            assistant_text="Everything visible on this form looks answered. You can review the form before submitting.",
            completed=True,
        )

    answer = _normalize_answer(question, data.text)
    patch = {question["id"]: answer}
    answers.update(patch)
    next_question = _first_unanswered(form, answers)

    if next_question:
        assistant = f"Got it. I filled {question['label']} as {answer}. Next: {next_question['label']}"
    else:
        assistant = f"Got it. I filled {question['label']} as {answer}. The visible questions are complete. Please review before submitting."

    return AgenticFillTurnResponse(
        assistant_text=assistant,
        answer_patch=patch,
        current_question_id=question["id"],
        next_question_id=next_question["id"] if next_question else None,
        completed=next_question is None,
    )


def _parse_jsonish(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text) or re.search(r"(\{[\s\S]*\})", text)
        if not match:
            raise
        return json.loads(match.group(1))


def _ai_turn(form: Form, data: AgenticFillTurnRequest) -> AgenticFillTurnResponse:
    if not settings.NVIDIA_API_KEY:
        return _local_turn(form, data)

    knowledge = _form_knowledge(form)
    visible = _visible_questions(form, data.draft_answers or {})
    prompt = f"""
You are ForeForm's assisted form filling agent.
Use the current form knowledge and draft answers to map the user's latest utterance to the best form field.
Return only JSON with this shape:
{{
  "assistant_text": "short natural response to say aloud",
  "answer_patch": {{"question_id": "answer value"}},
  "current_question_id": "question_id or null",
  "next_question_id": "question_id or null",
  "completed": false
}}

Rules:
- Do not invent questions. Use only ids from visible_questions.
- Keep answer_patch empty if the utterance is a question or is not enough to answer a field.
- For multiple_choice/dropdown/checkbox answers, use the exact option text when possible.
- Ask for the next unanswered visible question after applying the patch.
- Keep assistant_text concise and friendly.

form_knowledge:
{json.dumps(knowledge, default=str)}

visible_questions:
{json.dumps(visible, default=str)}

draft_answers:
{json.dumps(data.draft_answers or {}, default=str)}

current_question_id: {data.current_question_id}
user_utterance: {data.text}
"""
    try:
        maxxie = MaxxieAI(settings.NVIDIA_API_KEY)
        result = maxxie.chat(
            build_maxxie_messages([{"role": "user", "content": prompt}]),
            temperature=0.1,
            max_tokens=1200,
            reasoning_budget=512,
        )
        parsed = _parse_jsonish(result["content"])
        patch = parsed.get("answer_patch") or {}
        normalized_patch = {}
        question_by_id = {q["id"]: q for q in visible}
        for question_id, value in patch.items():
            if question_id in question_by_id:
                normalized_patch[question_id] = _normalize_answer(question_by_id[question_id], value)

        merged_answers = {**(data.draft_answers or {}), **normalized_patch}
        next_question = _first_unanswered(form, merged_answers)
        return AgenticFillTurnResponse(
            assistant_text=parsed.get("assistant_text") or parsed.get("assistantText") or "Updated the draft answer.",
            answer_patch=normalized_patch,
            current_question_id=parsed.get("current_question_id") or parsed.get("currentQuestionId"),
            next_question_id=(parsed.get("next_question_id") or parsed.get("nextQuestionId") or (next_question["id"] if next_question else None)),
            completed=bool(parsed.get("completed", next_question is None)),
        )
    except (NvidiaAIError, Exception):
        return _local_turn(form, data)


def _build_live_system_instruction(form: Form, answers: Dict[str, Any]) -> str:
    context = _live_form_context(form, answers)
    field_lines = []
    for field in context["fields"]:
        required = "required" if field.get("required") else "optional"
        options = field.get("options")
        option_text = f" Options: {', '.join(map(str, options))}." if isinstance(options, list) else ""
        current_value = field.get("current_value")
        value_text = f" Current value: {current_value}." if current_value else ""
        field_lines.append(
            f"- {field.get('id')}: {field.get('label')} ({field.get('type')}, {required}).{option_text}{value_text}"
        )

    return f"""You are ForeForm's fast voice form filling agent.

You are speaking with the user over live audio. Keep replies brief, warm, and natural.
Ask exactly one focused question at a time. Do not list every missing field at once.
Listen for the user's full answer before replying. Do not repeat the same sentence or question.
If the user interrupts you, stop your current thought and respond to the newest thing they said.
When you fill a field, acknowledge it once in a short sentence, then ask the next needed question.

Current form: {form.title}
Description: {_strip_html(form.description or "")}
Fields:
{chr(10).join(field_lines) if field_lines else "- No visible fields."}

When the user provides a field value, immediately call update_form with every field you can confidently update.
Use only the exact field_id values listed above. If a value is unclear, ask a short clarification.
When all required fields are filled, tell the user the form is ready to review.

You are the voice. Do not ask the browser or JavaScript to speak for you."""


def _live_config(system_instruction: str) -> Dict[str, Any]:
    return {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "media_resolution": "MEDIA_RESOLUTION_MEDIUM",
        "realtime_input_config": {
            "automatic_activity_detection": {
                "disabled": False,
                "prefix_padding_ms": 200,
                "silence_duration_ms": 350,
            },
            "activity_handling": "START_OF_ACTIVITY_INTERRUPTS",
        },
        "speech_config": {
            "voice_config": {"prebuilt_voice_config": {"voice_name": "Zephyr"}},
        },
        "context_window_compression": {
            "trigger_tokens": 104857,
            "sliding_window": {"target_tokens": 52428},
        },
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "tools": [
            {
                "function_declarations": [
                    {
                        "name": "update_form",
                        "description": "Update one or more form fields with values provided by the user.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "field_updates": {
                                    "type": "ARRAY",
                                    "items": {
                                        "type": "OBJECT",
                                        "properties": {
                                            "field_id": {
                                                "type": "STRING",
                                                "description": "Exact ID of the form field to update.",
                                            },
                                            "value": {
                                                "type": "STRING",
                                                "description": "Value to put in the form field.",
                                            },
                                        },
                                        "required": ["field_id", "value"],
                                    },
                                }
                            },
                            "required": ["field_updates"],
                        },
                    }
                ]
            }
        ],
    }


async def _safe_send_json(websocket: WebSocket, payload: Dict[str, Any]) -> None:
    try:
        await websocket.send_json(payload)
    except (RuntimeError, WebSocketDisconnect):
        pass


async def _safe_close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except RuntimeError:
        pass


def _user_turn(text: str) -> Dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def _response_audio_chunks(response: Any) -> List[bytes]:
    server_content = getattr(response, "server_content", None)
    model_turn = getattr(server_content, "model_turn", None) if server_content else None
    chunks = []
    for part in getattr(model_turn, "parts", []) or []:
        inline_data = getattr(part, "inline_data", None)
        data = getattr(inline_data, "data", None) if inline_data else None
        if data:
            chunks.append(bytes(data))

    if chunks:
        return chunks

    data = getattr(response, "data", None)
    if data is not None:
        chunks.append(bytes(data))

    return chunks


@router.get("/forms/{form_id}/knowledge")
def get_agentic_fill_knowledge(form_id: str, db: Session = Depends(get_db)):
    form = _public_form_or_404(db, form_id)
    return _form_knowledge(form)


@router.post("/forms/{form_id}/turn", response_model=AgenticFillTurnResponse)
def agentic_fill_turn(form_id: str, data: AgenticFillTurnRequest, db: Session = Depends(get_db)):
    form = _public_form_or_404(db, form_id)
    return _ai_turn(form, data)


@router.websocket("/ws/{form_id}")
async def agentic_fill_ws(websocket: WebSocket, form_id: str):
    await websocket.accept()
    db = SessionLocal()
    try:
        form = _public_form_or_404(db, form_id)
        knowledge = _form_knowledge(form)
        await websocket.send_json({"type": "formKnowledge", "data": knowledge})

        draft_answers: Dict[str, Any] = {}
        current_question_id: Optional[str] = None

        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            message_type = message.get("type")

            if message_type == "init":
                draft_answers = message.get("draftAnswers") or message.get("draft_answers") or {}
                current_question = _first_unanswered(form, draft_answers)
                current_question_id = current_question["id"] if current_question else None
                await websocket.send_json({
                    "type": "textStream",
                    "data": f"Ready. {('First question: ' + current_question['label']) if current_question else 'The visible questions are complete.'}",
                })

            elif message_type == "contentUpdateText":
                payload = AgenticFillTurnRequest(
                    text=message.get("text") or "",
                    draft_answers=message.get("draftAnswers") or message.get("draft_answers") or draft_answers,
                    current_question_id=message.get("currentQuestionId") or message.get("current_question_id") or current_question_id,
                )
                result = _ai_turn(form, payload)
                draft_answers.update(result.answer_patch)
                current_question_id = result.next_question_id or result.current_question_id
                await websocket.send_json({"type": "formPatch", "data": result.model_dump()})
                await websocket.send_json({"type": "textStream", "data": result.assistant_text})

            elif message_type == "realtimeInput":
                await websocket.send_json({
                    "type": "textStream",
                    "data": "Voice audio reached the FastAPI agent. This endpoint expects browser speech-to-text text turns for form filling.",
                })
    except WebSocketDisconnect:
        pass
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "data": exc.detail})
    except Exception as exc:
        await websocket.send_json({"type": "error", "data": str(exc)})
    finally:
        db.close()


@router.websocket("/live/{form_id}")
async def agentic_fill_live(websocket: WebSocket, form_id: str):
    await websocket.accept()

    if not settings.GEMINI_API_KEY:
        await _safe_send_json(
            websocket,
            {"type": "error", "message": "GEMINI_API_KEY or GOOGLE_API_KEY is not configured on the backend."},
        )
        await _safe_close(websocket, code=1011)
        return

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        await _safe_send_json(
            websocket,
            {"type": "error", "message": "Install google-genai in the backend venv to use live voice."},
        )
        await _safe_close(websocket, code=1011)
        return

    db = SessionLocal()
    try:
        form = _public_form_or_404(db, form_id)
    except HTTPException as exc:
        await _safe_send_json(websocket, {"type": "error", "message": str(exc.detail)})
        await _safe_close(websocket, code=1008)
        db.close()
        return

    try:
        first = await websocket.receive_json()
    except WebSocketDisconnect:
        db.close()
        return
    except Exception:
        await _safe_send_json(websocket, {"type": "error", "message": "Invalid live session start payload."})
        await _safe_close(websocket, code=1003)
        db.close()
        return

    if first.get("type") != "start":
        await _safe_send_json(websocket, {"type": "error", "message": "Live session must start with form context."})
        await _safe_close(websocket, code=1003)
        db.close()
        return

    draft_answers: Dict[str, Any] = first.get("draft_answers") or first.get("draftAnswers") or {}
    valid_question_ids = {question["id"] for question in _visible_questions(form, draft_answers)}
    client = genai.Client(http_options={"api_version": "v1beta"}, api_key=settings.GEMINI_API_KEY)
    config = _live_config(_build_live_system_instruction(form, draft_answers))

    async def receive_from_gemini(session: Any) -> None:
        async for response in session.receive():
            for audio_chunk in _response_audio_chunks(response):
                await _safe_send_json(
                    websocket,
                    {"type": "audio", "audio": base64.b64encode(audio_chunk).decode("ascii")},
                )

            response_text = getattr(response, "text", None)
            if isinstance(response_text, str) and response_text.strip():
                await _safe_send_json(websocket, {"type": "outputTranscript", "text": response_text.strip()})

            server_content = getattr(response, "server_content", None)
            if server_content is not None:
                input_transcription = getattr(server_content, "input_transcription", None)
                if input_transcription and getattr(input_transcription, "text", None):
                    await _safe_send_json(websocket, {"type": "inputTranscript", "text": input_transcription.text})

                output_transcription = getattr(server_content, "output_transcription", None)
                if output_transcription and getattr(output_transcription, "text", None):
                    await _safe_send_json(websocket, {"type": "outputTranscript", "text": output_transcription.text})

                if getattr(server_content, "interrupted", False):
                    await _safe_send_json(websocket, {"type": "interrupted"})

            tool_call = getattr(response, "tool_call", None)
            if tool_call and getattr(tool_call, "function_calls", None):
                function_responses = []
                for call in tool_call.function_calls:
                    args = call.args if isinstance(call.args, dict) else {}
                    if call.name != "update_form":
                        function_responses.append(
                            types.FunctionResponse(
                                id=call.id,
                                name=call.name,
                                response={"status": "error", "message": f"Unsupported function: {call.name}"},
                            )
                        )
                        continue

                    raw_updates = args.get("field_updates")
                    clean_updates = []
                    if isinstance(raw_updates, list):
                        for item in raw_updates:
                            if not isinstance(item, dict):
                                continue
                            field_id = str(item.get("field_id") or "")
                            if field_id not in valid_question_ids or item.get("value") is None:
                                continue
                            question = next((q for q in _visible_questions(form, draft_answers) if q["id"] == field_id), None)
                            value = _normalize_answer(question or {}, item.get("value"))
                            clean_updates.append({"field_id": field_id, "value": str(value)})
                            draft_answers[field_id] = value

                    await _safe_send_json(websocket, {"type": "formUpdate", "field_updates": clean_updates})
                    await _safe_send_json(
                        websocket,
                        {
                            "type": "formPatch",
                            "data": {
                                "answer_patch": {item["field_id"]: item["value"] for item in clean_updates},
                                "next_question_id": (_first_unanswered(form, draft_answers) or {}).get("id"),
                                "completed": _first_unanswered(form, draft_answers) is None,
                            },
                        },
                    )
                    function_responses.append(
                        types.FunctionResponse(
                            id=call.id,
                            name=call.name,
                            response={"status": "ok", "updated": clean_updates},
                        )
                    )
                if function_responses:
                    await session.send_tool_response(function_responses=function_responses)

    async def receive_from_browser(session: Any) -> None:
        while True:
            message = await websocket.receive_text()
            payload = json.loads(message)
            message_type = payload.get("type")

            if message_type == "audio":
                audio = payload.get("audio")
                if isinstance(audio, str) and audio:
                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=base64.b64decode(audio),
                            mime_type=f"audio/pcm;rate={INPUT_AUDIO_RATE}",
                        )
                    )
            elif message_type == "audioStreamEnd":
                await session.send_realtime_input(audio_stream_end=True)
            elif message_type == "client_text":
                text = payload.get("text")
                if isinstance(text, str) and text.strip():
                    await session.send_client_content(turns=_user_turn(text.strip()), turn_complete=True)

    try:
        async with client.aio.live.connect(model=settings.GEMINI_LIVE_MODEL, config=config) as session:
            await _safe_send_json(websocket, {"type": "ready", "form": _live_form_context(form, draft_answers)})
            await session.send_client_content(
                turns=_user_turn("Greet the user and ask the first missing required form question."),
                turn_complete=True,
            )
            tasks = {
                asyncio.create_task(receive_from_gemini(session)),
                asyncio.create_task(receive_from_browser(session)),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc is None:
                    continue
                if isinstance(exc, WebSocketDisconnect):
                    return
                raise exc
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.exception("Gemini Live session failed for form %s using model %s", form_id, settings.GEMINI_LIVE_MODEL)
        await _safe_send_json(websocket, {"type": "error", "message": str(exc)})
        await _safe_close(websocket, code=1011)
    finally:
        db.close()
