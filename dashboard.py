"""
dashboard.py
-------------
Extension du sujet (§4.2) : "Tableau de bord de suivi des écarts entre
notes proposées par l'agent et notes validées par les enseignants, pour
mesurer la fiabilité du système dans le temps."

Source des données : les fichiers `grille_validee_*.json` téléchargés
depuis le bouton "Exporter les données" de l'interface de validation,
une fois qu'un évaluateur a réellement relu/corrigé/validé les
propositions (cf. `note_ia` figée vs `note` modifiable, ajouté dans
build_ui_data() précisément pour permettre cette mesure). Un fichier =
une session de validation, avec sa date d'export.

Usage :
    python dashboard.py --exports-dir mes_exports_valides/ --out dashboard.html

Ne traite QUE les couples où `valide_par_humain` est vrai ET la source
est "agent_ia" — un évaluateur qui n'a pas coché "validé" n'a pas
confirmé avoir relu cette proposition, donc elle ne compte pas comme un
signal de fiabilité mesuré.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class SessionStats:
    date: str
    projet: str
    n_valide: int
    biais_moyen: float
    ecart_absolu_moyen: float
    pct_sur_note: float
    pct_sous_note: float
    pct_exact: float


def load_session(path: Path) -> SessionStats | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])

    ecarts = []
    for r in rows:
        if not r.get("valide_par_humain"):
            continue  # l'évaluateur n'a pas confirmé avoir relu ce critère
        if r.get("note_source") != "agent_ia":
            continue  # rien à comparer (non évaluable / exclu)
        note_ia = r.get("note_ia")
        note_finale = r.get("note")
        if note_ia is None or note_finale is None:
            continue
        ecarts.append(float(note_finale) - float(note_ia))

    if not ecarts:
        return None

    return SessionStats(
        date=payload.get("date_export", path.stem),
        projet=payload.get("projet", path.stem),
        n_valide=len(ecarts),
        biais_moyen=round(statistics.mean(ecarts), 3),
        ecart_absolu_moyen=round(statistics.mean(abs(e) for e in ecarts), 3),
        pct_sur_note=round(100 * sum(1 for e in ecarts if e < 0) / len(ecarts), 1),  # note IA > note finale = agent avait sur-noté
        pct_sous_note=round(100 * sum(1 for e in ecarts if e > 0) / len(ecarts), 1),
        pct_exact=round(100 * sum(1 for e in ecarts if e == 0) / len(ecarts), 1),
    )


def load_all_sessions(exports_dir: str | Path) -> List[SessionStats]:
    exports_dir = Path(exports_dir)
    sessions = []
    for path in sorted(exports_dir.glob("*.json")):
        stats = load_session(path)
        if stats:
            sessions.append(stats)
    sessions.sort(key=lambda s: s.date)
    return sessions


DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Tableau de bord — fiabilité de l'agent</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

  *{{ box-sizing:border-box; }}
  body{{ font-family:'Inter', Arial, sans-serif; background:#F7FAFB; color:#0B1F33; margin:0; padding:0 0 48px; }}

  .hero{{
    background:#0B1F33;
    color:#fff;
    padding:40px 40px 34px;
  }}
  .hero .eyebrow{{
    font-family:'IBM Plex Mono', monospace;
    font-size:11px;
    letter-spacing:.08em;
    text-transform:uppercase;
    color:#2DD4BF;
    margin-bottom:10px;
  }}
  .hero h1{{
    font-family:'Fraunces', serif;
    font-weight:700;
    font-size:28px;
    letter-spacing:-0.015em;
    margin:0 0 10px;
  }}
  .hero p{{
    font-size:13.5px;
    line-height:1.6;
    color:#B9C6D4;
    max-width:640px;
    margin:0;
  }}

  .wrap{{ max-width:1000px; margin:0 auto; padding:0 40px; }}

  .stats-row{{
    display:flex;
    gap:16px;
    margin-top:-28px;
    margin-bottom:28px;
  }}
  .stat-card{{
    flex:1;
    background:#fff;
    border:1px solid #DCE6ED;
    border-radius:10px;
    padding:16px 20px;
    box-shadow:0 4px 16px rgba(10,37,64,.06);
  }}
  .stat-card .stat-value{{
    font-family:'Fraunces', serif;
    font-weight:700;
    font-size:26px;
    color:#0B1F33;
  }}
  .stat-card .stat-label{{
    font-size:12px;
    color:#51677A;
    margin-top:2px;
  }}

  table{{ border-collapse:collapse; width:100%; background:#fff; margin-top:8px; border:1px solid #DCE6ED; border-radius:10px; overflow:hidden; }}
  th, td{{ padding:10px 14px; border-bottom:1px solid #DCE6ED; text-align:left; font-size:13px; }}
  th{{ background:#EEF2F5; font-weight:600; }}
  tr:last-child td{{ border-bottom:none; }}
  .pos{{ color:#B7791F; font-weight:600; }}
  .neg{{ color:#0F6E66; font-weight:600; }}

  #chart{{ margin-top:8px; margin-bottom:28px; background:#fff; padding:18px; border-radius:10px; border:1px solid #DCE6ED; }}
  .section-title{{ font-family:'Fraunces', serif; font-weight:600; font-size:16px; margin:0 0 12px; color:#0B1F33; }}
</style>
</head>
<body>

<div class="hero">
  <div class="eyebrow">Agent IA d'évaluation — ePFE</div>
  <h1>Fiabilité de l'agent dans le temps</h1>
  <p>Écart = note finale validée par l'évaluateur − note proposée par l'agent. Positif = l'agent avait sous-noté ; négatif = l'agent avait sur-noté.</p>
</div>

<div class="wrap">
  <div class="stats-row">
    <div class="stat-card"><div class="stat-value">{n_sessions}</div><div class="stat-label">sessions de validation</div></div>
    <div class="stat-card"><div class="stat-value">{total_valide}</div><div class="stat-label">notes validées au total</div></div>
    <div class="stat-card"><div class="stat-value">{biais_global:+.3f}</div><div class="stat-label">biais moyen global</div></div>
  </div>

  <p class="section-title">Évolution du biais</p>
  <div id="chart"></div>

  <p class="section-title">Détail par session</p>
  <table>
    <tr><th>Date</th><th>Projet</th><th>Notes validées</th><th>Biais moyen</th><th>Écart absolu moyen</th><th>Sur-noté</th><th>Sous-noté</th><th>Exact</th></tr>
    {rows_html}
  </table>
</div>

<script>
const sessions = {sessions_json};
const w = 900, h = 260, pad = 40;
const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
svg.setAttribute('viewBox', `0 0 ${{w}} ${{h}}`);
svg.setAttribute('width', '100%');
document.getElementById('chart').appendChild(svg);

if(sessions.length > 0){{
  const biais = sessions.map(s => s.biais_moyen);
  const maxAbs = Math.max(0.5, ...biais.map(Math.abs));
  const x = i => pad + i * (w - 2*pad) / Math.max(1, sessions.length - 1);
  const y = v => h/2 - (v / maxAbs) * (h/2 - pad/2);

  // ligne zéro
  const zeroLine = document.createElementNS(svg.namespaceURI, 'line');
  zeroLine.setAttribute('x1', pad); zeroLine.setAttribute('x2', w - pad);
  zeroLine.setAttribute('y1', y(0)); zeroLine.setAttribute('y2', y(0));
  zeroLine.setAttribute('stroke', '#DCE6ED'); zeroLine.setAttribute('stroke-width', '1');
  svg.appendChild(zeroLine);

  const points = sessions.map((s,i) => `${{x(i)}},${{y(s.biais_moyen)}}`).join(' ');
  const polyline = document.createElementNS(svg.namespaceURI, 'polyline');
  polyline.setAttribute('points', points);
  polyline.setAttribute('fill', 'none');
  polyline.setAttribute('stroke', '#14B8A6');
  polyline.setAttribute('stroke-width', '2');
  svg.appendChild(polyline);

  sessions.forEach((s,i) => {{
    const c = document.createElementNS(svg.namespaceURI, 'circle');
    c.setAttribute('cx', x(i)); c.setAttribute('cy', y(s.biais_moyen)); c.setAttribute('r', 4);
    c.setAttribute('fill', s.biais_moyen < 0 ? '#B7791F' : '#0F6E66');
    svg.appendChild(c);
  }});
}} else {{
  document.getElementById('chart').innerHTML = '<p style="color:#8A9BA9">Pas encore de session validée à afficher.</p>';
}}
</script>
</body>
</html>
"""


