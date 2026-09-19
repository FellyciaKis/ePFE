"""
eval_engine.py
--------------
Appelle un LLM pour proposer, section par section, une note + justification
+ extrait pour chaque critère de la grille.

Deux fournisseurs supportés dès le MVP (l'extension "API cloud vs LLM
local" du sujet pourra en ajouter un troisième sans changer le reste du
pipeline, tout passe par l'interface CriterionEvaluation / evaluate_report) :

- "gemini" (PAR DÉFAUT) : API Google Gemini, gratuite sans carte bancaire
  via Google AI Studio (https://aistudio.google.com/apikey). Nécessite
  GOOGLE_API_KEY. Recommandé pour prototyper sans budget.
- "anthropic" : API Claude, payante à l'usage. Nécessite ANTHROPIC_API_KEY.

Le format de sortie demandé au modèle (JSON structuré) est le même pour
les deux, seul l'appel réseau change.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional

from grid_loader import Criterion
from prompt_builder import SYSTEM_PROMPT, SectionPrompt, build_section_prompts

DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL_BY_PROVIDER = {
    # gemini-3.5-flash-lite : gemini-2.5-flash-lite n'est plus disponible
    # pour les nouveaux comptes (message d'erreur 404 explicite de l'API
    # au 17/08/2026, qui recommande ce remplacement). Si Google change à
    # nouveau de modèle par défaut, l'erreur renvoyée par l'API l'indique
    # généralement clairement — mettre à jour cette ligne suffit.
    "gemini": "gemini-3.5-flash-lite",
    "anthropic": "claude-sonnet-4-6",  # cf. product-self-knowledge pour la liste à jour
}


@dataclass
class CriterionEvaluation:
    critere: str
    note_proposee: float
    bareme_max: float
    justification: str
    extrait: str
    non_evaluable: bool = False  # le modèle juge qu'un rapport écrit seul ne permet pas de noter
    hors_barème: bool = False  # flag de sécurité si le modèle dépasse le barème


def evaluate_report(
    criteria: List[Criterion],
    report_text: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    client=None,
    exclude_sections: Optional[List[str]] = None,
    exclude_criteria_ids: Optional[List[str]] = None,
) -> List[CriterionEvaluation]:
    """
    Lance un appel LLM par section de la grille et agrège les résultats.

    `provider` : "gemini" (défaut, gratuit) ou "anthropic".
    `model` : nom du modèle ; par défaut celui de DEFAULT_MODEL_BY_PROVIDER.
    `client` : pour le provider "anthropic" uniquement, permet d'injecter
    un client anthropic.Anthropic() déjà configuré (tests / réutilisation).
    Pour "gemini", les appels se font en HTTP direct (pas de client à
    injecter), l'argument est ignoré.
    `exclude_sections` / `exclude_criteria_ids` : critères à ne PAS
    soumettre au modèle (cf. prompt_builder.build_section_prompts). Par
    défaut, evaluate_report() ne exclut rien lui-même — c'est main.py qui
    fixe les valeurs par défaut recommandées (section Présentation +
    critères mono-évaluateur 84-87), pour laisser ce module réutilisable
    tel quel dans d'autres contextes.
    """
    model = model or DEFAULT_MODEL_BY_PROVIDER[provider]
    if provider == "anthropic" and client is None:
        client = _build_anthropic_client()

    prompts = build_section_prompts(
        criteria, report_text,
        exclude_sections=exclude_sections,
        exclude_criteria_ids=exclude_criteria_ids,
    )
    criteria_by_id = {c.id: c for c in criteria}

    all_evaluations: List[CriterionEvaluation] = []
    for section_prompt in prompts:
        if provider == "gemini":
            raw_evaluations = _call_gemini_for_section(model, section_prompt)
        elif provider == "anthropic":
            raw_evaluations = _call_anthropic_for_section(client, model, section_prompt)
        else:
            raise ValueError(f"Provider inconnu : {provider!r} (attendu: 'gemini' ou 'anthropic')")

        for item in raw_evaluations:
            crit = criteria_by_id.get(item.get("critere"))
            if crit is None:
                continue  # le modèle a halluciné un id de critère : on l'ignore
            non_evaluable = bool(item.get("non_evaluable", False))
            note = 0.0 if non_evaluable else float(item.get("note", 0))
            hors_bareme = not (0 <= note <= crit.bareme_max)
            if hors_bareme:
                note = max(0.0, min(note, crit.bareme_max))  # on clippe par sécurité
            all_evaluations.append(
                CriterionEvaluation(
                    critere=crit.id,
                    note_proposee=note,
                    bareme_max=crit.bareme_max,
                    justification=item.get("justification", ""),
                    extrait=item.get("extrait", ""),
                    non_evaluable=non_evaluable,
                    hors_barème=hors_bareme,
                )
            )

    _check_completeness(criteria, all_evaluations, exclude_sections, exclude_criteria_ids)
    return all_evaluations


def _build_anthropic_client():
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            "Le package 'anthropic' est requis : pip install anthropic"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY n'est pas définie. Configurez votre clé API "
            "(cf. https://docs.claude.com) ou injectez votre propre client "
            "via le paramètre `client=` de evaluate_report()."
        )
    return anthropic.Anthropic(api_key=api_key)


def _call_anthropic_for_section(client, model: str, section_prompt: SectionPrompt) -> list[dict]:
    parsed = _call_anthropic_for_section_raw(client, model, SYSTEM_PROMPT, section_prompt.user_prompt)
    return parsed.get("evaluations", [])


def _call_gemini_for_section(model: str, section_prompt: SectionPrompt) -> list[dict]:
    parsed = _call_gemini_raw(model, SYSTEM_PROMPT, section_prompt.user_prompt)
    return parsed.get("evaluations", [])


def _call_anthropic_for_section_raw(client, model: str, system_prompt: str, user_prompt: str) -> dict:
    """Appel générique à l'API Claude, réutilisé par le moteur de notation
    ET par alert_detector.py (prompt système différent selon la tâche)."""
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return _parse_llm_json(text)


def _call_gemini_raw(model: str, system_prompt: str, user_prompt: str, max_retries: int = 2) -> dict:
    """
    Appel HTTP générique à l'API Gemini (pas de SDK requis, juste
    `requests`), réutilisé par le moteur de notation ET par
    alert_detector.py. Free tier via Google AI Studio :
    https://aistudio.google.com/apikey

    En cas de limite de débit (429) *par minute*, on attend le délai
    suggéré par Gemini et on réessaie automatiquement (jusqu'à
    `max_retries` fois). Si le quota *journalier* est épuisé, réessayer
    ne sert à rien (le délai suggéré ne résout pas ce cas) : on abandonne
    après le nombre d'essais prévu plutôt que de bloquer le batch pendant
    des heures — cf. README pour changer de modèle si ça arrive souvent.
    """
    try:
        import requests
    except ImportError as exc:
        raise ImportError("Le package 'requests' est requis : pip install requests") from exc

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GOOGLE_API_KEY n'est pas définie. Créez une clé gratuite sur "
            "https://aistudio.google.com/apikey (aucune carte bancaire "
            "requise), puis : set GOOGLE_API_KEY=... (Windows) ou "
            "export GOOGLE_API_KEY=... (Mac/Linux)."
        )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    resp = None
    for attempt in range(max_retries + 1):
        resp = requests.post(url, params={"key": api_key}, json=payload, timeout=120)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait_s = _parse_retry_delay(resp.text) or (15 * (attempt + 1))
                print(f"      [!] Limite de débit Gemini atteinte, nouvelle tentative dans {wait_s:.0f}s ({attempt + 1}/{max_retries})...")
                time.sleep(wait_s)
                continue
            raise RuntimeError(
                f"Erreur API Gemini (429) après {max_retries + 1} tentative(s) — probablement le "
                f"quota JOURNALIER épuisé (pas résolu en attendant) : {resp.text[:500]}"
            )
        break

    if resp.status_code != 200:
        raise RuntimeError(f"Erreur API Gemini ({resp.status_code}) : {resp.text[:500]}")

    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise ValueError(f"Réponse Gemini inattendue : {json.dumps(data)[:500]}") from exc

    return _parse_llm_json(text)


def _parse_retry_delay(error_text: str) -> Optional[float]:
    """Extrait le délai suggéré par Gemini dans son message d'erreur 429 (ex: 'retry in 55.6s')."""
    m = re.search(r'retry in (\d+(?:\.\d+)?)s', error_text)
    if m:
        return float(m.group(1)) + 1  # petite marge de sécurité
    return None


