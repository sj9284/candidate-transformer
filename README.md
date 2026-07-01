# Candidate Data Transformer



## Overview
A pipeline that ingests candidate information from multiple sources (CSV recruiter export + PDF resumes), resolves identity across those sources, merges fields using a per-field conflict policy, and emits a clean, validated canonical profile in JSON format — complete with full provenance tracking and dynamic confidence scoring.

**Core principle:** Wrong-but-confident is worse than honestly-empty. Unknown values become `null`, never invented.

## Requirements
- **OS:** Windows / macOS / Linux
- **Python:** Python 3.10+
- **Memory:** 512MB RAM minimum

## Installation

```bash
# Clone the repo
git clone https://github.com/sj9284/candidate-transformer.git
cd candidate-transformer

# Create and activate virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Project Structure

```
candidate-transformer/
├── input/
│   ├── recruiter/
│   │   └── recruiter.csv          
│   └── resume/
│       ├── resume_shubham.pdf    
│       ├── resume_alice.pdf       
│       ├── resume_bob.pdf         
│       └── resume_charlie.pdf    
├── configs/
│   ├── default_projection.json    
│   └── custom_projection.json     
├── output/                        
├── src/
│   ├── parsers/               
│   ├── canonical_schema.py    
│   ├── normalizer.py         
│   ├── validator.py         
│   ├── matcher.py             
│   ├── merger.py            
│   ├── confidence.py         
│   ├── provenance.py         
│   ├── profile_builder.py     
│   ├── projector.py          
│   └── output_validator.py   
├── tests/                    
├── main.py                    
└── requirements.txt
```

## Input Format

1. **CSV (Structured Data):** Expects standard headers like `candidate_name`, `email`, `phone`, `current_company`, `location_city`, etc. Mock data can contain incomplete fields. Placed inside `input/recruiter/`.
2. **PDF Resumes (Unstructured Data):** Standard text-based PDF files. The pipeline uses `pdfminer.six` and Regex heuristics to parse headlines, experience, education, skills, and contact info. Placed inside `input/resume/`.

## Running the Project

You can pass entire folders (or specific file paths) to `--csv` and `--resume` to automatically process all files inside them:

**Default full-schema output (all canonical fields):**
```bash
python main.py --csv input/recruiter --resume input/resume --output output/result.json
```

**Custom projection via config:**
```bash
python main.py --csv input/recruiter --resume input/resume --config configs/custom_projection.json --output output/result.json
```

**Print to stdout (omit --output):**
```bash
python main.py --csv input/recruiter --resume input/resume
```

## Sample Run
```
03:40:25 INFO     __main__: Starting pipeline ...
03:40:25 INFO     __main__: Phase 3: Parsing CSV - input/recruiter/recruiter.csv
03:40:25 INFO     __main__: Phase 4: Parsing resume - input/resume/resume_shubham.pdf
...
03:40:26 INFO     __main__: Phase 6.5: Resolving identity across 8 dict(s)
03:40:26 INFO     src.matcher: Merged: [3]'Shubham Jain' + [4]'Shubham Jain' via email_exact
03:40:26 INFO     __main__: Phase 7: Merging 7 cluster(s)
03:40:26 INFO     __main__: Phase 8: Scoring confidence
03:40:26 INFO     src.confidence: Confidence scored: name='Shubham Jain' overall=0.9117 skills=22 sources=['input/recruiter/recruiter.csv', 'input/resume/resume_shubham.pdf']
03:40:26 INFO     __main__: Phase 11: Projecting output (config=default)
03:40:26 INFO     __main__: Output written to output/result.json
03:40:26 INFO     __main__: Pipeline complete - 7 candidate(s) processed.
```

## Sample Output (Default Configuration)
```json
{
  "candidate_id": "1b58d15fa067ba52",
  "full_name": "Shubham Jain",
  "headline": "Research Intern (Scientific Analysis Group)",
  "emails": ["shubhamjain9313.sjsj.sjsj@gmail.com"],
  "phones": ["+918595606855"],
  "overall_confidence": 0.9117,
  "skills": [
    {
      "name": "python",
      "confidence": 0.98,
      "sources": ["input/recruiter/recruiter.csv", "input/resume/resume_shubham.pdf"]
    }
  ],
  "experience": [
    {
      "company": "Defence Research And Development Organisation",
      "title": "Research Intern (Scientific Analysis Group)",
      "start": "2025-06",
      "end": "2025-07",
      "summary": "Built an AI-powered research paper search engine..."
    }
  ],
  "provenance": [
    {
      "field": "full_name",
      "value": "Shubham Jain",
      "source": "input/recruiter/recruiter.csv",
      "method": "merge_conflict_csv_won",
      "confidence": 1.0
    }
  ]
}
```

## Output Files
- The pipeline dumps a structured JSON array into the path defined by the `--output` flag (e.g., `output/result.json`).
- If no output path is provided, it prints the JSON array directly to standard output.

## Running the Tests

To verify that the normalization, merging, and projection logic work exactly as intended:
```bash
# Run unit test suite
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=src
```

## Notes
- **Identity Resolution**: Candidates are merged primarily using exact normalized email matches. The fallback logic checks fuzzy name similarity (≥ 85%) combined with phone number overlaps.
- **Determinism**: Candidate IDs are generated using a stable SHA-256 hash of the normalized email (or phone fallback), guaranteeing the same candidate always receives the same ID on subsequent runs.
- **Dynamic Confidence**: The confidence scoring engine is fully dynamic. It checks the completeness of Experience and Education fields, contact information volume, and rewards multiple sources corroborating the same skill.
- **Git Directory Structure**: Empty runtime directories (`input/recruiter`, `input/resume`, and `output`) are preserved in version control using `.gitkeep` files while ignoring actual data contents.
