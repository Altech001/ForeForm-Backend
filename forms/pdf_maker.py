import json, sys, textwrap
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# ── Color palette (university formal) ─────────────────────────────────────────
NAVY    = colors.HexColor("#1A2B5F")
GOLD    = colors.HexColor("#C8A951")
LIGHT   = colors.HexColor("#F5F7FA")
BORDER  = colors.HexColor("#CBD5E1")
GRAY    = colors.HexColor("#64748B")
WHITE   = colors.white
BLACK   = colors.HexColor("#0F172A")
ACCENT  = colors.HexColor("#E8F0FE")

# ── Styles ────────────────────────────────────────────────────────────────────
def make_styles():
    return {
        "uni_name": ParagraphStyle("uni_name",
            fontName="Helvetica-Bold", fontSize=13, textColor=NAVY,
            alignment=TA_CENTER, spaceAfter=2),
        "dept": ParagraphStyle("dept",
            fontName="Helvetica", fontSize=9, textColor=GRAY,
            alignment=TA_CENTER, spaceAfter=2),
        "form_title": ParagraphStyle("form_title",
            fontName="Helvetica-Bold", fontSize=16, textColor=NAVY,
            alignment=TA_CENTER, spaceBefore=6, spaceAfter=4),
        "form_subtitle": ParagraphStyle("form_subtitle",
            fontName="Helvetica-Oblique", fontSize=9, textColor=GRAY,
            alignment=TA_CENTER, spaceAfter=8),
        "section_header": ParagraphStyle("section_header",
            fontName="Helvetica-Bold", fontSize=10, textColor=WHITE,
            spaceBefore=10, spaceAfter=4, leftIndent=6),
        "question_label": ParagraphStyle("question_label",
            fontName="Helvetica-Bold", fontSize=9, textColor=BLACK,
            spaceBefore=6, spaceAfter=2),
        "help_text": ParagraphStyle("help_text",
            fontName="Helvetica-Oblique", fontSize=8, textColor=GRAY,
            spaceAfter=3),
        "body": ParagraphStyle("body",
            fontName="Helvetica", fontSize=9, textColor=BLACK,
            leading=13, alignment=TA_JUSTIFY),
        "consent": ParagraphStyle("consent",
            fontName="Helvetica", fontSize=8, textColor=BLACK,
            leading=12, spaceAfter=4),
        "footer": ParagraphStyle("footer",
            fontName="Helvetica", fontSize=7.5, textColor=GRAY,
            alignment=TA_CENTER),
        "required": ParagraphStyle("required",
            fontName="Helvetica-Bold", fontSize=9, textColor=colors.red,
            spaceAfter=0),
    }

# ── Header with university branding ───────────────────────────────────────────
def make_header(meta, styles):
    rows = []
    # University name & department
    rows.append(Paragraph(meta.get("university", "University Name"), styles["uni_name"]))
    rows.append(Paragraph(meta.get("department", "Department of Research"), styles["dept"]))
    rows.append(HRFlowable(width=CONTENT_W, thickness=2, color=GOLD, spaceAfter=6))
    rows.append(Paragraph(meta.get("title", "Survey Form"), styles["form_title"]))
    if meta.get("subtitle"):
        rows.append(Paragraph(meta["subtitle"], styles["form_subtitle"]))
    rows.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=BORDER, spaceAfter=8))

    # Info table (ref number, date, academic year, confidentiality)
    ref = meta.get("ref_number", "REF-001")
    acad_year = meta.get("academic_year", "2025/2026")
    info_data = [
        [Paragraph(f"<b>Reference No:</b> {ref}", styles["body"]),
         Paragraph(f"<b>Academic Year:</b> {acad_year}", styles["body"])],
        [Paragraph(f"<b>Date:</b> ______________________", styles["body"]),
         Paragraph("<b>Confidential:</b> Yes — responses are anonymous", styles["body"])],
    ]
    info_table = Table(info_data, colWidths=[CONTENT_W/2, CONTENT_W/2])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), LIGHT),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.3, BORDER),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    rows.append(info_table)
    rows.append(Spacer(1, 8))
    return rows

