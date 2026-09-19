"""
build_validation_ui.py
------------------------
Génère un interface_validation.html autonome (sans backend) à partir :
- d'un export produit par output_writer.py (ex: resultat.json) ;
- de la grille de critères (criteria_grid.json) pour retrouver libellé,
  section, sous-section, barème de chaque critère (absents de l'export).

Usage :
    python build_validation_ui.py --eval resultat.json --grid criteria_grid.json --out interface_validation.html

Réutilisable pour n'importe quel projet évalué par le pipeline, pas
seulement le cas de démo. Le gabarit HTML/CSS/JS (TEMPLATE_HTML) est le
même que celui livré précédemment ; seule la donnée injectée change.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "interface_validation_template.html"


def build_ui_data(eval_export: dict, grid: list[dict]) -> list[dict]:
    """
    Fusionne les entrées eval[] (note, justification, extrait, note_source)
    avec les métadonnées de la grille (label, section, subsection,
    bareme_max), et dérive les flags utilisés par l'interface :
    - low_confidence : True si note_source != "agent_ia" (non évaluable
      par l'IA, ou non soumis au modèle) — l'évaluateur doit trancher lui-même.

    `note_ia` conserve la proposition ORIGINALE de l'agent, jamais
    modifiée par l'interface (contrairement à `note`, que l'évaluateur
    peut corriger). C'est ce qui permet à dashboard.py de mesurer l'écart
    entre ce que l'agent a proposé et ce que l'évaluateur a finalement
    validé, une fois l'export téléchargé depuis l'interface.
    """
    grid_by_id = {c["id"]: c for c in grid}
    ui_rows = []
    for entry in eval_export["eval"]:
        crit = grid_by_id.get(entry["critere"])
        if crit is None:
            continue  # critère absent de la grille fournie : on ignore proprement
        note = entry["note"]
        note_value = note if note != "" else 0
        ui_rows.append(
            {
                "critere": entry["critere"],
                "intervenant": entry["intervenant"],
                "note": note_value,
                "note_ia": note_value,  # figée : jamais réécrite par l'interface
                "bareme_max": float(crit["bareme_max"]),  # sécurité : force le type numérique
                "label": crit["label"],
                "section": crit["section"],
                "subsection": crit.get("subsection"),
                "note_source": entry["note_source"],
                "justification": entry["justification"] or "(aucune proposition du modèle pour ce critère)",
                "extrait": entry["extrait"] or "—",
                "low_confidence": entry["note_source"] != "agent_ia",
                "valide_par_humain": entry["valide_par_humain"],
            }
        )
    return ui_rows


def main():
    parser = argparse.ArgumentParser(description="Génère interface_validation.html à partir d'un vrai résultat")
    parser.add_argument("--eval", required=True, help="Export produit par output_writer.py (ex: resultat.json)")
    parser.add_argument("--grid", default="criteria_grid.json", help="Grille de critères (défaut: criteria_grid.json)")
    parser.add_argument("--out", default="interface_validation.html")
    args = parser.parse_args()

    eval_export = json.loads(Path(args.eval).read_text(encoding="utf-8"))
    grid = json.loads(Path(args.grid).read_text(encoding="utf-8"))

    ui_data = build_ui_data(eval_export, grid)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    projects = [{
        "label": f"Projet {eval_export['idprojet']} · Session {eval_export['session']}",
        "data": ui_data,
        "signaux_ia": eval_export.get("signaux_ia", []),
    }]
    html = template.replace("/*__PROJECTS__*/", json.dumps(projects, ensure_ascii=False))

    Path(args.out).write_text(html, encoding="utf-8")
    print(f"{len(ui_data)} lignes écrites dans {args.out}")


if __name__ == "__main__":
    main()
