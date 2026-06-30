# Multi-Source Candidate Data Transformer

> Eightfold Engineering Intern Assignment — Jul–Dec 2026

## Overview

A pipeline that ingests candidate information from multiple sources (CSV recruiter export + PDF resume), resolves identity across sources, merges fields using a per-field conflict policy, and emits a clean, validated canonical profile — with full provenance and confidence tracking.

**Core principle:** Wrong-but-confident is worse than honestly-empty. Unknown values become `null`, never invented.

---

## How to Run

### 1. Setup

```bash
# Clone the repo
git clone <repo-url>
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

### 2. Run the pipeline

```bash
# Default full-schema output (all canonical fields)
python main.py --csv input/recruiter.csv --resume input/resume.pdf --output output/result.json

# Custom projection via config
python main.py --csv input/recruiter.csv --resume input/resume.pdf \
  --config configs/custom_projection.json --output output/result_custom.json

# Print to stdout (omit --output)
python main.py --csv input/recruiter.csv --resume input/resume.pdf
```

### 3. Run tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=src   # with coverage
```

---

## Project Structure

```
candidate-transformer/
├── input/
│   ├── recruiter.csv          # Structured source (4 candidate rows, see design notes)
│   └── resume.pdf             # Unstructured source (matches row 1 candidate)
├── configs/
│   ├── default_projection.json    # Full schema, no remapping
│   └── custom_projection.json     # Field selection + remapping + normalization override
├── output/                        # Git-ignored, created at runtime
├── src/
│   ├── parsers/
│   │   ├── csv_parser.py          # Phase 3: structured CSV reader
│   │   └── resume_parser.py       # Phase 4: PDF text extractor + regex parser
│   ├── canonical_schema.py        # Phase 2: Pydantic models
│   ├── normalizer.py              # Phase 5: pure normalization functions
│   ├── validator.py               # Phase 6: input-side field validator
│   ├── matcher.py                 # Phase 6.5: identity resolution / clustering
│   ├── merger.py                  # Phase 7: per-field conflict merge engine
│   ├── confidence.py              # Phase 8: confidence scoring
│   ├── provenance.py              # Phase 9: provenance tracking
│   ├── profile_builder.py         # Phase 10: assemble canonical CandidateProfile
│   ├── projector.py               # Phase 11: config-driven projection layer
│   └── output_validator.py        # Phase 11.5: output-side schema validator
├── tests/
│   ├── test_normalizer.py
│   ├── test_matcher.py
│   ├── test_merger.py
│   ├── test_projector.py
│   └── test_output_validator.py
├── main.py                        # Phase 12: CLI entry point
├── requirements.txt
└── README.md
```

---

## Pipeline Steps

1. **Parse** — CSV parser and resume parser each emit raw dicts tagged with `{"_source": "<filename>"}`. No normalization at this stage.
2. **Normalize** — Pure functions convert phones to E.164, emails to lowercase, dates to YYYY-MM, skills to canonical names, countries to ISO-3166 alpha-2.
3. **Validate** — Invalid values are set to `None` and logged. Pipeline never crashes on bad data.
4. **Identity Resolution** — Groups raw dicts from multiple sources into clusters representing the same person. Primary key: normalized email (exact). Fallback: fuzzy name similarity ≥ 85 AND phone overlap.
5. **Merge** — Per-field conflict policy (see table below) combines each cluster into one dict. List fields are unioned and deduplicated.
6. **Confidence** — Overall score = `base_score(source_count) × avg(source_reliability_weights)`. Per-skill confidence computed separately.
7. **Provenance** — Every field write records: field name, winning source, method (e.g. `merge_conflict_csv_won`).
8. **Build Canonical Profile** — Merged dict → `CandidateProfile(**data)` via Pydantic. This is the single validated source of truth.
9. **Project** — Config-driven transformation: path resolution, per-field re-normalization, `on_missing` handling, confidence/provenance toggles.
10. **Validate Output** — Checks projected JSON against config (required fields, type declarations). Aborts write only on `required: true` violations.

---

## Per-Field Conflict Resolution Policy

| Field | Preferred Source | Rationale |
|-------|-----------------|-----------|
| `emails` | Union of all | List field — keep all, deduplicate |
| `phones` | Union of all | List field — keep all, deduplicate |
| `full_name` | CSV, fallback resume | Recruiter-verified spelling |
| `location` | Whichever present; CSV wins on conflict | Rarely conflicts |
| `headline` | Resume | Usually absent from CSV |
| `years_experience` | Resume, fallback CSV | Resume has richer date context |
| `skills` | Union (resume enriches, CSV anchors) | List field — union + deduplicate |
| `experience` | Resume | Richer unstructured detail |
| `education` | Resume | Richer unstructured detail |
| `links` | Union (each sub-field: first non-null wins) | Different sources have different links |

---

## Identity Resolution Policy

- **Primary key:** Exact match on normalized email. If any email from source A matches any email from source B, they merge.
- **Fallback:** `rapidfuzz.fuzz.token_sort_ratio(name_A, name_B) ≥ 85` **AND** phone sets overlap.
- **Threshold rationale:** 85 covers common typos and abbreviations (Jon/John, Rob/Robert) without false-merging candidates with common names like "John Lee" and "John Li". Phone is required in the fallback to reduce false positive rate.
- **No match:** Treated as a separate candidate. No force-merging.

---

## `candidate_id` Generation

`candidate_id = sha256(normalized_primary_email)[:16]`

If no email is available: `sha256(normalized_full_name + normalized_primary_phone)[:16]`

**Determinism guarantee:** Same inputs always produce the same `candidate_id`. UUID4 is deliberately not used.

---

## Normalization Formats

| Field | Format |
|-------|--------|
| Phone | E.164 (`+14155552671`) |
| Email | lowercase, stripped |
| Country | ISO-3166 alpha-2 (`US`, `IN`) |
| Dates | YYYY-MM (`2023-04`) |
| Skills | Canonical lowercase name (synonym mapping applied) |

---

## Known Limitations

- Resume PDF extraction uses regex on section headers — accuracy depends on PDF formatting. Non-standard resume layouts may yield incomplete data.
- `years_experience` extracted from resume by summing date ranges in experience blocks. Best-effort; may be `None` for unusual date formats.
- ATS JSON blob, GitHub profile URL, LinkedIn profile URL parsers are **descoped** (see below).

---

## Descoped Items

The following were listed as options in the brief but were deliberately excluded to stay within scope:
- ATS JSON blob parser
- GitHub profile URL fetcher
- LinkedIn profile URL parser
- Recruiter notes (.txt) parser

The minimum requirement of **1 structured source (CSV) + 1 unstructured source (resume PDF)** is fully met.

---

## Sample Output

*(Populated after Phase 12 — will be added here)*

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Pipeline error (logged to stderr) |
| 2 | Bad arguments |
