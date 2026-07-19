# coding=utf-8
"""
Unit tests for WarmStorageService.

Tests:
  - CRUD operations (get, set, delete)
  - Full-text search
  - Promotion/demotion logic
  - Section summaries
  - Performance (<1s SLA)
  - Concurrent access
  - Statistics

Run: python -m pytest aot/services/test_warm_storage_service.py -v
"""
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir, os.path.pardir)))

from aot.services.warm_storage_service import (
    WarmStorageService,
    Document,
    SearchResult,
    SectionSummary,
    create_warm_storage_service,
)


class TestWarmStorageService(unittest.TestCase):
    """Test cases for WarmStorageService."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix='.db')
        cls.service = WarmStorageService(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        os.close(cls.db_fd)
        if os.path.exists(cls.db_path):
            os.unlink(cls.db_path)

    def setUp(self):
        """Clean database before each test."""
        conn = self.service._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM warm_documents")
            cursor.execute("DELETE FROM section_summaries")
            cursor.execute("DELETE FROM warm_transition_log")
            conn.commit()
        finally:
            conn.close()

    # =========================================================================
    # CRUD Tests
    # =========================================================================

    def test_set_and_get_document(self):
        """Test storing and retrieving a document."""
        doc = Document(
            doc_id="test-001",
            title="Test Document",
            content="This is a test document with temperature and humidity data.",
            tags="sensor,test",
            tier_level=2,
            token_count=100,
            char_count=500,
        )
        self.service.set(doc.doc_id, doc)

        retrieved = self.service.get(doc.doc_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.doc_id, "test-001")
        self.assertEqual(retrieved.title, "Test Document")
        self.assertEqual(retrieved.content, "This is a test document with temperature and humidity data.")
        self.assertEqual(retrieved.tags, "sensor,test")
        self.assertEqual(retrieved.tier_level, 2)

    def test_get_nonexistent_document(self):
        """Test retrieving a document that doesn't exist."""
        result = self.service.get("nonexistent-id")
        self.assertIsNone(result)

    def test_delete_document(self):
        """Test deleting a document."""
        doc = Document(
            doc_id="test-002",
            title="To Be Deleted",
            content="This document will be deleted.",
            tier_level=2,
        )
        self.service.set(doc.doc_id, doc)

        # Verify it exists
        self.assertIsNotNone(self.service.get(doc.doc_id))

        # Delete it
        self.service.delete(doc.doc_id)

        # Verify it's gone
        self.assertIsNone(self.service.get(doc.doc_id))

    def test_update_document(self):
        """Test updating an existing document."""
        doc = Document(
            doc_id="test-003",
            title="Original Title",
            content="Original content.",
            tier_level=2,
        )
        self.service.set(doc.doc_id, doc)

        # Update the document
        updated_doc = Document(
            doc_id="test-003",
            title="Updated Title",
            content="Updated content with more information.",
            tier_level=2,
        )
        self.service.set(doc.doc_id, updated_doc)

        # Verify update
        retrieved = self.service.get(doc.doc_id)
        self.assertEqual(retrieved.title, "Updated Title")
        self.assertEqual(retrieved.content, "Updated content with more information.")

    # =========================================================================
    # Search Tests
    # =========================================================================

    def test_search_basic(self):
        """Test basic full-text search."""
        docs = [
            Document(doc_id="search-001", title="Temperature Sensor", content="Temperature is 25 degrees.", tags="temp"),
            Document(doc_id="search-002", title="Humidity Sensor", content="Humidity is at 65 percent.", tags="humid"),
            Document(doc_id="search-003", title="Light Sensor", content="Light conditions are optimal.", tags="light"),
        ]
        for doc in docs:
            self.service.set(doc.doc_id, doc)

        results = self.service.search("temperature")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].doc_id, "search-001")

    def test_search_multiple_results(self):
        """Test search returning multiple results."""
        docs = [
            Document(doc_id="multi-001", title="Sensor Data 1", content="Temperature and humidity readings.", tags="sensor"),
            Document(doc_id="multi-002", title="Sensor Data 2", content="Temperature readings for analysis.", tags="sensor"),
            Document(doc_id="multi-003", title="Other Data", content="Light and CO2 levels.", tags="sensor"),
        ]
        for doc in docs:
            self.service.set(doc.doc_id, doc)

        results = self.service.search("temperature")
        self.assertEqual(len(results), 2)

    def test_search_with_tags_filter(self):
        """Test search with tags filter."""
        docs = [
            Document(doc_id="tag-001", title="Temperature", content="Temperature reading.", tags="temp,sensor"),
            Document(doc_id="tag-002", title="Humidity", content="Humidity reading.", tags="humid,sensor"),
            Document(doc_id="tag-003", title="Temperature", content="Temperature for system.", tags="temp,system"),
        ]
        for doc in docs:
            self.service.set(doc.doc_id, doc)

        results = self.service.search("temperature", tags_filter="system")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].doc_id, "tag-003")

    def test_search_empty_query(self):
        """Test search with empty query returns empty."""
        results = self.service.search("")
        self.assertEqual(len(results), 0)

    # =========================================================================
    # Section Summary Tests
    # =========================================================================

    def test_add_and_get_section_summaries(self):
        """Test adding and retrieving section summaries."""
        doc = Document(
            doc_id="section-001",
            title="Multi-Section Document",
            content="Long document content...",
            tier_level=2,
        )
        self.service.set(doc.doc_id, doc)

        sections = [
            SectionSummary(
                section_id="sec-001",
                doc_id="section-001",
                section_index=0,
                title="Introduction",
                summary="This is the introduction section.",
                keywords="intro,start",
            ),
            SectionSummary(
                section_id="sec-002",
                doc_id="section-001",
                section_index=1,
                title="Main Content",
                summary="This is the main content section.",
                keywords="content,main",
            ),
        ]
        for section in sections:
            self.service.add_section_summary(section)

        retrieved = self.service.get_section_summaries("section-001")
        self.assertEqual(len(retrieved), 2)
        self.assertEqual(retrieved[0].title, "Introduction")
        self.assertEqual(retrieved[1].title, "Main Content")

    def test_search_sections(self):
        """Test searching within sections."""
        doc = Document(
            doc_id="sec-search-001",
            title="Document",
            content="Content",
            tier_level=2,
        )
        self.service.set(doc.doc_id, doc)

        section = SectionSummary(
            section_id="sec-search-001",
            doc_id="sec-search-001",
            section_index=0,
            title="Temperature Analysis",
            summary="Temperature analysis results show optimal conditions.",
            keywords="temperature,analysis",
        )
        self.service.add_section_summary(section)

        results = self.service.search_sections("temperature")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].doc_id, "sec-search-001")

    # =========================================================================
    # Promotion/Demotion Tests
    # =========================================================================

    def test_promote_to_tier1(self):
        """Test promoting document from Tier 2 to Tier 1."""
        doc = Document(
            doc_id="promote-001",
            title="Promotable Document",
            content="This document will be promoted.",
            tier_level=2,
        )
        self.service.set(doc.doc_id, doc)

        result = self.service.promote_to_tier1("promote-001")
        self.assertTrue(result)

        retrieved = self.service.get("promote-001")
        self.assertEqual(retrieved.tier_level, 1)

        # Check transition log
        history = self.service.get_transition_history("promote-001")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['from_tier'], 2)
        self.assertEqual(history[0]['to_tier'], 1)

    def test_demote_to_tier3(self):
        """Test demoting document from Tier 2 to Tier 3."""
        doc = Document(
            doc_id="demote-001",
            title="Demotable Document",
            content="This document will be demoted.",
            tier_level=2,
        )
        self.service.set(doc.doc_id, doc)

        result = self.service.demote_to_tier3("demote-001")
        self.assertTrue(result)

        retrieved = self.service.get("demote-001")
        self.assertEqual(retrieved.tier_level, 3)

        # Check transition log
        history = self.service.get_transition_history("demote-001")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['from_tier'], 2)
        self.assertEqual(history[0]['to_tier'], 3)

    def test_promote_nonexistent_document(self):
        """Test promoting a document that doesn't exist."""
        result = self.service.promote_to_tier1("nonexistent-promote")
        self.assertFalse(result)

    def test_demote_nonexistent_document(self):
        """Test demoting a document that doesn't exist."""
        result = self.service.demote_to_tier3("nonexistent-demote")
        self.assertFalse(result)

    # =========================================================================
    # Statistics Tests
    # =========================================================================

    def test_get_stats(self):
        """Test getting database statistics."""
        # Add some documents
        for i in range(5):
            doc = Document(
                doc_id=f"stats-{i:03d}",
                title=f"Document {i}",
                content=f"Content for document {i}",
                tier_level=2 if i < 3 else 3,
            )
            self.service.set(doc.doc_id, doc)

        stats = self.service.get_stats()
        self.assertEqual(stats['total_documents'], 5)
        self.assertIn(2, stats['tier_distribution'])
        self.assertIn(3, stats['tier_distribution'])
        self.assertGreater(stats['database_size_bytes'], 0)

    def test_get_documents_by_tier(self):
        """Test retrieving documents by tier level."""
        docs = [
            Document(doc_id="tier-001", title="Tier 1 Doc", content="Content", tier_level=1),
            Document(doc_id="tier-002", title="Tier 2 Doc", content="Content", tier_level=2),
            Document(doc_id="tier-003", title="Tier 2 Doc", content="Content", tier_level=2),
            Document(doc_id="tier-004", title="Tier 3 Doc", content="Content", tier_level=3),
        ]
        for doc in docs:
            self.service.set(doc.doc_id, doc)

        tier2_docs = self.service.get_documents_by_tier(2)
        self.assertEqual(len(tier2_docs), 2)

    def test_get_top_accessed(self):
        """Test getting most accessed documents."""
        for i in range(5):
            doc = Document(
                doc_id=f"top-{i:03d}",
                title=f"Document {i}",
                content="Content",
                tier_level=2,
                access_count=i * 10,
            )
            self.service.set(doc.doc_id, doc)

        top_docs = self.service.get_top_accessed(limit=3)
        self.assertEqual(len(top_docs), 3)
        self.assertEqual(top_docs[0].access_count, 40)  # Most accessed

    # =========================================================================
    # Performance Tests
    # =========================================================================

    def test_search_performance_under_1s(self):
        """Test search achieves <1s SLA."""
        # Create 100 documents
        for i in range(100):
            doc = Document(
                doc_id=f"perf-{i:03d}",
                title=f"Performance Test Document {i}",
                content=f"Temperature humidity light sensor data for document {i}. " * 10,
                tags="sensor,test,performance",
                tier_level=2,
            )
            self.service.set(doc.doc_id, doc)

        start_time = time.time()
        results = self.service.search("temperature", limit=20)
        elapsed = time.time() - start_time

        self.assertLess(elapsed, 1.0, f"Search took {elapsed*1000:.2f}ms, exceeded 1s SLA")
        self.assertGreater(len(results), 0)

    def test_bulk_insert_performance(self):
        """Test bulk insert performance."""
        start_time = time.time()

        for i in range(100):
            doc = Document(
                doc_id=f"bulk-{i:03d}",
                title=f"Bulk Document {i}",
                content=f"Content for bulk document {i}",
                tier_level=2,
            )
            self.service.set(doc.doc_id, doc)

        elapsed = time.time() - start_time
        self.assertLess(elapsed, 5.0, f"Bulk insert took {elapsed:.2f}s for 100 docs")

    # =========================================================================
    # Concurrent Access Tests
    # =========================================================================

    def test_concurrent_writes(self):
        """Test concurrent write operations."""
        errors = []

        def write_worker(start_id, count):
            try:
                for i in range(count):
                    doc = Document(
                        doc_id=f"concurrent-{start_id + i:03d}",
                        title=f"Concurrent Document {start_id + i}",
                        content=f"Content for concurrent document {start_id + i}",
                        tier_level=2,
                    )
                    self.service.set(doc.doc_id, doc)
            except Exception as e:
                errors.append(str(e))

        threads = []
        for t in range(3):
            thread = Thread(target=write_worker, args=(t * 50, 50))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self.assertEqual(len(errors), 0, f"Concurrent write errors: {errors}")

        # Verify all documents were written
        stats = self.service.get_stats()
        self.assertEqual(stats['total_documents'], 150)

    def test_concurrent_reads(self):
        """Test concurrent read operations."""
        # Create test documents
        for i in range(20):
            doc = Document(
                doc_id=f"read-{i:03d}",
                title=f"Read Test Document {i}",
                content=f"Content for read test {i}",
                tier_level=2,
            )
            self.service.set(doc.doc_id, doc)

        errors = []
        results = []

        def read_worker():
            try:
                for _ in range(10):
                    doc = self.service.get(f"read-{_ % 20:03d}")
                    if doc:
                        results.append(doc)
            except Exception as e:
                errors.append(str(e))

        threads = []
        for t in range(5):
            thread = Thread(target=read_worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self.assertEqual(len(errors), 0, f"Concurrent read errors: {errors}")
        self.assertEqual(len(results), 50)


class TestDocumentDataclass(unittest.TestCase):
    """Test Document dataclass."""

    def test_document_to_dict(self):
        """Test Document to_dict method."""
        doc = Document(
            doc_id="test-001",
            title="Test",
            content="Content",
            tags="tag1,tag2",
            tier_level=2,
            token_count=100,
            char_count=500,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_accessed=datetime.utcnow(),
            access_count=10,
            tier_score=0.75,
        )

        d = doc.to_dict()
        self.assertEqual(d['doc_id'], "test-001")
        self.assertEqual(d['title'], "Test")
        self.assertEqual(d['tier_level'], 2)
        self.assertEqual(d['access_count'], 10)
        self.assertEqual(d['tier_score'], 0.75)


class TestSearchResultDataclass(unittest.TestCase):
    """Test SearchResult dataclass."""

    def test_search_result_creation(self):
        """Test SearchResult creation."""
        result = SearchResult(
            doc_id="test-001",
            title="Test",
            snippet="Test snippet...",
            rank=0.5,
            tags="test",
            tier_level=2,
        )

        self.assertEqual(result.doc_id, "test-001")
        self.assertEqual(result.rank, 0.5)


class TestServiceFactory(unittest.TestCase):
    """Test service factory function."""

    def test_create_warm_storage_service_default_path(self):
        """Test factory creates service with default path."""
        import os
        service = create_warm_storage_service()
        self.assertIsInstance(service, WarmStorageService)
        # Clean up default db
        if os.path.exists(service.db_path):
            os.unlink(service.db_path)

    def test_create_warm_storage_service_custom_path(self):
        """Test factory creates service with custom path."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            service = create_warm_storage_service(db_path)
            self.assertIsInstance(service, WarmStorageService)
            self.assertEqual(service.db_path, db_path)
        finally:
            os.unlink(db_path)


if __name__ == '__main__':
    unittest.main(verbosity=2)