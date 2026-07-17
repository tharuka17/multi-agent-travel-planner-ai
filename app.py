"""
Entrypoint for Hugging Face Spaces, which expects an `app.py` at the repo root.
Delegates to the real frontend implementation in frontend.py so there's only
one copy of the UI logic to maintain.
"""

from frontend import main

if __name__ == "__main__":
    main()
