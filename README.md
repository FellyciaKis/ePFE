# Agent IA d'aide à l'évaluation des rapports de PFE — MVP

Prototype développé pendant le stage, correspondant au périmètre MVP du
sujet (§4.1) : lecture dynamique de la grille, extraction du rapport,
moteur d'évaluation, génération de sortie, interface de validation.

## Architecture

```
PFE-XXXX.html (grille)  ──┐
                           ├──► grid_loader.py ───────┐
rapport.pdf ───► pdf_extractor.py                     ├──► prompt_builder.py ──► eval_engine.py (LLM) ──► output_writer.py ──► resultat.json
                                                        │                                                        │
                                                        └── json_export_parser.py (relit un export existant)     └──► interface_validation.html (relecture humaine)
```

| Module | Rôle |
|---|---|
| `grid_loader.py` | Parse dynamiquement la grille HTML (ou un export JSON de structure) — aucune grille codée en dur. |
| `json_export_parser.py` | Relit un export ePFE existant en gérant la duplication d'entrées identifiée (cf. plus bas). |
| `pdf_extractor.py` | Extrait le texte du rapport PDF, avec découpage heuristique en sections. |
| `prompt_builder.py` | Construit un prompt par section de la grille, en JSON structuré en sortie. |
| `eval_engine.py` | Appelle l'API Claude (ou tout autre modèle compatible) et agrège les propositions. |
| `output_writer.py` | Génère un export `eval[]` étendu (justification + extrait), sans dupliquer les entrées. |
| `alert_prompt.py` / `alert_detector.py` | Extension : détecte des **signaux** (pas des décisions) de plagiat potentiel ou d'implémentation insuffisante, en un seul appel LLM dédié. |
| `calibration.py` | Extension : compare les notes de l'agent à de vraies notes de jury externes (biais moyen, écart absolu, plus gros désaccords). |
| `dashboard.py` | Extension : suit la fiabilité de l'agent **dans le temps**, à partir des exports validés par les évaluateurs depuis l'interface. |
| `dashboard.py` | Extension : suit dans le temps l'écart entre les notes de l'agent et les notes validées par les évaluateurs, à partir des exports téléchargés depuis l'interface. |
| `main.py` | Orchestrateur CLI du pipeline complet (mono-rapport). |
| `batch_run.py` | Lance le pipeline sur tous les PDF d'un dossier, avec une interface unique regroupant tous les rapports. |
| `interface_validation.html` | Interface de relecture pour l'évaluateur humain (autonome, sans backend). |

## Comment lancer

```bash
pip install beautifulsoup4 pdfplumber requests anthropic
```

Deux fournisseurs LLM sont supportés (`--provider`), **`gemini` par défaut**
car gratuit sans carte bancaire :

```bash
# Option gratuite (recommandée pour prototyper) : Google Gemini
# Clé API sur https://aistudio.google.com/apikey (compte Google, pas de CB)
export GOOGLE_API_KEY=...                  # Windows : set GOOGLE_API_KEY=...
python main.py --grid PFE-2197.html --report rapport.pdf --idprojet 2197 --session 1 --out resultat.json

# Option payante : Claude
export ANTHROPIC_API_KEY=sk-...
python main.py --grid PFE-2197.html --report rapport.pdf --idprojet 2197 --session 1 --out resultat.json --provider anthropic
```

Sans clé API définie, le script s'arrête proprement après avoir validé la
grille et le rapport (utile pour tester ces deux étapes sans consommer
d'appels API).

## Décisions de conception

- **Un appel LLM par section** (et non par critère unique, ni un unique
  appel global) : compromis coût/qualité pour le MVP. Piste d'extension :
  mesurer si un appel par critère améliore significativement la précision,
  ou si un appel global suffit pour des rapports courts.
- **Traçabilité systématique** : chaque note proposée est accompagnée
  d'une justification et d'un extrait du rapport, pour que l'évaluateur
  puisse vérifier rapidement sans relire tout le rapport. C'est la
  condition posée par le sujet pour rester un outil d'aide à la décision
  et non un système de notation autonome.
- **Aucune duplication en sortie** : contrairement à l'export réel observé
  (voir plus bas), `output_writer.py` écrit une seule entrée par
  `(critere, intervenant)`.
- **La note finale n'est pas recalculée par l'agent** (`output_writer.py`
  la laisse à `null`) : sa formule exacte n'est pas confirmée (voir points
  ouverts).

## Point de vigilance résolu : duplication du `eval[]`

Sur l'export réel `PFE-2197.json` : 146 entrées pour 73 couples
`(critere, intervenant)` distincts (23 critères × 3 évaluateurs + 4
critères mono-évaluateur = 73). Chaque couple apparaît exactement deux
fois : une fois avec la vraie note, une fois avec `note=""`, dans le même
ordre — cohérent avec un template de formulaire vide concaténé aux
valeurs saisies plutôt qu'une erreur de sérialisation aléatoire.

`json_export_parser.py` déduplique en gardant la première valeur non vide
rencontrée par couple. **À confirmer avec l'équipe technique ePFE** avant
de généraliser cette hypothèse à tous les exports (le sujet le demandait
explicitement).

