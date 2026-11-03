"""Chargement de .env et chemins du projet."""

import os
from pathlib import Path

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()
MISTRAL_CHAT_MODEL = os.getenv("MISTRAL_CHAT_MODEL", "mistral-medium-latest")
MISTRAL_EMBED_MODEL = os.getenv("MISTRAL_EMBED_MODEL", "mistral-embed")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme")
VAULT_PATH = (RACINE / os.getenv("VAULT_PATH", "Obsidian/Demo")).resolve()
INDEX_FAISS = Path(__file__).resolve().parent / "index.faiss"
INDEX_META = Path(__file__).resolve().parent / "index.json"

# Champ de frontmatter -> type de relation Neo4j.
RELATIONS = {
    "technologie": "UTILISE",
    "organisation": "MEMBRE_DE",
    "departement": "RATTACHE_A",
    "parent": "DEPEND_DE",
    "pays": "DANS_PAYS",
    "programme": "RATTACHE_AU_PROGRAMME",
    "general": "LIE_AU_GENERAL",
    "commandement": "COMMANDE_PAR",
    "veto": "SOUS_VETO_DE",
    "membres": "COMPOSE_DE",
}

# Type de note -> dossier du coffre et label Neo4j.
TYPES = {
    "Personnage": ("Personnages", "Personnage"),
    "Technologie": ("Technologies", "Technologie"),
    "Organisation": ("Organisations", "Organisation"),
    "Programme": ("Organisations", "Programme"),
    "Departement": ("Departements", "Departement"),
    "Pays": ("Pays", "Pays"),
    "Regle": ("Regles", "Regle"),
}


def exiger_cle_mistral() -> str:
    if not MISTRAL_API_KEY:
        raise SystemExit(
            "MISTRAL_API_KEY est vide dans .env. Colle ta clé (console.mistral.ai) puis relance."
        )
    return MISTRAL_API_KEY
