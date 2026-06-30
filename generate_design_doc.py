from fpdf import FPDF

def generate_design_doc():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(20, 20, 20)
    
    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Candidate Data Transformer - Design Document", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    
    # Author
    pdf.set_font("Helvetica", "I", 12)
    pdf.cell(0, 10, "Author: Shubham Jain", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)

    # Core Design Choices
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "1. Core Design Choices", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    core_text = (
        "The architecture relies on a multi-phase batch processing pipeline. "
        "It decouples ingestion (parsers), normalization, identity resolution (matching), "
        "merging, and output projection. This modular design ensures that adding new "
        "data sources (e.g., an API endpoint) only requires writing a new parser without "
        "touching the core merging logic. All parsed data is internally structured into a "
        "canonical CandidateProfile schema before final projection."
    )
    pdf.multi_cell(0, 6, core_text)
    pdf.ln(5)

    # Dealing with Messy Data
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "2. Dealing with Messy / Missing Data", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    messy_text = (
        "We handle messy data in two distinct phases: Normalization and Validation. "
        "Normalizers use robust regex (e.g., extracting E164 phone numbers) and mapping "
        "(e.g., country codes). The Validator acts as a strict firewall: if a required field "
        "like an email is missing or unparseable, it rejects only that specific field while "
        "keeping the rest of the candidate's data intact. The pipeline relies heavily on "
        "best-effort extraction, meaning missing data simply results in nulls rather than crashes."
    )
    pdf.multi_cell(0, 6, messy_text)
    pdf.ln(5)

    # Identity Resolution
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "3. Identity Resolution", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    id_text = (
        "Identity resolution operates on an equivalence-class clustering algorithm. "
        "Two candidate records are considered the same person if they share an exact "
        "normalized email OR if they have a fuzzy name match (Jaro-Winkler distance) "
        "combined with an overlapping phone number. By computing the transitive closure "
        "of these matches, we safely cluster candidate fragments from across the CSV "
        "and PDFs into a single unified entity."
    )
    pdf.multi_cell(0, 6, id_text)
    pdf.ln(5)

    # Confidence Scoring
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "4. Confidence Scoring", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    conf_text = (
        "Confidence is scored mathematically based on source reliability and corroboration. "
        "Data found in a structured CSV is inherently trusted more than regex-extracted "
        "PDF fields. When a field is corroborated by multiple distinct sources (e.g., "
        "an email present in both the CSV and the Resume), the confidence score increases. "
        "We also penalize the score if conflicts are found between sources."
    )
    pdf.multi_cell(0, 6, conf_text)
    pdf.ln(5)

    # Required Twist: Configurable Output
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "5. Required Twist: Configurable Output", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    twist_text = (
        "To satisfy the required twist, a dynamic Projection Layer was implemented. "
        "Instead of hardcoding the final JSON structure, a custom JSON config defines "
        "a DSL (Domain Specific Language) that maps internal paths (e.g., 'emails[0]') "
        "to arbitrary output keys. This layer allows downstream products to define "
        "their exact schema requirements, normalization rules, and strict typing validations "
        "without requiring any code changes to the core transformer pipeline."
    )
    pdf.multi_cell(0, 6, twist_text)

    # Output file
    pdf.output("ShubhamJain_Eightfold_Design.pdf")
    print("Design document generated: ShubhamJain_Eightfold_Design.pdf")

if __name__ == "__main__":
    generate_design_doc()
