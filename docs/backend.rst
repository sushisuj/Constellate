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

Persistence
-------------

.. todo::
   data/uploads/<id>/ layout, meta.json, reload-on-startup logic in
   Assistant.__init__.
