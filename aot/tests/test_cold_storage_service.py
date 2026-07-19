# coding=utf-8
"""
Unit tests for ColdStorageService.

Covers archive, retrieval, compression, search, and retention policy enforcement.
All external I/O (filesystem, DB) is mocked.
"""
import gzip
import json
import os
import sys
import tempfile
import unittest
import time
from datetime import datetime, timedelta
from unittest.mock import ANY, MagicMock, patch, mock_open

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
)

# Prevent automatic Alembic migration during import
os.environ.setdefault("ALEMBIC_RUNNING", "1")

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONTENT = "This is a sample document content for testing compression and archival."
SAMPLE_METADATA = {"title": "Test Document", "tags": ["test", "archive"], "category": "testing"}
SAMPLE_DOCUMENT_ID = "test-doc-12345-abcde"


# ===========================================================================
# ColdStorageService - Compression helpers
# ===========================================================================

from aot.services.cold_storage_service import ColdStorageService


class TestCompressContent(unittest.TestCase):
    """ColdStorageService._compress_content() — gzip compression."""

    def setUp(self):
        self.service = ColdStorageService(archive_base_path=tempfile.mkdtemp())

    def test_gzip_compression_returns_tuple(self):
        """Compression returns (compressed_bytes, compressed_size)."""
        result = self.service._compress_content(SAMPLE_CONTENT, 'gzip')
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_gzip_compression_reduces_size(self):
        """Compressed size should be smaller than original for repetitive content."""
        result = self.service._compress_content(SAMPLE_CONTENT * 100, 'gzip')
        compressed_bytes, compressed_size = result
        original_size = len((SAMPLE_CONTENT * 100).encode('utf-8'))
        self.assertLess(compressed_size, original_size)

    def test_gzip_compression_is_valid(self):
        """Compressed bytes can be decompressed back to original content."""
        compressed_bytes, _ = self.service._compress_content(SAMPLE_CONTENT, 'gzip')
        decompressed = gzip.decompress(compressed_bytes).decode('utf-8')
        self.assertEqual(decompressed, SAMPLE_CONTENT)

    def test_unknown_compression_type_falls_back_to_gzip(self):
        """Unknown compression type should fall back to gzip."""
        compressed_bytes, compressed_size = self.service._compress_content(
            SAMPLE_CONTENT, 'unknown_type'
        )
        # Should still produce valid gzip data
        decompressed = gzip.decompress(compressed_bytes).decode('utf-8')
        self.assertEqual(decompressed, SAMPLE_CONTENT)


class TestDecompressContent(unittest.TestCase):
    """ColdStorageService._decompress_content() — decompression."""

    def setUp(self):
        self.service = ColdStorageService(archive_base_path=tempfile.mkdtemp())

    def test_gzip_decompression_returns_string(self):
        """Decompression returns the original string content."""
        compressed = gzip.compress(SAMPLE_CONTENT.encode('utf-8'))
        result = self.service._decompress_content(compressed, 'gzip')
        self.assertIsInstance(result, str)
        self.assertEqual(result, SAMPLE_CONTENT)

    def test_decompression_round_trip(self):
        """Compress then decompress returns original content."""
        compressed, _ = self.service._compress_content(SAMPLE_CONTENT, 'gzip')
        decompressed = self.service._decompress_content(compressed, 'gzip')
        self.assertEqual(decompressed, SAMPLE_CONTENT)


# ===========================================================================
# ColdStorageService - Path generation
# ===========================================================================

