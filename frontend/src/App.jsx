import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { askQuestion, listUploads, uploadFile } from './api.js'

const GRAPH_W = 240
const GRAPH_H = 220

function rand(min, max) {
  return min + Math.random() * (max - min)
}

// Real constellations (simplified line figures), each defined on a 0-100
// grid so they're easy to eyeball against the real shape. Not
// astronomically precise (relative star positions, not true RA/Dec), but
// recognizable -- which is the point, since this panel is pure brand
// decoration with no document data behind it (see GraphPanel's comment).
const CONSTELLATIONS = [
  {
    name: 'Orion',
    stars: [
      { x: 68, y: 15, bright: true }, // Betelgeuse
      { x: 32, y: 20 }, // Bellatrix
      { x: 58, y: 45 }, // belt
      { x: 50, y: 50 }, // belt
      { x: 42, y: 55 }, // belt
      { x: 60, y: 85 }, // Saiph
      { x: 28, y: 80, bright: true }, // Rigel
    ],
    edges: [[0, 2], [1, 4], [2, 3], [3, 4], [4, 6], [2, 5]],
  },
  {
    name: 'Ursa Major',
    stars: [
      { x: 8, y: 65 }, // Alkaid
      { x: 24, y: 52 }, // Mizar
      { x: 40, y: 45 }, // Alioth
      { x: 56, y: 40 }, // Megrez
      { x: 78, y: 30, bright: true }, // Dubhe
      { x: 74, y: 55 }, // Merak
      { x: 56, y: 62 }, // Phecda
    ],
    edges: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 3]],
  },
  {
    name: 'Cassiopeia',
    stars: [
      { x: 8, y: 55 },
      { x: 28, y: 20 },
      { x: 50, y: 60, bright: true },
      { x: 72, y: 15 },
      { x: 92, y: 45 },
    ],
    edges: [[0, 1], [1, 2], [2, 3], [3, 4]],
  },
  {
    name: 'Cygnus',
    stars: [
      { x: 50, y: 8, bright: true }, // Deneb
      { x: 50, y: 32 },
      { x: 50, y: 50 },
      { x: 50, y: 70 },
      { x: 50, y: 92 }, // Albireo
      { x: 18, y: 50 },
      { x: 82, y: 50 },
    ],
    edges: [[0, 1], [1, 2], [2, 3], [3, 4], [2, 5], [2, 6]],
  },
  {
    name: 'Crux',
    stars: [
      { x: 52, y: 8 },
      { x: 56, y: 48 },
      { x: 50, y: 92, bright: true }, // Acrux
      { x: 14, y: 52 },
      { x: 88, y: 42 },
    ],
    edges: [[0, 1], [1, 2], [3, 1], [1, 4]],
  },
  {
    name: 'Lyra',
    stars: [
      { x: 18, y: 12, bright: true }, // Vega
      { x: 42, y: 28 },
      { x: 58, y: 48 },
      { x: 46, y: 68 },
      { x: 24, y: 54 },
    ],
    edges: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 1]],
  },
  {
    name: 'Scorpius',
    stars: [
      { x: 8, y: 8 },
      { x: 18, y: 22 },
      { x: 26, y: 38 },
      { x: 30, y: 54, bright: true }, // Antares
      { x: 36, y: 66 },
      { x: 48, y: 74 },
      { x: 60, y: 76 },
      { x: 68, y: 68 },
      { x: 64, y: 56 },
    ],
    edges: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 8]],
  },
]

// Flavor text for a handful of stars in each constellation -- vaguely
// pipeline-shaped words, not real citations, so the gold labels read as
// brand texture rather than implying actual document data (there isn't
// any behind this panel -- see GraphPanel's comment).
const LABEL_WORDS = [
  'retrieve', 'embed', 'chunk', 'context', 'recall', 'ground',
  'cite', 'index', 'trace', 'query', 'resolve', 'compose',
  'source', 'vector', 'match', 'answer', 'reference', 'rank',
]

function shuffled(array) {
  const copy = [...array]
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[copy[i], copy[j]] = [copy[j], copy[i]]
  }
  return copy
}

function rotatePoint(x, y, cx, cy, angleRad) {
  const dx = x - cx
  const dy = y - cy
  return {
    x: cx + dx * Math.cos(angleRad) - dy * Math.sin(angleRad),
    y: cy + dx * Math.sin(angleRad) + dy * Math.cos(angleRad),
  }
}

