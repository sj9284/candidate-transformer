"""
Script to generate sample resume.pdf for testing.
Run once: python generate_resume.py
Requires: pip install fpdf2
"""

from fpdf import FPDF


def generate_resume():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(20, 20, 20)

    # --- Name & Contact ---
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, "John Smith", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, "john.smith@email.com  |  +1-415-555-0101  |  San Francisco, CA, US", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "LinkedIn: https://linkedin.com/in/johnsmith  |  GitHub: https://github.com/johnsmith", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # --- Headline ---
    pdf.set_font("Helvetica", "I", 12)
    pdf.cell(0, 8, "Senior Software Engineer with 5+ years building distributed systems at scale.",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # --- Skills ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "SKILLS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, "Python, SQL, Docker, Kubernetes, Go, PostgreSQL, Redis, AWS, Terraform, CI/CD, REST APIs, gRPC")
    pdf.ln(4)

    # --- Experience ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "EXPERIENCE", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Acme Corp - Senior Software Engineer", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 6, "2021-03 to Present", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7,
        "Led migration of monolithic backend to microservices using Kubernetes and Docker. "
        "Reduced deployment time by 60%. Mentored 3 junior engineers. "
        "Built real-time data pipelines processing 500k events/day using Python and Redis Streams."
    )
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "StartupXYZ - Software Engineer", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 6, "2019-06 to 2021-02", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7,
        "Designed and implemented REST APIs using Python/Flask serving 2M+ requests/day. "
        "Introduced automated testing with pytest, raising code coverage from 40% to 85%. "
        "Owned PostgreSQL database schema design and query optimization."
    )
    pdf.ln(4)

    # --- Education ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "EDUCATION", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "University of California, Berkeley", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, "B.S. Computer Science | 2019", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # --- Certifications (extra content to test robustness) ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "CERTIFICATIONS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, "AWS Certified Solutions Architect - Associate (2022)", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Certified Kubernetes Administrator (CKA) (2023)", new_x="LMARGIN", new_y="NEXT")

    pdf.output("input/resume.pdf")
    print("resume.pdf generated successfully in input/")


if __name__ == "__main__":
    generate_resume()
