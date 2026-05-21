def _normalize(value):
    return str(value or "").strip().lower()


def _filter_visible_questions(questions, answers):
    visible = []
    for question in questions or []:
        condition = question.get("condition") or {}
        source_id = condition.get("source_question_id")
        if not source_id:
            visible.append(question)
            continue

        source_answer = str(answers.get(source_id) or "").strip()
        operator = condition.get("operator")
        expected = str(condition.get("value") or "")

        if operator == "equals" and source_answer == expected:
            visible.append(question)
        elif operator == "not_equals" and source_answer != expected:
            visible.append(question)
        elif operator == "contains" and expected.lower() in source_answer.lower():
            visible.append(question)
        elif operator == "not_empty" and source_answer:
            visible.append(question)

    return visible


def calculate_score(form, answers):
    """
    Calculate quiz score from trusted form configuration.

    answers is a mapping of question_id -> submitted answer string.
    """
    quiz = getattr(form, "quiz", None) or {}
    if not quiz.get("enabled"):
        return None

    default_points = quiz.get("default_points", 10)
    earned = 0
    possible = 0
    scored_answers = []

    visible_questions = _filter_visible_questions(getattr(form, "questions", None) or [], answers)

    for question in visible_questions:
        points = question.get("points")
        if points is None:
            points = default_points
        points = float(points or 0)

        correct_answer = question.get("correct_answer")
        has_correct_answer = bool(str(correct_answer or "").strip())
        submitted_answer = answers.get(question.get("id"))
        is_correct = has_correct_answer and _normalize(submitted_answer) == _normalize(correct_answer)

        if has_correct_answer:
            possible += points
            if is_correct:
                earned += points

        scored_answers.append({
            "question_id": question.get("id"),
            "is_correct": is_correct if has_correct_answer else None,
            "points_earned": points if is_correct else 0,
            "points_possible": points if has_correct_answer else 0,
        })

    percent = round((earned / possible) * 100) if possible > 0 else None
    return {
        "earned": earned,
        "possible": possible,
        "percent": percent,
        "scored_answers": scored_answers,
    }