// Rotates the chosen constellation a little (like it would appear at a
// different time of night) and fits it into the panel at a random spot,
// without distorting its proportions -- the shape itself stays real.
function layoutConstellation(constellation, wordPool) {
  const angle = rand(-25, 25) * (Math.PI / 180)
  const rotated = constellation.stars.map((s) => rotatePoint(s.x, s.y, 50, 50, angle))

  const xs = rotated.map((p) => p.x)
  const ys = rotated.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = maxX - minX || 1
  const spanY = maxY - minY || 1

  const marginX = GRAPH_W * 0.14
  const marginY = GRAPH_H * 0.14
  const targetW = GRAPH_W - marginX * 2
  const targetH = GRAPH_H - marginY * 2
  const scale = Math.min(targetW / spanX, targetH / spanY)

  const slackX = targetW - spanX * scale
  const slackY = targetH - spanY * scale
  const offsetX = marginX + rand(0, slackX)
  const offsetY = marginY + rand(0, slackY)

  const nodes = rotated.map((p, i) => ({
    x: offsetX + (p.x - minX) * scale,
    y: offsetY + (p.y - minY) * scale,
    r: constellation.stars[i].bright ? 4.5 : 3,
  }))

  // Label a handful of stars (never all of them -- Scorpius has nine
  // points, and that many labels would just be noise).
  const labelCount = Math.min(4, nodes.length, wordPool.length)
  const labeledIndices = shuffled(nodes.map((_, i) => i)).slice(0, labelCount)
  const words = shuffled(wordPool).slice(0, labelCount)
  labeledIndices.forEach((nodeIndex, k) => {
    nodes[nodeIndex].label = words[k]
  })

  return { name: constellation.name, nodes, edges: constellation.edges }
}

// Purely cosmetic star-map: a real constellation (gold) picked at random,
// plus a scatter of dim, unrelated background stars for texture. The
// shape itself never means anything -- but the labels on a few of its
// stars are drawn from wordPool, which the caller fills with real words
// pulled from whatever's been uploaded (falling back to a generic
// pipeline-flavored bank before anything has).
function generateConstellationLayout(wordPool) {
  const dimCount = 6 + Math.floor(Math.random() * 3)
  const dimNodes = Array.from({ length: dimCount }, () => ({
    x: rand(15, GRAPH_W - 15),
    y: rand(10, GRAPH_H - 10),
    r: rand(1.5, 2.5),
  }))
  const dimEdges = []
  for (let i = 0; i < dimNodes.length - 1; i += 1 + Math.floor(Math.random() * 2)) {
    dimEdges.push([i, i + 1])
  }

  const constellation = CONSTELLATIONS[Math.floor(Math.random() * CONSTELLATIONS.length)]
  const { name, nodes: activeNodes, edges: activeEdges } = layoutConstellation(constellation, wordPool)

  return { name, dimNodes, dimEdges, activeNodes, activeEdges }
}

function ConstellationMark({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <line x1="6" y1="20" x2="13" y2="8" stroke="var(--gold)" strokeWidth="1" />
      <line x1="13" y1="8" x2="21" y2="12" stroke="var(--gold)" strokeWidth="1" />
      <line x1="13" y1="8" x2="18" y2="22" stroke="var(--gold)" strokeWidth="1" />
      <circle cx="6" cy="20" r="2" fill="var(--gold)" />
      <circle cx="13" cy="8" r="2.4" fill="var(--gold)" />
      <circle cx="21" cy="12" r="2" fill="var(--gold)" />
      <circle cx="18" cy="22" r="2" fill="var(--gold)" />
    </svg>
  )
}

// Unwired on purpose -- there's no knowledge graph behind this anymore (see
// the root README's "What changed" section). Kept as brand decoration, and
// redrawn to a new random layout each time it mounts (plus a manual
// reshuffle) rather than showing the same fixed placeholder graph forever.
// words: real keywords pulled from whatever's been uploaded so far, or []
// before anything has. Falls back to LABEL_WORDS either way.
function GraphPanel({ words }) {
  const pool = words.length > 0 ? words : LABEL_WORDS
  const [layout, setLayout] = useState(() => generateConstellationLayout(pool))
  const mounted = useRef(false)

  // Redraw with the new vocabulary as soon as it changes (a document just
  // got uploaded) -- skip the very first run, since useState already
  // generated an initial layout with it.
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true
      return
    }
    setLayout(generateConstellationLayout(pool))
    // pool is derived fresh from `words` each render; re-running this
    // effect only when `words` itself changes is what we want.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [words])

  return (
    <div className="graph">
      <div className="label-row">
        <div className="label">Connections used</div>
        <button
          type="button"
          className="shuffle-btn"
          onClick={() => setLayout(generateConstellationLayout(pool))}
          title="Redraw"
          aria-label="Redraw"
        >
          ⟳
        </button>
      </div>
      <div className="constellation-name">{layout.name}</div>
      <svg viewBox={`0 0 ${GRAPH_W} ${GRAPH_H}`}>
        <g stroke="var(--star-dim)" strokeWidth="0.75">
          {layout.dimEdges.map(([a, b], i) => (
            <line
              key={i}
              x1={layout.dimNodes[a].x}
              y1={layout.dimNodes[a].y}
              x2={layout.dimNodes[b].x}
              y2={layout.dimNodes[b].y}
            />
          ))}
        </g>
        <g fill="var(--star-dim)">
          {layout.dimNodes.map((n, i) => (
            <circle key={i} cx={n.x} cy={n.y} r={n.r} />
          ))}
        </g>
        <g stroke="var(--gold)" strokeWidth="1.25">
          {layout.activeEdges.map(([a, b], i) => (
            <line
              key={i}
              x1={layout.activeNodes[a].x}
              y1={layout.activeNodes[a].y}
              x2={layout.activeNodes[b].x}
              y2={layout.activeNodes[b].y}
            />
          ))}
        </g>
        <g fill="var(--gold)">
          {layout.activeNodes.map((n, i) => (
            <circle key={i} cx={n.x} cy={n.y} r={n.r} />
          ))}
        </g>
        {layout.activeNodes.map((n, i) =>
          n.label ? (
            <text key={i} x={n.x} y={n.y - 8} textAnchor="middle" className="node-name active">
              {n.label}
            </text>
          ) : null,
        )}
      </svg>
    </div>
  )
}

