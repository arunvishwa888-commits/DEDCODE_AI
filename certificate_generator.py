import os
import uuid
import datetime
import hashlib
from io import BytesIO
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

CERT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "certificates")
os.makedirs(CERT_DIR, exist_ok=True)

class CareerTrackCertificateService:
    """
    Generates cryptographic verified career certificates and PDF exports using ReportLab.
    """

    @staticmethod
    def generate_unique_certificate_id(user_id, course_id):
        raw_seed = f"DEDCODE-CAREER-TRACK-{user_id}-{course_id}-{datetime.datetime.now().isoformat()}-{uuid.uuid4()}"
        hash_digest = hashlib.sha256(raw_seed.encode("utf-8")).hexdigest().upper()
        unique_suffix = hash_digest[:8]
        return f"DED-CT-{datetime.datetime.now().year}-{unique_suffix}"

    @classmethod
    def generate_pdf(cls, cert_data):
        """
        Creates a beautifully styled landscape PDF certificate using ReportLab.
        """
        cert_id = cert_data["certificate_id"]
        student_name = cert_data["student_name"]
        course_title = cert_data["course_title"]
        project_score = cert_data["project_score"]
        interview_score = cert_data["interview_score"]
        overall_score = cert_data["overall_score"]
        issue_date = cert_data.get("issue_date", datetime.datetime.now().strftime("%B %d, %Y"))

        pdf_filename = f"certificate_{cert_id}.pdf"
        file_path = os.path.join(CERT_DIR, pdf_filename)

        # Create Landscape Canvas
        page_width, page_height = landscape(letter)
        c = canvas.Canvas(file_path, pagesize=landscape(letter))

        # 1. Background Fill & Borders
        c.setFillColor(colors.HexColor("#FCF8F4"))
        c.rect(0, 0, page_width, page_height, fill=1, stroke=0)

        # Outer Decorative Border (Coral)
        c.setStrokeColor(colors.HexColor("#FF684F"))
        c.setLineWidth(3)
        c.rect(24, 24, page_width - 48, page_height - 48)

        # Inner Subtle Border (Charcoal)
        c.setStrokeColor(colors.HexColor("#E8E1DB"))
        c.setLineWidth(1)
        c.rect(30, 30, page_width - 60, page_height - 60)

        # Top Accent Header Bar
        c.setFillColor(colors.HexColor("#252B35"))
        c.rect(30, page_height - 65, page_width - 60, 35, fill=1, stroke=0)

        # Top Logo & Header Text
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(45, page_height - 52, "DEDCODE • CONTINUOUS AI LEARNING ECOSYSTEM")

        c.setFont("Helvetica", 10)
        c.drawRightString(page_width - 45, page_height - 52, "VERIFIED CAREER TRACK CREDENTIAL")

        # Certificate Title
        c.setFillColor(colors.HexColor("#252B35"))
        c.setFont("Helvetica-Bold", 26)
        c.drawCentredString(page_width / 2, page_height - 120, "CERTIFICATE OF CAREER TRACK EXCELLENCE")

        c.setFillColor(colors.HexColor("#5A606A"))
        c.setFont("Helvetica", 13)
        c.drawCentredString(page_width / 2, page_height - 145, "This is to officially certify that")

        # Student Name (Large & Highlighted)
        c.setFillColor(colors.HexColor("#FF684F"))
        c.setFont("Helvetica-Bold", 28)
        c.drawCentredString(page_width / 2, page_height - 185, str(student_name).upper())

        # Underline under name
        name_width = c.stringWidth(str(student_name).upper(), "Helvetica-Bold", 28)
        c.setStrokeColor(colors.HexColor("#FF684F"))
        c.setLineWidth(1.5)
        c.line((page_width / 2) - (name_width / 2) - 20, page_height - 192, (page_width / 2) + (name_width / 2) + 20, page_height - 192)

        # Description text
        c.setFillColor(colors.HexColor("#252B35"))
        c.setFont("Helvetica", 12)
        desc_line1 = f"has successfully completed the comprehensive, multi-stage Career Track specialization for"
        c.drawCentredString(page_width / 2, page_height - 225, desc_line1)

        c.setFillColor(colors.HexColor("#252B35"))
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(page_width / 2, page_height - 250, str(course_title))

        desc_line2 = (
            "demonstrating verified mastery across full-stack course curricula, production-grade capstone engineering, "
            "and rigorous AI technical interviews."
        )
        c.setFillColor(colors.HexColor("#5A606A"))
        c.setFont("Helvetica", 10)
        c.drawCentredString(page_width / 2, page_height - 275, desc_line2)

        # Metrics Box
        box_x = (page_width / 2) - 240
        box_y = page_height - 350
        box_w = 480
        box_h = 55

        c.setFillColor(colors.HexColor("#FAF6F0"))
        c.setStrokeColor(colors.HexColor("#E8E1DB"))
        c.roundRect(box_x, box_y, box_w, box_h, 8, fill=1, stroke=1)

        # Metric 1: Project Score
        c.setFillColor(colors.HexColor("#5A606A"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(box_x + 25, box_y + 35, "CAPSTONE PROJECT")
        c.setFillColor(colors.HexColor("#252B35"))
        c.setFont("Helvetica-Bold", 15)
        c.drawString(box_x + 25, box_y + 15, f"{project_score}% (50/50 Eval)")

        # Divider 1
        c.setStrokeColor(colors.HexColor("#E8E1DB"))
        c.line(box_x + 160, box_y + 10, box_x + 160, box_y + 45)

        # Metric 2: Interview Score
        c.setFillColor(colors.HexColor("#5A606A"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(box_x + 180, box_y + 35, "AI TECHNICAL INTERVIEW")
        c.setFillColor(colors.HexColor("#252B35"))
        c.setFont("Helvetica-Bold", 15)
        c.drawString(box_x + 180, box_y + 15, f"{interview_score}%")

        # Divider 2
        c.setStrokeColor(colors.HexColor("#E8E1DB"))
        c.line(box_x + 335, box_y + 10, box_x + 335, box_y + 45)

        # Metric 3: Overall Composite
        c.setFillColor(colors.HexColor("#FF684F"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(box_x + 355, box_y + 35, "COMPOSITE STANDING")
        c.setFillColor(colors.HexColor("#FF684F"))
        c.setFont("Helvetica-Bold", 15)
        c.drawString(box_x + 355, box_y + 15, f"{overall_score}% Top Tier")

        # Bottom Signatures & Verification Info
        c.setFillColor(colors.HexColor("#252B35"))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, 75, "Dr. Elena Rostova")
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#5A606A"))
        c.drawString(50, 60, "Dean of AI & Engineering • DEDCODE")

        c.setFillColor(colors.HexColor("#252B35"))
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(page_width - 50, 75, "Marcus Vance")
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#5A606A"))
        c.drawRightString(page_width - 50, 60, "Lead Industry Mentor • Staff AI Architect")

        # Bottom Center: Certificate ID & Verification URL
        c.setFillColor(colors.HexColor("#8A8580"))
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(page_width / 2, 70, f"Certificate ID: {cert_id}")
        c.setFont("Helvetica", 8)
        c.drawCentredString(page_width / 2, 55, f"Issued on: {issue_date} • Authenticate at: http://localhost:5050/#/verify-certificate?id={cert_id}")

        c.showPage()
        c.save()

        return file_path