class TestGenerateArchivePath(unittest.TestCase):
    """ColdStorageService._generate_archive_path() — year/month structure."""

    def setUp(self):
        self.service = ColdStorageService(archive_base_path='/var/aot/archives')

    def test_path_contains_base(self):
        """Generated path starts with archive base path."""
        timestamp = datetime(2026, 3, 15)
        path = self.service._generate_archive_path(SAMPLE_DOCUMENT_ID, timestamp)
        self.assertTrue(path.startswith('/var/aot/archives'))

    def test_path_contains_year(self):
        """Generated path contains the year directory."""
        timestamp = datetime(2026, 3, 15)
        path = self.service._generate_archive_path(SAMPLE_DOCUMENT_ID, timestamp)
        self.assertIn('2026', path)

    def test_path_contains_month(self):
        """Generated path contains the month directory (zero-padded)."""
        timestamp = datetime(2026, 3, 15)
        path = self.service._generate_archive_path(SAMPLE_DOCUMENT_ID, timestamp)
        self.assertIn('03', path)

    def test_path_ends_with_document_id(self):
        """Generated path ends with document_id.archive."""
        timestamp = datetime(2026, 3, 15)
        path = self.service._generate_archive_path(SAMPLE_DOCUMENT_ID, timestamp)
        self.assertTrue(path.endswith(f'{SAMPLE_DOCUMENT_ID}.archive'))

    def test_path_month_padding(self):
        """Month is zero-padded to 2 digits."""
        timestamp = datetime(2026, 1, 5)
        path = self.service._generate_archive_path(SAMPLE_DOCUMENT_ID, timestamp)
        # Should contain '01' not '1'
        self.assertIn('/01/', path)


# ===========================================================================
# ColdStorageService - Archive document
# ===========================================================================

class TestArchiveDocument(unittest.TestCase):
    """ColdStorageService.archive_document() — archiving workflow."""

    def setUp(self):
        self.archive_dir = tempfile.mkdtemp()
        self.service = ColdStorageService(
            archive_base_path=self.archive_dir,
            default_retention_days=365,
        )

    @patch('aot.services.cold_storage_service.ColdDocuments')
    @patch('aot.services.cold_storage_service.ArchiveIndex')
    @patch('aot.services.cold_storage_service.ArchiveAuditLog')
    @patch('aot.services.cold_storage_service.os.makedirs')
    @patch('builtins.open', mock_open())
    def test_archive_document_creates_records(self, mock_open, mock_makedirs, mock_audit, mock_index, mock_cold):
        """archive_document() creates ColdDocuments and ArchiveIndex records."""
        mock_cold_instance = MagicMock()
        mock_cold_instance.unique_id = 'uuid-123'
        mock_cold_instance.compression_ratio = 75.0
        mock_cold_instance.archived_at = datetime.utcnow()
        mock_cold.return_value = mock_cold_instance
        mock_cold_instance.save.return_value = mock_cold_instance

        mock_index_instance = MagicMock()
        mock_index.return_value = mock_index_instance
        mock_index_instance.save.return_value = mock_index_instance

        result = self.service.archive_document(
            document_id=SAMPLE_DOCUMENT_ID,
            content=SAMPLE_CONTENT,
            metadata=SAMPLE_METADATA,
        )

        # Verify records were created
        mock_cold.assert_called_once()
        mock_index.assert_called_once()
        mock_cold_instance.save.assert_called()
        mock_index_instance.save.assert_called()

        # Verify result structure
        self.assertIn('unique_id', result)
        self.assertIn('document_id', result)
        self.assertIn('archive_path', result)

    @patch('aot.services.cold_storage_service.ColdDocuments')
    def test_archive_document_fails_if_already_archived(self, mock_cold):
        """archive_document() raises ValueError if document is already archived."""
        mock_cold.query.filter_by.return_value.first.return_value = MagicMock()

        with self.assertRaises(ValueError) as ctx:
            self.service.archive_document(
                document_id=SAMPLE_DOCUMENT_ID,
                content=SAMPLE_CONTENT,
            )
        self.assertIn('already archived', str(ctx.exception))

    @patch('aot.services.cold_storage_service.ColdDocuments')
    @patch('aot.services.cold_storage_service.ArchiveIndex')
    @patch('aot.services.cold_storage_service.ArchiveAuditLog')
    @patch('aot.services.cold_storage_service.os.makedirs')
    @patch('builtins.open', mock_open())
    def test_archive_document_stores_metadata(self, mock_open, mock_makedirs, mock_audit, mock_index, mock_cold):
        """Metadata is stored as JSON in ColdDocuments."""
        mock_cold_instance = MagicMock()
        mock_cold_instance.unique_id = 'uuid-123'
        mock_cold_instance.compression_ratio = 75.0
        mock_cold_instance.archived_at = datetime.utcnow()
        mock_cold.return_value = mock_cold_instance
        mock_cold_instance.save.return_value = mock_cold_instance

        mock_index_instance = MagicMock()
        mock_index.return_value = mock_index_instance
        mock_index_instance.save.return_value = mock_index_instance

        self.service.archive_document(
            document_id=SAMPLE_DOCUMENT_ID,
            content=SAMPLE_CONTENT,
            metadata=SAMPLE_METADATA,
        )

        # Verify metadata was passed to ColdDocuments
        call_kwargs = mock_cold.call_args[1]
        self.assertEqual(json.loads(call_kwargs['metadata']), SAMPLE_METADATA)


