"""
Phase 12 — CLI Entry Point
===========================
Wires all pipeline stages together into a single runnable command.

Usage:
    # Default full-schema output (all canonical fields)
    python main.py --csv input/recruiter.csv --resume input/resume.pdf

    # Custom projection config
    python main.py --csv input/recruiter.csv --resume input/resume.pdf \\
        --config configs/custom_projection.json --output output/result.json

    # Print to stdout (omit --output)
    python main.py --csv input/recruiter.csv --resume input/resume.pdf \\
        --config configs/custom_projection.json

    # Verbose logging (debug level)
    python main.py --csv input/recruiter.csv --resume input/resume.pdf --verbose

Exit codes:
    0  Success — output written (or printed to stdout)
    1  Pipeline error — see stderr for details
    2  Bad arguments

Pipeline stages (in order):
    Phase 3   CSV Parser
    Phase 4   Resume Parser
    Phase 6   Field Validation
    Phase 6.5 Identity Resolution
    Phase 7   Merge Engine
    Phase 8   Confidence Engine
    Phase 10  Build Canonical Profiles
    Phase 11  Projection Layer
    Phase 11.5 Output Validation
    Write     stdout or file
"""

import argparse
import json
import logging
import os
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # Silence pdfminer's chatty internal loggers unless verbose
    if not verbose:
        for noisy in ("pdfminer", "pdfminer.pdfpage", "pdfminer.pdfinterp",
                      "pdfminer.converter", "pdfminer.cmapdb", "pdfminer.layout"):
            logging.getLogger(noisy).setLevel(logging.ERROR)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Multi-Source Candidate Data Transformer — "
            "ingests CSV + PDF resume, emits a clean canonical JSON profile."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py --csv input/recruiter.csv --resume input/resume.pdf
  python main.py --csv input/recruiter.csv --resume input/resume.pdf \\
      --config configs/custom_projection.json --output output/result.json
        """,
    )

    parser.add_argument(
        "--csv",
        metavar="FILE",
        help="Path to recruiter CSV file (structured source).",
    )
    parser.add_argument(
        "--resume",
        metavar="FILE",
        nargs="+",
        help="Path to one or more resume PDF files (unstructured source).",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        default=None,
        help=(
            "Path to projection config JSON. "
            "If omitted, outputs the full canonical schema."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Path to write JSON output. If omitted, prints to stdout.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable debug-level logging to stderr.",
    )

    args = parser.parse_args(argv)

    # At least one source is required
    if not args.csv and not args.resume:
        parser.error("At least one of --csv or --resume must be provided.")

    return args


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(
    csv_path: str | None,
    resume_path: list[str] | str | None,
    config_path: str | None,
) -> list[dict[str, Any]]:
    """
    Execute the full transformation pipeline.

    Args:
        csv_path:     Path to recruiter CSV, or None to skip.
        resume_path:  Path to one or more resume PDFs, or None to skip.
        config_path:  Path to projection config, or None for default.

    Returns:
        List of projected + validated output dicts.

    Raises:
        ValueError: If config is malformed.
        RuntimeError: If the pipeline produces zero profiles.
    """
    from src.confidence import score_merged_dict
    from src.matcher import cluster_candidates
    from src.merger import merge_all
    from src.output_validator import filter_valid, validate_all_outputs
    from src.parsers.csv_parser import parse_csv
    from src.parsers.resume_parser import parse_resume
    from src.profile_builder import build_all
    from src.projector import load_config, project_all
    from src.validator import validate_all, validate_dict

    # ------------------------------------------------------------------
    # Phase 3 + 4: Parse sources
    # ------------------------------------------------------------------
    raw_dicts: list[dict] = []

    if csv_path:
        logger.info("Phase 3: Parsing CSV — %s", csv_path)
        csv_rows = parse_csv(csv_path)
        logger.info("  %d row(s) loaded", len(csv_rows))
        raw_dicts.extend(csv_rows)
    else:
        logger.info("Phase 3: No CSV provided — skipping")

    if resume_path:
        resume_paths = [resume_path] if isinstance(resume_path, str) else resume_path
        for path in resume_paths:
            logger.info("Phase 4: Parsing resume — %s", path)
            resume_dict = parse_resume(path)
            if resume_dict.get("full_name") or resume_dict.get("emails"):
                raw_dicts.append(resume_dict)
                logger.info("  Resume loaded: name=%r", resume_dict.get("full_name"))
            else:
                logger.warning("  Resume produced no usable data — skipping: %s", path)
    else:
        logger.info("Phase 4: No resume provided — skipping")

    if not raw_dicts:
        raise RuntimeError(
            "No input data parsed from any source. "
            "Check that --csv and/or --resume paths are valid."
        )

    # ------------------------------------------------------------------
    # Phase 6: Field Validation
    # ------------------------------------------------------------------
    logger.info("Phase 6: Validating %d raw dict(s)", len(raw_dicts))
    validated_dicts = validate_all(raw_dicts)
    total_rejections = sum(
        len(d.get("_validation_log", [])) for d in validated_dicts
    )
    logger.info("  Validation complete — %d field rejection(s) total", total_rejections)

    # ------------------------------------------------------------------
    # Phase 6.5: Identity Resolution
    # ------------------------------------------------------------------
    logger.info("Phase 6.5: Resolving identity across %d dict(s)", len(validated_dicts))
    clusters = cluster_candidates(validated_dicts)
    logger.info("  %d dict(s) → %d candidate cluster(s)", len(validated_dicts), len(clusters))

    # ------------------------------------------------------------------
    # Phase 7: Merge Engine
    # ------------------------------------------------------------------
    logger.info("Phase 7: Merging %d cluster(s)", len(clusters))
    merged_list = merge_all(clusters)

    # ------------------------------------------------------------------
    # Phase 8: Confidence Engine
    # ------------------------------------------------------------------
    logger.info("Phase 8: Scoring confidence")
    for merged in merged_list:
        score_merged_dict(merged)

    # ------------------------------------------------------------------
    # Phase 10: Build Canonical Profiles
    # ------------------------------------------------------------------
    logger.info("Phase 10: Building canonical profiles")
    profiles = build_all(merged_list)
    logger.info("  %d profile(s) built", len(profiles))

    if not profiles:
        raise RuntimeError(
            "Pipeline produced zero canonical profiles. "
            "Check that input data contains valid identifiers (email/name/phone)."
        )

    # ------------------------------------------------------------------
    # Phase 11: Projection Layer
    # ------------------------------------------------------------------
    logger.info("Phase 11: Projecting output (config=%s)", config_path or "default")
    config = load_config(config_path)
    projected = project_all(profiles, config)
    logger.info("  %d projected record(s)", len(projected))

    # ------------------------------------------------------------------
    # Phase 11.5: Output Validation
    # ------------------------------------------------------------------
    logger.info("Phase 11.5: Validating output against config")
    validated_output = validate_all_outputs(projected, config)
    final_output = filter_valid(validated_output)

    skipped = len(projected) - len(final_output)
    if skipped:
        logger.warning(
            "  %d record(s) excluded by output validator "
            "(required fields missing or type errors)",
            skipped,
        )
    logger.info("  %d record(s) ready to write", len(final_output))

    return final_output


# ---------------------------------------------------------------------------
# Output writer
# ---------------------------------------------------------------------------

def _write_output(data: list[dict[str, Any]], output_path: str | None) -> None:
    """Write JSON to a file or stdout."""
    json_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)

    if output_path is None:
        print(json_str)
        return

    # Create output directory if needed
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(json_str)
        fh.write("\n")

    logger.info("Output written to %s (%d bytes)", output_path, len(json_str))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """
    Main entry point.

    Returns:
        Exit code (0=success, 1=pipeline error, 2=bad args).
    """
    args = _parse_args(argv)
    _setup_logging(args.verbose)

    logger.info(
        "Starting pipeline — csv=%s resume=%s config=%s output=%s",
        args.csv, args.resume, args.config, args.output,
    )

    try:
        output = run_pipeline(
            csv_path    = args.csv,
            resume_path = args.resume,
            config_path = args.config,
        )
    except ValueError as err:
        # Config parse error or similar user-fixable issue
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    except RuntimeError as err:
        # Pipeline produced no output
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    except Exception as err:           # noqa: BLE001
        print(f"UNEXPECTED ERROR: {err}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc(file=sys.stderr)
        return 1

    if not output:
        print(
            "WARNING: Pipeline completed but all records were filtered out "
            "by output validation.",
            file=sys.stderr,
        )
        # Still write the empty array — don't treat this as exit code 1
        _write_output([], args.output)
        return 0

    try:
        _write_output(output, args.output)
    except OSError as err:
        print(f"ERROR writing output: {err}", file=sys.stderr)
        return 1

    logger.info(
        "Pipeline complete — %d candidate(s) processed.", len(output)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
