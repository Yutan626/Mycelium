#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    
    # --- AUTOMATICALLY LOAD .ENV FOR HACKATHON ---
    try:
        from dotenv import load_dotenv
        # Looks up one level if manage.py is inside /backend but .env is at the root
        base_dir = Path(__file__).resolve().parent
        env_path = base_dir.parent / '.env' if (base_dir.parent / '.env').exists() else base_dir / '.env'
        load_dotenv(env_path)

    except ImportError:
        # If python-dotenv isn't installed yet, fail gracefully until pip install
        pass
    # ----------------------------------------------

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
