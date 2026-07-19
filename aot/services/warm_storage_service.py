# coding=utf-8
"""
WarmStorageService — Tier 2 (Warm) Document Storage Service.

Provides <1s response time for medium-frequency documents using SQLite with FTS5.

Features:
  - CRUD operations for warm documents
  - Full-text search via FTS5
  - Promotion/demotion between tiers
  - Section-level search support
  - Access frequency tracking
  - Async I/O support via aiosqlite

Ref: TIER_DECISION_LOGIC.md (ADS_TIER_001, v1.0, 2026-04-04)
Design: Adaptive Document Storage Architecture Section 3.2
"""
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import sqlite3

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Document:
    """Represents a document stored in warm storage."""
    doc_id: str
    title: str
    content: str
    tags: str = ""  # comma-separated
    tier_level: int = 2
    token_count: int = 0
    char_count: int = 0
    section_count: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_accessed: Optional[datetime] = None
    access_count: int = 0
    tier_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'doc_id': self.doc_id,
            'title': self.title,
            'content': self.content,
            'tags': self.tags,
            'tier_level': self.tier_level,
            'token_count': self.token_count,
            'char_count': self.char_count,
            'section_count': self.section_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_accessed': self.last_accessed.isoformat() if self.last_accessed else None,
            'access_count': self.access_count,
            'tier_score': self.tier_score,
        }


@dataclass
class SearchResult:
    """Represents a search result with ranking."""
    doc_id: str
    title: str
    snippet: str = ""
    rank: float = 0.0
    tags: str = ""
    tier_level: int = 2


@dataclass
class SectionSummary:
    """Represents a section summary within a document."""
    section_id: str
    doc_id: str
    section_index: int
    title: str
    summary: str
    keywords: str = ""
    created_at: Optional[datetime] = None


# =============================================================================
# WarmStorageService
# =============================================================================