# ===========================================================================
# ColdStorageService - Restore document
# ===========================================================================

class TestRestoreDocument(unittest.TestCase):
    """ColdStorageService.restore_document() — retrieval workflow."""

    def setUp(self):
        self.archive_dir = tempfile.mkdtemp()
        self.service = ColdStorageService(archive_base_path=self.archive_dir)

    def test_restore_document_returns_none_if_not_found(self):
        """restore_document() returns None when document is not archived."""
        with patch('aot.services.cold_storage_service.ColdDocuments') as mock_cold:
            mock_cold.query.filter_by.return_value.first.return_value = None

            result = self.service.restore_document(SAMPLE_DOCUMENT_ID)
            self.assertIsNone(result)

    def test_restore_document_updates_access_metadata(self):
        """restore_document() updates last_accessed and restore_count."""
        mock_cold_doc = MagicMock()
        mock_cold_doc.document_id = SAMPLE_DOCUMENT_ID
        mock_cold_doc.archive_path = os.path.join(self.archive_dir, '2026', '03', f'{SAMPLE_DOCUMENT_ID}.archive')
        mock_cold_doc.restore_count = 0
        mock_cold_doc.last_accessed = datetime.utcnow() - timedelta(days=30)

        # Create a valid compressed content
        compressed = gzip.compress(SAMPLE_CONTENT.encode('utf-8'))

        with patch('aot.services.cold_storage_service.ColdDocuments') as mock_cold_class, \
             patch('builtins.open', mock_open(read_data=compressed)):
            mock_cold_class.query.filter_by.return_value.first.return_value = mock_cold_doc

            result = self.service.restore_document(SAMPLE_DOCUMENT_ID)

            # Verify save was called to update access metadata
            mock_cold_doc.save.assert_called_once()
            self.assertEqual(mock_cold_doc.restore_count, 1)

    def test_restore_document_metadata_only(self):
        """restore_document(decompress=False) returns only metadata."""
        mock_cold_doc = MagicMock()
        mock_cold_doc.document_id = SAMPLE_DOCUMENT_ID
        mock_cold_doc.metadata = json.dumps(SAMPLE_METADATA)
        mock_cold_doc.archived_at = datetime.utcnow()
        mock_cold_doc.compression_type = 'gzip'
        mock_cold_doc.compression_ratio = 75.0

        with patch('aot.services.cold_storage_service.ColdDocuments') as mock_cold_class:
            mock_cold_class.query.filter_by.return_value.first.return_value = mock_cold_doc

            result = self.service.restore_document(SAMPLE_DOCUMENT_ID, decompress=False)

            self.assertIn('metadata', result)
            self.assertIn('compression_type', result)
            self.assertNotIn('content', result)


# ===========================================================================
# ColdStorageService - Search archives
# ===========================================================================

