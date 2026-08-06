import './App.css'

const activeCitations = [
  { doc: 'vendor_contract.pdf', ref: '§4.2' },
  { doc: 'sla_agreement.pdf', ref: '§9.1' },
]

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

function GraphPanel() {
  return (
    <div className="graph">
      <div className="label">Connections used</div>
      <svg viewBox="0 0 240 220">
        <g stroke="var(--star-dim)" strokeWidth="0.75">
          <line x1="30" y1="30" x2="70" y2="55" />
          <line x1="70" y1="55" x2="40" y2="95" />
          <line x1="200" y1="25" x2="175" y2="60" />
          <line x1="200" y1="180" x2="165" y2="150" />
          <line x1="30" y1="30" x2="60" y2="10" />
        </g>
        <g fill="var(--star-dim)">
          <circle cx="30" cy="30" r="2.5" />
          <circle cx="70" cy="55" r="2" />
          <circle cx="40" cy="95" r="2" />
          <circle cx="200" cy="25" r="2" />
          <circle cx="175" cy="60" r="2" />
          <circle cx="200" cy="180" r="2" />
          <circle cx="165" cy="150" r="2" />
          <circle cx="60" cy="10" r="1.5" />
        </g>
        <g stroke="var(--gold)" strokeWidth="1.25">
          <line x1="120" y1="70" x2="150" y2="110" />
          <line x1="150" y1="110" x2="110" y2="140" />
          <line x1="150" y1="110" x2="185" y2="130" />
        </g>
        <circle cx="120" cy="70" r="4" fill="var(--gold)" />
        <circle cx="150" cy="110" r="5" fill="var(--gold)" />
        <circle cx="110" cy="140" r="4" fill="var(--gold)" />
        <circle cx="185" cy="130" r="4" fill="var(--gold)" />
        <text x="120" y="62" textAnchor="middle" className="node-name active">§4.2</text>
        <text x="150" y="98" textAnchor="middle" className="node-name active">vendor_contract</text>
        <text x="110" y="158" textAnchor="middle" className="node-name active">§9.1</text>
        <text x="185" y="148" textAnchor="middle" className="node-name active">sla_agreement</text>
      </svg>
    </div>
  )
}

function App() {
  return (
    <div className="wrap">
      <header>
        <ConstellationMark />
        <span className="word">Constellate</span>
      </header>
      <p className="tagline">trace how your documents connect</p>

      <div className="card">
        <div className="chat">
          <div className="msg user">
            How does the retrieval clause in the vendor contract relate to the SLA doc?
          </div>
          <div className="msg assistant">
            The vendor contract's retrieval clause (§4.2) sets a 30-day data
            return window. The SLA doc references the same window under its
            termination terms, so a breach of §4.2 also triggers the SLA's
            early-termination penalty.
            <div className="cites">
              {activeCitations.map((c) => (
                <span className="cite" key={c.doc}>
                  {c.doc} · {c.ref}
                </span>
              ))}
            </div>
          </div>
          <div className="inputbar">Ask about your documents…</div>
        </div>
        <GraphPanel />
      </div>

      <p className="status-note">
        Dummy page — no backend wired up yet. Static placeholder to confirm
        the frontend scaffold and brand render correctly.
      </p>
    </div>
  )
}

export default App
