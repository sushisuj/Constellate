API Reference
==============

.. todo::
   One-paragraph summary of what the API covers.

Upload Endpoints
-------------------

.. todo::
   POST /upload, GET /uploads, POST /uploads/remove, POST /uploads/clear.
   Follow the SimplyServe per-endpoint shape: Purpose / Auth Required? /
   Input / Success Behaviour / Error Cases / Frontend Feature That Uses
   It.

Ask Endpoint
--------------

.. todo::
   POST /ask -- same per-endpoint shape as above. Cover the flags field
   (``blocked_injection``, ``low_groundedness``, ``unsafe_word:<word>``,
   etc.) and how a blocked question short-circuits before retrieval/
   generation -- see guardrails.py.

Session Endpoints
--------------------

.. todo::
   POST /reset.

API Error Handling
----------------------

.. todo::
   Common error responses (400/404/502), CORS allowlist note.
