"""
json_export_parser.py
----------------------
Lecture robuste d'un export ePFE (format PFE-XXXX.json).

Point de vigilance identifié pendant l'analyse (cf. sujet §3.3) : le tableau
eval[] peut contenir deux fois chaque couple (critere, intervenant) — une
fois avec la vraie note, une fois avec note="" — vraisemblablement un
artefact du template de formulaire par défaut concaténé aux valeurs
saisies. Sur l'export réel PFE-2197.json : 146 entrées pour 73 couples
distincts, chaque couple apparaissant exactement 2 fois, la seconde moitié
du tableau étant une copie exacte de la première avec note="".

Stratégie de dédoublonnage retenue ici : pour chaque couple
(critere, intervenant), garder la première occurrence NON VIDE rencontrée
(et ignorer les doublons vides). Si toutes les occurrences sont vides, le
couple est considéré comme "non noté".

⚠️ Ce comportement doit être confirmé avec l'équipe technique ePFE avant
d'être considéré comme fiable sur l'ensemble des projets (cf. sujet).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class GradingExport:
    idprojet: int
    session: int
    grid: int
    mention: str
    etat: str  # "-1" = aucun problème éliminatoire, "1" = plagiat, "2" = implémentation insuffisante
    malus: float
    commentaire: str
    note: Optional[float]
    # (critere, intervenant) -> note (float) ; None si non renseigné
    scores: Dict[Tuple[str, str], Optional[float]]


def load_export(json_path: str | Path) -> GradingExport:
    raw = json.loads(Path(json_path).read_text(encoding="utf-8-sig"))

    scores: Dict[Tuple[str, str], Optional[float]] = {}
    dropped_duplicates = 0
    for entry in raw.get("eval", []):
        key = (entry["critere"], entry["intervenant"])
        note_str = entry.get("note", "")
        note_val = float(note_str) if note_str not in ("", None) else None

        if key not in scores:
            scores[key] = note_val
        elif scores[key] is None and note_val is not None:
            # On avait déjà vu ce couple vide (ou pas), on garde la valeur non vide
            scores[key] = note_val
            dropped_duplicates += 1
        else:
            dropped_duplicates += 1

    if dropped_duplicates:
        print(
            f"[json_export_parser] {dropped_duplicates} entrées dupliquées "
            f"ignorées/fusionnées sur {len(raw.get('eval', []))} au total."
        )

    return GradingExport(
        idprojet=raw["idprojet"],
        session=raw["session"],
        grid=raw["grid"],
        mention=raw.get("mention", ""),
        etat=raw.get("etat", "-1"),
        malus=float(raw.get("malus", 0) or 0),
        commentaire=raw.get("commentaire", ""),
        note=float(raw["note"]) if raw.get("note") not in ("", None) else None,
        scores=scores,
    )


if __name__ == "__main__":
    export = load_export("/mnt/user-data/uploads/PFE-2197.json")
    print(f"Projet {export.idprojet}, session {export.session}, note finale = {export.note}")
    print(f"{len(export.scores)} couples (critere, intervenant) distincts")
    non_notes = [k for k, v in export.scores.items() if v is None]
    print(f"Couples sans note : {non_notes if non_notes else 'aucun'}")