def build_dashboard_html(sessions: List[SessionStats]) -> str:
    rows_html = "\n".join(
        f"<tr><td>{s.date}</td><td>{s.projet}</td><td>{s.n_valide}</td>"
        f"<td class=\"{'neg' if s.biais_moyen < 0 else 'pos'}\">{s.biais_moyen:+.3f}</td>"
        f"<td>{s.ecart_absolu_moyen:.3f}</td>"
        f"<td>{s.pct_sur_note}%</td><td>{s.pct_sous_note}%</td><td>{s.pct_exact}%</td></tr>"
        for s in sessions
    )
    total_valide = sum(s.n_valide for s in sessions)
    biais_global = (
        sum(s.biais_moyen * s.n_valide for s in sessions) / total_valide
        if total_valide else 0.0
    )
    sessions_json = json.dumps([
        {"date": s.date, "biais_moyen": s.biais_moyen} for s in sessions
    ], ensure_ascii=False)

    return DASHBOARD_TEMPLATE.format(
        n_sessions=len(sessions),
        total_valide=total_valide,
        biais_global=biais_global,
        rows_html=rows_html or "<tr><td colspan='8'>Aucune session validée trouvée.</td></tr>",
        sessions_json=sessions_json,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tableau de bord de fiabilité agent vs évaluateur, dans le temps")
    parser.add_argument("--exports-dir", required=True, help="Dossier contenant les grille_validee_*.json téléchargés depuis l'interface")
    parser.add_argument("--out", default="dashboard.html")
    args = parser.parse_args()

    sessions = load_all_sessions(args.exports_dir)
    if not sessions:
        print(
            f"Aucune session validée trouvée dans {args.exports_dir}. "
            f"Le dashboard aura besoin de fichiers grille_validee_*.json avec au moins "
            f"un critère coché 'validé' par un évaluateur."
        )

    html = build_dashboard_html(sessions)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"{len(sessions)} session(s) chargée(s). Dashboard écrit dans {args.out}")
