import BrutalistCard from './BrutalistCard'

const pillars = [
  {
    icon: 'Memory',
    name: 'Memory',
    tagline: 'Claude remembers everything.',
    body: 'SQLite-backed project memory. Decisions, patterns, and errors are captured after every session and injected before the next one.',
    detail: ['Persists across sessions', 'Per-project context', 'Decisions, patterns, errors', 'Zero cloud dependency'],
  },
  {
    icon: 'Skills',
    name: 'Skills',
    tagline: '1,944 skills. Auto-injected.',
    body: 'Each task is scored against the full vault and the most relevant skills are injected automatically before execution.',
    detail: ['Scored per task in <5ms', '32 always-on instincts', 'Use-when descriptions', 'Learn your own skills'],
  },
  {
    icon: 'Agents',
    name: 'Agents',
    tagline: 'Per-agent skill injection.',
    body: 'Complex tasks are split into specialist agents so each one receives only the context and skills it actually needs.',
    detail: ['Frontend/backend/devops routing', 'Per-agent skill injection', 'Ralph autonomous loop', 'Ruflo swarm architecture'],
  },
]

export default function HowItWorks() {
  return (
    <section id="how" className="py-24 px-6 bg-brut-bg2 border-y border-brut-border2">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-14">
          <h2 className="text-4xl font-syne font-extrabold tracking-tight uppercase mb-3 text-brut-ink">Three pillars. One runtime.</h2>
          <p className="text-sm uppercase tracking-wide text-brut-muted">Everything injects automatically. Zero prompt engineering required.</p>
        </div>

        <div className="grid md:grid-cols-3 gap-2">
          {pillars.map((p) => (
            <BrutalistCard key={p.name} title={p.name}>
              <p className="text-xs uppercase tracking-wide text-[#1a4a8c] font-bold mb-3">{p.tagline}</p>
              <p className="text-sm leading-relaxed mb-4 text-brut-ink2">{p.body}</p>
              <ul className="space-y-1.5 border-t border-brut-border pt-4">
                {p.detail.map((d) => (
                  <li key={d} className="text-xs flex items-center gap-2 text-brut-ink2">
                    <span className="w-1.5 h-1.5 bg-brut-border2 flex-shrink-0" />
                    {d}
                  </li>
                ))}
              </ul>
            </BrutalistCard>
          ))}
        </div>
      </div>
    </section>
  )
}
