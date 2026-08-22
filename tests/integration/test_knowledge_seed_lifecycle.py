"""End-to-end offline lifecycle for an anonymous versioned seed package."""

from __future__ import annotations

from jobfit.knowledge import (
    KnowledgeDatabase,
    SqliteKnowledgeRepository,
    initialize_knowledge_schema,
)
from tests.knowledge.seed_factory import write_seed_package


def test_load_import_publish_query_retire_lifecycle(tmp_path) -> None:
    from jobfit.knowledge.importer import KnowledgeSeedImporter
    from jobfit.knowledge.seed_loader import load_knowledge_seed
    from jobfit.knowledge.versioning import KnowledgeVersionPublisher

    package = write_seed_package(tmp_path / "seed")
    database = KnowledgeDatabase(tmp_path / "knowledge.sqlite3")
    initialize_knowledge_schema(database)
    try:
        bundle = load_knowledge_seed(package)
        imported = KnowledgeSeedImporter(database).import_seed(bundle)
        publisher = KnowledgeVersionPublisher(database)
        published = publisher.publish(imported.version_id)
        repository = SqliteKnowledgeRepository(database)

        assert repository.get_published_version("2099.01.1") is not None
        retired = publisher.retire(imported.version_id)
        assert published.content_hash == retired.content_hash
        assert repository.get_published_version("2099.01.1") is None
    finally:
        database.dispose()
