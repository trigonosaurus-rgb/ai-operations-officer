"""Per-turn state shared by the tools of a single agent run."""

from dataclasses import dataclass, field

from llama_index.core.schema import NodeWithScore

from app.agent.events import Citation

SNIPPET_CHARS = 900


@dataclass
class TurnRecorder:
    """Numbers document passages across all searches in one answer.

    If the agent searches twice, the second search continues at [4], [5]…, and a
    passage seen twice keeps its first number — so inline [n] references in the
    final answer map unambiguously to one citation.
    """

    citations: list[Citation] = field(default_factory=list)
    _by_node: dict[str, Citation] = field(default_factory=dict)

    def cite(self, hit: NodeWithScore) -> Citation:
        node_id = hit.node.node_id
        if node_id in self._by_node:
            return self._by_node[node_id]
        meta = hit.node.metadata
        citation = Citation(
            n=len(self.citations) + 1,
            slug=meta["slug"],
            doc_id=meta["doc_id"],
            title=meta["title"],
            page=meta["page"],
            snippet=hit.node.get_content()[:SNIPPET_CHARS].strip(),
            score=round(hit.score, 4) if hit.score is not None else None,
        )
        self.citations.append(citation)
        self._by_node[node_id] = citation
        return citation
