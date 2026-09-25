from app import auto_ingestion, pipeline


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, documents):
        self.documents = documents
        self.locked = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        pass

    def rollback(self):
        pass

    def execute(self, sql, params=None):
        if "SELECT pg_advisory_lock" in sql:
            assert not self.locked
            self.locked = True
            return Result()
        if "SELECT pg_try_advisory_lock" in sql:
            if self.locked:
                return Result({"acquired": False})
            self.locked = True
            return Result({"acquired": True})
        if "SELECT pg_advisory_unlock" in sql:
            self.locked = False
            return Result()
        if "UPDATE documents SET ingestion_queued_at = NULL" in sql and "WHERE document_id" not in sql:
            for document in self.documents:
                if document["review_status"] in {"ready", "ready_with_warnings", "approved", "rejected", "failed"}:
                    document["ingestion_queued_at"] = None
            return Result()
        if "FROM documents d LEFT JOIN plans" in sql:
            pending = [document for document in self.documents
                       if document["ingestion_queued_at"] and document["review_status"]
                       in {"uploaded", "processing", "needs_review"}]
            return Result(pending[0] if pending else None)
        if "SET ingestion_attempts = ingestion_attempts + 1" in sql:
            self._document(params[0])["ingestion_attempts"] += 1
            return Result()
        if "Automatic ingestion was interrupted twice" in sql:
            document = self._document(params[0])
            document["review_status"] = "failed"
            document["ingestion_queued_at"] = None
            return Result()
        if "SET review_status = 'failed'" in sql:
            document = self._document(params[1])
            document["review_status"] = "failed"
            document["ingestion_queued_at"] = None
            return Result()
        if "SET ingestion_queued_at = NULL WHERE document_id" in sql:
            self._document(params[0])["ingestion_queued_at"] = None
            return Result()
        raise AssertionError(sql)

    def _document(self, document_id):
        return next(document for document in self.documents if document["document_id"] == document_id)


def _document(document_id, status="uploaded", attempts=0):
    return {"document_id": document_id, "pdf_bytes": b"%PDF-", "plan_id": document_id,
            "plan_name": "Example", "insurer": "Example", "review_status": status,
            "ingestion_attempts": attempts, "ingestion_queued_at": "queued"}


def test_automatic_ingestion_resumes_queued_and_interrupted_documents(monkeypatch):
    documents = [_document(1), _document(2, "processing", 1)]
    connection = Connection(documents)
    processed = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(auto_ingestion.psycopg, "connect", lambda *_args, **_kwargs: connection)

    def process(_connection, document):
        processed.append(document["document_id"])
        connection._document(document["document_id"])["review_status"] = "ready"
        return {"status": "ready"}

    monkeypatch.setattr(pipeline, "process_document", process)
    auto_ingestion.drain_pending_documents()

    assert processed == [1, 2]
    assert all(document["ingestion_queued_at"] is None for document in documents)
    assert [document["ingestion_attempts"] for document in documents] == [1, 2]
    assert connection.locked is False


def test_repeated_interruption_stops_until_admin_retry(monkeypatch):
    document = _document(3, "needs_review", 2)
    connection = Connection([document])
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(auto_ingestion.psycopg, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(pipeline, "process_document", lambda *_args: (_ for _ in ()).throw(AssertionError("must not process")))

    auto_ingestion.drain_pending_documents()

    assert document["review_status"] == "failed"
    assert document["ingestion_queued_at"] is None