## Extension implémentée : signal de plagiat / implémentation insuffisante

Comme demandé dans le sujet (§4.2), cette détection **ne décide jamais** :
elle produit une liste de signaux (`alert_detector.py`), chacun avec une
confiance et un extrait à l'appui, affichés dans l'interface comme un
bandeau d'avertissement **au-dessus** du bloc "Critère éliminatoire" —
jamais en pré-cochant une case. Vérifié dans un DOM réel (jsdom) que les
boutons radio ne sont jamais cochés automatiquement, quel que soit le
signal détecté.

Limites assumées : pas de comparaison à une base de référence (ce n'est
pas un détecteur type Compilatio/Turnitin), uniquement des indices
internes au texte (ruptures de style, généricité suspecte, usage
systématique du conditionnel pour des résultats qui devraient être
acquis...). Activé par défaut dans `main.py`/`batch_run.py`
(`--no-alerts` pour désactiver, un appel LLM en moins).

## Extension implémentée : calibration (agent vs vraies notes de jury)

`calibration.py` compare un `resultat_XXXX.json` (sortie de l'agent) à un
export ePFE réel du **même projet** (avec les vraies notes saisies par le
jury). Il calcule :
- le **biais moyen** (signé — positif = sur-notation, cohérent avec le
  biais connu des LLM évoqué dans le sujet) ;
- l'**écart absolu moyen** (à quel point l'agent se trompe, dans un sens
  ou l'autre) ;
- les **5 plus gros désaccords**, pour aller relire directement les
  critères les plus problématiques.

Validé sur un cas contrôlé (biais de +8% injecté artificiellement sur les
vraies notes de PFE-2197) : l'outil a correctement détecté un biais de
+6.8% (l'écart avec les 8% injectés vient du plafonnement des notes déjà
proches du barème maximum — cohérent).

**Limite actuelle : aucun projet de test ne dispose à la fois d'un vrai
rapport PDF traité par l'agent ET des vraies notes de jury correspondantes**
(on a les vraies notes de PFE-2197 mais pas son PDF ; on a plusieurs PDF
réels traités par l'agent — cf. `resultats_batch/` — mais pas leurs
vraies notes de jury). Dès qu'un même projet aura les deux, lancer :
```bash
python calibration.py --reference PFE-XXXX.json --agent resultat_XXXX.json --out calibration_XXXX.csv
```

## Extension implémentée : tableau de bord de suivi dans le temps

`dashboard.py` répond littéralement à l'extension du sujet : suivre les
écarts entre notes de l'agent et notes validées par les enseignants, dans
le temps. Ça nécessitait un changement structurel : l'interface de
validation **écrasait** la proposition de l'agent dès qu'un évaluateur la
corrigeait, rendant toute comparaison ultérieure impossible.

**Correctif appliqué** : `build_ui_data()` (dans `build_validation_ui.py`)
ajoute désormais un champ `note_ia` figé à côté de `note` — la proposition
originale de l'agent n'est plus jamais réécrite, seule `note` change quand
l'évaluateur corrige. L'export ("Exporter les données" dans l'interface)
inclut maintenant une date (`date_export`) et le nom du projet, dans un
fichier `grille_validee_<projet>.json`.

**Utilisation** :
1. Les évaluateurs utilisent l'interface normalement (corrigent les notes,
   cochent "validé"), puis cliquent "Exporter les données".
2. Ces exports s'accumulent dans un dossier au fil des sessions.
3. `python dashboard.py --exports-dir mes_exports_valides/ --out dashboard.html`
   génère un tableau de bord HTML (tableau + graphique SVG) montrant
   l'évolution du biais moyen (sur/sous-notation) et de l'écart absolu
   moyen, session après session.

Ne compte que les couples (critère, intervenant) où `valide_par_humain`
est vrai ET où l'agent avait proposé une note — un critère non relu par
un humain n'est pas un signal de fiabilité fiable. Testé sur 4 sessions
simulées avec un biais décroissant volontaire (0.35 → 0.03) : la tendance
est correctement retrouvée dans les chiffres et le graphique.

**Limite actuelle** : comme pour `calibration.py`, aucune vraie session de
validation n'existe encore (le module est prêt, mais vide tant qu'aucun
export réel n'est produit depuis l'interface).

## Extension implémentée : tableau de bord de suivi dans le temps

`dashboard.py` répond directement au point du sujet (§4.2) : *"tableau de
bord de suivi des écarts entre notes proposées par l'agent et notes
validées par les enseignants, pour mesurer la fiabilité du système dans
le temps"*.

