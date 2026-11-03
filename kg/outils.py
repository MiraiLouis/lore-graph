"""Outils de l'agent : Cypher lecture seule, recherche FAISS, lecture de note."""

import json
import re

from langchain_core.tools import tool
from neo4j import GraphDatabase

from kg import config
from kg.vault import trouver_note

_ECRITURE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s+\{|apoc\.(create|merge|refactor|periodic|load|export)|FOREACH)\b",
    re.IGNORECASE,
)
_driver = None
_faiss = None


def driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    return _driver


def schema() -> str:
    with driver().session() as session:
        labels = [r["label"] for r in session.run(
            "CALL db.labels() YIELD label RETURN label ORDER BY label"
        )]
        rels = [r["relationshipType"] for r in session.run(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType"
        )]
        motifs = session.run(
            "MATCH (a)-[r]->(b) "
            "WITH [l IN labels(a) WHERE l <> 'Noeud'][0] AS la, type(r) AS t, [l IN labels(b) WHERE l <> 'Noeud'][0] AS lb, count(*) AS n "
            "RETURN la, t, lb, n ORDER BY la, t, lb"
        )
        lignes = [f"  (:{m['la']})-[:{m['t']}]->(:{m['lb']})  x{m['n']}" for m in motifs]
        props = session.run(
            "MATCH (n:Noeud) UNWIND keys(n) AS k RETURN DISTINCT k ORDER BY k"
        )
        cles = [p["k"] for p in props]
    return (
        "Labels : " + ", ".join(labels) + "\n"
        "Relations : " + ", ".join(rels) + "\n"
        "Motifs :\n" + "\n".join(lignes) + "\n"
        "Propriétés des nœuds : " + ", ".join(cles) + "\n"
        "Tous les nœuds portent aussi le label Noeud et les propriétés id, titre, type, statut, chemin."
    )


@tool
def cypher(requete: str) -> str:
    """Exécute une requête Cypher en LECTURE SEULE sur le graphe Neo4j du lore.
    Utilise les labels, relations et propriétés du schéma fourni. Retourne au plus 50 lignes en JSON."""
    if _ECRITURE.search(requete):
        return "Refusé : seule la lecture est autorisée (MATCH / RETURN / WITH / ORDER BY / LIMIT)."
    try:
        with driver().session() as session:
            result = session.run(requete)
            lignes = []
            for record in result:
                ligne = {}
                for cle, valeur in record.items():
                    if hasattr(valeur, "items") and hasattr(valeur, "labels"):
                        ligne[cle] = {"labels": sorted(valeur.labels), **dict(valeur.items())}
                    elif hasattr(valeur, "type") and hasattr(valeur, "start_node"):
                        ligne[cle] = {"type": valeur.type, **dict(valeur.items())}
                    elif hasattr(valeur, "nodes") and hasattr(valeur, "relationships"):
                        ligne[cle] = " ".join(
                            f"({n.get('titre')})" if i % 2 == 0 else f"-[:{n.type}]->"
                            for i, n in enumerate(_aplatir_chemin(valeur))
                        )
                    else:
                        ligne[cle] = valeur
                lignes.append(ligne)
                if len(lignes) >= 50:
                    break
        if not lignes:
            return "Aucun résultat. " + _indice_vide(requete)
        return json.dumps(lignes, ensure_ascii=False, default=str)
    except Exception as exc:  # noqa: BLE001
        return f"Erreur Cypher : {exc}"


_FILTRE_TITRE = re.compile(r"""\{\s*(\w+)\s*:\s*["']([^"']+)["']\s*\}""")


def _indice_vide(requete: str) -> str:
    """Quand une requête ne renvoie rien, dit si les valeurs filtrées existent sous `titre`."""
    filtres = _FILTRE_TITRE.findall(requete)
    if not filtres:
        return "Vérifie que les nœuds existent : MATCH (n:Noeud) WHERE toLower(n.titre) CONTAINS \"...\" RETURN n.titre, labels(n)."
    indices = []
    with driver().session() as session:
        for prop, valeur in filtres:
            if prop != "titre":
                indices.append(f"le filtre {{{prop}: \"{valeur}\"}} n'utilise pas la propriété `titre`")
            proches = [
                r["t"] for r in session.run(
                    "MATCH (n:Noeud) WHERE toLower(n.titre) CONTAINS toLower($v) RETURN n.titre AS t LIMIT 5",
                    v=valeur,
                )
            ]
            if proches:
                indices.append(f"des nœuds dont le titre contient \"{valeur}\" existent : {proches}")
            else:
                indices.append(f"aucun nœud dont le titre contient \"{valeur}\"")
    return "Indices : " + " ; ".join(indices) + "."


def _aplatir_chemin(path):
    items = []
    noeuds = list(path.nodes)
    rels = list(path.relationships)
    for i, noeud in enumerate(noeuds):
        items.append(noeud)
        if i < len(rels):
            items.append(rels[i])
    return items


def _charger_faiss():
    global _faiss
    if _faiss is None:
        import faiss
        from langchain_mistralai import MistralAIEmbeddings

        if not config.INDEX_FAISS.exists() or not config.INDEX_META.exists():
            raise FileNotFoundError("Index FAISS absent. Lance `python kg/sync.py` avec MISTRAL_API_KEY renseignée.")
        index = faiss.read_index(str(config.INDEX_FAISS))
        meta = json.loads(config.INDEX_META.read_text(encoding="utf-8"))
        embeddings = MistralAIEmbeddings(model=config.MISTRAL_EMBED_MODEL, api_key=config.MISTRAL_API_KEY)
        _faiss = (index, meta, embeddings)
    return _faiss


@tool
def recherche(texte: str, k: int = 5) -> str:
    """Recherche sémantique dans les notes du lore (FAISS). Utile quand on ne connaît pas
    le nom exact d'une entité ou qu'on cherche un thème (ex: "armure qui ne guérit pas").
    Retourne les k notes les plus proches avec leur titre, type, statut et chemin."""
    try:
        import numpy as np

        index, meta, embeddings = _charger_faiss()
        vecteur = np.asarray([embeddings.embed_query(texte)], dtype="float32")
        import faiss

        faiss.normalize_L2(vecteur)
        scores, indices = index.search(vecteur, min(k, index.ntotal))
        resultats = []
        for score, i in zip(scores[0], indices[0]):
            if i < 0:
                continue
            m = meta[i]
            resultats.append({"score": round(float(score), 3), **m})
        return json.dumps(resultats, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return f"Erreur recherche : {exc}"


@tool
def lire_note(titre_ou_id: str) -> str:
    """Lit le contenu complet d'une note Obsidian par son titre (ex: "Garde")
    ou son id (ex: "org-garde"). Sert à citer précisément une fiche."""
    note = trouver_note(titre_ou_id)
    if note is None:
        return f"Aucune note nommée {titre_ou_id!r}."
    meta = json.dumps(note.meta, ensure_ascii=False, default=str)
    return f"# {note.titre}\nchemin : {note.relatif}\nfrontmatter : {meta}\n\n{note.corps}"


OUTILS = [cypher, recherche, lire_note]
