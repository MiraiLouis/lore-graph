# Lore graph

Un assistant qui répond aux questions sur l'univers d'un roman en s'appuyant uniquement sur ce qui est écrit. Il cite ses sources et répond « Information insuffisante » quand rien n'est documenté.

Les fiches sont écrites dans [Obsidian](https://obsidian.md). Un script les copie dans un graphe Neo4j (les relations) et dans un index FAISS (la recherche par sens). Un agent LangGraph, branché sur un modèle Mistral, interroge ces deux sources avant de répondre.

```
Coffre Obsidian (source de vérité)
        │  python kg/sync.py
        ├──────────────► Neo4j  : nœuds + relations tirées des [[liens]]
        └──────────────► FAISS  : une vectorisation par note (mistral-embed)
                                   │
              python kg/agent.py   ▼
        Agent LangGraph (Mistral) ── outils : cypher · recherche · lire_note
```

L'idée vient de l'article de Fareed Khan, [Structuring 40 Million Documents into an Agentic Knowledge Graph](https://levelup.gitconnected.com/structuring-40-million-documents-into-an-agentic-knowledge-graph-92010e609dfa) : ne suivre que des relations déjà écrites, citer le chemin et refuser de répondre avant d'inventer.

## Le faux coffre

`Obsidian/Demo` est un petit univers inventé pour montrer le format : l'archipel d'Ostrel, sa Garde, son Bureau des cartes et deux artefacts. Il contient tous les types de notes et tous les statuts.

Une note est un fichier Markdown avec un en-tête YAML :

```yaml
---
id: personnage-mara
type: Personnage
statut: "CANON"
technologie: "[[Boussole d'écho]]"
organisation: "[[Garde]]"
departement: "[[Amirauté]]"
---
```

- `id` et `type` sont obligatoires. Sans eux, la note est ignorée.
- Les champs `technologie`, `organisation`, `departement`, `parent`, `pays`, `programme`, `general`, `commandement`, `veto` et `membres` deviennent des relations dans Neo4j (liste dans `kg/config.py`).
- Les autres champs simples (`categorie`, `niveau`, une date…) deviennent des propriétés du nœud.
- `statut` vaut `CANON`, `À CONFIRMER`, `À DÉFINIR` ou `ABANDONNÉ`. L'agent le signale quand ce n'est pas du canon.
- `_consignes.md`, à la racine du coffre, contient les règles propres à l'univers. L'agent les ajoute à son prompt.

## Lancer

Prérequis : Python 3.11, Docker Desktop et une clé API [Mistral](https://console.mistral.ai).

```bash
pip install -r requirements.txt
cp .env.example .env          # puis renseigner MISTRAL_API_KEY
docker compose up -d          # Neo4j sur http://localhost:7474
python kg/sync.py             # coffre -> Neo4j + FAISS
python kg/agent.py "Quel artefact utilise Mara Velin ?"
python kg/agent.py            # mode conversation
python graph/arbre.py         # arbre pays / départements / organisations / personnages
```

Après chaque modification dans Obsidian, relancer `python kg/sync.py`. Pour utiliser un autre coffre, changer `VAULT_PATH` dans `.env`.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `kg/config.py` | Lecture de `.env`, champs qui deviennent des relations |
| `kg/vault.py` | Lecture des notes, de l'en-tête et des `[[liens]]` |
| `kg/sync.py` | Remplit Neo4j et construit l'index FAISS |
| `kg/outils.py` | Outils de l'agent : Cypher en lecture seule, recherche sémantique, lecture d'une note |
| `kg/agent.py` | Boucle LangGraph modèle → outils → modèle |
| `graph/arbre.py` | Fenêtre Tkinter qui affiche la hiérarchie du coffre |