**Source des données** : les fichiers `grille_validee_*.json` téléchargés
depuis le bouton "Exporter les données" de l'interface, une fois qu'un
évaluateur a réellement relu/corrigé/coché "validé" les propositions.
Chaque export contient, pour chaque critère, `note_ia` (la proposition
originale de l'agent, **jamais modifiée** par l'interface — cf.
`build_ui_data()`) et `note` (la valeur finale, modifiable). L'écart entre
les deux, une fois agrégé sur tous les critères cochés "validé", donne le
biais réel de l'agent — pas besoin d'un fichier externe de vraies notes de
jury (contrairement à `calibration.py`, qui reste utile quand on dispose
d'un export ePFE de référence).

Usage :
```bash
python dashboard.py --exports-dir mes_exports_valides/ --out dashboard.html
```

Validé sur 4 sessions simulées avec des biais différents (dont une
tendance à l'amélioration) : le tableau de bord affiche correctement le
nombre de sessions, le biais global pondéré, un graphique d'évolution du
biais par session, et un tableau détaillé. Gère aussi le cas où aucune
session validée n'existe encore (message clair plutôt qu'un plantage).

**Pour l'alimenter en conditions réelles** : il suffit qu'un évaluateur
utilise normalement l'interface (corriger si besoin, cocher "validé"
critère par critère, cliquer "Exporter les données"), et de regrouper ces
exports dans un dossier avant de lancer `dashboard.py` dessus.

## Points ouverts (à traiter pendant le stage, pas devinés ici)

0. **[Corrigé après premier test réel]** Sur un premier test avec un rapport
   réel, le modèle notait quand même la section "Évaluation de la
   présentation" (oral, diapos, interaction jury) et les critères
   mono-évaluateur (84-87, assiduité/autonomie...) en inventant une note
   "moyenne" (souvent ~50% du barème), alors même que sa propre
   justification disait explicitement ne pas pouvoir juger. Corrections
   appliquées : (1) le schéma de sortie inclut un champ
   `"non_evaluable": true/false` avec une règle explicite dans le prompt
   système pour ne jamais deviner dans ce cas ; (2) `main.py` exclut
   désormais **par défaut** la section Présentation et les critères
   84-87 de l'appel au modèle (`--include-all` pour forcer) ; (3)
   `output_writer.py` distingue `agent_ia` / `non_evaluable_par_ia` /
   `non_evalue` dans le champ `note_source` de la sortie.

1. **[RÉSOLU] Formule exacte de la note finale.** Confirmée à partir des
   captures d'écran de la vraie interface ePFE (grille grid=5) : chaque
   section pèse 50% (Rapport) / 30% (Présentation) / 20% (Stage) dans la
   note finale ; à l'intérieur de chaque section, les évaluateurs pèsent
   30/45/25% (Rapport), 25/40/35% (Présentation), 100% encadrant seul
   (Stage). Recalcul vérifié sur l'export réel PFE-2197 : donne
   exactement 17.34, la vraie note. Implémentée dans
   `interface_validation_template.html` (calcul en direct, avec malus).
   **Attention** : ces poids sont propres à `grid=5` — à vérifier si
   d'autres grilles (`grid` différent) utilisent une pondération
   différente avant de généraliser à tous les projets ePFE.
2. **Critères mono-évaluateur.** Le modèle n'a accès qu'au texte du
   rapport, pas au vécu réel du stage (assiduité, autonomie...). Pour ces
   4 critères, ses propositions doivent être traitées comme des indices
   faibles, pas des estimations fiables — à discuter avec les encadrants.
3. **OCR.** Si des rapports sont scannés (pas de couche texte), le module
   `pdf_extractor.py` le détecte et prévient, mais l'OCR lui-même n'est
   pas implémenté (hors MVP).
4. **Rapports longs.** `prompt_builder.py` tronque au-delà de 60k
   caractères par défaut. Pour des rapports plus longs, prévoir un
   découpage plus fin (par section du rapport plutôt que par grille) —
   cf. extension "calibration" du sujet.
5. **API cloud vs LLM local.** L'architecture isole l'appel modèle dans
   `eval_engine.py` (paramètre `client=`), pour permettre de comparer
   facilement un modèle cloud et un modèle local si la confidentialité des
   rapports non publiés l'exige (extension du sujet).
6. **Quota gratuit Gemini.** `gemini-2.5-flash` (modèle initialement
   choisi) a vu son quota gratuit réduit à ~20 requêtes/jour fin 2025 —
   insuffisant pour un batch de plusieurs rapports. Le pipeline utilise
   désormais `gemini-2.5-flash-lite` par défaut (~1000 requêtes/jour
   gratuites), et `_call_gemini_raw()` réessaie automatiquement en cas de
   429 *par minute* (avec le délai suggéré par l'API). Si le quota
   *journalier* est épuisé, réessayer ne sert à rien : l'erreur le
   précise explicitement, et le rapport concerné est simplement ignoré
   (pas de crash du batch) — il sera retenté automatiquement au run
   suivant grâce au cache.

## Interface de validation

`interface_validation.html` est un prototype autonome (pas de backend) :
il charge des données de démonstration réalistes (générées à partir de la
vraie grille), affiche les propositions groupées par section/sous-section,
permet de corriger chaque note et de cocher "validé" par évaluateur, et
exporte la grille corrigée en JSON. Pour la brancher sur de vraies
données, remplacer la constante `DATA` par la sortie de
`output_writer.py`. Prochaine étape naturelle : brancher un vrai backend
(la plateforme ePFE elle-même) pour l'enregistrement définitif.
