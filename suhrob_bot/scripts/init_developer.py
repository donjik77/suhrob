"""Compatibility entry point for initial developer/company setup.

Run:
    python scripts/init_developer.py
"""
import asyncio

from scripts.init import main


if __name__ == "__main__":
    asyncio.run(main())
