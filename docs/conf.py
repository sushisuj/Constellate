"""Sphinx configuration for the Constellate documentation.

Structure and theme (Furo, on ReadTheDocs) modeled on the SimplyServe
docs -- see the project README for why: it's a documentation structure
that's already been assessed and scored well, so there was no reason to
invent a different shape from scratch.
"""

project = "Constellate"
copyright = "2026, Sujan"
author = "Sujan"
release = "0.1"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.todo",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_static_path = ["_static"]

# Surfaces `.. todo::` markers in the build instead of silently dropping
# them -- useful while pages are still stubs.
todo_include_todos = True
