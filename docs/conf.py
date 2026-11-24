from importlib.metadata import version as installed_version
import posixpath


project = "megalibpy"
author = "Yong Sheng"
release = installed_version(project)

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "nbsphinx",
    "sphinxcontrib.mermaid",
]

exclude_patterns = ["_build", "**/.ipynb_checkpoints", "**/.DS_Store"]
html_theme = "sphinx_rtd_theme"
autoclass_content = "both"
autodoc_member_order = "bysource"
nbsphinx_execute = "never"

# English stays at the existing URLs; Chinese shares the same document names.
language = "en"
locale_dirs = ["locales/"]
gettext_compact = False
templates_path = ["_templates"]
html_static_path = ["_static"]
html_css_files = ["languages.css", "diagrams.css"]
html_js_files = ["diagrams.js"]
# Match the renderer and light theme used by SiYuan.
mermaid_version = "12.2.0"
mermaid_config = {
    "theme": "default",
    "look": "classic",
    # SiYuan's native shadow; embed it in every SVG, before any page enhancement.
    "themeCSS": ".node .label-container { filter: drop-shadow(1px 2px 2px #b9b9b9); }",
    "securityLevel": "strict",
    "fontFamily": "sans-serif",
    "altFontFamily": "sans-serif",
    "htmlLabels": False,
    "flowchart": {
        "curve": "rounded", "htmlLabels": False, "useMaxWidth": True,
        "wrappingWidth": 220, "padding": 24,
        "subGraphTitleMargin": {"top": 12, "bottom": 12},
    },
}


def language_links(app, pagename, templatename, context, doctree):
    """Keep page names and relative deployment prefixes when switching language."""
    chinese = app.config.language == "zh_CN"
    page = pagename + ".html"
    directory = posixpath.dirname(page) or "."
    root = posixpath.relpath("index.html", directory)[:-len("index.html")]
    context["documentation_language"] = "zh_CN" if chinese else "en"
    context["english_url"] = root + ("../" if chinese else "") + page
    context["chinese_url"] = root + ("" if chinese else "zh_CN/") + page


def setup(app):
    app.connect("html-page-context", language_links)
