from __future__ import annotations

from contextlib import contextmanager
import math
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app import main, retrieval


class Result:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class SemanticConnection:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "FROM chunks c JOIN documents" in sql:
            return Result(rows=[{
                "chunk_id": 7,
                "document_id": 20,
                "plan_id": 10,
                "plan_name": "Example plan",
                "original_filename": "plan.pdf",
                "chunk_text": "Deductible is $500",
                "page_start": 2,
                "page_end": 2,
                "provenance": {"units": [{"section": "Deductible"}]},
            }])
        if "FROM chunk_embeddings ce" in sql:
            return Result(rows=[{
                "chunk_id": 7,
                "embedding_values": self.vectors,
                "model_fingerprint": "fingerprint",
            }])
        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeArray(list):
    @property
    def ndim(self):
        return 2

    @property
    def shape(self):
        if not self:
            return (0, 0)
        widths = {len(row) for row in self}
        if len(widths) != 1:
            raise ValueError("ragged array")
        return len(self), widths.pop()

    def __le__(self, other):
        return [value <= other for value in self]


def install_fake_semantic_dependencies(monkeypatch):
    class Model:
        def get_sentence_embedding_dimension(self):
            return 2

        def encode(self, _texts, **_kwargs):
            return [[1.0, 0.0]]

    load_model = lambda: Model()
    load_model.cache_info = lambda: SimpleNamespace(currsize=1)
    monkeypatch.setattr(retrieval, "_load_model", load_model)
    monkeypatch.setattr(retrieval, "_model", load_model)
    monkeypatch.setattr(retrieval, "model_fingerprint", lambda: "fingerprint")

    numpy = ModuleType("numpy")
    numpy.asarray = lambda values, dtype=None: FakeArray(values)
    def finite(array):
        values = [value for item in array for value in (item if isinstance(item, list) else [item])]
        return SimpleNamespace(all=lambda: all(math.isfinite(value) for value in values))
    numpy.isfinite = finite
    numpy.any = lambda values: any(values)
    numpy.linalg = SimpleNamespace(norm=lambda array, axis: FakeArray([
        math.sqrt(sum(value * value for value in row)) for row in array
    ]))
    monkeypatch.setitem(sys.modules, "numpy", numpy)

    class Index:
        def __init__(self, _dimension):
            self.count = 0

        def add(self, array):
            self.count = len(array)

        def search(self, _query, _count):
            return [[0.9]], [[0]]

    faiss = ModuleType("faiss")
    faiss.normalize_L2 = lambda _matrix: None
    faiss.IndexFlatIP = Index
    monkeypatch.setitem(sys.modules, "faiss", faiss)


def test_semantic_embedding_query_applies_the_same_filters_as_chunks(monkeypatch):
    install_fake_semantic_dependencies(monkeypatch)
    connection = SemanticConnection([0.8, 0.6])

    result = retrieval.retrieve(
        connection,
        "What is the deductible?",
        "semantic",
        "section_aware",
        top_k=3,
        strategy_version=1,
        plan_id=10,
        document_id=20,
        section="Deductible",
    )

    embedding_sql, params = connection.calls[1]
    chunk_sql, chunk_params = connection.calls[0]
    assert "d.plan_id = %s" in chunk_sql
    assert "d.corpus_status <> 'ineligible'" in chunk_sql
    assert "d.document_id = %s" in chunk_sql
    assert "c.provenance::text ILIKE %s" in chunk_sql
    assert chunk_params[-3:] == (10, 20, "%Deductible%")
    assert "d.plan_id = %s" in embedding_sql
    assert "d.corpus_status <> 'ineligible'" in embedding_sql
    assert "d.document_id = %s" in embedding_sql
    assert "c.provenance::text ILIKE %s" in embedding_sql
    assert params[-3:] == (10, 20, "%Deductible%")
    assert [row["chunk_id"] for row in result["results"]] == [7]


@pytest.mark.parametrize("vectors", [[0.2], [float("nan"), 0.3], [0.0, 0.0]])
def test_semantic_rejects_malformed_or_zero_embeddings(monkeypatch, vectors):
    install_fake_semantic_dependencies(monkeypatch)
    connection = SemanticConnection(vectors)

    with pytest.raises(retrieval.EmbeddingDataError):
        retrieval.retrieve(connection, "question", "semantic", "fixed_size")


def test_bm25_retrieval_does_not_read_embedding_rows(monkeypatch):
    class BM25:
        def __init__(self, _tokens):
            pass

        def get_scores(self, _tokens):
            return [1.0]

    bm25_module = ModuleType("rank_bm25")
    bm25_module.BM25Okapi = BM25
    monkeypatch.setitem(sys.modules, "rank_bm25", bm25_module)

    class Connection:
        def execute(self, sql, _params=()):
            assert "FROM chunk_embeddings" not in sql
            return Result(rows=[{
                "chunk_id": 1, "document_id": 2, "plan_id": 3,
                "plan_name": "Plan", "original_filename": "plan.pdf",
                "chunk_text": "Deductible is $500", "page_start": 1,
                "page_end": 1, "provenance": {},
            }])

    result = retrieval.retrieve(Connection(), "deductible", "bm25", "fixed_size")

    assert result["results"][0]["chunk_id"] == 1
    assert result["timings"]["index_build_ms"] >= 0
    assert result["timings"]["search_ms"] >= 0


