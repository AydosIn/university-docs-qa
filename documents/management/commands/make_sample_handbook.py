from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# A fictional handbook. Keeping each topic on a known page lets later steps
# check that search finds the right page.
SAMPLE_PAGES = [
    (
        "Northbridge Institute: Student Handbook 2026-2027",
        "This handbook sets out the academic rules for all undergraduate students. "
        "It applies from 1 September 2026 and replaces all earlier editions.",
    ),
    (
        "Section 1: Attendance",
        "1.1 Students must attend at least 75 percent of the classes in each course.\n"
        "1.2 A student may miss no more than 6 classes in a course of 24 classes.\n"
        "1.3 A student who exceeds this limit is barred from the final examination.\n"
        "1.4 Absences for illness require a medical certificate, submitted to the "
        "Registrar's Office within 5 working days.",
    ),
    (
        "Section 2: Examinations",
        "2.1 Final examinations take place in January and in June.\n"
        "2.2 A student who misses a final examination for a documented medical or "
        "family emergency may apply for a deferred examination.\n"
        "2.3 The application must reach the Examinations Office within 3 working days "
        "of the missed examination.\n"
        "2.4 A student who misses an examination without an approved reason receives "
        "a mark of zero for that examination.",
    ),
    (
        "Section 3: Grading",
        "3.1 The minimum passing grade for a course is 55 out of 100.\n"
        "3.2 Grades are awarded as follows:\n"
        "Grade A: 86 to 100\n"
        "Grade B: 71 to 85\n"
        "Grade C: 55 to 70\n"
        "Grade F: 0 to 54\n"
        "3.3 The final examination counts for 40 percent of the course grade.",
    ),
    (
        "Section 4: Assignments",
        "4.1 The final assignment for each course is due by 23:59 on the last Friday "
        "of the teaching term.\n"
        "4.2 Late work loses 10 percent of its mark for each day it is late.\n"
        "4.3 Work submitted more than 5 days late receives a mark of zero.",
    ),
    (
        "Section 5: Appeals",
        "5.1 A student may appeal a final grade within 10 working days of its "
        "publication.\n"
        "5.2 Appeals are submitted in writing to the Dean of Students.\n"
        "5.3 Contact: registrar@northbridge.example",
    ),
]


class Command(BaseCommand):
    help = "Create a small fictional handbook PDF for trying out the system."

    def handle(self, *args, **options):
        from fpdf import FPDF  # Only needed in development (requirements-dev.txt).

        pdf = FPDF()
        for heading, body in SAMPLE_PAGES:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 10, heading, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
            pdf.set_font("Helvetica", size=12)
            pdf.multi_cell(0, 8, body, new_x="LMARGIN", new_y="NEXT")

        output = Path(settings.BASE_DIR) / "samples" / "sample_handbook.pdf"
        output.parent.mkdir(exist_ok=True)
        pdf.output(str(output))
        self.stdout.write(self.style.SUCCESS(f"Created {output}"))