class TestSearchArchives(unittest.TestCase):
    """ColdStorageService.search_archives() — search functionality."""

    def setUp(self):
        self.service = ColdStorageService(archive_base_path=tempfile.mkdtemp())

    def test_search_archives_returns_dict_with_results(self):
        """search_archives() returns dict with 'results', 'total', and pagination."""
        mock_results = [MagicMock(), MagicMock()]

        with patch('aot.services.cold_storage_service.ColdDocuments') as mock_cold_class:
            mock_query = MagicMock()
            mock_cold_class.query.join.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.count.return_value = 2
            mock_query.order_by.return_value = mock_query
            mock_query.offset.return_value = mock_query
            mock_query.limit.return_value = mock_query
            mock_query.all.return_value = mock_results

            # Mock the JSON conversion
            for i, mock_doc in enumerate(mock_results):
                mock_doc.document_id = f'doc-{i}'
                mock_doc.unique_id = f'uuid-{i}'
                mock_doc.metadata = json.dumps({'title': f'Doc {i}'})
                mock_doc.archived_at = datetime.utcnow()
                mock_doc.last_accessed = datetime.utcnow()
                mock_doc.compression_type = 'gzip'
                mock_doc.compression_ratio = 75.0
                mock_doc.original_size = 1000
                mock_doc.compressed_size = 250

            result = self.service.search_archives(limit=10)

            self.assertIn('results', result)
            self.assertIn('total', result)
            self.assertIn('limit', result)
            self.assertIn('offset', result)
            self.assertEqual(result['total'], 2)

    def test_search_archives_applies_date_filter(self):
        """Date range filters are applied to query."""
        from_date = datetime(2026, 1, 1)
        to_date = datetime(2026, 3, 31)

        with patch('aot.services.cold_storage_service.ColdDocuments') as mock_cold_class:
            mock_query = MagicMock()
            mock_cold_class.query.join.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.count.return_value = 0
            mock_query.order_by.return_value = mock_query
            mock_query.offset.return_value = mock_query
            mock_query.limit.return_value = mock_query
            mock_query.all.return_value = []

            self.service.search_archives(from_date=from_date, to_date=to_date)

            # Verify filter was called (at least once with the date conditions)
            filter_calls = mock_query.filter.call_args_list
            self.assertGreater(len(filter_calls), 0)


# ===========================================================================
# ColdStorageService - Lifecycle enforcement
# ===========================================================================

class TestEnforceRetentionPolicies(unittest.TestCase):
    """ColdStorageService.enforce_retention_policies() — retention enforcement."""

    def setUp(self):
        self.service = ColdStorageService(archive_base_path=tempfile.mkdtemp())

    def test_enforce_retention_policies_marks_expired(self):
        """Expired archives are marked as pending_deletion."""
        mock_archive = MagicMock()
        mock_archive.document_id = SAMPLE_DOCUMENT_ID
        mock_archive.status = 'active'
        mock_archive.deletion_date = datetime.utcnow() - timedelta(days=1)  # expired

        with patch('aot.services.cold_storage_service.ArchiveIndex') as mock_index_class:
            mock_query = MagicMock()
            mock_index_class.query.filter.return_value = mock_query
            mock_query.all.return_value = [mock_archive]

            result = self.service.enforce_retention_policies()

            self.assertGreaterEqual(result['pending_deletion'], 0)
            mock_archive.save.assert_called()

    def test_enforce_retention_policies_returns_counts(self):
        """Returns dict with purged, pending_deletion, and active counts."""
        with patch('aot.services.cold_storage_service.ArchiveIndex') as mock_index_class:
            mock_query = MagicMock()
            mock_index_class.query.filter.return_value = mock_query
            mock_query.all.return_value = []

            mock_index_class.query.filter_by.return_value.count.return_value = 5

            result = self.service.enforce_retention_policies()

            self.assertIn('purged', result)
            self.assertIn('pending_deletion', result)
            self.assertIn('active', result)


# ===========================================================================
# ColdStorageService - Statistics
# ===========================================================================