# ── Consent notice ─────────────────────────────────────────────────────────────
def make_consent(meta, styles):
    text = meta.get("consent_text",
        "This survey is conducted for academic research purposes. Participation is voluntary and all responses are strictly confidential. "
        "Data will be used solely for research and will be reported in aggregate form. "
        "By completing this form you consent to your responses being used for this purpose.")
    box_data = [[Paragraph(f"<b>Participant Information &amp; Consent</b><br/>{text}", styles["consent"])]]
    t = Table(box_data, colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), ACCENT),
        ("BOX", (0,0), (-1,-1), 1, NAVY),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    return [t, Spacer(1, 10)]

# ── Section header ─────────────────────────────────────────────────────────────
def make_section(title, styles):
    data = [[Paragraph(title.upper(), styles["section_header"])]]
    t = Table(data, colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), NAVY),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
    ]))
    return [t, Spacer(1, 4)]

# ── Individual field renderers ─────────────────────────────────────────────────
def field_text(field, q_num, styles):
    lines = []
    label = f"{q_num}. {field['label']}"
    req = " *" if field.get("required") else ""
    lines.append(Paragraph(label + req, styles["question_label"]))
    if field.get("help"):
        lines.append(Paragraph(field["help"], styles["help_text"]))
    # Answer line(s)
    n_lines = field.get("lines", 1)
    for _ in range(n_lines):
        data = [[""]]
        t = Table(data, colWidths=[CONTENT_W], rowHeights=[14])
        t.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 0.5, BORDER),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 0),
        ]))
        lines.append(t)
        lines.append(Spacer(1, 3))
    return lines

def field_textarea(field, q_num, styles):
    lines = []
    label = f"{q_num}. {field['label']}"
    req = " *" if field.get("required") else ""
    lines.append(Paragraph(label + req, styles["question_label"]))
    if field.get("help"):
        lines.append(Paragraph(field["help"], styles["help_text"]))
    rows = field.get("rows", 4)
    data = [[""] for _ in range(rows)]
    t = Table(data, colWidths=[CONTENT_W], rowHeights=[14]*rows)
    t.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.3, BORDER),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    lines.append(t)
    lines.append(Spacer(1, 4))
    return lines

