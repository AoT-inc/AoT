"""
Memory profiler for AoT_ai
Tracks memory usage and provides snapshots for optimization analysis
"""
import tracemalloc
import logging
import psutil
import os
from datetime import datetime

logger = logging.getLogger(__name__)


class MemoryProfiler:
    """메모리 사용량 프로파일링"""

    @staticmethod
    def start_profiling():
        """프로파일링 시작"""
        tracemalloc.start()
        logger.info("[MemoryProfiler] Started")

    @staticmethod
    def take_snapshot():
        """현재 메모리 스냅샷"""
        if not tracemalloc.is_tracing():
            return None

        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('lineno')

        # 프로세스 메모리
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()

        report = {
            'timestamp': datetime.now().isoformat(),
            'rss_mb': mem_info.rss / 1024 / 1024,
            'vms_mb': mem_info.vms / 1024 / 1024,
            'top_allocations': []
        }

        for stat in top_stats[:20]:
            report['top_allocations'].append({
                'file': stat.traceback.format()[0],
                'size_mb': stat.size / 1024 / 1024,
                'count': stat.count
            })

        return report

    @staticmethod
    def log_snapshot():
        """스냅샷을 로그에 기록"""
        report = MemoryProfiler.take_snapshot()
        if report:
            logger.info(f"[MemoryProfiler] RSS: {report['rss_mb']:.2f}MB, VMS: {report['vms_mb']:.2f}MB")
            for alloc in report['top_allocations'][:5]:
                logger.info(f"  - {alloc['file']}: {alloc['size_mb']:.2f}MB ({alloc['count']} objects)")
