Documentation languages
=======================

English is the default language at the existing site URLs. Simplified Chinese
is published under ``zh_CN/``. Use **English · 简体中文** in the sidebar to switch
to the same page in the other language. Each language has its own search index.
The switch also works inside an isolated PR preview and does not send readers
to the published version of an unmerged page.

The guides, tutorial index and API prose are translated. Python identifiers,
signatures, type expressions, native configuration names, literal units, code
examples and notebook contents are shared unchanged. Both language sites offer
the original English notebooks for download. Translated pages do not execute
the notebooks or load PyROOT into the documentation process.

Build both languages
--------------------

From the repository root, activate the development environment, install the
package, and run:

.. code-block:: bash

   python docs/build.py docs/_build/html

The build checks translation coverage, then builds English at the output root
and Chinese in ``zh_CN/``, with separate Sphinx doctrees and strict warnings.
Serve the combined directory to test both language links:

.. code-block:: bash

   python -m http.server --directory docs/_build/html 8000

For an individual language during editing, use Sphinx directly:

.. code-block:: bash

   sphinx-build -W -b html -D language=zh_CN docs docs/_build/zh-only

Maintain translations
---------------------

English reStructuredText and Python docstrings remain the source of truth.
Chinese translations live in ``docs/locales/zh_CN/LC_MESSAGES/*.po``, including
the nested ``api/index.po`` and ``tutorials/index.po`` catalogs. Sphinx uses
gettext to translate prose while preserving document names and API anchors.
Notebook catalogs are deliberately omitted.

Extract current messages before updating a translation:

.. code-block:: bash

   sphinx-build -b gettext docs docs/_build/gettext

Compare the generated catalogs with the matching PO files, retain the original
``msgid`` exactly and update the Chinese ``msgstr``. Preserve cross-reference
roles, links, math and inline markup; keep type expressions unchanged so their
API references still resolve. Do not mark unreviewed translations as complete.
The combined build rejects missing, empty or fuzzy translations outside notebooks,
so changed guide/API prose must be accompanied by its Chinese translation.
Compiled MO files and generated POT files are build products and are not committed.

Architecture diagrams
---------------------

The :doc:`architecture` page uses native Mermaid diagrams. Shared graph structure
is maintained in ``docs/diagrams/*.mmd``; matching ``*.zh_CN.mmd`` files translate
node and edge labels. Update both variants when changing a diagram's meaning.
The Mermaid extension selects the language-specific source automatically;
diagram labels are not taken from the PO catalogs.

HTML diagrams render in the browser using Mermaid 12.2.0 from jsDelivr.
Reading diagrams requires JavaScript and access to that CDN. Strict Sphinx builds
check document integration; also check the rendered diagrams in a browser after
editing graph syntax. Mermaid is a documentation dependency, not a megalibpy
runtime dependency, and does not execute the scientific examples.

Publishing
----------

CI validates and packages both languages together. The regular GitHub Pages site
is deployed from ``develop`` after merge. Feature branches can publish only an
explicitly selected, marked PR preview; both language variants carry its source
commit and unmerged notice. A local build does not update the online site.