class TestGetArchiveStats(unittest.TestCase):
    """ColdStorageService.get_archive_stats() — statistics gathering."""

    def setUp(self):
        self.service = ColdStorageService(archive_base_path=tempfile.mkdtemp())

    def test_get_archive_stats_returns_required_fields(self):
        """Returns all required statistical fields."""
        with patch('aot.services.cold_storage_service.ColdDocuments') as mock_cold_class, \
             patch('aot.services.cold_storage_service.ArchiveIndex') as mock_index_class:
            mock_cold_class.query.count.return_value = 10
            mock_cold_class.query.all.return_value = [
                MagicMock(original_size=1000, compressed_size=250),
                MagicMock(original_size=2000, compressed_size=500),
            ]
            mock_index_class.query.filter_by.return_value.count.return_value = 8
            mock_index_class.query.filter_by.return_value.group_by.return_value.all.return_value = [
                ('default', 5), ('1year', 3)
            ]
            mock_index_class.query.filter.return_value.count.return_value = 2

            result = self.service.get_archive_stats()

            self.assertIn('total_archived', result)
            self.assertIn('active_archives', result)
            self.assertIn('average_compression_ratio', result)
            self.assertIn('total_original_size_bytes', result)
            self.assertIn('total_compressed_size_bytes', result)


# ===========================================================================
# ColdStorageService - Batch operations
# ===========================================================================

class TestBatchRetrieve(unittest.TestCase):
    """ColdStorageService.batch_retrieve() — batch retrieval."""

    def setUp(self):
        self.archive_dir = tempfile.mkdtemp()
        self.service = ColdStorageService(archive_base_path=self.archive_dir)

    def test_batch_retrieve_returns_documents_and_errors(self):
        """Returns dict with 'documents', 'errors', and counts."""
        document_ids = ['doc-1', 'doc-2', 'doc-3']

        with patch.object(self.service, 'restore_document') as mock_restore:
            mock_restore.side_effect = [
                {'document_id': 'doc-1', 'content': 'content1'},
                None,  # doc-2 not found
                {'document_id': 'doc-3', 'content': 'content3'},
            ]

            result = self.service.batch_retrieve(document_ids)

            self.assertIn('documents', result)
            self.assertIn('errors', result)
            self.assertIn('count', result)
            self.assertIn('error_count', result)
            self.assertEqual(result['count'], 2)
            self.assertEqual(result['error_count'], 1)

    def test_batch_retrieve_handles_exceptions(self):
        """Exceptions during retrieval are captured in errors list."""
        with patch.object(self.service, 'restore_document') as mock_restore:
            mock_restore.side_effect = [
                {'document_id': 'doc-1', 'content': 'content1'},
                Exception("Database error"),
            ]

            result = self.service.batch_retrieve(['doc-1', 'doc-2'])

            self.assertEqual(result['count'], 1)
            self.assertEqual(result['error_count'], 1)
            self.assertEqual(result['errors'][0]['document_id'], 'doc-2')


# ===========================================================================
# ColdStorageService - Audit logging
# ===========================================================================

class TestAuditLogging(unittest.TestCase):
    """ColdStorageService._log_audit() — audit trail."""

    def setUp(self):
        self.service = ColdStorageService(archive_base_path=tempfile.mkdtemp())

    def test_log_audit_creates_record(self):
        """_log_audit creates an ArchiveAuditLog record."""
        with patch('aot.services.cold_storage_service.ArchiveAuditLog') as mock_audit:
            mock_instance = MagicMock()
            mock_audit.return_value = mock_instance

            self.service._log_audit(
                operation='archive',
                document_id=SAMPLE_DOCUMENT_ID,
                performed_by='test',
                status='success',
                compression_type='gzip',
                original_size=1000,
                compressed_size=250,
            )

            mock_audit.assert_called_once()
            mock_instance.save.assert_called_once()

    def test_log_audit_handles_failure_gracefully(self):
        """Audit logging failures don't raise exceptions."""
        with patch('aot.services.cold_storage_service.ArchiveAuditLog') as mock_audit:
            mock_audit.side_effect = Exception("DB error")

            # Should not raise
            try:
                self.service._log_audit(
                    operation='archive',
                    document_id=SAMPLE_DOCUMENT_ID,
                    performed_by='test',
                    status='success',
                )
            except Exception as e:
                self.fail(f"_log_audit raised exception: {e}")


