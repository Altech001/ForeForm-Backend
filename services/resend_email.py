import logging
from typing import Iterable, Optional

import resend
from config import settings

logger = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY


def _sender() -> str:
    return f"{settings.FROM_NAME} <{settings.FROM_EMAIL}>"


def _normalize_recipients(to: str | Iterable[str]) -> list[str]:
    if isinstance(to, str):
        recipients = [to]
    else:
        recipients = list(to)
    return [email.strip().lower() for email in recipients if email and email.strip()]


def send_email(
    to: str | Iterable[str],
    subject: str,
    html: str,
    reply_to: Optional[str] = None,
) -> bool:
    """Send an email through Resend. Returns False if email is not configured."""
    recipients = _normalize_recipients(to)
    if not recipients:
        return False
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY is not configured; skipped email to %s", recipients)
        return False

    params: resend.Emails.SendParams = {
        "from": _sender(),
        "to": recipients,
        "subject": subject,
        "html": html,
    }
    if reply_to:
        params["reply_to"] = reply_to

    try:
        resend.Emails.send(params)
        logger.info("Successfully sent email to %s", recipients)
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", recipients, e)
        return False


def _escape_html(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _format_answer(answer: dict) -> str:
    raw = answer.get("answer") or ""
    if answer.get("question_type") == "file_upload" and raw:
        try:
            import json

            file_info = json.loads(raw)
            file_name = _escape_html(file_info.get("file_name") or "Uploaded file")
            file_url = _escape_html(file_info.get("file_url") or raw)
            return f'<a href="{file_url}">{file_name}</a>'
        except Exception:
            return _escape_html(raw)
    return _escape_html(raw) or "No answer"


def send_response_confirmation_email(
    recipient_email: str,
    form_title: str,
    answers: Optional[list[dict]] = None,
    respondent_name: Optional[str] = None,
    organization: Optional[str] = None,
):
    """
    Sends an email to the person who filled out the form.
    """
    if not recipient_email:
        return

    answer_rows = ""
    for index, answer in enumerate(answers or [], start=1):
        label = _escape_html(answer.get("question_label") or f"Question {index}")
        value = _format_answer(answer)
        answer_rows += f"<p><strong>{index}. {label}</strong><br>{value}</p>"

    greeting = _escape_html(respondent_name or "there")
    title = _escape_html(form_title)
    org = _escape_html(organization or settings.FROM_NAME)
    html = f"""
        <p>Hi {greeting},</p>
        <p>Thank you for completing <strong>{title}</strong>. Your response has been successfully recorded.</p>
        {f"<h3>Your response summary</h3>{answer_rows}" if answer_rows else ""}
        <p>Best regards,<br>{org}</p>
    """
    return send_email(
        recipient_email,
        f"Your response to {form_title}",
        html,
    )


def send_share_invitation_email(
    recipient_email: str,
    form_title: str,
    shared_by: str,
    permission: str,
) -> bool:
    title = _escape_html(form_title)
    owner = _escape_html(shared_by)
    access = _escape_html(permission)
    html = f"""
        <p>{owner} shared <strong>{title}</strong> with you on ForeForm.</p>
        <p>You have been granted <strong>{access}</strong> access. Log in to ForeForm to view it.</p>
    """
    return send_email(recipient_email, f"ForeForm access: {form_title}", html)
