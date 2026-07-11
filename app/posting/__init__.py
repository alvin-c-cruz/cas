"""Shared journal-entry posting primitives.

A thin service layer sitting *below* the feature views: it holds the
behaviour-preserving building blocks that the AP / SI / CDV / CRV posting paths
(and the sales credit/debit memos) all share, so the money-path algorithms live
in one place instead of six near-copies. See `buckets.py`.
"""
