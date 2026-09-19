"""
output_writer.py
-----------------
Génère un export compatible avec la structure eval[] de la plateforme
ePFE (cf. PFE-2197.json), étendu avec un champ "justification" et
"extrait" par entrée (extension proposée dans le sujet §3.2, absente du
format existant).

Décisions de conception :
- On écrit UNE seule entrée par (critere, intervenant) — pas de
  duplication artificielle comme celle observée sur l'export réel
  (cf. json_export_parser.py). Si la plateforme exige ce format dupliqué
  en écriture, un adaptateur séparé pourra le regénérer, mais on ne le
  reproduit pas par défaut.
- Le champ "intervenant" est répété pour les 3 rôles (encadrant,
  rapporteur, président) avec la MÊME proposition du modèle : c'est
  volontaire pour le MVP (le modèle ne "joue" pas des rôles différents),
  mais chaque évaluateur reste libre d'ajuster sa propre valeur dans
  l'interface de validation avant enregistrement définitif.
- Les critères mono-évaluateur (encadrant seul) ne génèrent qu'une seule
  entrée "encadrant", conformément à la grille.
- La note finale ("note") n'est PAS recalculée ici : sa formule exacte
  n'est pas encore confirmée (cf. README, section "Points ouverts") et le
  sujet demande explicitement de l'extraire du code existant plutôt que
  de la deviner. On la laisse à None / absente tant qu'elle n'est pas
  validée par un humain.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List

from eval_engine import CriterionEvaluation
from grid_loader import Criterion

ROLES_TRI_EVALUATEUR = ["encadrant", "rapporteur", "president"]


def build_eval_export(
    idprojet: int,
    session: int,
    criteria: List[Criterion],
    evaluations: List[CriterionEvaluation],
    alerts: list | None = None,
    page_count: int | None = None,
) -> dict:
    """
    `alerts` : liste d'objets Alert (cf. alert_detector.py), purement
    informative. Ce champ n'influence JAMAIS "note", "eval" ou un futur
    champ "etat" — il ne fait que transporter le signal jusqu'à
    l'interface, où il reste un bandeau consultatif (jamais une case
    pré-cochée). Absent ou vide si la détection n'a pas été lancée.

    `page_count` : nombre de pages du rapport PDF source, conservé dans
    les métadonnées pour permettre de reconstruire une ligne de résumé
    (batch_run.py) sans avoir à ré-extraire le PDF — utile pour le cache.
    """
    criteria_by_id = {c.id: c for c in criteria}
    eval_by_critere = {e.critere: e for e in evaluations}

    eval_entries = []
    for crit in criteria:
        proposal = eval_by_critere.get(crit.id)
        roles = crit.evaluators  # ["encadrant"] ou les 3 rôles, selon la grille

        for role in roles:
            if proposal is None:
                note_source = "non_evalue"  # exclu du périmètre agent (cf. exclude_sections)
            elif proposal.non_evaluable:
                note_source = "non_evaluable_par_ia"
            else:
                note_source = "agent_ia"

            entry = {
                "critere": crit.id,
                "intervenant": role,
                "note": proposal.note_proposee if (proposal and not proposal.non_evaluable) else "",
                "bareme_max": crit.bareme_max,
                "note_source": note_source,
                "justification": proposal.justification if proposal else "",
                "extrait": proposal.extrait if proposal else "",
                "valide_par_humain": False,
            }
            eval_entries.append(entry)

    alerts = alerts or []

    return {
        "idprojet": idprojet,
        "session": session,
        "note": None,  # à calculer/valider par la plateforme, pas par l'agent (cf. README)
        "eval": eval_entries,
        "signaux_ia": [
            {"type": a.type, "confiance": a.confidence, "description": a.description, "extrait": a.extrait}
            for a in alerts
        ],
        "meta": {
            "generateur": "pfe_agent (MVP)",
            "nb_criteres": len(criteria),
            "nb_criteres_evalues": len(evaluations),
            "nb_criteres_non_evalues": len(criteria) - len(evaluations),
            "pages": page_count,
        },
    }


def write_eval_export(export: dict, out_path: str | Path) -> None:
    Path(out_path).write_text(
        json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    from grid_loader import parse_html_grid

    criteria = parse_html_grid("/mnt/user-data/uploads/PFE-2197.html")

    # Petites évaluations factices pour valider le format de sortie
    fake_evals = [
        CriterionEvaluation(
            critere=c.id,
            note_proposee=round(c.bareme_max * 0.8, 2),
            bareme_max=c.bareme_max,
            justification="Justification de démonstration.",
            extrait="Extrait de démonstration.",
        )
        for c in criteria
    ]

    export = build_eval_export(2197, 1, criteria, fake_evals)
    write_eval_export(export, "/home/claude/sample_output.json")
    print(f"{len(export['eval'])} entrées écrites (attendu : 23*3 + 4 = 73)")
    print(json.dumps(export["eval"][0], ensure_ascii=False, indent=2))
