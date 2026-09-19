"""
prompt_builder.py
------------------
Construit le prompt d'évaluation envoyé au LLM, à partir :
- de la grille de critères (dynamique, cf. grid_loader.py) ;
- du texte du rapport extrait (cf. pdf_extractor.py).

Choix de conception :
- Un seul appel LLM par SECTION de la grille (et non par critère individuel),
  avec sortie structurée en JSON pour tous les critères de la section.
  Compromis retenu pour le MVP : moins d'appels (coût/latence) qu'un appel
  par critère, tout en gardant un contexte raisonnable (une section ~
  6-9 critères). À réévaluer pendant le stage selon la qualité obtenue.
- Les critères mono-évaluateur (encadrant seul, ex. "Déroulement du stage")
  sont signalés explicitement au modèle : celui-ci doit noter la mesure où
  le rapport permet de juger le critère, mais on rappelle dans le README
  que ces critères concernent un suivi que seul l'encadrant a réellement
  observé — le modèle n'a accès qu'au texte du rapport, pas au vécu du
  stage. C'est un des points de vigilance méthodologiques du sujet.
- Le modèle doit toujours citer un extrait court du rapport à l'appui de
  chaque note, pour permettre à l'évaluateur humain de vérifier rapidement
  (traçabilité = condition du "outil d'aide à la décision", pas de
  notation autonome, cf. sujet §2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from grid_loader import Criterion

SYSTEM_PROMPT = """\
Tu es un assistant qui AIDE des évaluateurs humains (encadrant, rapporteur, \
président de jury) à pré-remplir une grille de notation de rapport de \
projet de fin d'études (PFE). Tu ne remplaces jamais leur jugement : \
chaque note que tu proposes sera relue et validée (ou corrigée) par un \
humain avant d'être enregistrée.

Règles impératives :
1. Pour chaque critère, propose une note comprise entre 0 et le barème \
maximum indiqué (les demi-points sont autorisés si le barème le permet).
2. Justifie chaque note en 1-2 phrases maximum, en te basant UNIQUEMENT \
sur le contenu du rapport fourni.
3. Cite un COURT extrait du rapport (une phrase ou moins) qui appuie ta \
note, avec la page si elle est identifiable.
4. SI LE RAPPORT NE PERMET PAS DE JUGER UN CRITÈRE (ex : critère portant \
sur l'oral, la présentation, l'assiduité ou le comportement pendant le \
stage — des éléments qu'un texte écrit ne peut pas révéler), NE DEVINE \
PAS de note. Mets "non_evaluable": true, laisse "note" à 0 et explique \
pourquoi dans la justification. Une note inventée par défaut serait plus \
trompeuse pour l'évaluateur humain qu'une absence de note claire.
5. N'invente jamais de contenu qui ne serait pas dans le rapport.
6. Réponds UNIQUEMENT en JSON valide, sans texte avant/après, selon le \
schéma fourni dans le message utilisateur.
"""


@dataclass
class SectionPrompt:
    section: str
    subsection_groups: List[str]
    user_prompt: str
    criteria_ids: List[str]


def build_section_prompts(
    criteria: List[Criterion],
    report_text: str,
    max_report_chars: int = 60_000,
    exclude_sections: List[str] | None = None,
    exclude_criteria_ids: List[str] | None = None,
) -> List[SectionPrompt]:
    """
    Regroupe les critères par section et construit un prompt utilisateur
    par section. Le texte du rapport est tronqué si nécessaire (les
    rapports très longs devront être découpés plus finement — extension
    possible si les rapports PFE dépassent régulièrement cette taille).

    `exclude_sections` / `exclude_criteria_ids` permettent de ne pas
    solliciter le modèle sur des critères qu'un rapport écrit seul ne
    peut structurellement pas révéler (ex : la section "Évaluation de la
    présentation", qui porte sur l'oral, ou les critères mono-évaluateur
    84-87 qui portent sur le vécu du stage — cf. README, points ouverts).
    Ces critères restent alors à la saisie humaine pure, comme aujourd'hui.
    """
    exclude_sections = set(exclude_sections or [])
    exclude_criteria_ids = set(exclude_criteria_ids or [])

    truncated_report = report_text[:max_report_chars]
    truncation_note = (
        ""
        if len(report_text) <= max_report_chars
        else f"\n[ATTENTION : rapport tronqué à {max_report_chars} caractères sur {len(report_text)}]"
    )

    sections: dict[str, List[Criterion]] = {}
    for c in criteria:
        if c.section in exclude_sections or c.id in exclude_criteria_ids:
            continue
        sections.setdefault(c.section, []).append(c)

    prompts: List[SectionPrompt] = []
    for section_name, section_criteria in sections.items():
        criteria_block = "\n".join(
            _format_criterion(c) for c in section_criteria
        )

        output_schema = _build_output_schema(section_criteria)

        user_prompt = f"""\
RAPPORT (extrait) :
---
{truncated_report}{truncation_note}
---

GRILLE À REMPLIR — section "{section_name}" :
{criteria_block}

Réponds avec un JSON de cette forme exacte (un objet par critère, dans \
l'ordre de la grille ci-dessus) :
{output_schema}
"""
        prompts.append(
            SectionPrompt(
                section=section_name,
                subsection_groups=sorted(set(c.subsection or "" for c in section_criteria)),
                user_prompt=user_prompt,
                criteria_ids=[c.id for c in section_criteria],
            )
        )

    return prompts


def _format_criterion(c: Criterion) -> str:
    mono_flag = (
        " [réservé à l'encadrant — juge dans quelle mesure le rapport en "
        "témoigne, en restant prudent]"
        if c.is_mono_evaluateur
        else ""
    )
    sub = f" ({c.subsection})" if c.subsection else ""
    return f"- id={c.id} | {c.label}{sub} | barème max = {c.bareme_max}{mono_flag}"


def _build_output_schema(section_criteria: List[Criterion]) -> str:
    example_items = ",\n    ".join(
        f'{{"critere": "{c.id}", "note": <0-{c.bareme_max}>, '
        f'"non_evaluable": <true|false>, '
        f'"justification": "...", "extrait": "..."}}'
        for c in section_criteria
    )
    return f"{{\n  \"evaluations\": [\n    {example_items}\n  ]\n}}"


if __name__ == "__main__":
    from grid_loader import parse_html_grid
    from pdf_extractor import extract_report

    criteria = parse_html_grid("/mnt/user-data/uploads/PFE-2197.html")
    report = extract_report("/home/claude/sample_report.pdf")

    prompts = build_section_prompts(criteria, report.full_text)
    for p in prompts:
        print(f"--- Section: {p.section} ({len(p.criteria_ids)} critères) ---")
        print(p.user_prompt[:600])
        print("...\n")
