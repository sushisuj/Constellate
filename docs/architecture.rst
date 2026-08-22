Architecture
=============

.. todo::
   One-paragraph summary of the shape of the system.

Architecture Diagram
---------------------

.. figure:: /_static/architecture.png
   :alt: Constellate component diagram -- client panels and services,
         server routes and internal services, persistence, and the two
         external NVIDIA-hosted dependencies, with every real call
         between them drawn as an arrow.
   :width: 100%

   Every arrow here is a real call verified against the source, not a
   sketch -- traced flow by flow: upload, ask, the four admin routes
   (list/remove/clear/reset), and sentiment, which deliberately bypasses
   Orchestration Service entirely rather than being routed through it
   like everything else. Two boxes are correctly disconnected on
   purpose: Health Route (a liveness check the frontend doesn't call
   today) and Constellation Panel (decorative -- it renders vocabulary
   already fetched by Upload Service/Uploads List Service for other
   reasons, rather than calling anything itself).

Frontend Layer
---------------

.. todo::
   React/Vite chat UI, what it owns.

Backend Layer
--------------

.. todo::
   FastAPI orchestrator, what it owns.

Persistence Layer
-------------------

.. todo::
   Per-upload Chroma collections under data/uploads/, meta.json, reload on
   startup.

Architectural Changes
-----------------------

.. todo::
   The knowledge-graph -> RAG pipeline pivot, model choice, why ingestion
   got folded into one service, ephemeral -> persistent uploads. Most of
   this is already written, just needs restructuring from the two
   existing READMEs.