def field_radio(field, q_num, styles):
    lines = []
    label = f"{q_num}. {field['label']}"
    req = " *" if field.get("required") else ""
    lines.append(Paragraph(label + req, styles["question_label"]))
    if field.get("help"):
        lines.append(Paragraph(field["help"], styles["help_text"]))
    options = field.get("options", [])
    cols = field.get("columns", 1)
    # Build option rows
    opt_rows = []
    row = []
    for i, opt in enumerate(options):
        cell = Paragraph(f"○  {opt}", styles["body"])
        row.append(cell)
        if len(row) == cols:
            opt_rows.append(row)
            row = []
    if row:
        while len(row) < cols:
            row.append("")
        opt_rows.append(row)
    if opt_rows:
        col_w = CONTENT_W / cols
        t = Table(opt_rows, colWidths=[col_w]*cols)
        t.setStyle(TableStyle([
            ("TOPPADDING", (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
        ]))
        lines.append(t)
    lines.append(Spacer(1, 4))
    return lines

def field_checkbox(field, q_num, styles):
    lines = []
    label = f"{q_num}. {field['label']}"
    req = " *" if field.get("required") else ""
    lines.append(Paragraph(label + req, styles["question_label"]))
    if field.get("help"):
        lines.append(Paragraph(field["help"], styles["help_text"]))
    options = field.get("options", [])
    cols = field.get("columns", 1)
    opt_rows = []
    row = []
    for opt in options:
        cell = Paragraph(f"☐  {opt}", styles["body"])
        row.append(cell)
        if len(row) == cols:
            opt_rows.append(row)
            row = []
    if row:
        while len(row) < cols:
            row.append("")
        opt_rows.append(row)
    if opt_rows:
        col_w = CONTENT_W / cols
        t = Table(opt_rows, colWidths=[col_w]*cols)
        t.setStyle(TableStyle([
            ("TOPPADDING", (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
        ]))
        lines.append(t)
    lines.append(Spacer(1, 4))
    return lines

def field_rating(field, q_num, styles):
    lines = []
    label = f"{q_num}. {field['label']}"
    req = " *" if field.get("required") else ""
    lines.append(Paragraph(label + req, styles["question_label"]))
    if field.get("help"):
        lines.append(Paragraph(field["help"], styles["help_text"]))
    scale = field.get("scale", 5)
    low_label = field.get("low_label", "Strongly Disagree")
    high_label = field.get("high_label", "Strongly Agree")
    # Scale row
    headers = [Paragraph(f"<b>{i}</b>", ParagraphStyle("c", fontName="Helvetica-Bold", fontSize=9, alignment=TA_CENTER))
               for i in range(1, scale+1)]
    circles = [Paragraph("○", ParagraphStyle("c", fontName="Helvetica", fontSize=12, alignment=TA_CENTER))
               for _ in range(scale)]
    col_w = (CONTENT_W - 40*mm) / scale
    data = [headers, circles]
    t = Table(data, colWidths=[col_w]*scale)
    t.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.3, BORDER),
        ("BACKGROUND", (0,0), (-1,0), LIGHT),
    ]))
    label_row_data = [[Paragraph(low_label, styles["help_text"]),
                       Paragraph(high_label, ParagraphStyle("r", fontName="Helvetica-Oblique", fontSize=8, textColor=GRAY, alignment=TA_LEFT))]]
    label_t = Table(label_row_data, colWidths=[CONTENT_W/2, CONTENT_W/2])
    label_t.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
    # Wrap in outer with labels
    outer = Table([[Paragraph(low_label, styles["help_text"]), t, Paragraph(high_label, styles["help_text"])]],
                   colWidths=[20*mm, CONTENT_W - 40*mm, 20*mm])
    outer.setStyle(TableStyle([
        ("ALIGN", (0,0), (0,0), "RIGHT"),
        ("ALIGN", (2,0), (2,0), "LEFT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    lines.append(outer)
    lines.append(Spacer(1, 4))
    return lines

def field_matrix(field, q_num, styles):
    lines = []
    label = f"{q_num}. {field['label']}"
    req = " *" if field.get("required") else ""
    lines.append(Paragraph(label + req, styles["question_label"]))
    if field.get("help"):
        lines.append(Paragraph(field["help"], styles["help_text"]))
    rows_labels = field.get("rows", ["Row 1"])
    cols_labels = field.get("options", ["Option 1", "Option 2"])
    n_cols = len(cols_labels)
    row_w = 50*mm
    col_w = (CONTENT_W - row_w) / n_cols
    # Header row
    header = [Paragraph("", styles["body"])] + [
        Paragraph(f"<b>{c}</b>", ParagraphStyle("ch", fontName="Helvetica-Bold", fontSize=8, alignment=TA_CENTER))
        for c in cols_labels
    ]
    data = [header]
    for r in rows_labels:
        data.append([Paragraph(r, styles["body"])] + [
            Paragraph("○", ParagraphStyle("cc", fontName="Helvetica", fontSize=12, alignment=TA_CENTER))
            for _ in cols_labels
        ])
    t = Table(data, colWidths=[row_w] + [col_w]*n_cols)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), NAVY),
        ("TEXTCOLOR", (0,0), (-1,0), WHITE),
        ("BACKGROUND", (0,1), (-1,-1), WHITE),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LIGHT]),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.3, BORDER),
        ("ALIGN", (1,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (0,-1), 6),
    ]))
    lines.append(t)
    lines.append(Spacer(1, 4))
    return lines

def field_select(field, q_num, styles):
    # Render as radio for print
    return field_radio({**field, "type": "radio"}, q_num, styles)

