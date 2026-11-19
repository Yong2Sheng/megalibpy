from importlib.metadata import version as installed_version


project = "megalibpy"
author = "Yong Sheng"
release = installed_version(project)

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "nbsphinx",
]

exclude_patterns = ["_build", "**/.ipynb_checkpoints", "**/.DS_Store"]
html_theme = "sphinx_rtd_theme"
autoclass_content = "both"
autodoc_member_order = "bysource"
nbsphinx_execute = "never"