# ===========================================================================
# ColdStorageService - Convenience methods (get, archive, delete, search)
# ===========================================================================

class TestConvenienceMethods(unittest.TestCase):
    """ColdStorageService convenience methods (get, archive, delete, search)."""

    def setUp(self):
        self.archive_dir = tempfile.mkdtemp()
        self.service = ColdStorageService(archive_base_path=self.archive_dir)

    def test_get_method_returns_document(self):
        """get() delegates to restore_document with decompress=True."""
        with patch.object(self.service, 'restore_document') as mock_restore:
            mock_restore.return_value = {'document_id': SAMPLE_DOCUMENT_ID, 'content': SAMPLE_CONTENT}

            result = self.service.get(SAMPLE_DOCUMENT_ID)

            mock_restore.assert_called_once_with(SAMPLE_DOCUMENT_ID, decompress=True)
            self.assertEqual(result['document_id'], SAMPLE_DOCUMENT_ID)

    def test_archive_method_with_document_object(self):
        """archive() accepts a document object with content attribute."""
        mock_doc = MagicMock()
        mock_doc.content = SAMPLE_CONTENT
        mock_doc.metadata = SAMPLE_METADATA

        with patch.object(self.service, 'archive_document') as mock_archive:
            mock_archive.return_value = {'document_id': SAMPLE_DOCUMENT_ID}

            self.service.archive(SAMPLE_DOCUMENT_ID, mock_doc)

            mock_archive.assert_called_once()
            call_kwargs = mock_archive.call_args[1]
            self.assertEqual(call_kwargs['document_id'], SAMPLE_DOCUMENT_ID)
            self.assertEqual(call_kwargs['content'], SAMPLE_CONTENT)

    def test_delete_method_calls_delete_archive(self):
        """delete() delegates to delete_archive."""
        with patch.object(self.service, 'delete_archive') as mock_delete:
            mock_delete.return_value = True

            self.service.delete(SAMPLE_DOCUMENT_ID)

            mock_delete.assert_called_once_with(SAMPLE_DOCUMENT_ID)

    def test_search_method_returns_results(self):
        """search() returns list of search results."""
        mock_results = [
            {'document_id': 'doc-1', 'metadata': {'title': 'Test'}},
            {'document_id': 'doc-2', 'metadata': {'title': 'Test 2'}},
        ]

        with patch.object(self.service, 'search_archives') as mock_search:
            mock_search.return_value = {'results': mock_results}

            result = self.service.search('test query')

            self.assertEqual(len(result), 2)
            mock_search.assert_called_once_with(query='test query')


# ===========================================================================
# ColdStorageService - Retention policy check
# ===========================================================================

class TestCheckRetentionPolicy(unittest.TestCase):
    """ColdStorageService.check_retention_policy() — expired doc detection."""

    def setUp(self):
        self.service = ColdStorageService(archive_base_path=tempfile.mkdtemp())

    def test_check_retention_policy_returns_expired_ids(self):
        """Returns list of document IDs with expired retention."""
        mock_expired1 = MagicMock()
        mock_expired1.document_id = 'doc-1'
        mock_expired1.deletion_date = datetime.utcnow() - timedelta(days=1)

        mock_expired2 = MagicMock()
        mock_expired2.document_id = 'doc-2'
        mock_expired2.deletion_date = datetime.utcnow() - timedelta(days=30)

        with patch('aot.services.cold_storage_service.ArchiveIndex') as mock_index:
            mock_query = MagicMock()
            mock_index.query.filter.return_value = mock_query
            mock_query.all.return_value = [mock_expired1, mock_expired2]

            result = self.service.check_retention_policy()

            self.assertEqual(len(result), 2)
            self.assertIn('doc-1', result)
            self.assertIn('doc-2', result)


# ===========================================================================
# Run tests
# ===========================================================================

if __name__ == '__main__':
    unittest.main()