def test_bm25_only_evaluation_skips_semantic_model_and_records_snapshot(monkeypatch, tmp_path):
    manifest_directory = tmp_path / "evaluation"
    manifest_directory.mkdir()
    (manifest_directory / "questions.json").write_text(
        '{"manifest_version":"test-v1","corpus":"fixture","questions":['
        '{"question_id":"q1","question":"Question?","question_type":"lookup",'
        '"expected_answer":"Answer","expected_document_ids":[5],"expected_pages":[2]}]}'
    )

    class FakePath:
        def __init__(self, _value):
            pass

        def resolve(self):
            return SimpleNamespace(parents=(None, None, tmp_path))

    monkeypatch.setattr(main, "Path", FakePath)
    monkeypatch.setattr(main, "model_fingerprint", lambda: pytest.fail("BM25 should not load the semantic model"))
    monkeypatch.setattr(main, "run_retrieval", lambda _connection, request: {
        "results": [{"document_id": 5, "page_start": 2, "page_end": 2,
                     "rank": 1, "chunk_id": 11}],
        "timings": {"total_request_ms": 4.0, "corpus_load_ms": 1.0,
                    "index_build_ms": 2.0, "search_ms": 1.0},
    })

    class Connection:
        def __init__(self):
            self.queries = []

        @contextmanager
        def transaction(self):
            yield

        def execute(self, sql, _params=()):
            self.queries.append(sql)
            if "string_agg" in sql:
                return Result(rows=[{"chunk_strategy": "fixed_size", "strategy_version": 1,
                                     "chunk_count": 2, "chunk_digests": "1:abc,2:def"},
                                    {"chunk_strategy": "section_aware", "strategy_version": 1,
                                     "chunk_count": 2, "chunk_digests": "3:ghi,4:jkl"}])
            if "GROUP BY c.chunk_strategy" in sql and "embedding_count" not in sql:
                return Result(rows=[{"chunk_strategy": "fixed_size", "chunk_count": 2},
                                    {"chunk_strategy": "section_aware", "chunk_count": 2}])
            if "SELECT document_id, document_sha256" in sql:
                return Result(rows=[{"document_id": 5, "document_sha256": "a" * 64,
                                     "reviewed_at": None}])
            if "INSERT INTO evaluation_runs" in sql:
                assert sql.count("%s") == len(_params)
                assert "manifest_sha256" in sql
                assert "embedding_model_fingerprint" in sql
                assert "corpus_snapshot" in sql
                assert "chunk_strategy_version" in sql
                return Result(row={"run_id": 22})
            if "INSERT INTO evaluation_results" in sql:
                assert sql.count("%s") == len(_params)
                assert "query_embedding_ms" in sql
                assert "search_ms" in sql
                return Result()
            raise AssertionError(f"Unexpected SQL: {sql}")

    connection = Connection()
    response = main.run_evaluation({}, connection, method="bm25")

    assert len(response["results"]) == 2
    assert all(row["method"] == "bm25" for row in response["results"])
    assert all("INSERT INTO evaluation_runs" in query or "INSERT INTO evaluation_results" in query
               for query in connection.queries if query.startswith("INSERT"))


