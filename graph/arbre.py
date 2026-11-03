"""Ouvre une fenêtre avec l'arbre des pays, départements et organisations, lu depuis le coffre Obsidian."""

import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kg.config import VAULT_PATH  # noqa: E402
from kg.vault import lire_coffre  # noqa: E402

TYPES = ("Pays", "Departement", "Organisation", "Programme", "Personnage")
CHAMPS = ("parent", "organisation", "departement", "pays")
_SECTION_NOTE = re.compile(r"^## Note\s*\n(.*?)(?=^## |\Z)", re.S | re.M)

LEVELS = {
    "pouvoir": "Pouvoir",
    "departement": "Département",
    "sous-departement": "Sous-département",
    "Pays": "Pays",
    "Organisation": "Organisation",
    "Programme": "Programme",
    "Personnage": "Personnage",
}


def label(node: dict) -> str:
    text = node["titre"]
    if node.get("repertorie") is False:
        text += " (non répertorié)"
    return text


def kind(node: dict) -> str:
    return LEVELS.get(node.get("niveau") or node.get("type"), node.get("type") or "")


def load() -> list[dict]:
    notes = [n for n in lire_coffre() if n.type in TYPES]
    par_titre = {n.titre.casefold(): n.id for n in notes}
    nodes = []
    for n in notes:
        node = {**n.meta, "id": n.id, "type": n.type, "titre": n.titre}
        for champ in CHAMPS:
            cibles = n.liens.get(champ) or []
            node[champ] = par_titre.get(cibles[0].casefold()) if cibles else None
        section = _SECTION_NOTE.search(n.corps)
        node["note"] = section.group(1).strip() if section else ""
        nodes.append(node)
    return nodes


def display_parent(node: dict, ids: set[str]) -> str | None:
    if node.get("type") == "Personnage" and node.get("departement"):
        return node["departement"]
    parent = node.get("parent") or node.get("organisation")
    if parent:
        return parent
    pays = node.get("pays")
    if pays and pays in ids and node.get("type") != "Pays":
        return pays
    return None


def relevant(node: dict) -> bool:
    if node.get("type") == "Personnage":
        return bool(node.get("organisation") or node.get("parent") or node.get("departement"))
    return True


def children_of(nodes: list[dict], ids: set[str]) -> dict[str | None, list[dict]]:
    grouped: dict[str | None, list[dict]] = {}
    for node in nodes:
        if not relevant(node):
            continue
        parent = display_parent(node, ids)
        if parent not in ids:
            parent = None
        grouped.setdefault(parent, []).append(node)
    return grouped


def main() -> None:
    nodes = load()
    ids = {node["id"] for node in nodes}
    grouped = children_of(nodes, ids)
    notes: dict[str, str] = {}

    window = tk.Tk()
    window.title(f"Arbre — {VAULT_PATH.name}")
    window.geometry("780x860")
    window.minsize(520, 400)

    frame = ttk.Frame(window, padding=8)
    frame.pack(fill="both", expand=True)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    tree = ttk.Treeview(frame, columns=("kind",), show="tree headings", selectmode="browse")
    tree.heading("#0", text="Nom", anchor="w")
    tree.heading("kind", text="Niveau", anchor="w")
    tree.column("#0", width=520, stretch=True)
    tree.column("kind", width=150, stretch=False)
    tree.grid(row=0, column=0, sticky="nsew")

    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    tree.configure(yscrollcommand=scroll.set)

    detail = tk.StringVar(value="Sélectionne une ligne pour lire sa note.")
    ttk.Label(frame, textvariable=detail, wraplength=720, justify="left").grid(
        row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0)
    )

    def insert(parent_iid: str, node: dict) -> None:
        iid = tree.insert(parent_iid, "end", text=label(node), values=(kind(node),), open=True)
        notes[iid] = node.get("note") or ""
        for child in grouped.get(node["id"], []):
            insert(iid, child)

    for root_node in grouped.get(None, []):
        insert("", root_node)

    def show_note(_event: object = None) -> None:
        selected = tree.focus()
        detail.set(notes.get(selected) or "Pas de note.")

    tree.bind("<<TreeviewSelect>>", show_note)
    window.mainloop()


if __name__ == "__main__":
    main()
