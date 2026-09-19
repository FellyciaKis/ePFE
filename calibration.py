"""
calibration.py
----------------
Extension du sujet (§4.2) : compare les notes proposées par l'agent à de
vraies notes attribuées par un jury, pour mesurer la fiabilité du système
— en particulier le biais de sur-notation classique des LLM.

Deux sources en entrée :
- `--reference` : un export ePFE réel (format PFE-XXXX.json, avec les
  vraies notes saisies par encadrant/rapporteur/président). Relu avec
  json_export_parser.py (gère la duplication d'entrées déjà identifiée).
- `--agent` : un resultat_XXXX.json produit par notre pipeline
  (main.py / batch_run.py) pour le MÊME projet.

Ne compare que les couples (critère, intervenant) où l'agent a
effectivement proposé une note (note_source == "agent_ia") ET où la
référence a une vraie note saisie — tout le reste (non évaluable, exclu,
non encore noté par un humain) est ignoré plutôt que comparé à du vide.

Usage :
    python calibration.py --reference PFE-2197.json --agent resultat_2197.json
    python calibration.py --reference PFE-2197.json --agent resultat_2197.json --out calibration_2197.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from json_export_parser import load_export


@dataclass
class Gap:
    critere: str
    intervenant: str
    note_agent: float
    note_reference: float
    bareme_max: Optional[float]

    @property
    def ecart(self) -> float:
        return self.note_agent - self.note_reference  # >0 : agent sur-note

    @property
    def ecart_pct(self) -> Optional[float]:
        if not self.bareme_max:
            return None
        return round(100 * self.ecart / self.bareme_max, 1)


def load_agent_export(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compute_gaps(reference_path: str | Path, agent_path: str | Path) -> List[Gap]:
    reference = load_export(reference_path)  # dédoublonne déjà (cf. json_export_parser.py)
    agent_export = load_agent_export(agent_path)

    gaps: List[Gap] = []
    for entry in agent_export["eval"]:
        if entry.get("note_source") != "agent_ia":
            continue  # on ne compare que ce que l'agent a réellement proposé
        note_agent = entry.get("note")
        if note_agent in ("", None):
            continue

        key = (entry["critere"], entry["intervenant"])
        note_ref = reference.scores.get(key)
        if note_ref is None:
            continue  # pas de vraie note à comparer pour ce couple

        gaps.append(Gap(
            critere=entry["critere"],
            intervenant=entry["intervenant"],
            note_agent=float(note_agent),
            note_reference=float(note_ref),
            bareme_max=entry.get("bareme_max"),  # peut être absent selon la version de l'export
        ))

    return gaps


def summarize(gaps: List[Gap]) -> dict:
    if not gaps:
        return {}
    ecarts = [g.ecart for g in gaps]
    ecarts_pct = [g.ecart_pct for g in gaps if g.ecart_pct is not None]
    return {
        "n": len(gaps),
        "biais_moyen": round(statistics.mean(ecarts), 3),  # signé : >0 = sur-notation
        "ecart_absolu_moyen": round(statistics.mean(abs(e) for e in ecarts), 3),
        "ecart_type": round(statistics.pstdev(ecarts), 3) if len(ecarts) > 1 else 0.0,
        "biais_moyen_pct_bareme": round(statistics.mean(ecarts_pct), 1) if ecarts_pct else None,
        "pct_sur_notes": round(100 * sum(1 for e in ecarts if e > 0) / len(ecarts), 1),
        "pct_sous_notes": round(100 * sum(1 for e in ecarts if e < 0) / len(ecarts), 1),
        "pct_exact": round(100 * sum(1 for e in ecarts if e == 0) / len(ecarts), 1),
    }


def print_report(gaps: List[Gap]) -> None:
    stats = summarize(gaps)
    if not stats:
        print("Aucun couple (critère, intervenant) comparable trouvé entre les deux fichiers.")
        print("Vérifiez qu'ils correspondent bien au même projet, et que l'agent a proposé des notes.")
        return

    print(f"=== Calibration sur {stats['n']} note(s) comparable(s) ===\n")
    signe = "sur-note" if stats["biais_moyen"] > 0 else ("sous-note" if stats["biais_moyen"] < 0 else "neutre")
    print(f"Biais moyen        : {stats['biais_moyen']:+.3f} point ({signe} en moyenne)")
    if stats["biais_moyen_pct_bareme"] is not None:
        print(f"                      soit {stats['biais_moyen_pct_bareme']:+.1f}% du barème en moyenne")
    print(f"Écart absolu moyen  : {stats['ecart_absolu_moyen']:.3f} point (à quel point l'agent se trompe, dans un sens ou l'autre)")
    print(f"Écart-type          : {stats['ecart_type']:.3f}")
    print(f"Répartition          : {stats['pct_sur_notes']}% sur-noté · {stats['pct_sous_notes']}% sous-noté · {stats['pct_exact']}% exact\n")

    worst = sorted(gaps, key=lambda g: abs(g.ecart), reverse=True)[:5]
    print("Plus gros désaccords :")
    for g in worst:
        pct = f" ({g.ecart_pct:+.0f}% du barème)" if g.ecart_pct is not None else ""
        print(f"  - critère {g.critere} / {g.intervenant} : agent={g.note_agent} vs jury={g.note_reference} (écart {g.ecart:+.2f}{pct})")


def write_csv(gaps: List[Gap], out_path: str | Path) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["critere", "intervenant", "note_agent", "note_jury", "ecart", "ecart_pct_bareme"])
        for g in gaps:
            writer.writerow([g.critere, g.intervenant, g.note_agent, g.note_reference, g.ecart, g.ecart_pct])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare les notes de l'agent à de vraies notes de jury")
    parser.add_argument("--reference", required=True, help="Export ePFE réel avec les vraies notes (ex: PFE-2197.json)")
    parser.add_argument("--agent", required=True, help="Résultat produit par l'agent pour le MÊME projet (ex: resultat_2197.json)")
    parser.add_argument("--out", help="Chemin CSV optionnel pour le détail ligne par ligne")
    args = parser.parse_args()

    gaps = compute_gaps(args.reference, args.agent)
    print_report(gaps)

    if args.out and gaps:
        write_csv(gaps, args.out)
        print(f"\nDétail complet écrit dans {args.out}")
