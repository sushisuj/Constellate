Backend
========

.. todo::
   What the orchestrator service is responsible for.

Backend Responsibilities
---------------------------

.. todo::
   Upload, retrieval, generation, session/memory -- all one service.

Pipeline
----------

.. todo::
   Upload -> chunk -> embed -> retrieve -> compose. Point to chunker.py,
   store.py, llm.py.

Retrieval and Ranking
------------------------

.. todo::
   No scope gate -- why (see retriever.py's own docstring). Similarity +
   lexical overlap + topic-continuity scoring.

Guardrails
------------

.. todo::
   guardrails.py -- input injection blocking, output groundedness/
   safety/format checks. Why rule-based, not a second LLM call. The
   context-is-data-not-instructions prompt hardening in llm.py as the
   complementary indirect-injection defense.

Persistence
-------------

.. todo::
   data/uploads/<id>/ layout, meta.json, reload-on-startup logic in
   Assistant.__init__.
