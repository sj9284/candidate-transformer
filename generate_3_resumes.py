"""
Script to generate test data with 3 CSV rows and 3 corresponding resumes.
"""

from fpdf import FPDF
import csv

def create_csv():
    data = [
        ["candidate_id", "name", "email", "phone", "company", "title", "location"],
        ["C201", "Alice Smith", "alice.smith@example.com", "555-0101", "Acme", "Developer", "Seattle"],
        ["C202", "Bob Jones", "bob.jones@example.com", "+1-555-0102", "Globex", "Data Analyst", "Austin"],
        ["C203", "Charlie Brown", "charlie.b@example.com", "555-0103", "Initech", "Manager", "Denver"]
    ]
    with open("input/test3.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(data)
    print("Created input/test3.csv")

def generate_resume(name, email, phone, headline, skills, filename):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(20, 20, 20)
    
    # Header
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 15, name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, f"{email} | {phone}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    
    # Headline
    pdf.set_font("Helvetica", "I", 12)
    pdf.cell(0, 8, headline, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    
    # Skills
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "SKILLS", new_x="LMARGIN", new_y="NEXT", border="B")
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, skills)
    pdf.ln(5)
    
    # Experience (dummy)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "EXPERIENCE", new_x="LMARGIN", new_y="NEXT", border="B")
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, f"Professional | Some Company", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 11)
    pdf.cell(0, 6, "Jan 2020 to Present", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, "Did amazing work.")
    
    pdf.output(f"input/{filename}")
    print(f"Created input/{filename}")

if __name__ == "__main__":
    create_csv()
    generate_resume("Alice Smith", "alice.smith@example.com", "555-0101", "Frontend Specialist", "React, TypeScript, CSS", "resume_alice.pdf")
    generate_resume("Bob Jones", "bob.jones@example.com", "+1-555-0102", "Data Wizard", "Python, Pandas, SQL", "resume_bob.pdf")
    generate_resume("Charlie Brown", "charlie.b@example.com", "555-0103", "Engineering Leader", "Agile, Jira, Architecture", "resume_charlie.pdf")
