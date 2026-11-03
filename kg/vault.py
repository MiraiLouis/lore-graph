"""Lecture du coffre Obsidian : notes, frontmatter, wikilinks."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from kg.config import RELATIONS, VAULT_PATH

_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


@dataclass
class Note:
    chemin: Path
    titre: str
    id: str
    type: str
    statut: str
    meta: dict
    corps: str
    liens: dict[str, list[str]] = field(default_factory=dict)  # champ -> titres cibles

    @property
    def relatif(self) -> str:
        return self.chemin.relative_to(VAULT_PATH).as_posix()


def extraire_wikilinks(valeur) -> list[str]:
    if isinstance(valeur, str):
        return [m.strip() for m in _WIKILINK.findall(valeur)]
    if isinstance(valeur, list):
        out = []
        for item in valeur:
            out.extend(extraire_wikilinks(item))
        return out
    return []


def lire_coffre(racine: Path | None = None) -> list[Note]:
    racine = racine or VAULT_PATH
    notes = []
    for chemin in sorted(racine.rglob("*.md")):
        if ".obsidian" in chemin.parts or ".trash" in chemin.parts:
            continue
        post = frontmatter.load(chemin, encoding="utf-8")
        meta = dict(post.metadata)
        if "id" not in meta or "type" not in meta:
            continue
        liens = {}
        for champ in RELATIONS:
            if champ in meta:
                cibles = extraire_wikilinks(meta[champ])
                if cibles:
                    liens[champ] = cibles
        notes.append(
            Note(
                chemin=chemin,
                titre=chemin.stem,
                id=str(meta["id"]),
                type=str(meta["type"]),
                statut=str(meta.get("statut") or ""),
                meta=meta,
                corps=post.content.strip(),
                liens=liens,
            )
        )
    return notes


def trouver_note(titre_ou_id: str, racine: Path | None = None) -> Note | None:
    cle = titre_ou_id.strip().casefold()
    for note in lire_coffre(racine):
        if note.id.casefold() == cle or note.titre.casefold() == cle:
            return note
    return None
