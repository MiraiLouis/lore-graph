"""Agent LangGraph (Mistral) qui interroge Neo4j, FAISS et le coffre Obsidian.

Usage :
  python kg/agent.py                       # boucle de chat
  python kg/agent.py "Qui sont les membres de la Garde ?"
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_mistralai import ChatMistralAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from kg import config
from kg.outils import OUTILS, schema

CONSIGNE = """Tu es l'assistant de lore d'un univers de fiction décrit dans un coffre Obsidian.
Tu réponds en français, uniquement à partir de ce que renvoient tes outils.

Règles :
- Commence par `cypher` pour les questions de relations (qui appartient à quoi, qui utilise quoi, chaîne hiérarchique).
  Utilise `recherche` quand tu ne connais pas le nom exact ou pour une question thématique.
  Utilise `lire_note` pour citer une fiche précise.
- Pour trouver un nœud par son nom, filtre TOUJOURS sur la propriété `titre` (ex: {{titre: "Garde"}}),
  jamais sur `designation`, `nom` ou un autre champ. `titre` est le nom de la note Obsidian.
  En cas de doute sur l'orthographe : MATCH (n:Noeud) WHERE toLower(n.titre) CONTAINS "garde" RETURN n.titre, labels(n).
- Un nom de groupe (« les membres de X ») désigne en général une Organisation : cherche ses membres
  par (p:Personnage)-[:MEMBRE_DE]->(:Organisation {{titre: "X"}}) plutôt qu'en filtrant sur un mot du titre.
- Avant de conclure qu'une relation n'existe pas, vérifie que chaque nœud mentionné existe
  (MATCH (n:Noeud) WHERE toLower(n.titre) CONTAINS "...") et liste ses relations directes
  (MATCH (n)-[r]-(m) RETURN type(r), m.titre). Une requête vide à cause d'un mauvais filtre n'est pas une absence.
- Ne devine jamais une relation absente du graphe. Si, après ces vérifications, aucun chemin ni aucune note ne répond, écris exactement :
  « Information insuffisante. » puis dis ce qui manque.
- Cite les notes utilisées (titre entre [[ ]]) à la fin de ta réponse.
- Respecte les statuts : CANON (établi), À CONFIRMER (hypothèse), À DÉFINIR (incomplet), ABANDONNÉ (ne plus utiliser comme canon).
  Mentionne le statut quand il n'est pas CANON.
- La relation DANS_PAYS relie souvent presque tout au même pays : ne l'utilise pas comme lien entre deux institutions.
- Ne propose pas d'idées nouvelles sauf si on te le demande ; dans ce cas, marque-les comme propositions.
{consignes_univers}
Schéma Neo4j actuel :
{schema}
"""


def consignes_univers() -> str:
    """Règles propres à l'univers, lues dans `_consignes.md` à la racine du coffre si le fichier existe."""
    chemin = config.VAULT_PATH / "_consignes.md"
    if not chemin.exists():
        return ""
    return "\nConsignes propres à cet univers :\n" + chemin.read_text(encoding="utf-8").strip() + "\n"


class Etat(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def construire_agent():
    """Boucle ReAct explicite : modèle -> outils -> modèle, jusqu'à une réponse sans appel d'outil."""
    config.exiger_cle_mistral()
    llm = ChatMistralAI(model=config.MISTRAL_CHAT_MODEL, api_key=config.MISTRAL_API_KEY, temperature=0)
    llm_outils = llm.bind_tools(OUTILS)
    systeme = SystemMessage(content=CONSIGNE.format(schema=schema(), consignes_univers=consignes_univers()))

    def appeler_modele(etat: Etat) -> dict:
        # L'API Mistral renvoie parfois finish_reason=error avec un contenu vide : on réessaie.
        for tentative in range(3):
            reponse = llm_outils.invoke([systeme, *etat["messages"]])
            if reponse.response_metadata.get("finish_reason") != "error":
                return {"messages": [reponse]}
            time.sleep(1.5 * (tentative + 1))
        reponse.content = "Information insuffisante. L'API Mistral a renvoyé une erreur trois fois de suite ; réessaie."
        return {"messages": [reponse]}

    def suite(etat: Etat) -> str:
        dernier = etat["messages"][-1]
        return "outils" if getattr(dernier, "tool_calls", None) else END

    graphe = StateGraph(Etat)
    graphe.add_node("modele", appeler_modele)
    graphe.add_node("outils", ToolNode(OUTILS))
    graphe.add_edge(START, "modele")
    graphe.add_conditional_edges("modele", suite, {"outils": "outils", END: END})
    graphe.add_edge("outils", "modele")
    return graphe.compile()


def repondre(agent, question: str, historique: list | None = None) -> tuple[str, list]:
    messages = list(historique or []) + [HumanMessage(content=question)]
    etat = agent.invoke({"messages": messages}, config={"recursion_limit": 40})
    reponse = etat["messages"][-1].content
    if isinstance(reponse, list):
        reponse = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in reponse)
    return reponse, etat["messages"]


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass
    argv = sys.argv[1:] if argv is None else argv
    agent = construire_agent()
    if argv:
        reponse, _ = repondre(agent, " ".join(argv))
        print(reponse)
        return 0
    print("Agent de lore. Tape une question, ou `q` pour quitter.")
    historique: list = []
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("q", "quit", "exit"):
            break
        reponse, historique = repondre(agent, question, historique)
        print(f"\n{reponse}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
