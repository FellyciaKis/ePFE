"""
grid_loader.py
--------------
Lecture dynamique de la grille de critères d'un projet ePFE.

Deux sources possibles, comme prévu dans le sujet de stage :
1. Un export "structure" (fichier JSON du type criteria_grid.json généré par
   parse_html_grid()) — utile en attendant un accès direct à la BD ePFE.
2. Directement le HTML de la grille (PFE-2197.html), qu'on peut re-parser à
   la volée si aucun export structure n'est disponible pour un projet donné.

Aucune information de critère (libellé, barème, évaluateurs) n'est codée en
dur ici : tout est extrait du fichier source. Si la plateforme change un
critère ou une section, ce module suit sans modification de code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

try:
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "beautifulsoup4 est requis pour parser la grille HTML : "
        "pip install beautifulsoup4"
    ) from exc


@dataclass
class Criterion:
    id: str
    section: str
    subsection: Optional[str]
    label: str
    bareme_max: float
    evaluators: List[str] = field(default_factory=list)

    @property
    def is_mono_evaluateur(self) -> bool:
        """Critères réservés au seul encadrant (ex. suivi du stage)."""
        return self.evaluators == ["encadrant"]


def parse_html_grid(html_path: str | Path) -> List[Criterion]:
    """
    Parse le HTML natif de la grille ePFE (ex. PFE-2197.html) et retourne
    la liste structurée des critères, avec leur section/sous-section,
    libellé, barème et les intervenants habilités à noter.

    C'est volontairement générique : on découvre les sections via les
    onglets `<a data-toggle="tab">`, puis on parcourt chaque table de
    critères en repérant les lignes d'en-tête de sous-section (une seule
    <th> non vide, pas de <td>) et les lignes de critère (un <td> libellé
    + des <input name="critere[ID][role]">).
    """
    html = Path(html_path).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # Découverte des sections depuis les onglets de navigation.
    # ex: <a href="#section_9" data-toggle="tab">Évaluation du Rapport</a>
    section_names = {}
    for tab in soup.select('a[data-toggle="tab"]'):
        href = tab.get("href", "")
        if href.startswith("#section_"):
            section_names[href.lstrip("#")] = tab.get_text(strip=True)

    criteria: List[Criterion] = []
    for section_id, section_name in section_names.items():
        container = soup.find(id=section_id)
        if container is None:
            continue
        table = container.find("table")
        if table is None:
            continue

        subsection = None
        for tr in table.find_all("tr"):
            ths, tds = tr.find_all("th"), tr.find_all("td")

            # Ligne d'en-tête de sous-section : une seule <th> avec texte,
            # pas de <td> de saisie sur cette ligne.
            if ths and not tds:
                text = ths[0].get_text(strip=True)
                if text:
                    subsection = text
                continue

            inputs = tr.find_all("input")
            if not tds or not inputs:
                continue

            label = tds[0].get_text(strip=True)
            if not label:
                continue

            crit_id, bareme_max, evaluators = None, None, []
            for inp in inputs:
                m = re.match(r"critere\[(\d+)\]\[(\w+)\]", inp.get("name", ""))
                if not m:
                    continue
                crit_id = m.group(1)
                evaluators.append(m.group(2))
                bareme_max = float(inp.get("data-max", 0))

            if crit_id is None:
                continue

            criteria.append(
                Criterion(
                    id=crit_id,
                    section=section_name,
                    subsection=subsection,
                    label=label,
                    bareme_max=bareme_max,
                    evaluators=evaluators,
                )
            )

    return criteria


def load_grid_from_json(json_path: str | Path) -> List[Criterion]:
    """Charge une grille déjà extraite (format criteria_grid.json)."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return [
        Criterion(
            id=c["id"],
            section=c["section"],
            subsection=c.get("subsection"),
            label=c["label"],
            bareme_max=float(c["bareme_max"]),
            evaluators=c["evaluators"],
        )
        for c in data
    ]


def save_grid_to_json(criteria: List[Criterion], json_path: str | Path) -> None:
    Path(json_path).write_text(
        json.dumps([asdict(c) for c in criteria], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    # Auto-test : reparse le HTML fourni et vérifie la cohérence avec
    # criteria_grid.json déjà généré à l'étape précédente.
    criteria = parse_html_grid("/mnt/user-data/uploads/PFE-2197.html")
    print(f"{len(criteria)} critères trouvés")
    for sec in sorted(set(c.section for c in criteria)):
        sub = [c for c in criteria if c.section == sec]
        total_bareme = sum(c.bareme_max for c in sub)
        print(f"  - {sec}: {len(sub)} critères, barème total = {total_bareme}")

    mono = [c for c in criteria if c.is_mono_evaluateur]
    print(f"Critères mono-évaluateur (encadrant seul) : {[c.id for c in mono]}")