function App() {
  const [uploads, setUploads] = useState([])
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [uploading, setUploading] = useState(false)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)
  const chatEndRef = useRef(null)

  // Real words from whatever's been uploaded, for GraphPanel's decorative
  // labels -- see its own comment for why real vocabulary is nicer than
  // the generic fallback bank once there's something to draw from.
  const documentWords = useMemo(
    () => uploads.flatMap((doc) => doc.keywords || []),
    [uploads],
  )

  // Pick up any documents already sitting in the backend (e.g. a previous
  // session's uploads, since Assistant is a single shared instance).
  useEffect(() => {
    listUploads()
      .then((body) => setUploads(body.uploads))
      .catch(() => {
        // Backend not running yet -- stay quiet here, the ask/upload
        // actions will surface a clear error when the user tries them.
      })
  }, [])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleFileChange(event) {
    const file = event.target.files?.[0]
    event.target.value = '' // allow re-selecting the same file later
    if (!file) return

    setUploading(true)
    setError(null)
    try {
      const uploaded = await uploadFile(file)
      setUploads((prev) => [...prev, uploaded])
    } catch (err) {
      setError(`Upload failed: ${err.message}`)
    } finally {
      setUploading(false)
    }
  }

  async function handleAsk(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || asking) return

    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setQuestion('')
    setAsking(true)
    setError(null)
    try {
      const reply = await askQuestion(trimmed)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: reply.message,
          sources: reply.sources,
          related: reply.related,
          backend: reply.backend,
        },
      ])
    } catch (err) {
      setError(`Ask failed: ${err.message}`)
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="wrap">
      <header>
        <ConstellationMark />
        <span className="word">Constellate</span>
      </header>
      <p className="tagline">trace how your documents connect</p>

      <div className="uploads-row">
        <button
          type="button"
          className="upload-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
        >
          {uploading ? 'Uploading…' : '+ Upload document'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".md,.markdown,.txt,.pdf,.docx,.jpg,.jpeg,.png,.webp"
          onChange={handleFileChange}
          hidden
        />
        <div className="uploads-list">
          {uploads.length === 0 ? (
            <span className="uploads-empty">No documents uploaded yet</span>
          ) : (
            uploads.map((doc) => (
              <span className="upload-chip" key={doc.filename}>
                {doc.filename} · {doc.chunks} chunks
              </span>
            ))
          )}
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <div className="chat">
          {messages.length === 0 ? (
            <div className="chat-empty">
              {uploads.length === 0
                ? 'Upload a document, then ask a question about it.'
                : 'Ask a question about what you’ve uploaded.'}
            </div>
          ) : (
            messages.map((msg, i) => (
              <div className={`msg ${msg.role}`} key={i}>
                {msg.text}
                {msg.role === 'assistant' && msg.backend === 'stub' && (
                  <div className="stub-note">
                    offline stub answer — set NVIDIA_API_KEY on the backend for real generation
                  </div>
                )}
                {msg.sources?.length > 0 && (
                  <div className="cites">
                    {msg.sources.map((s, j) => (
                      <span className="cite" key={j}>
                        {s.source} · {s.citation}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
          {asking && <div className="msg assistant thinking">Thinking…</div>}
          <div ref={chatEndRef} />
          <form className="inputbar" onSubmit={handleAsk}>
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about your documents…"
              disabled={asking}
            />
            <button type="submit" disabled={asking || !question.trim()}>
              Ask
            </button>
          </form>
        </div>
        <GraphPanel words={documentWords} />
      </div>
    </div>
  )
}

export default App
