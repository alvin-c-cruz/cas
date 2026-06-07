"""
Database seeding package.

This package contains seed data for initializing the database with
default values needed for the application to function properly.
"""

from app.seeds.seed_data import seed_all

__all__ = ['seed_all']