class WarmStorageService:
    """
    Tier 2 (Warm) document storage service with <1s search SLA.

    Uses SQLite with FTS5 for full-text search capabilities.
    Supports async operations via aiosqlite for non-blocking I/O.

    @phase active
    @stability stable
    """

    # Schema version for migrations
    SCHEMA_VERSION = 1

    # FTS5 table name
    FTS_TABLE = "warm_documents_fts"

    def __init__(self, db_path: str):
        """
        Initialize WarmStorageService.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_database()
        logger.info(f"WarmStorageService initialized: {db_path}")

    def _ensure_db_directory(self) -> None:
        """Ensure the database directory exists."""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Database Initialization
    # =========================================================================

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper settings."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    def _init_database(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Create warm_documents table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS warm_documents (
                    doc_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    tier_level INTEGER DEFAULT 2,
                    token_count INTEGER DEFAULT 0,
                    char_count INTEGER DEFAULT 0,
                    section_count INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed TEXT,
                    access_count INTEGER DEFAULT 0,
                    tier_score REAL DEFAULT 0.0
                )
            """)

            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_warm_documents_tier
                ON warm_documents(tier_level)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_warm_documents_last_accessed
                ON warm_documents(last_accessed)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_warm_documents_tier_score
                ON warm_documents(tier_score)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_warm_documents_tags
                ON warm_documents(tags)
            """)

            # Create FTS5 virtual table for full-text search (simple mode)
            cursor.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {self.FTS_TABLE} USING fts5(
                    doc_id,
                    title,
                    content,
                    tags
                )
            """)

            # Create section_summaries table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS section_summaries (
                    section_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    section_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    keywords TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (doc_id) REFERENCES warm_documents(doc_id)
                        ON DELETE CASCADE
                )
            """)

            # Create indexes for section_summaries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_section_doc_id
                ON section_summaries(doc_id)
            """)

            # Create transition_log table for audit trail
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS warm_transition_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    from_tier INTEGER NOT NULL,
                    to_tier INTEGER NOT NULL,
                    reason TEXT DEFAULT '',
                    transition_type TEXT DEFAULT 'evaluated',
                    triggered_by TEXT DEFAULT 'system',
                    timestamp TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_transition_doc_id
                ON warm_transition_log(doc_id)
            """)

            # Create schema version table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS warm_storage_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            # Set initial schema version
            cursor.execute("""
                INSERT OR IGNORE INTO warm_storage_meta (key, value)
                VALUES ('schema_version', ?)
            """, (str(self.SCHEMA_VERSION),))

            conn.commit()
            logger.info("Warm storage database initialized successfully")

        except Exception as exc:
            logger.error(f"Database initialization failed: {exc}")
            conn.rollback()
            raise
        finally:
            conn.close()

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def get(self, doc_id: str) -> Optional[Document]:
        """
        Retrieve a document by ID.

        Args:
            doc_id: Document unique ID

        Returns:
            Document object or None if not found
        """
        start_time = time.time()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM warm_documents WHERE doc_id = ?",
                (doc_id,)
            )
            row = cursor.fetchone()

            if row:
                # Update last accessed time
                now = datetime.utcnow().isoformat()
                cursor.execute(
                    "UPDATE warm_documents SET last_accessed = ?, access_count = access_count + 1 WHERE doc_id = ?",
                    (now, doc_id)
                )
                conn.commit()

                return self._row_to_document(row)
            return None

        finally:
            conn.close()
            elapsed = time.time() - start_time
            logger.debug(f"get({doc_id}) completed in {elapsed*1000:.2f}ms")

    def set(self, doc_id: str, document: Document) -> None:
        """
        Insert or update a document.

        Args:
            doc_id: Document unique ID
            document: Document object to store
        """
        start_time = time.time()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()

            # Calculate token count from content if not provided
            token_count = document.token_count or len(document.content) // 4
            char_count = document.char_count or len(document.content)

            cursor.execute("""
                INSERT OR REPLACE INTO warm_documents
                (doc_id, title, content, tags, tier_level, token_count, char_count,
                 section_count, created_at, updated_at, last_accessed, access_count, tier_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                doc_id,
                document.title,
                document.content,
                document.tags,
                document.tier_level,
                token_count,
                char_count,
                document.section_count,
                document.created_at.isoformat() if document.created_at else now,
                now,
                now,
                document.access_count,
                document.tier_score,
            ))

            # Update FTS index - delete then insert to handle updates properly
            cursor.execute(f"DELETE FROM {self.FTS_TABLE} WHERE doc_id = ?", (doc_id,))
            cursor.execute(f"""
                INSERT INTO {self.FTS_TABLE}(doc_id, title, content, tags)
                VALUES (?, ?, ?, ?)
            """, (doc_id, document.title, document.content, document.tags))

            conn.commit()

        except Exception as exc:
            logger.error(f"set({doc_id}) failed: {exc}")
            conn.rollback()
            raise
        finally:
            conn.close()
            elapsed = time.time() - start_time
            logger.debug(f"set({doc_id}) completed in {elapsed*1000:.2f}ms")

    def delete(self, doc_id: str) -> None:
        """
        Delete a document by ID.

        Args:
            doc_id: Document unique ID
        """
        start_time = time.time()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Delete from FTS index
            cursor.execute(f"DELETE FROM {self.FTS_TABLE} WHERE doc_id = ?", (doc_id,))

            # Delete from main table
            cursor.execute("DELETE FROM warm_documents WHERE doc_id = ?", (doc_id,))

            # Delete section summaries
            cursor.execute("DELETE FROM section_summaries WHERE doc_id = ?", (doc_id,))

            conn.commit()
            logger.info(f"Deleted document: {doc_id}")

        except Exception as exc:
            logger.error(f"delete({doc_id}) failed: {exc}")
            conn.rollback()
            raise
        finally:
            conn.close()
            elapsed = time.time() - start_time
            logger.debug(f"delete({doc_id}) completed in {elapsed*1000:.2f}ms")

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search(self, query: str, limit: int = 10, tags_filter: Optional[str] = None) -> List[SearchResult]:
        """
        Search documents using FTS5 full-text search.

        Achieves <1s SLA through:
          - FTS5 optimized queries
          - Indexed columns
          - LIMIT clause

        Args:
            query: Search query string
            limit: Maximum number of results (default 10)
            tags_filter: Optional comma-separated tags to filter by

        Returns:
            List of SearchResult objects ranked by relevance
        """
        start_time = time.time()

        # Sanitize query for FTS5
        fts_query = self._sanitize_fts_query(query)
        if not fts_query:
            return []

        conn = self._get_connection()
        results = []
        try:
            cursor = conn.cursor()

            try:
                # Build search query with ranking
                if tags_filter:
                    # Search with tags filter using FTS5
                    cursor.execute(f"""
                        SELECT w.doc_id, w.title, w.tags, w.tier_level,
                               snippet({self.FTS_TABLE}, 2, '<b>', '</b>', '...', 32) as snippet,
                               bm25({self.FTS_TABLE}) as rank
                        FROM {self.FTS_TABLE}
                        JOIN warm_documents w ON {self.FTS_TABLE}.doc_id = w.doc_id
                        WHERE {self.FTS_TABLE} MATCH ?
                        AND w.tags LIKE ?
                        ORDER BY rank
                        LIMIT ?
                    """, (fts_query, f"%{tags_filter}%", limit))
                else:
                    # Search without tags filter using FTS5
                    cursor.execute(f"""
                        SELECT w.doc_id, w.title, w.tags, w.tier_level,
                               snippet({self.FTS_TABLE}, 2, '<b>', '</b>', '...', 32) as snippet,
                               bm25({self.FTS_TABLE}) as rank
                        FROM {self.FTS_TABLE}
                        JOIN warm_documents w ON {self.FTS_TABLE}.doc_id = w.doc_id
                        WHERE {self.FTS_TABLE} MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """, (fts_query, limit))

                for row in cursor.fetchall():
                    results.append(SearchResult(
                        doc_id=row['doc_id'],
                        title=row['title'],
                        snippet=row['snippet'] or "",
                        rank=abs(row['rank']) if row['rank'] else 0.0,
                        tags=row['tags'] or "",
                        tier_level=row['tier_level'],
                    ))

            except Exception as exc:
                logger.error(f"FTS search failed: {exc}, falling back to LIKE search")
                # Fallback to LIKE-based search
                cursor.execute("""
                    SELECT doc_id, title, tags, tier_level,
                           SUBSTR(content, 1, 100) as snippet,
                           0.0 as rank
                    FROM warm_documents
                    WHERE content LIKE ? OR title LIKE ?
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", limit))

                for row in cursor.fetchall():
                    results.append(SearchResult(
                        doc_id=row['doc_id'],
                        title=row['title'],
                        snippet=row['snippet'] or "",
                        rank=row['rank'],
                        tags=row['tags'] or "",
                        tier_level=row['tier_level'],
                    ))

        finally:
            conn.close()
            elapsed = time.time() - start_time
            if elapsed > 1.0:
                logger.warning(f"Search exceeded 1s SLA: {elapsed*1000:.2f}ms")
            else:
                logger.debug(f"search('{query}', limit={limit}) returned {len(results)} results in {elapsed*1000:.2f}ms")
            return results

    def _sanitize_fts_query(self, query: str) -> str:
        """Sanitize query for FTS5 safety."""
        if not query:
            return ""
        # Remove special FTS5 operators except + and "
        sanitized = query.replace('"', '""').strip()
        # Split into terms and add + prefix for AND behavior
        terms = sanitized.split()
        if not terms:
            return ""
        # Use simple match without special operators for safety
        return " ".join(f'"{t}"' for t in terms if t)

    def _row_to_document(self, row: sqlite3.Row) -> Document:
        """Convert a database row to a Document object."""
        return Document(
            doc_id=row['doc_id'],
            title=row['title'],
            content=row['content'],
            tags=row['tags'] or "",
            tier_level=row['tier_level'],
            token_count=row['token_count'],
            char_count=row['char_count'],
            section_count=row['section_count'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
            last_accessed=datetime.fromisoformat(row['last_accessed']) if row['last_accessed'] else None,
            access_count=row['access_count'],
            tier_score=row['tier_score'],
        )

    # =========================================================================
    # Section Operations
    # =========================================================================

    def add_section_summary(self, section: SectionSummary) -> None:
        """
        Add a section summary to a document.

        Args:
            section: SectionSummary object to store
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()

            cursor.execute("""
                INSERT OR REPLACE INTO section_summaries
                (section_id, doc_id, section_index, title, summary, keywords, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                section.section_id,
                section.doc_id,
                section.section_index,
                section.title,
                section.summary,
                section.keywords,
                section.created_at.isoformat() if section.created_at else now,
            ))

            conn.commit()

        except Exception as exc:
            logger.error(f"add_section_summary failed: {exc}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_section_summaries(self, doc_id: str) -> List[SectionSummary]:
        """
        Get all section summaries for a document.

        Args:
            doc_id: Document unique ID

        Returns:
            List of SectionSummary objects
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM section_summaries
                WHERE doc_id = ?
                ORDER BY section_index
            """, (doc_id,))

            results = []
            for row in cursor.fetchall():
                results.append(SectionSummary(
                    section_id=row['section_id'],
                    doc_id=row['doc_id'],
                    section_index=row['section_index'],
                    title=row['title'],
                    summary=row['summary'],
                    keywords=row['keywords'] or "",
                    created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
                ))
            return results

        finally:
            conn.close()

    def search_sections(self, query: str, limit: int = 10) -> List[SearchResult]:
        """
        Search within section summaries.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of SearchResult objects with section-level matches
        """
        start_time = time.time()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT doc_id, title, summary as content, keywords as tags, 2 as tier_level, 0.0 as rank
                FROM section_summaries
                WHERE summary LIKE ? OR title LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))

            results = []
            for row in cursor.fetchall():
                results.append(SearchResult(
                    doc_id=row['doc_id'],
                    title=row['title'],
                    snippet=row['content'][:200] + "..." if len(row['content']) > 200 else row['content'],
                    rank=row['rank'],
                    tags=row['tags'] or "",
                    tier_level=row['tier_level'],
                ))

            return results

        finally:
            conn.close()
            elapsed = time.time() - start_time
            logger.debug(f"search_sections completed in {elapsed*1000:.2f}ms")

    # =========================================================================
    # Tier Transition Operations
    # =========================================================================

    def promote_to_tier1(self, doc_id: str) -> bool:
        """
        Promote a document from Tier 2 to Tier 1.

        Args:
            doc_id: Document unique ID

        Returns:
            True if promotion succeeded, False if document not found or already at Tier 1
        """
        return self._transition_tier(doc_id, from_tier=2, to_tier=1, reason="promotion", transition_type="promotion")

    def demote_to_tier3(self, doc_id: str) -> bool:
        """
        Demote a document from Tier 2 to Tier 3.

        Args:
            doc_id: Document unique ID

        Returns:
            True if demotion succeeded, False if document not found or already at Tier 3
        """
        return self._transition_tier(doc_id, from_tier=2, to_tier=3, reason="demotion", transition_type="demotion")

    def _transition_tier(
        self,
        doc_id: str,
        from_tier: int,
        to_tier: int,
        reason: str = "",
        transition_type: str = "evaluated",
        triggered_by: str = "system"
    ) -> bool:
        """
        Execute a tier transition with audit logging.

        Args:
            doc_id: Document unique ID
            from_tier: Current tier level
            to_tier: Target tier level
            reason: Reason for transition
            transition_type: Type of transition ('promotion', 'demotion', 'evaluated', 'manual')
            triggered_by: Who triggered the transition ('system', 'manual', 'scheduled')

        Returns:
            True if transition succeeded
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()

            # Get current tier
            cursor.execute("SELECT tier_level FROM warm_documents WHERE doc_id = ?", (doc_id,))
            row = cursor.fetchone()

            if not row:
                logger.warning(f"Document not found for tier transition: {doc_id}")
                return False

            current_tier = row['tier_level']
            if current_tier != from_tier:
                logger.warning(f"Document {doc_id} is at tier {current_tier}, expected {from_tier}")
                return False

            # Update tier level
            cursor.execute(
                "UPDATE warm_documents SET tier_level = ?, updated_at = ? WHERE doc_id = ?",
                (to_tier, now, doc_id)
            )

            # Log transition
            cursor.execute("""
                INSERT INTO warm_transition_log
                (doc_id, from_tier, to_tier, reason, transition_type, triggered_by, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (doc_id, from_tier, to_tier, reason, transition_type, triggered_by, now))

            conn.commit()
            logger.info(f"Document {doc_id} transitioned: Tier {from_tier} -> {to_tier} ({reason})")
            return True

        except Exception as exc:
            logger.error(f"Tier transition failed for {doc_id}: {exc}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_transition_history(self, doc_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get tier transition history for a document.

        Args:
            doc_id: Document unique ID
            limit: Maximum number of records

        Returns:
            List of transition records
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM warm_transition_log
                WHERE doc_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (doc_id, limit))

            results = []
            for row in cursor.fetchall():
                results.append({
                    'doc_id': row['doc_id'],
                    'from_tier': row['from_tier'],
                    'to_tier': row['to_tier'],
                    'reason': row['reason'],
                    'transition_type': row['transition_type'],
                    'triggered_by': row['triggered_by'],
                    'timestamp': row['timestamp'],
                })
            return results

        finally:
            conn.close()

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def get_documents_by_tier(self, tier: int, limit: int = 100, offset: int = 0) -> List[Document]:
        """
        Get documents by tier level with pagination.

        Args:
            tier: Tier level (1, 2, or 3)
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of Document objects
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM warm_documents
                WHERE tier_level = ?
                ORDER BY tier_score DESC, last_accessed DESC
                LIMIT ? OFFSET ?
            """, (tier, limit, offset))

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_document(row))
            return results

        finally:
            conn.close()

    def get_documents_needing_reclassification(self, window_hours: int = 168) -> List[Document]:
        """
        Get documents that haven't been accessed within the window.

        Args:
            window_hours: Window in hours (default 168 = 7 days)

        Returns:
            List of Document objects needing tier evaluation
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cutoff = (datetime.utcnow() - timedelta(hours=window_hours)).isoformat()

            cursor.execute("""
                SELECT * FROM warm_documents
                WHERE last_accessed IS NULL OR last_accessed < ?
                ORDER BY last_accessed ASC
                LIMIT 100
            """, (cutoff,))

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_document(row))
            return results

        finally:
            conn.close()

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        Get warm storage statistics.

        Returns:
            Dictionary with database statistics
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Total documents
            cursor.execute("SELECT COUNT(*) as count FROM warm_documents")
            total_docs = cursor.fetchone()['count']

            # Documents by tier
            cursor.execute("""
                SELECT tier_level, COUNT(*) as count
                FROM warm_documents
                GROUP BY tier_level
            """)
            tier_counts = {row['tier_level']: row['count'] for row in cursor.fetchall()}

            # Average access count
            cursor.execute("SELECT AVG(access_count) as avg FROM warm_documents")
            avg_access = cursor.fetchone()['avg'] or 0

            # Database size
            db_path = Path(self.db_path)
            db_size = db_path.stat().st_size if db_path.exists() else 0

            # Section count
            cursor.execute("SELECT COUNT(*) as count FROM section_summaries")
            total_sections = cursor.fetchone()['count']

            # Total transitions
            cursor.execute("SELECT COUNT(*) as count FROM warm_transition_log")
            total_transitions = cursor.fetchone()['count']

            return {
                'total_documents': total_docs,
                'tier_distribution': tier_counts,
                'average_access_count': round(avg_access, 2),
                'database_size_bytes': db_size,
                'database_size_mb': round(db_size / (1024 * 1024), 2),
                'total_sections': total_sections,
                'total_transitions': total_transitions,
            }

        finally:
            conn.close()

    def get_top_accessed(self, limit: int = 10) -> List[Document]:
        """
        Get most frequently accessed documents.

        Args:
            limit: Maximum number of results

        Returns:
            List of Document objects
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM warm_documents
                ORDER BY access_count DESC
                LIMIT ?
            """, (limit,))

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_document(row))
            return results

        finally:
            conn.close()


