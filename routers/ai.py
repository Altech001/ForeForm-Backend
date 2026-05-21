#type: ignore

from typing import Optional, List
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.user import User
from models.form import Form
from models.form_response import FormResponse
from auth.jwt import get_current_user
from config import settings
from db import get_db
from services.nvidia_ai import MaxxieAI, NvidiaAIError, build_maxxie_messages

router = APIRouter(prefix="/api/ai", tags=["ai"])


def parse_jsonish(text: str):
    import json
    import re

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text) or re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if not match:
            raise
        return json.loads(match.group(1))


def strip_html(value: str) -> str:
    """Remove HTML tags from a string for clean text."""
    import re
    return re.sub(r"<[^>]+>", "", value or "").strip()


def build_form_summary(form: Form, responses: List[FormResponse]) -> dict:
    """Build a comprehensive summary of a single form with its responses."""
    questions = form.questions or []
    question_map = {q.get("id") or q.get("label"): q for q in questions}

    # Basic form info
    summary = {
        "id": form.id,
        "title": form.title,
        "description": strip_html(form.description or ""),
        "status": form.status,
        "created_date": form.created_date.isoformat() if form.created_date else None,
        "updated_date": form.updated_date.isoformat() if form.updated_date else None,
        "total_questions": len(questions),
        "total_responses": len(responses),
        "questions": [],
        "response_analytics": {},
    }

    # Build question details
    for q in questions:
        q_info = {
            "label": q.get("label", ""),
            "type": q.get("type", "unknown"),
            "required": q.get("required", False),
        }
        if q.get("options"):
            q_info["options"] = [opt if isinstance(opt, str) else opt.get("label", str(opt)) for opt in q["options"]]
        summary["questions"].append(q_info)

    # Skip analytics if no responses
    if not responses:
        summary["response_analytics"] = {"note": "No responses yet"}
        return summary

    # Response analytics
    analytics = {}

    # Time-based analytics
    response_dates = [r.created_date for r in responses if r.created_date]
    if response_dates:
        analytics["first_response"] = min(response_dates).isoformat()
        analytics["latest_response"] = max(response_dates).isoformat()

        # Responses in last 7 days
        week_ago = datetime.utcnow() - timedelta(days=7)
        analytics["responses_last_7_days"] = sum(1 for d in response_dates if d >= week_ago)

        # Responses in last 30 days
        month_ago = datetime.utcnow() - timedelta(days=30)
        analytics["responses_last_30_days"] = sum(1 for d in response_dates if d >= month_ago)

    # Respondent info
    named_responses = [r for r in responses if r.respondent_name]
    emailed_responses = [r for r in responses if r.respondent_email]
    analytics["respondents_with_name"] = len(named_responses)
    analytics["respondents_with_email"] = len(emailed_responses)
    analytics["unique_emails"] = len(set(r.respondent_email for r in emailed_responses))

    # GPS/Location data
    geo_responses = [r for r in responses if r.gps_latitude and r.gps_longitude]
    if geo_responses:
        analytics["responses_with_location"] = len(geo_responses)
        locations = [r.gps_address for r in geo_responses if r.gps_address]
        if locations:
            analytics["locations"] = list(set(locations))[:10]

    # Quiz analytics
    quiz_responses = [r for r in responses if r.quiz_score is not None]
    if quiz_responses:
        scores = [r.quiz_score for r in quiz_responses]
        analytics["quiz"] = {
            "total_quiz_takers": len(quiz_responses),
            "average_score": round(sum(scores) / len(scores), 2),
            "highest_score": max(scores),
            "lowest_score": min(scores),
            "max_possible": quiz_responses[0].quiz_max_score,
            "average_percent": round(
                sum(r.quiz_percent for r in quiz_responses if r.quiz_percent is not None) / len(quiz_responses), 1
            ),
            "grades_released_count": sum(1 for r in quiz_responses if r.grades_released),
        }

    # Per-question answer analysis (sample up to 100 responses for performance)
    sample_responses = responses[:100]
    question_answers = {}
    for resp in sample_responses:
        answers = resp.answers or []
        if isinstance(answers, dict):
            answers = [{"question_id": k, "value": v} for k, v in answers.items()]
        for ans in answers:
            q_id = ans.get("question_id") or ans.get("questionId") or ans.get("label", "unknown")
            q_label = q_id
            # Try to resolve label from question map
            if q_id in question_map:
                q_label = question_map[q_id].get("label", q_id)

            if q_label not in question_answers:
                question_answers[q_label] = []
            value = ans.get("value") or ans.get("answer", "")
            if isinstance(value, list):
                question_answers[q_label].extend(value)
            else:
                question_answers[q_label].append(value)

    # Build answer distributions
    answer_analysis = {}
    for q_label, values in question_answers.items():
        non_empty = [v for v in values if v not in (None, "", [])]
        completion_rate = round(len(non_empty) / len(sample_responses) * 100, 1) if sample_responses else 0

        q_analysis = {
            "total_answers": len(non_empty),
            "completion_rate": f"{completion_rate}%",
        }

        # For short answers, show common values
        str_values = [str(v) for v in non_empty]
        if str_values:
            counter = Counter(str_values)
            most_common = counter.most_common(5)
            if len(counter) <= 10:
                # Categorical — show full distribution
                q_analysis["value_distribution"] = dict(counter.most_common(10))
            else:
                # Free text — show top answers and unique count
                q_analysis["unique_answers"] = len(counter)
                q_analysis["top_answers"] = [{"value": v, "count": c} for v, c in most_common]
                # Show a few sample answers
                q_analysis["sample_answers"] = str_values[:3]

        answer_analysis[q_label] = q_analysis

    if answer_analysis:
        analytics["answer_analysis"] = answer_analysis

    # Recent respondents (last 5)
    sorted_responses = sorted(responses, key=lambda r: r.created_date or datetime.min, reverse=True)
    recent = []
    for r in sorted_responses[:5]:
        entry = {}
        if r.respondent_name:
            entry["name"] = r.respondent_name
        if r.respondent_email:
            entry["email"] = r.respondent_email
        if r.created_date:
            entry["submitted"] = r.created_date.isoformat()
        if r.quiz_score is not None:
            entry["quiz_score"] = r.quiz_score
        recent.append(entry)
    if recent:
        analytics["recent_respondents"] = recent

    summary["response_analytics"] = analytics
    return summary


