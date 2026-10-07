# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared limits for paragraph producers and Codex batch consumers."""
BATCH_SIZE = 12
MAX_CHARS = 16000
CONCURRENCY = 8
LINGER = 0.35
TIMEOUT = 240
TRANSPORT = "HTTPS/SSE"
# Enough producer threads to supply eight full batches plus scheduling headroom.
PARAGRAPH_WORKERS = BATCH_SIZE * CONCURRENCY + 32
PARAGRAPH_QPS = 64