# =============================================================================
# Async Support (optional aiosqlite)
# =============================================================================

try:
    import aiosqlite

    class AsyncWarmStorageService:
        """
        Async version of WarmStorageService using aiosqlite.

        Provides non-blocking I/O for high-concurrency scenarios.
        """

        def __init__(self, db_path: str):
            self.db_path = db_path

        async def init_database(self) -> None:
            """Initialize database schema asynchronously."""
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                # Run schema creation
                await db.commit()

        async def get(self, doc_id: str) -> Optional[Document]:
            """Async get operation."""
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM warm_documents WHERE doc_id = ?", (doc_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return Document(
                            doc_id=row['doc_id'],
                            title=row['title'],
                            content=row['content'],
                            tags=row['tags'] or "",
                            tier_level=row['tier_level'],
                            token_count=row['token_count'],
                            char_count=row['char_count'],
                            section_count=row['section_count'],
                            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
                            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
                            last_accessed=datetime.fromisoformat(row['last_accessed']) if row['last_accessed'] else None,
                            access_count=row['access_count'],
                            tier_score=row['tier_score'],
                        )
                    return None

        async def set(self, doc_id: str, document: Document) -> None:
            """Async set operation."""
            async with aiosqlite.connect(self.db_path) as db:
                now = datetime.utcnow().isoformat()
                await db.execute("""
                    INSERT OR REPLACE INTO warm_documents
                    (doc_id, title, content, tags, tier_level, token_count, char_count,
                     section_count, created_at, updated_at, last_accessed, access_count, tier_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_id, document.title, document.content, document.tags,
                    document.tier_level, document.token_count, document.char_count,
                    document.section_count, now, now, now,
                    document.access_count, document.tier_score,
                ))
                await db.commit()

        async def search(self, query: str, limit: int = 10) -> List[SearchResult]:
            """Async search operation."""
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    f"SELECT doc_id, title, content, tags, tier_level FROM warm_documents WHERE content LIKE ? LIMIT ?",
                    (f"%{query}%", limit)
                ) as cursor:
                    results = []
                    async for row in cursor:
                        results.append(SearchResult(
                            doc_id=row['doc_id'],
                            title=row['title'],
                            snippet=row['content'][:200] + "..." if len(row['content']) > 200 else row['content'],
                            rank=0.0,
                            tags=row['tags'] or "",
                            tier_level=row['tier_level'],
                        ))
                    return results

except ImportError:
    # aiosqlite not available, sync-only version
    AsyncWarmStorageService = None
    logger.debug("aiosqlite not available, async support disabled")


# =============================================================================
# Service Factory
# =============================================================================

def create_warm_storage_service(db_path: Optional[str] = None) -> WarmStorageService:
    """
    Factory function to create WarmStorageService.

    Args:
        db_path: Optional custom database path.
                 Defaults to warm_storage.db in data directory.

    Returns:
        WarmStorageService instance
    """
    if db_path is None:
        import os
        data_dir = os.path.expanduser("~/.foreman/data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "warm_storage.db")

    return WarmStorageService(db_path)