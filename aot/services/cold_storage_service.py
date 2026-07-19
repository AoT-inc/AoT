# coding=utf-8
"""
ColdStorageService - Tier 3 (Cold/Archive) Storage Implementation.

Provides archive storage for rarely accessed documents with:
- Compression (gzip/brotli)
- Year/month directory structure
- Retention policy management
- Auto-deletion of expired archives
- Search and retrieval with <10s SLA
"""
import gzip
import hashlib
import json
import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

from aot.aot_flask.extensions import db
from aot.databases.models.cold_storage import (
    ArchiveAuditLog,
    ArchiveIndex,
    ColdDocuments,
    COMPRESSION_TYPES,
    DEFAULT_COMPRESSION,
    RETENTION_POLICIES,
)

logger = logging.getLogger(__name__)


class ColdStorageService:
    """
    Service for managing Tier 3 cold/archive document storage.

    Handles compression, storage, retrieval, and lifecycle management
    of archived documents with retention policy enforcement.
    """

    # Default archive base path (configurable)
    DEFAULT_ARCHIVE_BASE = "/var/aot/archives"

    def __init__(
        self,
        archive_base_path: Optional[str] = None,
        default_retention_days: int = 1095,
        compression_type: str = DEFAULT_COMPRESSION,
    ):
        """
        Initialize ColdStorageService.

        Args:
            archive_base_path: Base directory for archive storage.
                              Defaults to /var/aot/archives
            default_retention_days: Default retention period in days (3 years).
            compression_type: Default compression type ('gzip' or 'brotli').
        """
        self.archive_base_path = archive_base_path or self.DEFAULT_ARCHIVE_BASE
        self.default_retention_days = default_retention_days
        self.compression_type = compression_type if compression_type in COMPRESSION_TYPES else DEFAULT_COMPRESSION

    # -------------------------------------------------------------------------
    # Archive Operations
    # -------------------------------------------------------------------------

    def get(self, doc_id: str) -> Optional[dict]:
        """
        Retrieve an archived document by ID.

        Args:
            doc_id: Document ID to retrieve.

        Returns:
            dict with document content and metadata, or None if not found.
        """
        return self.restore_document(doc_id, decompress=True)

    def archive(self, doc_id: str, document: 'Document') -> None:
        """
        Archive a document.

        Args:
            doc_id: Document ID to archive.
            document: Document object to archive (must have content attribute).

        Raises:
            ValueError: If document already archived.
        """
        content = document.content if hasattr(document, 'content') else str(document)
        metadata = None
        if hasattr(document, 'metadata'):
            metadata = document.metadata
        elif hasattr(document, 'to_dict'):
            metadata = document.to_dict()

        self.archive_document(
            document_id=doc_id,
            content=content,
            metadata=metadata,
        )

    def delete(self, doc_id: str) -> None:
        """
        Delete an archive by document ID.

        Args:
            doc_id: Document ID to delete.
        """
        self.delete_archive(doc_id)

    def search(self, query: str) -> List[dict]:
        """
        Search archived documents.

        Args:
            query: Search query string.

        Returns:
            List of search results.
        """
        result = self.search_archives(query=query)
        return result.get('results', [])

    def check_retention_policy(self) -> List[str]:
        """
        Check which documents have expired retention policies.

        Returns:
            List of document IDs that have expired retention.
        """
        now = datetime.utcnow()
        expired = ArchiveIndex.query.filter(
            ArchiveIndex.status == 'active',
            ArchiveIndex.deletion_date <= now,
            ArchiveIndex.deletion_date.isnot(None),
        ).all()
        return [a.document_id for a in expired]

    def purge_expired(self) -> int:
        """
        Purge all expired archives.

        Returns:
            Number of archives purged.
        """
        # First enforce policies
        self.enforce_retention_policies()
        # Then purge
        result = self.purge_expired_archives()
        return result['purged_count']

    def archive_document(
        self,
        document_id: str,
        content: str,
        metadata: Optional[dict] = None,
        compression_type: Optional[str] = None,
        retention_policy: str = 'default',
        archived_by: str = 'system',
    ) -> dict:
        """
        Archive a document with compression.

        Args:
            document_id: Unique document identifier.
            content: Document content to archive.
            metadata: Optional metadata dict to store with archive.
            compression_type: Compression type ('gzip' or 'brotli').
                             Defaults to service setting.
            retention_policy: Retention policy key from RETENTION_POLICIES.
            archived_by: Who/what initiated the archival ('system', 'user', 'scheduled').

        Returns:
            dict with archive details (cold_documents record info)

        Raises:
            ValueError: If document already archived or compression fails.
        """
        compression = compression_type if compression_type in COMPRESSION_TYPES else self.compression_type

        # Check if already archived
        existing = ColdDocuments.query.filter_by(document_id=document_id).first()
        if existing:
            raise ValueError(f"Document {document_id} is already archived")

        # Calculate content hash
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

        # Compress content
        original_size = len(content.encode('utf-8'))
        compressed_content, compressed_size = self._compress_content(content, compression)

        # Generate archive path (year/month structure)
        now = datetime.utcnow()
        archive_path = self._generate_archive_path(document_id, now)

        # Ensure directory exists
        archive_dir = os.path.dirname(archive_path)
        os.makedirs(archive_dir, exist_ok=True)

        # Write compressed file
        with open(archive_path, 'wb') as f:
            f.write(compressed_content)

        # Create ColdDocuments record
        cold_doc = ColdDocuments(
            document_id=document_id,
            content_hash=content_hash,
            archive_path=archive_path,
            metadata=json.dumps(metadata) if metadata else None,
            archived_at=now,
            last_accessed=now,
            compression_type=compression,
            original_size=original_size,
            compressed_size=compressed_size,
        )
        cold_doc.save()

        # Calculate retention
        retention_days = RETENTION_POLICIES.get(retention_policy, self.default_retention_days)
        deletion_date = None
        if retention_days > 0:
            deletion_date = now + timedelta(days=retention_days)

        # Create ArchiveIndex record
        archive_index = ArchiveIndex(
            document_id=document_id,
            archive_date=now,
            deletion_date=deletion_date,
            retention_policy=retention_policy,
            retention_days=retention_days,
            status='active',
            archived_by=archived_by,
        )
        archive_index.save()

        # Log audit
        self._log_audit(
            operation='archive',
            document_id=document_id,
            performed_by=archived_by,
            compression_type=compression,
            original_size=original_size,
            compressed_size=compressed_size,
            status='success',
        )

        logger.info(
            "[ColdStorage] Archived document %s (ratio: %.1f%%)",
            document_id, cold_doc.compression_ratio
        )

        return {
            'unique_id': cold_doc.unique_id,
            'document_id': document_id,
            'archive_path': archive_path,
            'compression_ratio': cold_doc.compression_ratio,
            'archived_at': cold_doc.archived_at.isoformat(),
        }

    def restore_document(
        self,
        document_id: str,
        decompress: bool = True,
    ) -> Optional[dict]:
        """
        Restore an archived document.

        Args:
            document_id: Document ID to restore.
            decompress: If True, decompress content. If False, return metadata only.

        Returns:
            dict with document content and metadata, or None if not found.

        Raises:
            FileNotFoundError: If archive file is missing.
        """
        start_time = time.time()

        cold_doc = ColdDocuments.query.filter_by(document_id=document_id).first()
        if not cold_doc:
            logger.warning("[ColdStorage] Document %s not found in archives", document_id)
            return None

        # Update access metadata
        cold_doc.last_accessed = datetime.utcnow()
        cold_doc.restore_count += 1
        cold_doc.save()

        if not decompress:
            elapsed = (time.time() - start_time) * 1000
            logger.debug("[ColdStorage] Metadata retrieval for %s: %.1fms", document_id, elapsed)
            return {
                'document_id': document_id,
                'metadata': json.loads(cold_doc.metadata) if cold_doc.metadata else {},
                'archived_at': cold_doc.archived_at.isoformat(),
                'compression_type': cold_doc.compression_type,
                'compression_ratio': cold_doc.compression_ratio,
            }

        # Read and decompress
        if not os.path.exists(cold_doc.archive_path):
            self._log_audit(
                operation='restore',
                document_id=document_id,
                performed_by='system',
                status='failed',
                error_message='Archive file not found',
            )
            raise FileNotFoundError(f"Archive file not found: {cold_doc.archive_path}")

        with open(cold_doc.archive_path, 'rb') as f:
            compressed_content = f.read()

        content = self._decompress_content(compressed_content, cold_doc.compression_type)

        elapsed = (time.time() - start_time) * 1000
        logger.info(
            "[ColdStorage] Restored document %s (%.1fms, ratio: %.1f%%)",
            document_id, elapsed, cold_doc.compression_ratio
        )

        self._log_audit(
            operation='restore',
            document_id=document_id,
            performed_by='system',
            compression_type=cold_doc.compression_type,
            status='success',
        )

        return {
            'document_id': document_id,
            'content': content,
            'content_hash': cold_doc.content_hash,
            'metadata': json.loads(cold_doc.metadata) if cold_doc.metadata else {},
            'archived_at': cold_doc.archived_at.isoformat(),
            'compression_type': cold_doc.compression_type,
            'compression_ratio': cold_doc.compression_ratio,
            'restore_time_ms': round(elapsed, 2),
        }

    def delete_archive(self, document_id: str, deletion_reason: str = '') -> bool:
        """
        Delete an archive and its associated records.

        Args:
            document_id: Document ID to delete.
            deletion_reason: Reason for deletion (for audit log).

        Returns:
            True if deleted, False if not found.
        """
        cold_doc = ColdDocuments.query.filter_by(document_id=document_id).first()
        if not cold_doc:
            return False

        # Delete physical file
        if os.path.exists(cold_doc.archive_path):
            os.remove(cold_doc.archive_path)

        # Update archive index
        archive_index = ArchiveIndex.query.filter_by(document_id=document_id).first()
        if archive_index:
            archive_index.status = 'deleted'
            archive_index.deletion_reason = deletion_reason
            archive_index.is_purgeable = True
            archive_index.save()

        # Log audit
        self._log_audit(
            operation='delete',
            document_id=document_id,
            performed_by='system',
            status='success',
        )

        # Delete cold_doc record
        cold_doc.delete()

        logger.info("[ColdStorage] Deleted archive for document %s", document_id)
        return True

    # -------------------------------------------------------------------------
    # Search & Retrieval
    # -------------------------------------------------------------------------

    def search_archives(
        self,
        query: Optional[str] = None,
        metadata_filters: Optional[dict] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """
        Search archived documents by metadata.

        Args:
            query: Optional text query (searches in metadata values).
            metadata_filters: Filter by specific metadata fields.
            from_date: Filter by archive date (start).
            to_date: Filter by archive date (end).
            limit: Maximum results to return.
            offset: Offset for pagination.

        Returns:
            dict with 'results' list and 'total' count.
        """
        start_time = time.time()

        # Base query
        cold_query = ColdDocuments.query.join(ArchiveIndex)

        # Date range filter
        if from_date:
            cold_query = cold_query.filter(ArchiveIndex.archive_date >= from_date)
        if to_date:
            cold_query = cold_query.filter(ArchiveIndex.archive_date <= to_date)

        # Status filter (only active archives)
        cold_query = cold_query.filter(ArchiveIndex.status == 'active')

        # Metadata filter (stored as JSON text)
        if metadata_filters:
            for key, value in metadata_filters.items():
                cold_query = cold_query.filter(
                    ColdDocuments.metadata.contains(f'"{key}":{json.dumps(value)}')
                )

        # Get total count
        total = cold_query.count()

        # Apply pagination
        results = cold_query.order_by(ArchiveIndex.archive_date.desc()) \
            .offset(offset) \
            .limit(limit) \
            .all()

        # Format results
        archives = []
        for doc in results:
            archives.append({
                'document_id': doc.document_id,
                'unique_id': doc.unique_id,
                'metadata': json.loads(doc.metadata) if doc.metadata else {},
                'archived_at': doc.archived_at.isoformat(),
                'last_accessed': doc.last_accessed.isoformat(),
                'compression_type': doc.compression_type,
                'compression_ratio': doc.compression_ratio,
                'original_size': doc.original_size,
                'compressed_size': doc.compressed_size,
            })

        elapsed = (time.time() - start_time) * 1000

        # Log search (only for actual queries)
        if query or metadata_filters:
            self._log_audit(
                operation='search',
                document_id='',
                performed_by='system',
                metadata=json.dumps({
                    'query': query,
                    'filters': metadata_filters,
                    'results_count': len(archives),
                    'elapsed_ms': round(elapsed, 2),
                }),
                status='success',
            )

        return {
            'results': archives,
            'total': total,
            'limit': limit,
            'offset': offset,
            'elapsed_ms': round(elapsed, 2),
        }

    def batch_retrieve(
        self,
        document_ids: list,
        decompress: bool = True,
    ) -> dict:
        """
        Retrieve multiple archived documents.

        Args:
            document_ids: List of document IDs to retrieve.
            decompress: If True, decompress content. If False, metadata only.

        Returns:
            dict with 'documents' list and 'errors' list.
        """
        start_time = time.time()

        documents = []
        errors = []

        for doc_id in document_ids:
            try:
                result = self.restore_document(doc_id, decompress=decompress)
                if result:
                    documents.append(result)
                else:
                    errors.append({'document_id': doc_id, 'error': 'Not found'})
            except Exception as e:
                errors.append({'document_id': doc_id, 'error': str(e)})

        elapsed = (time.time() - start_time) * 1000

        return {
            'documents': documents,
            'errors': errors,
            'count': len(documents),
            'error_count': len(errors),
            'elapsed_ms': round(elapsed, 2),
        }

    # -------------------------------------------------------------------------
    # Lifecycle Management
    # -------------------------------------------------------------------------

    def enforce_retention_policies(self) -> dict:
        """
        Enforce retention policies by marking expired archives for deletion.

        Returns:
            dict with 'purged', 'pending_deletion', and 'active' counts.
        """
        now = datetime.utcnow()
        expired_archives = ArchiveIndex.query.filter(
            ArchiveIndex.status == 'active',
            ArchiveIndex.deletion_date <= now,
            ArchiveIndex.deletion_date.isnot(None),
        ).all()

        purged_count = 0
        pending_count = 0

        for archive in expired_archives:
            archive.status = 'pending_deletion'
            archive.is_purgeable = True
            archive.save()
            pending_count += 1

            # Log audit
            self._log_audit(
                operation='retention_expired',
                document_id=archive.document_id,
                performed_by='system',
                status='success',
                metadata=json.dumps({
                    'retention_policy': archive.retention_policy,
                    'retention_days': archive.retention_days,
                }),
            )

        active_count = ArchiveIndex.query.filter_by(status='active').count()

        logger.info(
            "[ColdStorage] Retention enforcement: %d pending deletion, %d active",
            pending_count, active_count
        )

        return {
            'purged': purged_count,
            'pending_deletion': pending_count,
            'active': active_count,
        }

    def purge_expired_archives(self, batch_size: int = 100) -> dict:
        """
        Actually delete archives marked as pending_deletion.

        Args:
            batch_size: Maximum number of archives to purge in this run.

        Returns:
            dict with purge results.
        """
        to_purge = ArchiveIndex.query.filter_by(
            status='pending_deletion',
            is_purgeable=True,
        ).limit(batch_size).all()

        purged_ids = []
        error_ids = []

        for archive in to_purge:
            try:
                success = self.delete_archive(
                    archive.document_id,
                    deletion_reason='Retention policy expired'
                )
                if success:
                    purged_ids.append(archive.document_id)
                else:
                    error_ids.append(archive.document_id)
            except Exception as e:
                logger.error(
                    "[ColdStorage] Failed to purge archive %s: %s",
                    archive.document_id, str(e)
                )
                error_ids.append(archive.document_id)

        return {
            'purged': purged_ids,
            'failed': error_ids,
            'purged_count': len(purged_ids),
            'failed_count': len(error_ids),
        }

    def get_archive_stats(self) -> dict:
        """
        Get archive storage statistics.

        Returns:
            dict with storage metrics and compression statistics.
        """
        total_docs = ColdDocuments.query.count()
        active_archives = ArchiveIndex.query.filter_by(status='active').count()
        pending_deletion = ArchiveIndex.query.filter_by(status='pending_deletion').count()

        # Calculate storage metrics
        total_original_size = sum(d.original_size or 0 for d in ColdDocuments.query.all())
        total_compressed_size = sum(d.compressed_size or 0 for d in ColdDocuments.query.all())

        avg_compression_ratio = 0
        if total_original_size > 0:
            avg_compression_ratio = round(
                (1 - total_compressed_size / total_original_size) * 100, 2
            )

        # Retention policy distribution
        policy_dist = db.session.query(
            ArchiveIndex.retention_policy,
            db.func.count(ArchiveIndex.id)
        ).filter_by(status='active').group_by(ArchiveIndex.retention_policy).all()

        policy_distribution = {policy: count for policy, count in policy_dist}

        # Recent operations (last 24h)
        day_ago = datetime.utcnow() - timedelta(days=1)
        recent_ops = ArchiveAuditLog.query.filter(
            ArchiveAuditLog.timestamp >= day_ago
        ).count()

        return {
            'total_archived': total_docs,
            'active_archives': active_archives,
            'pending_deletion': pending_deletion,
            'total_original_size_bytes': total_original_size,
            'total_compressed_size_bytes': total_compressed_size,
            'average_compression_ratio': avg_compression_ratio,
            'policy_distribution': policy_distribution,
            'recent_operations_24h': recent_ops,
        }

    # -------------------------------------------------------------------------
    # Compression Helpers
    # -------------------------------------------------------------------------

    def _compress_content(self, content: str, compression_type: str) -> tuple:
        """
        Compress content using specified algorithm.

        Args:
            content: String content to compress.
            compression_type: 'gzip' or 'brotli'.

        Returns:
            Tuple of (compressed_bytes, compressed_size).
        """
        content_bytes = content.encode('utf-8')

        if compression_type == 'gzip':
            compressed = gzip.compress(content_bytes)
        elif compression_type == 'brotli':
            try:
                import brotli
                compressed = brotli.compress(content_bytes)
            except ImportError:
                logger.warning("[ColdStorage] brotli not available, falling back to gzip")
                compressed = gzip.compress(content_bytes)
        else:
            compressed = gzip.compress(content_bytes)

        return compressed, len(compressed)

    def _decompress_content(self, compressed_content: bytes, compression_type: str) -> str:
        """
        Decompress content using specified algorithm.

        Args:
            compressed_content: Compressed bytes.
            compression_type: 'gzip' or 'brotli'.

        Returns:
            Decompressed string content.
        """
        if compression_type == 'gzip':
            decompressed = gzip.decompress(compressed_content)
        elif compression_type == 'brotli':
            try:
                import brotli
                decompressed = brotli.decompress(compressed_content)
            except ImportError:
                logger.warning("[ColdStorage] brotli not available, trying gzip")
                decompressed = gzip.decompress(compressed_content)
        else:
            decompressed = gzip.decompress(compressed_content)

        return decompressed.decode('utf-8')

    def _generate_archive_path(self, document_id: str, timestamp: datetime) -> str:
        """
        Generate archive path with year/month directory structure.

        Args:
            document_id: Document ID.
            timestamp: Archive timestamp.

        Returns:
            Full path to archive file.
        """
        year = timestamp.strftime('%Y')
        month = timestamp.strftime('%m')
        filename = f"{document_id}.archive"
        return os.path.join(self.archive_base_path, year, month, filename)

    def _log_audit(
        self,
        operation: str,
        document_id: str,
        performed_by: str,
        status: str,
        compression_type: Optional[str] = None,
        original_size: Optional[int] = None,
        compressed_size: Optional[int] = None,
        error_message: Optional[str] = None,
        metadata: Optional[str] = None,
    ) -> None:
        """Log an audit entry."""
        try:
            audit_log = ArchiveAuditLog(
                operation=operation,
                document_id=document_id,
                performed_by=performed_by,
                compression_type=compression_type,
                original_size=original_size,
                compressed_size=compressed_size,
                status=status,
                error_message=error_message,
                metadata=metadata,
            )
            audit_log.save()
        except Exception as e:
            logger.error("[ColdStorage] Failed to log audit: %s", str(e))