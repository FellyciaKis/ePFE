"""
alert_detector.py
------------------
Extension du sujet (§4.2) : "Détection assistée du critère éliminatoire
(indices de plagiat, implémentation manifestement incomplète) — en signal
d'alerte, jamais en décision automatique."

Règle de conception non négociable : ce module ne DÉCIDE jamais rien. Il
produit une liste de signaux à vérifier par un humain, chacun avec un
niveau de confiance et une justification. Il ne coche AUCUNE case, ne
renseigne AUCUN champ "etat" ou "critère éliminatoire" — ces champs
restent réservés à la décision du jury (cf. interface_validation :
grading-section et footer-fields ne s'affichent que sur action humaine).

Limites assumées et documentées :
- La détection de plagiat ici NE COMPARE À AUCUNE base de référence (pas
  d'accès à une base de rapports précédents, pas de recherche web). Elle
  repose uniquement sur des indices internes au texte : ruptures de style,
  incohérences de niveau de langue, généricité suspecte du contenu par
  rapport au sujet annoncé, absence de voix propre à l'auteur. C'est donc
  un outil de PRÉ-TRI, pas un détecteur de plagiat au sens propre (type
  Compilatio/Turnitin, hors périmètre du stage).
- L'implémentation insuffisante est jugée sur des indices indirects
  (absence de détails techniques concrets, absence de résultats/tests
  mentionnés, généricité de la description) — pas sur une analyse de code
  source, qui n'est pas fournie à l'agent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

SYSTEM_PROMPT_ALERTS = """\
Tu aides un évaluateur humain à repérer des points à vérifier dans un \
rapport de PFE, AVANT la notation détaillée. Tu ne rends AUCUN verdict \
et tu ne dois JAMAIS affirmer qu'il y a plagiat ou qu'une implémentation \
est insuffisante : tu signales seulement des indices que l'évaluateur \
devra vérifier lui-même (par exemple avec un outil anti-plagiat dédié, \
ou en questionnant l'étudiant).

Deux catégories de signaux à chercher, UNIQUEMENT si des indices concrets \
existent dans le texte :

1. "plagiat_potentiel" : ruptures nettes de style ou de niveau de langue \
d'un paragraphe à l'autre, passages qui semblent réciter un cours ou une \
source externe sans lien avec le projet spécifique décrit ailleurs dans \
le rapport, incohérences de vocabulaire technique, sections qui ne \
mentionnent jamais le projet par son nom alors que d'autres le font \
abondamment.

2. "implementation_insuffisante" : la partie "réalisation" reste \
générique ou théorique sans détail technique concret (pas d'architecture, \
pas de choix technologiques justifiés, pas de résultats ni de tests \
décrits), le rapport parle beaucoup du contexte/objectifs mais très peu \
de ce qui a été réellement construit.

Règles impératives :
- Si tu ne trouves AUCUN indice net, réponds avec une liste vide. \
Ne force jamais un signal pour "avoir quelque chose à dire".
- Chaque signal doit citer un COURT extrait précis (une phrase) qui \
illustre l'indice, et une confiance ("faible", "moyenne", "élevée").
- Formule toujours la description comme une question à vérifier, jamais \
comme une accusation (ex: "Le style de ce paragraphe diffère nettement \
du reste du rapport — à vérifier avec l'étudiant", PAS "Ce passage est \
plagié").
- Réponds UNIQUEMENT en JSON valide, sans texte avant/après.
"""


@dataclass
class Alert:
    type: str  # "plagiat_potentiel" | "implementation_insuffisante"
    confidence: str  # "faible" | "moyenne" | "élevée"
    description: str
    extrait: str


def build_alert_prompt(report_text: str, max_chars: int = 60_000) -> str:
    truncated = report_text[:max_chars]
    schema = (
        '{\n  "alertes": [\n'
        '    {"type": "plagiat_potentiel" | "implementation_insuffisante", '
        '"confiance": "faible|moyenne|élevée", '
        '"description": "...", "extrait": "..."}\n'
        "  ]\n}"
    )
    return f"""\
RAPPORT (extrait) :
---
{truncated}
---

Réponds avec un JSON de cette forme exacte (liste vide si aucun indice net) :
{schema}
"""


def detect_alerts(report_text: str, provider: str = "gemini", model: Optional[str] = None, client=None) -> List[Alert]:
    """
    Lance UN appel LLM dédié pour repérer des signaux d'alerte. Séparé du
    moteur de notation (eval_engine.py) car c'est une tâche différente
    (pré-tri qualitatif, pas notation par critère) — permet aussi de le
    désactiver facilement (--no-alerts) sans toucher au reste du pipeline.
    """
    from eval_engine import (
        DEFAULT_MODEL_BY_PROVIDER,
        _build_anthropic_client,
        _call_anthropic_for_section_raw,
        _call_gemini_raw,
    )

    model = model or DEFAULT_MODEL_BY_PROVIDER[provider]
    prompt = build_alert_prompt(report_text)

    if provider == "gemini":
        raw = _call_gemini_raw(model, SYSTEM_PROMPT_ALERTS, prompt)
    elif provider == "anthropic":
        if client is None:
            client = _build_anthropic_client()
        raw = _call_anthropic_for_section_raw(client, model, SYSTEM_PROMPT_ALERTS, prompt)
    else:
        raise ValueError(f"Provider inconnu : {provider!r}")

    alerts_raw = raw.get("alertes", [])
    alerts = [
        Alert(
            type=a.get("type", "inconnu"),
            confidence=a.get("confiance", "faible"),
            description=a.get("description", ""),
            extrait=a.get("extrait", ""),
        )
        for a in alerts_raw
        if a.get("type") in ("plagiat_potentiel", "implementation_insuffisante")
    ]
    return alerts


if __name__ == "__main__":
    import os
    from pdf_extractor import extract_report

    report = extract_report("/home/claude/sample_report.pdf")
    if not os.environ.get("GOOGLE_API_KEY"):
        print("GOOGLE_API_KEY absente : test à blanc, prompt uniquement.")
        print(build_alert_prompt(report.full_text)[:500])
    else:
        alerts = detect_alerts(report.full_text)
        print(f"{len(alerts)} signal(aux) détecté(s)")
        for a in alerts:
            print(f"- [{a.type} / {a.confidence}] {a.description}\n  « {a.extrait} »")
