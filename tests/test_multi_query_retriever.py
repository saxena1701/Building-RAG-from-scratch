from rag_core.multi_query_retriever import multi_query_retrieve


def _stub_retriever(results_by_query: dict[str, list[dict]]) -> callable:
    def _retriever(query: str, db_url: str, top_k: int = 5) -> dict:
        return {"results": results_by_query.get(query, [])}

    return _retriever


def test_dedup_keeps_max_normalized_score():
    base_retriever = _stub_retriever(
        {
            "q1": [
                {"chunk_id": "a", "source": "s", "text": "t", "score": 1.0},
                {"chunk_id": "b", "source": "s", "text": "t", "score": 0.0},
            ],
            "q2": [
                {"chunk_id": "a", "source": "s", "text": "t", "score": 0.0},
                {"chunk_id": "b", "source": "s", "text": "t", "score": 1.0},
            ],
        }
    )
    out = multi_query_retrieve(["q1", "q2"], db_url="", base_retriever=base_retriever)
    scores = {r["chunk_id"]: r["score"] for r in out["results"]}
    # a: max(1.0, 0.0)=1.0 ; b: max(0.0, 1.0)=1.0
    assert scores["a"] == 1.0
    assert scores["b"] == 1.0


def test_queries_provenance_lists_every_surfacing_query():
    base_retriever = _stub_retriever(
        {
            "q1": [{"chunk_id": "a", "source": "s", "text": "t", "score": 1.0}],
            "q2": [{"chunk_id": "a", "source": "s", "text": "t", "score": 0.5}],
        }
    )
    out = multi_query_retrieve(["q1", "q2"], db_url="", base_retriever=base_retriever)
    assert out["results"][0]["queries"] == ["q1", "q2"]


def test_single_element_score_list_normalizes_to_one():
    base_retriever = _stub_retriever(
        {"q1": [{"chunk_id": "a", "source": "s", "text": "t", "score": -3.7}]}
    )
    out = multi_query_retrieve(["q1"], db_url="", base_retriever=base_retriever)
    assert out["results"][0]["score"] == 1.0


def test_all_equal_scores_normalize_to_one_without_crashing():
    base_retriever = _stub_retriever(
        {
            "q1": [
                {"chunk_id": "a", "source": "s", "text": "t", "score": 2.0},
                {"chunk_id": "b", "source": "s", "text": "t", "score": 2.0},
            ]
        }
    )
    out = multi_query_retrieve(["q1"], db_url="", base_retriever=base_retriever)
    assert all(r["score"] == 1.0 for r in out["results"])


def test_final_k_truncates():
    base_retriever = _stub_retriever(
        {
            "q1": [
                {"chunk_id": "a", "source": "s", "text": "t", "score": 1.0},
                {"chunk_id": "b", "source": "s", "text": "t", "score": 0.5},
                {"chunk_id": "c", "source": "s", "text": "t", "score": 0.0},
            ]
        }
    )
    out = multi_query_retrieve(["q1"], db_url="", base_retriever=base_retriever, final_k=2)
    assert len(out["results"]) == 2
    assert [r["chunk_id"] for r in out["results"]] == ["a", "b"]


def test_dedup_and_empty_queries_are_dropped():
    calls: list[str] = []

    def _retriever(query: str, db_url: str, top_k: int = 5) -> dict:
        calls.append(query)
        return {"results": []}

    multi_query_retrieve(["q1", "q1", "  ", "", "q2"], db_url="", base_retriever=_retriever)
    assert calls == ["q1", "q2"]
