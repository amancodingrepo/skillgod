const stats = [
  { num: '1,944', label: 'curated skills' },
  { num: '11', label: 'categories' },
  { num: '32', label: 'always-on instincts' },
  { num: '12', label: 'source repos' },
]

export default function Stats() {
  return (
    <div className="border-y border-[#3b3a36] bg-brut-hero">
      <div className="max-w-5xl mx-auto px-6 py-12 grid grid-cols-2 md:grid-cols-4 gap-2">
        {stats.map((s) => (
          <div key={s.label} className="border border-[#3b3a36] bg-[#1a1917]/85 p-4 text-center">
            <div className="text-3xl font-syne font-extrabold text-brut-yellow">{s.num}</div>
            <div className="text-[11px] uppercase tracking-wide mt-1 text-brut-muted">{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
