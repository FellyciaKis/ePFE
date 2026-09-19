"""
main.py
-------
Orchestre le pipeline MVP complet :

  grille (HTML/JSON)  ┐
                       ├─► prompt_builder ─► eval_engine (LLM) ─► output_writer ─► JSON réinjectable
  rapport (PDF)        ┘

Usage :
    python main.py --grid PFE-2197.html --report rapport.pdf \
                    --idprojet 2197 --session 1 --out resultat.json

Sans ANTHROPIC_API_KEY définie, le script s'arrête après avoir construit
les prompts et affiche un message explicite (utile pour valider la partie
grille/rapport sans consommer d'appels API).
"""

from __future__ import annotations

import argparse
import os
import sys

from eval_engine import evaluate_report
from grid_loader import parse_html_grid
from output_writer import build_eval_export, write_eval_export
from pdf_extractor import extract_report
from alert_detector import detect_alerts


DEFAULT_EXCLUDED_SECTIONS = ["Évaluation de la présentation"]
DEFAULT_EXCLUDED_CRITERIA_IDS = ["84", "85", "86", "87"]  # mono-évaluateur, réservés à l'encadrant


def run(
    grid_html_path: str, report_pdf_path: str, idprojet: int, session: int, out_path: str,
    provider: str = "gemini", include_all: bool = False, detect_alerts_flag: bool = True,
) -> None:
    print(f"[1/5] Lecture de la grille : {grid_html_path}")
    criteria = parse_html_grid(grid_html_path)
    print(f"      -> {len(criteria)} critères chargés")

    print(f"[2/5] Extraction du rapport : {report_pdf_path}")
    report = extract_report(report_pdf_path)
    print(f"      -> {report.page_count} pages, {len(report.sections)} sections détectées")
    for w in report.warnings:
        print(f"      [!] {w}")

    key_var = "GOOGLE_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
    if not os.environ.get(key_var):
        hint = (
            "clé gratuite sur https://aistudio.google.com/apikey"
            if provider == "gemini"
            else "clé sur https://console.anthropic.com"
        )
        print(
            f"\n[3/5] {key_var} non définie : arrêt avant l'appel LLM.\n"
            f"      Grille et rapport sont valides ; configurez la clé API "
            f"({hint}) pour poursuivre."
        )
        sys.exit(0)

    print(f"[3/5] Évaluation par le modèle ({provider}, un appel par section)...")
    exclude_sections = [] if include_all else DEFAULT_EXCLUDED_SECTIONS
    exclude_criteria_ids = [] if include_all else DEFAULT_EXCLUDED_CRITERIA_IDS
    if exclude_sections or exclude_criteria_ids:
        print(
            f"      (sections exclues : {exclude_sections or 'aucune'} ; "
            f"critères exclus : {exclude_criteria_ids or 'aucun'} — "
            f"le rapport écrit seul ne permet pas de les juger ; "
            f"utilisez --include-all pour forcer le modèle à proposer une note quand même)"
        )
    evaluations = evaluate_report(
        criteria, report.full_text, provider=provider,
        exclude_sections=exclude_sections, exclude_criteria_ids=exclude_criteria_ids,
    )
    print(f"      -> {len(evaluations)} critères évalués sur {len(criteria)}")

    alerts = []
    if detect_alerts_flag:
        print("[4/5] Détection de signaux (plagiat / implémentation insuffisante)...")
        try:
            alerts = detect_alerts(report.full_text, provider=provider)
        except Exception as exc:
            print(f"      [!] Détection de signaux échouée (notation conservée) : {exc}")
            alerts = []
        if alerts:
            print(f"      -> {len(alerts)} signal(aux) à vérifier par le jury :")
            for a in alerts:
                print(f"         [{a.type} / confiance {a.confidence}] {a.description}")
        else:
            print("      -> aucun signal notable.")
    else:
        print("[4/5] Détection de signaux désactivée (--no-alerts).")

    print(f"[5/5] Écriture de la sortie : {out_path}")
    export = build_eval_export(idprojet, session, criteria, evaluations, alerts=alerts, page_count=report.page_count)
    write_eval_export(export, out_path)
    print("      -> terminé. Résultat à valider par les évaluateurs humains avant enregistrement.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent IA d'aide à l'évaluation des rapports de PFE")
    parser.add_argument("--grid", required=True, help="Chemin vers le HTML de la grille (ex: PFE-2197.html)")
    parser.add_argument("--report", required=True, help="Chemin vers le rapport PFE au format PDF")
    parser.add_argument("--idprojet", required=True, type=int)
    parser.add_argument("--session", required=True, type=int)
    parser.add_argument("--out", default="resultat_eval.json")
    parser.add_argument(
        "--provider", default="gemini", choices=["gemini", "anthropic"],
        help="Fournisseur LLM : 'gemini' (gratuit, défaut) ou 'anthropic' (payant)",
    )
    parser.add_argument(
        "--include-all", action="store_true",
        help="Ne pas exclure la section Présentation ni les critères mono-évaluateur "
             "(84-87) — par défaut ils sont laissés à la saisie humaine, car un rapport "
             "écrit seul ne permet pas de les juger.",
    )
    parser.add_argument(
        "--no-alerts", action="store_true",
        help="Désactive la détection de signaux plagiat/implémentation insuffisante "
             "(actif par défaut, un appel LLM en plus).",
    )
    args = parser.parse_args()

    run(
        args.grid, args.report, args.idprojet, args.session, args.out,
        provider=args.provider, include_all=args.include_all,
        detect_alerts_flag=not args.no_alerts,
    )