def _parse_llm_json(text: str) -> dict:
    text = text.strip()
    # Filet de sécurité si le modèle entoure malgré tout le JSON de ```
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0] if "```" in text else text

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass  # on tente une réparation avant d'abandonner (cf. _repair_json_escapes)

    repaired = _repair_json_escapes(text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Réponse LLM non-JSON (même après réparation) : {exc}\nContenu brut : {text[:500]}"
        ) from exc


def _repair_json_escapes(text: str) -> str:
    r"""
    Le modèle produit parfois un JSON invalide en citant du texte du
    rapport tel quel : un backslash suivi d'un caractère qui n'est pas un
    échappement JSON valide (ex: chemin Windows, notation mathématique,
    LaTeX...) casse le parsing strict. On double les backslashes "orphelins"
    (ceux qui ne forment pas un échappement JSON reconnu : \" \\ \/ \b \f
    \n \r \t \uXXXX) pour les neutraliser, sans toucher aux échappements
    valides.
    """
    return re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', text)


def _check_completeness(
    criteria: List[Criterion],
    evaluations: List[CriterionEvaluation],
    exclude_sections: Optional[List[str]],
    exclude_criteria_ids: Optional[List[str]],
) -> None:
    exclude_sections = set(exclude_sections or [])
    exclude_criteria_ids = set(exclude_criteria_ids or [])
    expected_ids = {
        c.id for c in criteria
        if c.section not in exclude_sections and c.id not in exclude_criteria_ids
    }
    got_ids = {e.critere for e in evaluations}
    missing = expected_ids - got_ids
    if missing:
        print(
            f"[eval_engine] ATTENTION : {len(missing)} critère(s) sans proposition "
            f"du modèle : {sorted(missing)}. L'évaluateur humain devra les compléter "
            f"manuellement."
        )
    non_eval = [e.critere for e in evaluations if e.non_evaluable]
    if non_eval:
        print(
            f"[eval_engine] {len(non_eval)} critère(s) jugés non évaluables par le "
            f"modèle à partir du seul rapport écrit : {sorted(non_eval)}."
        )


if __name__ == "__main__":
    from grid_loader import parse_html_grid
    from pdf_extractor import extract_report

    criteria = parse_html_grid("/mnt/user-data/uploads/PFE-2197.html")
    report = extract_report("/home/claude/sample_report.pdf")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY absente de l'environnement : test à blanc.\n"
            "Les prompts ont été validés dans prompt_builder.py ; branchez "
            "une clé API pour tester l'appel réel."
        )
    else:
        evals = evaluate_report(criteria, report.full_text)
        for e in evals:
            print(e)
