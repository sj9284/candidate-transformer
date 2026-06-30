"""
Script to generate a second sample resume.pdf for testing different data.
Run once: python generate_resume2.py
"""

from fpdf import FPDF

def generate_resume():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(20, 20, 20)

    # --- Header ---
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 15, "Jane Austen", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 12)
    # Notice we use one of the emails from the CSV to trigger the Identity Resolution
    pdf.cell(0, 8, "jane.austen@example.com | +1 (212) 555-1234 | New York, NY", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # --- Headline ---
    pdf.set_font("Helvetica", "I", 12)
    pdf.cell(0, 8, "Software Engineer specializing in scalable backend services.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # --- Experience (Notice the different header style) ---
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "EXPERIENCE", new_x="LMARGIN", new_y="NEXT", border="B")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Backend Engineer | Stripe", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 11)
    pdf.cell(0, 6, "October 2021 to Present", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, "Designed core APIs for payment processing. Integrated machine learning models to reduce fraud by 15%. Led a team of 4 engineers.")
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Junior Developer | Tech Startup", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 11)
    pdf.cell(0, 6, "Jan 2019 to Sep 2021", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, "Developed REST APIs using Node.js and PostgreSQL. Migrated legacy systems to AWS.")
    pdf.ln(5)

    # --- Skills ---
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "SKILLS", new_x="LMARGIN", new_y="NEXT", border="B")
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, "Node.js, PostgreSQL, AWS, Machine Learning, Python, Ruby on Rails, Git")
    pdf.ln(5)

    # --- Education ---
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "EDUCATION", new_x="LMARGIN", new_y="NEXT", border="B")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "New York University", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, "Bachelor of Science in Computer Science | 2018", new_x="LMARGIN", new_y="NEXT")

    pdf.output("input/resume2.pdf")
    print("resume2.pdf generated successfully in input/")

if __name__ == "__main__":
    generate_resume()
