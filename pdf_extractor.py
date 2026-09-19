"""
pdf_extractor.py
-----------------
Extraction de texte et de structure à partir d'un rapport de PFE (PDF),
pour alimenter le moteur d'évaluation.

Approche :
- pdfplumber pour une extraction texte page par page avec préservation
  raisonnable de la mise en page (utile pour les rapports multi-colonnes
  ou avec tableaux).
- Découpage heuristique en "sections" à partir des titres probables
  (lignes courtes, en majuscules ou numérotées, en début de ligne) pour
  permettre au moteur d'évaluation de citer des extraits localisés
  (numéro de page + section) dans ses justifications.
- Repli automatique sur un avertissement explicite si le PDF est un scan
  sans couche texte (aucun texte n'est extrait) : dans ce cas il faut une
  étape d'OCR en amont, hors périmètre du MVP mais à prévoir en extension.

Ce module ne fait aucune hypothèse sur le contenu du rapport (pas de
mots-clés codés en dur) : il produit une représentation texte structurée
que le prompt_builder / eval_engine exploiteront.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pdfplumber

# Un titre probable : ligne courte, commence par un numéro de section
# (1, 1.2, I., etc.) ou est entièrement en majuscules, sans ponctuation
# finale de phrase.
_HEADING_RE = re.compile(
    r"^\s*(\d+(\.\d+)*[\.\)]?\s+.{3,80}|[IVXLC]+[\.\)]\s+.{3,80}|[A-ZÀ-Ü][A-ZÀ-Ü\s\-']{6,80})\s*$"
)


@dataclass
class ReportSection:
    title: str
    page_start: int
    text: str = ""


@dataclass
class ExtractedReport:
    source_path: str
    page_count: int
    full_text: str
    sections: List[ReportSection] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def extract_report(pdf_path: str | Path) -> ExtractedReport:
    pdf_path = Path(pdf_path)
    pages_text: List[str] = []
    warnings: List[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)

    full_text = "\n".join(pages_text)
    if not full_text.strip():
        warnings.append(
            "Aucun texte extrait : le PDF est probablement un scan sans "
            "couche texte. Une étape d'OCR est nécessaire avant l'évaluation "
            "(hors périmètre du MVP — cf. extensions possibles du sujet)."
        )

    sections = _split_into_sections(pages_text)

    return ExtractedReport(
        source_path=str(pdf_path),
        page_count=page_count,
        full_text=full_text,
        sections=sections,
        warnings=warnings,
    )


def _split_into_sections(pages_text: List[str]) -> List[ReportSection]:
    sections: List[ReportSection] = []
    current: ReportSection | None = None

    for page_num, page_text in enumerate(pages_text, start=1):
        for line in page_text.splitlines():
            if _HEADING_RE.match(line.strip()):
                if current is not None:
                    sections.append(current)
                current = ReportSection(title=line.strip(), page_start=page_num)
                continue
            if current is not None:
                current.text += line + "\n"

    if current is not None:
        sections.append(current)

    # Si aucune section détectée (rapport sans titres reconnaissables),
    # on retombe sur un unique bloc "Document entier".
    if not sections:
        sections = [
            ReportSection(
                title="Document entier",
                page_start=1,
                text="\n".join(pages_text),
            )
        ]

    return sections


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pdf_extractor.py <chemin_vers_rapport.pdf>")
        sys.exit(1)

    report = extract_report(sys.argv[1])
    print(f"{report.page_count} pages, {len(report.sections)} sections détectées")
    for s in report.sections[:10]:
        print(f"  p.{s.page_start:>3}  {s.title[:70]}")
    for w in report.warnings:
        print(f"[!] {w}")
