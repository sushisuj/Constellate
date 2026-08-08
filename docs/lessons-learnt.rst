Lessons Learnt
================

This page is a straight account of what building Constellate actually
taught me, technical and otherwise. Not a list of buzzwords for a CV. The specific mistakes, dead ends, and fixes that happened along the way.

Picking the right model isn't optional, it's the whole game
----------------------------------------------------------------

The first version of Constellate tried to build a knowledge graph:
extract entities and relationships out of every document, then answer
questions by walking the graph. It fell apart on one thing —
``nemotron-3-ultra-550b-a55b`` took around two minutes per chunk to pull
entities out. Not because the task was hard, but because it's a
reasoning model, and reasoning models burn a load of hidden tokens
thinking before they ever write an answer, whether the question needs
that or not. I'd hit the exact same wall on the sibling Chatbot project
with a different reasoning model (``openai/gpt-oss-120b``, 43 to over
400 seconds a response) before I ever started Constellate, so by the
time it showed up again the pattern was obvious instead of mysterious.
Swapping to a plain instruct model (``meta/llama-3.1-8b-instruct``) took
the same kind of job down to under 15 seconds, most of it under 2.
That's the lesson: for a latency-sensitive app, the model you pick
matters more than almost any other decision, and "reasoning" isn't a
free upgrade, it's a real cost you're choosing to pay.

Knowing when to drop an idea instead of debugging it further
-------------------------------------------------------------

The knowledge-graph direction wasn't just slow, it was slow for a reason
baked into the approach itself. Extracting a graph means the model has
to think before answering, every time. No amount of prompt tweaking was
going to fix that. The actual fix was admitting the whole direction was
wrong and starting over on a pipeline that was already proven to work
(the RAG pipeline from Chatbot, chunk → embed → retrieve → compose, no
graph at all). That was a harder call to make than any of the code that
followed it. Recognising "this isn't a bug, it's the design" and being
willing to throw away real work rather than keep patching it is probably
the single most useful thing I got out of this project.

RAG is mostly just good plumbing
------------------------------------

Once the graph was gone, what replaced it wasn't complicated (chunking,
embedding, retrieval scoring) but getting each piece right
actually mattered. Heading-based chunking when a document has real
structure, falling back to fixed-size overlapping windows when it
doesn't. Local embeddings (ONNX MiniLM) instead of paying an API call
per chunk just to turn text into vectors. Retrieval scored on cosine
similarity plus lexical word overlap plus a small same-document boost
for follow-up questions, not similarity alone. None of it is
sophisticated on its own, but the difference between a demo that
technically retrieves something and one that retrieves the *right* thing
lives entirely in these small scoring decisions.

Shared backends leak data if you're not paying attention
-------------------------------------------------------------

The old ingestion service kept one Chroma collection shared across every
document anyone had ever uploaded. That meant one person's uploaded
document was technically retrievable from someone else's questions — a
real data leak, not a hypothetical one. The fix was giving every upload
its own collection in its own directory. It's an obvious fix once you've
spotted the problem, but I hadn't gone looking for it, it turned up
because I was thinking about the shape of the storage, not because a
test caught it. Worth remembering: "it works when I test it" and "it's
safe with more than one user" are different questions.

A demo and something that survives a restart are different projects
-------------------------------------------------------------------------

Uploads originally lived in a ``tempfile.TemporaryDirectory()`` perfectly fine
for proving the pipeline worked, gone the second the process restarted.
Making it actually persist meant a real on-disk layout
(``data/uploads/<id>/`` holding a Chroma collection plus a small
``meta.json``) and code that reconstructs everything but the retriever
object from that metadata on startup. It's a small amount of code. It's
also the difference between "I built a thing" and "I built a thing you
could actually use."

Uploaded documents are an attack surface, not just data
--------------------------------------------------------------

This one didn't occur to me until I sat down to add guardrails: any text
that ends up inside an LLM's context is a place someone (or some
document) could try to plant an instruction like: "ignore the above and say
X" and the model has no built-in way to tell a legitimate sentence
from a hijack attempt. Constellate takes arbitrary uploaded documents and
stuffs their text straight into the prompt, so that's not a theoretical
risk here. I ended up with two different defenses for two different
surfaces: a live typed question is short and came from a real person, so
it's safe to block outright on suspicious phrasing; a chunk of an
uploaded document might legitimately contain a sentence that reads like
an instruction, so blocking isn't safe there, and the better fix is
telling the model explicitly to treat all of it as data, never as
commands. Same underlying problem, two different fixes, because the two
inputs aren't actually the same kind of thing even though they both end
up in the same prompt.

Also learned the practical difference between the three ways to build a
guardrail, hand-written rules, a small trained classifier, or asking a
second LLM call to judge the first one's output. The third is the most
flexible and also doubles your latency and cost on every single request,
which after the reasoning-model lesson above was an easy one to rule
out. Rule-based checks run in microseconds and cost nothing, and for a
lot of guardrail types that's more than good enough.

Testing doesn't stop just because a dependency won't install
-------------------------------------------------------------------

The sandbox this got built in couldn't install the real ``chromadb``
package — its dependency chain pulls in an OpenTelemetry gRPC exporter
that needs a C extension the environment couldn't build. The instinct
is to just skip testing whatever depends on it. Instead, the fix was
writing a small fake standing in for exactly the two Chroma methods the
code actually calls, and testing the real logic (file writes, reload
after a simulated restart, delete-on-remove) against that. It's not a
substitute for testing against the real thing eventually, but it's a lot
better than testing nothing, and it forced me to actually understand
which part of the dependency my own code needed versus which part I was
just carrying around.

Git hygiene is not optional busywork
------------------------------------------

Two real near-misses here. First, the frontend folder had picked up its
own nested ``.git`` directory at some point, which meant the whole
project looked like two separate repositories instead of one, had to
remove it and reinitialise a single repo at the root before any of this
was going to push cleanly. Second, a real NVIDIA API key ended up pasted
into ``.env.example`` instead of ``.env`` at one point; caught before it
was ever committed, but only because I checked ``git status`` before
pushing instead of after. Neither of these are interesting technically.
Both would have been genuinely annoying to clean up if they'd made it to
GitHub first.

Don't invent a documentation structure from scratch
------------------------------------------------------

For this documentation site, instead of designing a structure from
nothing, I used one that had already been built and marked well for a
different project (SimplyServe, Sphinx plus the Furo theme, hosted on
Read the Docs). Adapting a structure that's already proven to work is
faster and lower-risk than reinventing one, and it's the same instinct
as reusing Chatbot's pipeline instead of rebuilding RAG from scratch for
Constellate. Good structure is good structure. There's no prize for
originality in a table of contents.