@pytest.mark.parametrize("method,expected_methods", [
    ("semantic", {"semantic"}),
    ("hybrid", {"hybrid"}),
    ("all", {"bm25", "semantic", "hybrid"}),
])
def test_semantic_and_all_evaluation_run_expected_configurations(
        monkeypatch, tmp_path, method, expected_methods):
    manifest_directory = tmp_path / "evaluation"
    manifest_directory.mkdir()
    (manifest_directory / "questions.json").write_text(
        '{"manifest_version":"test-v1","corpus":"fixture","questions":['
        '{"question_id":"q1","question":"Question?","question_type":"lookup",'
        '"expected_answer":"Answer","expected_document_ids":[5],"expected_pages":[2]}]}'
    )

    class FakePath:
        def __init__(self, _value):
            pass

        def resolve(self):
            return SimpleNamespace(parents=(None, None, tmp_path))

    monkeypatch.setattr(main, "Path", FakePath)
    monkeypatch.setattr(main, "model_fingerprint", lambda: "model-digest")
    calls = []

    def fake_retrieval(_connection, request):
        calls.append((request.method, request.chunk_strategy))
        return {
            "results": [{"document_id": 5, "page_start": 2, "page_end": 2,
                         "rank": 1, "chunk_id": 11}],
            "timings": {"total_request_ms": 4.0, "corpus_load_ms": 1.0,
                        "embedding_load_ms": 0.5 if request.method == "semantic" else 0.0,
                        "index_build_ms": 1.0, "query_embedding_ms": 1.0 if request.method == "semantic" else 0.0,
                        "model_load_ms": 0.0, "search_ms": 1.0},
        }

    monkeypatch.setattr(main, "run_retrieval", fake_retrieval)

    class Connection:
        def __init__(self):
            self.queries = []

        @contextmanager
        def transaction(self):
            yield

        def execute(self, sql, params=()):
            self.queries.append((sql, params))
            if "string_agg" in sql:
                return Result(rows=[{"chunk_strategy": "fixed_size", "strategy_version": 1,
                                     "chunk_count": 2, "chunk_digests": "1:abc,2:def"},
                                    {"chunk_strategy": "section_aware", "strategy_version": 1,
                                     "chunk_count": 2, "chunk_digests": "3:ghi,4:jkl"}])
            if "GROUP BY c.chunk_strategy" in sql and "embedding_count" not in sql:
                return Result(rows=[{"chunk_strategy": "fixed_size", "chunk_count": 2},
                                    {"chunk_strategy": "section_aware", "chunk_count": 2}])
            if "embedding_count" in sql:
                return Result(rows=[{"chunk_strategy": "fixed_size", "embedding_count": 2},
                                    {"chunk_strategy": "section_aware", "embedding_count": 2}])
            if "SELECT document_id, document_sha256" in sql:
                return Result(rows=[{"document_id": 5, "document_sha256": "a" * 64,
                                     "reviewed_at": None}])
            if "INSERT INTO evaluation_runs" in sql:
                assert sql.count("%s") == len(params)
                return Result(row={"run_id": len([q for q, _ in self.queries if q.startswith("INSERT INTO evaluation_runs")])})
            if "INSERT INTO evaluation_results" in sql:
                assert sql.count("%s") == len(params)
                return Result()
            raise AssertionError(f"Unexpected SQL: {sql}")

    response = main.run_evaluation({}, Connection(), method=method)

    assert {row["method"] for row in response["results"]} == expected_methods
    assert len(response["results"]) == len(expected_methods) * 2
    assert set(calls) == {
        (retrieval_method, strategy)
        for retrieval_method in expected_methods
        for strategy in ("fixed_size", "section_aware")
    }
    assert all(row["hit_rate"] == 1.0 and row["mean_reciprocal_rank"] == 1.0
               for row in response["results"])


def test_semantic_evaluation_rejects_incomplete_embeddings(monkeypatch, tmp_path):
    manifest_directory = tmp_path / "evaluation"
    manifest_directory.mkdir()
    (manifest_directory / "questions.json").write_text(
        '{"manifest_version":"test-v1","questions":['
        '{"question_id":"q1","question":"Question?","question_type":"lookup",'
        '"expected_answer":"Answer","expected_document_ids":[5]}]}'
    )

    class FakePath:
        def __init__(self, _value):
            pass

        def resolve(self):
            return SimpleNamespace(parents=(None, None, tmp_path))

    class Connection:
        def execute(self, sql, _params=()):
            if "GROUP BY c.chunk_strategy" in sql and "embedding_count" not in sql:
                return Result(rows=[{"chunk_strategy": "fixed_size", "chunk_count": 2},
                                    {"chunk_strategy": "section_aware", "chunk_count": 2}])
            if "embedding_count" in sql:
                return Result(rows=[{"chunk_strategy": "fixed_size", "embedding_count": 1},
                                    {"chunk_strategy": "section_aware", "embedding_count": 2}])
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.setattr(main, "Path", FakePath)
    monkeypatch.setattr(main, "model_fingerprint", lambda: "model-digest")

    with pytest.raises(main.HTTPException) as error:
        main.run_evaluation({}, Connection(), method="semantic")

    assert error.value.status_code == 409
    assert "current model-fingerprinted embeddings" in error.value.detail


def test_semantic_model_initialization_failure_returns_service_unavailable(monkeypatch):
    monkeypatch.setattr(retrieval, "approved_chunks", lambda *_args: [{"chunk_id": 1}])
    monkeypatch.setattr(retrieval, "model_fingerprint",
                        lambda: (_ for _ in ()).throw(RuntimeError("model failed")))
    request = main.RetrievalRequest(question="Q", method="semantic", chunk_strategy="fixed_size")

    with pytest.raises(main.HTTPException) as error:
        main.run_retrieval(object(), request)

    assert error.value.status_code == 503
    assert "model unavailable" in error.value.detail


def test_hybrid_fuses_bm25_and_semantic_ranks_with_reciprocal_rank_fusion(monkeypatch):
    def fake_retrieve(_connection, _question, method, _strategy, top_k, *_args):
        assert top_k == retrieval.HYBRID_CANDIDATES
        order = {"bm25": [1, 2, 3], "semantic": [3, 1, 4]}[method]
        return {"results": [{"chunk_id": chunk_id, "rank": rank, "score": 0.0}
                            for rank, chunk_id in enumerate(order, 1)],
                "timings": {"search_ms": 1.0}}

    monkeypatch.setattr(retrieval, "retrieve", fake_retrieve)
    result = retrieval._hybrid(None, "question", "section_aware", 3, 1, None, None, None, False)

    assert [row["chunk_id"] for row in result["results"]] == [1, 3, 2]
    assert result["results"][0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert result["timings"]["search_ms"] == 2.0