def build_workspace_context(user: User, db: Session) -> str:
    """Build the full workspace context string for the AI."""
    forms = db.query(Form).filter(Form.created_by == user.email).all()

    if not forms:
        return "This user has no forms in their workspace yet."

    # Fetch all responses for all user forms in one query
    form_ids = [f.id for f in forms]
    all_responses = db.query(FormResponse).filter(FormResponse.form_id.in_(form_ids)).all()

    # Group responses by form
    responses_by_form = {}
    for r in all_responses:
        responses_by_form.setdefault(r.form_id, []).append(r)

    # Build summaries
    form_summaries = []
    for form in forms:
        form_responses = responses_by_form.get(form.id, [])
        form_summaries.append(build_form_summary(form, form_responses))

    # Workspace-level stats
    total_forms = len(forms)
    total_responses = len(all_responses)
    published = sum(1 for f in forms if f.status == "published")
    drafts = sum(1 for f in forms if f.status == "draft")
    closed = sum(1 for f in forms if f.status == "closed")

    workspace_stats = {
        "total_forms": total_forms,
        "total_responses": total_responses,
        "published_forms": published,
        "draft_forms": drafts,
        "closed_forms": closed,
        "average_responses_per_form": round(total_responses / total_forms, 1) if total_forms else 0,
    }

    import json
    context = (
        f"=== WORKSPACE OVERVIEW ===\n"
        f"{json.dumps(workspace_stats, indent=2)}\n\n"
        f"=== ALL FORMS WITH FULL DATA ===\n"
        f"{json.dumps(form_summaries, indent=2, default=str)}\n"
    )
    return context


MAXXIE_SYSTEM_PROMPT = """You are Maxxie, ForeForm's intelligent AI assistant. You have FULL access to the user's workspace data including all their forms, questions, responses, analytics, and more.

Your capabilities:
1. **Form Analysis**: Analyze form structure, question quality, question types, and suggest improvements.
2. **Response Analysis**: Analyze response data — trends, patterns, completion rates, answer distributions, popular answers.
3. **Quiz Analysis**: If forms have quiz scoring, analyze scores, averages, pass rates, grade distributions.
4. **Search**: Find specific forms, responses, or respondents across the workspace.
5. **Insights & Recommendations**: Provide actionable insights — which forms need attention, response rate trends, data quality issues.
6. **General Knowledge**: Answer general questions about anything — you are not limited to ForeForm topics.
7. **Grammar & Writing**: Help with grammar correction, text rewriting, and content creation.
8. **Navigation Guide**: Guide users to specific ForeForm pages and features.

Available app routes:
- Dashboard: /
- AI Builder: /complex-ai
- Agent: /agent
- AI Respondents: /ai-respondents
- Profile: /profile
- Form Editor: /forms/{id}/edit

Rules:
- Answer in concise, well-formatted markdown.
- Use tables when comparing data across forms.
- When analyzing responses, reference actual data — don't make up numbers.
- If the user asks about something outside ForeForm, answer it naturally — you are a general-purpose assistant too.
- If teaching, give clear step-by-step instructions with page references.
- Be proactive: if you notice issues (low response rates, unanswered required questions, etc.), mention them.
"""


