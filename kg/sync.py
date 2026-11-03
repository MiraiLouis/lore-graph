"""Synchronise le coffre Obsidian vers Neo4j et FAISS.

Usage :
  python kg/sync.py            # Neo4j + FAISS (FAISS exige MISTRAL_API_KEY)
  python kg/sync.py --sans-faiss
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from neo4j import GraphDatabase

from kg import config
from kg.vault import Note, lire_coffre


def _console_utf8() -> None:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass


def _label(note: Note) -> str:
    return config.TYPES.get(note.type, (None, note.type))[1]


def _proprietes(note: Note) -> dict:
    props = {
        "id": note.id,
        "titre": note.titre,
        "type": note.type,
        "statut": note.statut,
        "chemin": note.relatif,
    }
    for cle, valeur in note.meta.items():
        if cle in ("id", "type", "statut") or cle in config.RELATIONS:
            continue
        if isinstance(valeur, (str, int, float, bool)):
            props[cle] = valeur
        elif isinstance(valeur, list) and all(isinstance(v, (str, int, float, bool)) for v in valeur):
            props[cle] = valeur
    return props


def synchroniser_neo4j(notes: list[Note]) -> tuple[int, int, list[str]]:
    par_titre = {note.titre.casefold(): note for note in notes}
    casses: list[str] = []
    relations: list[tuple[str, str, str, str]] = []
    for note in notes:
        for champ, cibles in note.liens.items():
            for cible in cibles:
                cible_note = par_titre.get(cible.casefold())
                if cible_note is None:
                    casses.append(f"{note.relatif} : {champ} -> [[{cible}]]")
                    continue
                relations.append((note.id, config.RELATIONS[champ], cible_note.id, champ))

    driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    with driver:
        driver.verify_connectivity()
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            session.run("CREATE CONSTRAINT noeud_id IF NOT EXISTS FOR (n:Noeud) REQUIRE n.id IS UNIQUE")
            for note in notes:
                label = _label(note)
                session.run(
                    f"MERGE (n:Noeud {{id: $id}}) SET n:`{label}`, n += $props",
                    id=note.id,
                    props=_proprietes(note),
                )
            for source, rel, cible, champ in relations:
                session.run(
                    f"MATCH (a:Noeud {{id: $a}}), (b:Noeud {{id: $b}}) "
                    f"MERGE (a)-[r:`{rel}`]->(b) SET r.champ = $champ",
                    a=source,
                    b=cible,
                    champ=champ,
                )
            n_noeuds = session.run("MATCH (n:Noeud) RETURN count(n) AS c").single()["c"]
            n_rel = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    return n_noeuds, n_rel, casses


def texte_pour_embedding(note: Note) -> str:
    entete = [f"{note.titre} ({note.type}, {note.statut})"]
    for cle in ("nom", "designation", "categorie", "statut_operationnel", "realisme", "titre_ordre", "regime", "position", "niveau", "classement"):
        valeur = note.meta.get(cle)
        if valeur:
            entete.append(f"{cle} : {valeur}")
    return "\n".join(entete) + "\n\n" + note.corps


def construire_faiss(notes: list[Note]) -> int:
    import faiss
    from langchain_mistralai import MistralAIEmbeddings

    config.exiger_cle_mistral()
    embeddings = MistralAIEmbeddings(model=config.MISTRAL_EMBED_MODEL, api_key=config.MISTRAL_API_KEY)
    textes = [texte_pour_embedding(note) for note in notes]
    vecteurs: list[list[float]] = []
    lot = 32
    for debut in range(0, len(textes), lot):
        vecteurs.extend(embeddings.embed_documents(textes[debut:debut + lot]))
    matrice = np.asarray(vecteurs, dtype="float32")
    faiss.normalize_L2(matrice)
    index = faiss.IndexFlatIP(matrice.shape[1])
    index.add(matrice)
    faiss.write_index(index, str(config.INDEX_FAISS))
    meta = [
        {"id": note.id, "titre": note.titre, "type": note.type, "statut": note.statut, "chemin": note.relatif}
        for note in notes
    ]
    config.INDEX_META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return index.ntotal


def main(argv: list[str] | None = None) -> int:
    _console_utf8()
    parser = argparse.ArgumentParser(description="Coffre Obsidian -> Neo4j + FAISS")
    parser.add_argument("--sans-faiss", action="store_true", help="Ne pas reconstruire l'index FAISS")
    args = parser.parse_args(argv)

    notes = lire_coffre()
    print(f"Notes lues : {len(notes)} depuis {config.VAULT_PATH}")
    doublons = {}
    for note in notes:
        doublons.setdefault(note.id, []).append(note.relatif)
    for id_, chemins in doublons.items():
        if len(chemins) > 1:
            print(f"  id en double {id_} : {', '.join(chemins)}")

    n_noeuds, n_rel, casses = synchroniser_neo4j(notes)
    print(f"Neo4j : {n_noeuds} nœuds, {n_rel} relations")
    print(f"Wikilinks cassés : {len(casses)}")
    for ligne in casses:
        print(f"  {ligne}")

    if args.sans_faiss:
        print("FAISS : ignoré (--sans-faiss)")
        return 0
    if not config.MISTRAL_API_KEY:
        print("FAISS : ignoré, MISTRAL_API_KEY est vide dans .env")
        return 0
    total = construire_faiss(notes)
    print(f"FAISS : {total} vecteurs -> {config.INDEX_FAISS.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
