"""
Phase 6.5 — Identity Resolution
================================
Groups validated candidate dicts from multiple sources into clusters,
where each cluster represents one unique real-world person.

Design rules:
- Input:  flat list of validated dicts (from Phase 6) across all sources
- Output: list[list[dict]] — each inner list is a cluster to be merged

Match policy (in priority order):
  Step 1 — Exact email match (primary key)
            Any email from set A matches any email from set B → same person.
            Rationale: emails are unique identifiers. Fuzzy email match is
            too risky — one wrong merge silently corrupts the profile.

  Step 2 — Fuzzy name + phone (fallback)
            rapidfuzz.fuzz.token_sort_ratio(name_A, name_B) >= 85
            AND at least one phone number in common (E.164).
            Both conditions must hold simultaneously.
            Rationale:
              - 85 covers typos and common abbreviations (Jon/John, Rob/Robert)
                while avoiding merges on common names like "John Lee" / "John Li".
              - Phone required alongside name: name alone is insufficient for
                unique identity and would produce too many false positives.

  Step 3 — No match → treat as a separate candidate. Never force-merge.

Algorithm: Union-Find (disjoint set union) over the list indices.
  O(n²) pairwise comparisons — acceptable for thousands of candidates.

Edge cases handled:
  - No email in either dict → fall through to name+phone fallback.
  - Phone missing in one or both → name+phone fallback cannot fire → no merge.
  - Identical email in same source (duplicate CSV rows) → still merged.
"""

import logging
from typing import Any

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Minimum token_sort_ratio score to consider names a match.
# Documented here because it is a judgment call a reviewer should see.
NAME_SIMILARITY_THRESHOLD = 85


# ---------------------------------------------------------------------------
# Union-Find (Disjoint Set Union)
# ---------------------------------------------------------------------------

class _UnionFind:
    """Minimal union-find for clustering by index."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank   = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]   # path compression
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        # Union by rank
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def clusters(self, n: int) -> dict[int, list[int]]:
        """Return mapping root_index → [member_indices]."""
        groups: dict[int, list[int]] = {}
        for i in range(n):
            root = self.find(i)
            groups.setdefault(root, []).append(i)
        return groups


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _get_emails(d: dict[str, Any]) -> set[str]:
    """Return all normalized emails from a validated dict as a set."""
    emails: set[str] = set()

    # List form (resume parser / validator output)
    for e in d.get("emails", []):
        if e:
            emails.add(e.strip().lower())

    # Scalar form (CSV validator output)
    scalar = d.get("email")
    if scalar:
        emails.add(scalar.strip().lower())

    return emails


def _get_phones(d: dict[str, Any]) -> set[str]:
    """Return all normalized (E.164) phones from a validated dict as a set."""
    phones: set[str] = set()

    for p in d.get("phones", []):
        if p:
            phones.add(p.strip())

    scalar = d.get("phone")
    if scalar:
        phones.add(scalar.strip())

    return phones


def _get_name(d: dict[str, Any]) -> str:
    """Return a cleaned lowercase full name for fuzzy comparison."""
    name = d.get("full_name") or ""
    return name.strip().lower()


def _emails_match(a: dict, b: dict) -> bool:
    """True if any email in a intersects any email in b."""
    return bool(_get_emails(a) & _get_emails(b))


def _name_phone_match(a: dict, b: dict) -> bool:
    """
    True if:
      - fuzzy name similarity >= NAME_SIMILARITY_THRESHOLD
      AND
      - at least one phone number in common

    Both conditions must hold — phone alone or name alone is not enough.
    """
    name_a = _get_name(a)
    name_b = _get_name(b)

    if not name_a or not name_b:
        return False                    # can't compare without names

    phones_a = _get_phones(a)
    phones_b = _get_phones(b)

    if not phones_a or not phones_b:
        return False                    # phone required for this fallback

    score = fuzz.token_sort_ratio(name_a, name_b)
    phones_overlap = bool(phones_a & phones_b)

    return score >= NAME_SIMILARITY_THRESHOLD and phones_overlap


def _should_merge(a: dict, b: dict) -> tuple[bool, str]:
    """
    Decide whether two validated dicts represent the same person.

    Returns:
        (True, reason_string) if they should merge.
        (False, "")           if they should not.
    """
    if _emails_match(a, b):
        shared = _get_emails(a) & _get_emails(b)
        return True, "email_exact:" + ",".join(sorted(shared))

    if _name_phone_match(a, b):
        score = int(fuzz.token_sort_ratio(_get_name(a), _get_name(b)))
        return True, f"name_phone_fuzzy:score={score}"

    return False, ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def cluster_candidates(
    validated_dicts: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """
    Group validated candidate dicts into same-person clusters.

    Args:
        validated_dicts: Flat list of validated dicts from ALL sources.
                         Each dict must have "_source" and optionally
                         "email", "emails", "phone", "phones", "full_name".

    Returns:
        list[list[dict]] — each inner list is a cluster of dicts
        representing the same person. Clusters with one dict = unique
        candidate with no match found. Order within a cluster preserves
        the original input order.

    Never raises — bad/partial dicts are treated as isolated candidates.
    """
    n = len(validated_dicts)
    if n == 0:
        return []
    if n == 1:
        return [validated_dicts]

    uf = _UnionFind(n)

    for i in range(n):
        for j in range(i + 1, n):
            try:
                merge, reason = _should_merge(validated_dicts[i], validated_dicts[j])
                if merge:
                    uf.union(i, j)
                    logger.info(
                        "Merged: [%d]%r + [%d]%r via %s",
                        i, validated_dicts[i].get("full_name"),
                        j, validated_dicts[j].get("full_name"),
                        reason,
                    )
            except Exception as err:       # noqa: BLE001
                # One bad comparison must never abort the whole clustering
                logger.warning(
                    "Error comparing dicts[%d] and dicts[%d]: %s — skipping pair",
                    i, j, err,
                )

    # Collect clusters preserving original order within each group
    groups = uf.clusters(n)
    clusters = [
        [validated_dicts[i] for i in sorted(indices)]
        for indices in groups.values()
    ]

    logger.info(
        "Identity resolution: %d dict(s) → %d cluster(s)",
        n, len(clusters),
    )

    return clusters