class ExtractRequest(BaseModel):
    text: Optional[str] = None
    file_url: Optional[str] = None


class ExtractedQuestion(BaseModel):
    label: str
    type: str
    required: bool = True
    options: List[str] = []


class ExtractResponse(BaseModel):
    questions: List[ExtractedQuestion]


class ChatRequest(BaseModel):
    prompt: str
    system_prompt: Optional[str] = None
    temperature: Optional[float] = 0.6
    max_tokens: Optional[int] = 8192
    response_json_schema: Optional[dict] = None


@router.post("/chat")
async def chat_with_maxxie(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not data.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    # Build full workspace context from the database
    workspace_context = build_workspace_context(current_user, db)

    # Build the system prompt with full context
    system_prompt = (
        f"{MAXXIE_SYSTEM_PROMPT}\n\n"
        f"=== CURRENT USER ===\n"
        f"Name: {current_user.full_name}\n"
        f"Email: {current_user.email}\n"
        f"Role: {current_user.role}\n"
        f"Account created: {current_user.created_date.isoformat() if current_user.created_date else 'unknown'}\n\n"
        f"{workspace_context}"
    )

    if data.response_json_schema:
        system_prompt += "\n\nReturn only valid JSON that matches the requested response schema."

    try:
        maxxie = MaxxieAI(settings.NVIDIA_API_KEY)
        result = maxxie.chat(
            build_maxxie_messages([{"role": "user", "content": data.prompt}], system_prompt),
            temperature=data.temperature or 0.6,
            max_tokens=min(data.max_tokens or 8192, 16384),
            reasoning_budget=4096,
        )
        return {
            "text": result["content"],
            "reasoning": result["reasoning"],
            "model": "maxxie",
        }
    except NvidiaAIError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Maxxie request failed: {str(e)}")


@router.post("/extract-questions", response_model=ExtractResponse)
async def extract_questions(
    data: ExtractRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Extract structured questions from raw text or an uploaded file.
    Requires NVIDIA_API_KEY or OPENAI_API_KEY to be set in environment.
    """
    if not data.text and not data.file_url:
        raise HTTPException(status_code=400, detail="Provide either 'text' or 'file_url'")

    if not settings.NVIDIA_API_KEY and not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=501,
            detail="AI question extraction is not configured. Set NVIDIA_API_KEY or OPENAI_API_KEY in .env",
        )

    try:
        if settings.NVIDIA_API_KEY:
            maxxie = MaxxieAI(settings.NVIDIA_API_KEY)
            content = data.text or f"Extract questions from the file at: {data.file_url}"
            prompt = (
                "Extract structured form questions from the following text. "
                "Use only these types: short_text, long_text, multiple_choice, checkbox, dropdown, date, number, email, file_upload, rating. "
                "Return only a JSON object with a questions array. Each question must have label, type, required, and options. "
                "Only multiple_choice, checkbox, and dropdown should have options.\n\n"
                f"Text:\n{content}"
            )
            result = maxxie.chat(
                build_maxxie_messages([{"role": "user", "content": prompt}]),
                temperature=0.2,
                max_tokens=4096,
                reasoning_budget=1024,
            )
            parsed = parse_jsonish(result["content"])
            questions = parsed.get("questions", parsed) if isinstance(parsed, dict) else parsed
            return {"questions": questions}

        import openai

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        content = data.text or f"Extract questions from the file at: {data.file_url}"
        prompt = (
            "You are a form-building assistant. Extract structured form questions from the "
            "following text. For each question, determine the best field type from: "
            "short_text, long_text, multiple_choice, checkbox, dropdown, date, number, email, file_upload, rating. "
            "Return ONLY a JSON array of objects with keys: label, type, required, options. "
            "The options array should only be populated for multiple_choice, checkbox, and dropdown types.\n\n"
            f"Text:\n{content}"
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        import json
        result = json.loads(response.choices[0].message.content)
        questions = result.get("questions", result) if isinstance(result, dict) else result
        return {"questions": questions}

    except ImportError:
        raise HTTPException(status_code=501, detail="openai package not installed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI extraction failed: {str(e)}")
