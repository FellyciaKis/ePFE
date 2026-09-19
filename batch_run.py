"""
batch_run.py
-------------
Lance le pipeline complet sur TOUS les PDF d'un dossier, avec la même
grille, pour comparer le comportement de l'agent d'un rapport à l'autre.

Usage :
    python batch_run.py --grid PFE-2197.html --reports-dir mes_rapports/ --out-dir resultats_batch/

CACHE : un fichier resultats_batch/.batch_cache.json retient l'empreinte
(SHA-256) de chaque PDF déjà traité. Au prochain lancement, seuls les
fichiers NOUVEAUX ou MODIFIÉS depuis la dernière fois sont réellement
renvoyés au modèle — les rapports inchangés réutilisent directement leur
resultat_<nom>.json existant (aucun appel API, gratuit et instantané).
Si le contenu de --grid change, le cache entier est invalidé (les
critères ne correspondraient plus). Utilisez --force pour ignorer le
cache et tout retraiter.

Pour chaque <nom>.pdf trouvé dans --reports-dir, génère :
    - resultats_batch/resultat_<nom>.json  (export eval[] complet, un par rapport)
    - resultats_batch/summary.csv          (une ligne par rapport, pour comparer vite)
    - resultats_batch/interface.html       (UNE SEULE interface pour TOUS les
      rapports, avec un menu déroulant en haut pour passer de l'un à l'autre)

Chaque NOUVEAU rapport est numéroté idprojet = --idprojet-start + index
(à défaut d'un vrai id ePFE par fichier) — passez --idprojet-start si vous
voulez faire correspondre des id réels. Les rapports déjà en cache
conservent leur idprojet d'origine (lu dans leur resultat_<nom>.json).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from grid_loader import parse_html_grid, save_grid_to_json
from pdf_extractor import extract_report
from eval_engine import evaluate_report
from output_writer import build_eval_export, write_eval_export
from build_validation_ui import build_ui_data
from alert_detector import detect_alerts

DEFAULT_EXCLUDED_SECTIONS = ["Évaluation de la présentation"]
DEFAULT_EXCLUDED_CRITERIA_IDS = ["84", "85", "86", "87"]

TEMPLATE_PATH = Path(__file__).parent / "interface_validation_template.html"
CACHE_FILENAME = ".batch_cache.json"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cache(out_dir: Path, grid_hash: str) -> dict:
    cache_path = out_dir / CACHE_FILENAME
    if not cache_path.exists():
        return {"grid_hash": grid_hash, "reports": {}}
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"grid_hash": grid_hash, "reports": {}}
    if cache.get("grid_hash") != grid_hash:
        print("[cache] La grille a changé depuis le dernier run : cache invalidé, tout est retraité.")
        return {"grid_hash": grid_hash, "reports": {}}
    return cache


def save_cache(out_dir: Path, cache: dict) -> None:
    (out_dir / CACHE_FILENAME).write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_export(export: dict, pdf_name: str) -> dict:
    """Reconstruit une ligne de résumé à partir d'un export déjà sur disque (pas d'appel LLM)."""
    seen: dict[str, tuple[str, object]] = {}
    for e in export["eval"]:
        if e["critere"] not in seen:
            seen[e["critere"]] = (e["note_source"], e["note"])

    n_eval = sum(1 for src, _ in seen.values() if src == "agent_ia")
    n_non_eval = sum(1 for src, _ in seen.values() if src == "non_evaluable_par_ia")
    n_excluded = sum(1 for src, _ in seen.values() if src == "non_evalue")
    notes = [float(note) for src, note in seen.values() if src == "agent_ia" and note != ""]
    moyenne = round(sum(notes) / len(notes), 2) if notes else None

    return {
        "rapport": pdf_name,
        "idprojet": export["idprojet"],
        "pages": export.get("meta", {}).get("pages"),
        "criteres_notes": n_eval,
        "non_evaluables": n_non_eval,
        "exclus_par_defaut": n_excluded,
        "moyenne_pct_bareme": moyenne,
        "signaux_ia": len(export.get("signaux_ia", [])),
        "resultat_json": f"resultat_{Path(pdf_name).stem}.json",
    }


def run_one(pdf_path: Path, idprojet: int, session: int,
            provider: str, include_all: bool, detect_alerts_flag: bool, criteria):
    print(f"\n=== {pdf_path.name} ===")
    report = extract_report(pdf_path)
    print(f"  {report.page_count} pages, {len(report.sections)} sections détectées")
    for w in report.warnings:
        print(f"  [!] {w}")

    exclude_sections = [] if include_all else DEFAULT_EXCLUDED_SECTIONS
    exclude_criteria_ids = [] if include_all else DEFAULT_EXCLUDED_CRITERIA_IDS

    evaluations = evaluate_report(
        criteria, report.full_text, provider=provider,
        exclude_sections=exclude_sections, exclude_criteria_ids=exclude_criteria_ids,
    )

    alerts = []
    if detect_alerts_flag:
        try:
            alerts = detect_alerts(report.full_text, provider=provider)
        except Exception as exc:
            print(f"  [!] Détection de signaux échouée pour ce rapport (notation conservée) : {exc}")
            alerts = []

    export = build_eval_export(idprojet, session, criteria, evaluations, alerts=alerts, page_count=report.page_count)

    n_eval = sum(1 for e in evaluations if not e.non_evaluable)
    n_non_eval = sum(1 for e in evaluations if e.non_evaluable)
    n_excluded = len(criteria) - len(evaluations)
    print(f"  -> {n_eval} notés, {n_non_eval} non évaluables, {n_excluded} exclus, {len(alerts)} signal(aux)")

    return export


def main():
    parser = argparse.ArgumentParser(description="Lance le pipeline sur plusieurs rapports PDF (avec cache)")
    parser.add_argument("--grid", required=True, help="Grille HTML (ex: PFE-2197.html)")
    parser.add_argument("--reports-dir", required=True, help="Dossier contenant les PDF à tester")
    parser.add_argument("--out-dir", default="resultats_batch")
    parser.add_argument("--session", type=int, default=1)
    parser.add_argument("--idprojet-start", type=int, default=1)
    parser.add_argument("--provider", default="gemini", choices=["gemini", "anthropic"])
    parser.add_argument("--include-all", action="store_true")
    parser.add_argument("--no-alerts", action="store_true", help="Désactive la détection de signaux plagiat/implémentation insuffisante")
    parser.add_argument("--force", action="store_true", help="Ignore le cache et retraite tous les rapports")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    criteria = parse_html_grid(args.grid)
    grid_json_path = out_dir / "criteria_grid.json"
    save_grid_to_json(criteria, grid_json_path)
    grid = json.loads(grid_json_path.read_text(encoding="utf-8"))

    reports_dir = Path(args.reports_dir)
    pdfs = sorted(reports_dir.glob("*.pdf"))
    if not pdfs:
        print(f"Aucun fichier .pdf trouvé dans {reports_dir}")
        return

    grid_hash = file_hash(Path(args.grid))
    cache = {"grid_hash": grid_hash, "reports": {}} if args.force else load_cache(out_dir, grid_hash)

    print(f"{len(pdfs)} rapport(s) dans le dossier : {[p.name for p in pdfs]}")

    rows, projects, failures = [], [], []
    existing_ids = [v["idprojet"] for v in cache["reports"].values() if isinstance(v.get("idprojet"), int)]
    next_idprojet = max(existing_ids, default=args.idprojet_start - 1) + 1
    n_cached, n_processed = 0, 0

    for pdf in pdfs:
        try:
            h = file_hash(pdf)
            cached_entry = cache["reports"].get(pdf.name)
            resultat_path = out_dir / f"resultat_{pdf.stem}.json"

            if cached_entry and cached_entry["hash"] == h and resultat_path.exists() and not args.force:
                export = json.loads(resultat_path.read_text(encoding="utf-8"))
                print(f"\n=== {pdf.name} === [cache] inchangé depuis le dernier run, réutilisation directe")
                n_cached += 1
            else:
                if cached_entry and isinstance(cached_entry.get("idprojet"), int):
                    idprojet = cached_entry["idprojet"]  # rapport modifié : on garde son id d'origine
                else:
                    idprojet = next_idprojet
                    next_idprojet += 1
                export = run_one(pdf, idprojet, args.session, args.provider, args.include_all, not args.no_alerts, criteria)
                write_eval_export(export, resultat_path)
                cache["reports"][pdf.name] = {"hash": h, "idprojet": export["idprojet"]}
                n_processed += 1

            rows.append(summarize_export(export, pdf.name))
            projects.append({
                "label": f"{pdf.stem} (projet {export['idprojet']})",
                "data": build_ui_data(export, grid),
                "signaux_ia": export.get("signaux_ia", []),
            })
        except Exception as exc:
            print(f"\n=== {pdf.name} === [ÉCHEC] ce rapport est ignoré, le batch continue : {exc}")
            failures.append(pdf.name)

    # Nettoie le cache des rapports qui ne sont plus dans le dossier
    present_names = {p.name for p in pdfs}
    cache["reports"] = {k: v for k, v in cache["reports"].items() if k in present_names}
    save_cache(out_dir, cache)

    if not rows:
        print(f"\nAucun rapport n'a pu être traité ({len(failures)} échec(s)). Rien à écrire.")
        return

    summary_path = out_dir / "summary.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("/*__PROJECTS__*/", json.dumps(projects, ensure_ascii=False))
    interface_path = out_dir / "interface.html"
    interface_path.write_text(html, encoding="utf-8")

    print(f"\n{len(rows)} rapport(s) au total : {n_processed} traité(s) par le modèle, {n_cached} réutilisé(s) depuis le cache.")
    if failures:
        print(f"[!] {len(failures)} rapport(s) en échec (ignorés, à relancer) : {failures}")
    print(f"Résumé : {summary_path}")
    print(f"Interface unique (tous les rapports, menu déroulant en haut) : {interface_path}")


if __name__ == "__main__":
    main()