def field_date(field, q_num, styles):
    lines = []
    label = f"{q_num}. {field['label']}"
    req = " *" if field.get("required") else ""
    lines.append(Paragraph(label + req, styles["question_label"]))
    data = [[Paragraph("DD", styles["body"]), Paragraph("/", styles["body"]),
             Paragraph("MM", styles["body"]), Paragraph("/", styles["body"]),
             Paragraph("YYYY", styles["body"])]]
    widths = [18*mm, 6*mm, 18*mm, 6*mm, 24*mm]
    t = Table(data, colWidths=widths, rowHeights=[18])
    t.setStyle(TableStyle([
        ("BOX", (0,0), (0,0), 0.5, BORDER), ("BOX", (2,0), (2,0), 0.5, BORDER),
        ("BOX", (4,0), (4,0), 0.5, BORDER),
        ("ALIGN", (0,0), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    lines.append(t)
    lines.append(Spacer(1, 4))
    return lines

FIELD_RENDERERS = {
    "text":     field_text,
    "email":    field_text,
    "number":   field_text,
    "tel":      field_text,
    "textarea": field_textarea,
    "radio":    field_radio,
    "checkbox": field_checkbox,
    "select":   field_select,
    "rating":   field_rating,
    "matrix":   field_matrix,
    "date":     field_date,
}

# ── Footer via canvas ──────────────────────────────────────────────────────────
class UniversityFooter:
    def __init__(self, meta):
        self.uni = meta.get("university", "University Name")
        self.form_title = meta.get("title", "Survey Form")
        self.ref = meta.get("ref_number", "REF-001")

    def __call__(self, canvas_obj, doc):
        canvas_obj.saveState()
        canvas_obj.setStrokeColor(GOLD)
        canvas_obj.setLineWidth(1)
        canvas_obj.line(MARGIN, 18*mm, PAGE_W - MARGIN, 18*mm)
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.setFillColor(GRAY)
        canvas_obj.drawString(MARGIN, 14*mm, f"{self.uni}  |  {self.form_title}  |  {self.ref}")
        canvas_obj.drawRightString(PAGE_W - MARGIN, 14*mm, f"Page {doc.page}")
        canvas_obj.restoreState()

# ── Main generator ─────────────────────────────────────────────────────────────
def generate_pdf(schema: dict, output_path: str):
    styles = make_styles()
    meta   = schema.get("meta", {})
    sections = schema.get("sections", [])

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=22*mm, bottomMargin=25*mm,
        title=meta.get("title", "Survey Form"),
        author=meta.get("university", "University"),
    )

    story = []
    story += make_header(meta, styles)
    story += make_consent(meta, styles)

    q_num = 1
    for section in sections:
        story += make_section(section.get("title", "Section"), styles)
        if section.get("description"):
            story.append(Paragraph(section["description"], styles["body"]))
            story.append(Spacer(1, 4))
        for field in section.get("fields", []):
            ftype = field.get("type", "text")
            renderer = FIELD_RENDERERS.get(ftype, field_text)
            block = renderer(field, q_num, styles)
            story.append(KeepTogether(block))
            q_num += 1

    # Signature / declaration block
    story += make_section("Declaration", styles)
    story.append(Paragraph(
        "I confirm that the information provided above is accurate to the best of my knowledge.",
        styles["body"]))
    story.append(Spacer(1, 8))
    sig_data = [
        [Paragraph("<b>Signature:</b>", styles["body"]),
         Paragraph("_" * 35, styles["body"]),
         Paragraph("<b>Date:</b>", styles["body"]),
         Paragraph("_" * 20, styles["body"])],
    ]
    sig_t = Table(sig_data, colWidths=[25*mm, 65*mm, 15*mm, 45*mm])
    sig_t.setStyle(TableStyle([
        ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6)
    ]))
    story.append(sig_t)

    footer_cb = UniversityFooter(meta)
    doc.build(story, onFirstPage=footer_cb, onLaterPages=footer_cb)
    print(f"PDF generated: {output_path}")

# ── Run with sample schema ─────────────────────────────────────────────────────
if __name__ == "__main__":
    schema_path = sys.argv[1] if len(sys.argv) > 1 else None
    if schema_path:
        with open(schema_path) as f:
            schema = json.load(f)
    else:
        # Built-in demo schema
        schema = {
            "meta": {
                "university":    "Makerere University",
                "department":    "School of Computing & Informatics Technology",
                "title":         "Student Learning Experience Survey",
                "subtitle":      "Academic Year 2025/2026 — Semester II",
                "ref_number":    "MUK/SCI/SURV/2025/001",
                "academic_year": "2025/2026",
                "consent_text":  (
                    "This survey is conducted by the School of Computing & Informatics Technology to evaluate the quality "
                    "of teaching and learning. Your participation is voluntary and all responses are strictly confidential. "
                    "Results will be reported in aggregate only and used solely to improve academic programmes."
                )
            },
            "sections": [
                {
                    "title": "Section A — Respondent Information",
                    "description": "Please provide your academic details. Do not write your name.",
                    "fields": [
                        {"type": "radio",    "label": "Year of Study", "required": True,
                         "options": ["Year 1", "Year 2", "Year 3", "Year 4", "Postgraduate"], "columns": 3},
                        {"type": "radio",    "label": "Programme of Study", "required": True,
                         "options": ["BSc Computer Science", "BSc Information Technology",
                                     "BSc Software Engineering", "MSc Information Systems", "Other"], "columns": 2},
                        {"type": "radio",    "label": "Gender", "required": False,
                         "options": ["Male", "Female", "Prefer not to say"], "columns": 3},
                    ]
                },
                {
                    "title": "Section B — Teaching Quality",
                    "description": "Rate the following statements on a scale of 1 (Strongly Disagree) to 5 (Strongly Agree).",
                    "fields": [
                        {"type": "rating", "label": "Lectures are well-organised and clearly delivered.", "required": True, "scale": 5,
                         "low_label": "Strongly Disagree", "high_label": "Strongly Agree"},
                        {"type": "rating", "label": "Course materials are relevant and up-to-date.", "required": True, "scale": 5,
                         "low_label": "Strongly Disagree", "high_label": "Strongly Agree"},
                        {"type": "rating", "label": "Lecturers are available for consultation outside class.", "required": True, "scale": 5,
                         "low_label": "Strongly Disagree", "high_label": "Strongly Agree"},
                        {"type": "matrix",
                         "label": "Please rate your satisfaction with the following resources:",
                         "rows": ["Library resources", "Computer labs", "Internet connectivity", "Study spaces"],
                         "options": ["Very Poor", "Poor", "Fair", "Good", "Excellent"]},
                    ]
                },
                {
                    "title": "Section C — Assessment & Feedback",
                    "fields": [
                        {"type": "checkbox", "label": "Which assessment methods are used in your programme? (Select all that apply)",
                         "options": ["Written exams", "Coursework / assignments", "Group projects",
                                     "Presentations", "Practical / lab work", "Online quizzes"], "columns": 2},
                        {"type": "radio", "label": "How would you rate the timeliness of feedback on your assessments?",
                         "options": ["Always timely", "Usually timely", "Sometimes delayed", "Often delayed", "Never timely"],
                         "columns": 2},
                        {"type": "textarea", "label": "What aspects of the assessment process work well?",
                         "rows": 3, "help": "Please be specific."},
                        {"type": "textarea", "label": "What improvements would you suggest to the assessment process?",
                         "rows": 3},
                    ]
                },
                {
                    "title": "Section D — Overall Experience",
                    "fields": [
                        {"type": "rating", "label": "Overall, I am satisfied with my academic experience at this institution.",
                         "scale": 5, "low_label": "Strongly Disagree", "high_label": "Strongly Agree", "required": True},
                        {"type": "textarea",
                         "label": "Please share any additional comments, suggestions or concerns:",
                         "rows": 5, "help": "Your feedback is greatly valued."},
                    ]
                }
            ]
        }

    output = sys.argv[2] if len(sys.argv) > 2 else "/mnt/user-data/outputs/university_survey.pdf"
    generate_pdf(schema, output)
