import BrutalistCard from './BrutalistCard'

const before = [
  'Claude forgets your stack between sessions',
  'Generic responses needing 3 correction messages',
  'Re-explains your architecture every conversation',
  'No idea you use Zustand, not Redux',
  'Every agent gets the same generic context',
  'Skills fire on gut feel, not evidence',
]

const after = [
  'Project memory persists across every session',
  'Right skill injected before Claude even starts',
  'Your conventions are always in context',
  'Remembers every decision you have ever made',
  'Frontend agent gets UI skills, backend gets API skills',
  'Signal analytics show what is actually working',
]

export default function BeforeAfter() {
  return (
    <section className="py-24 px-6 max-w-5xl mx-auto">
      <div className="text-center mb-14">
        <h2 className="text-4xl font-syne font-extrabold tracking-tight uppercase mb-3 text-brut-ink">What changes</h2>
        <p className="text-sm uppercase tracking-wide text-brut-muted">Same Claude. Completely different results.</p>
      </div>

      <div className="grid md:grid-cols-2 gap-2">
        <BrutalistCard title="Without SkillGod">
          <ul className="space-y-2">
            {before.map((item) => (
              <li key={item} className="flex gap-3 text-sm text-brut-ink2">
                <span className="text-brut-accent flex-shrink-0 font-bold mt-0.5">x</span>
                {item}
              </li>
            ))}
          </ul>
        </BrutalistCard>

        <BrutalistCard title="With SkillGod">
          <ul className="space-y-2">
            {after.map((item) => (
              <li key={item} className="flex gap-3 text-sm text-brut-ink2">
                <span className="text-[#1a6b3c] flex-shrink-0 font-bold mt-0.5">+</span>
                {item}
              </li>
            ))}
          </ul>
        </BrutalistCard>
      </div>
    </section>
  )
}
