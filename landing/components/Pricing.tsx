const LEMON_URL = 'https://lemon.squeezy.com/buy/REPLACE_ME'

const plans = [
  {
    name: 'Free',
    price: '$0',
    period: 'forever',
    note: 'No account needed',
    badge: null,
    featured: false,
    features: [
      { text: '30 starter skills', included: true },
      { text: 'All 32 instincts', included: true },
      { text: 'Full SQLite memory layer', included: true },
      { text: 'Basic agent layer', included: true },
      { text: 'sg init, find, learn, build', included: true },
      { text: 'Full vault (1,944 skills)', included: false },
      { text: 'Monthly vault updates', included: false },
      { text: 'Signal analytics', included: false },
    ],
    cta: 'Install from GitHub',
    ctaHref: 'https://github.com/amancodingrepo/skillgod',
    ctaStyle: 'secondary',
  },
  {
    name: 'Early Adopter',
    price: '$7',
    period: '/mo',
    note: 'Locked forever - price never goes up',
    badge: 'FIRST 200 USERS',
    featured: true,
    features: [
      { text: 'Everything in Free', included: true },
      { text: 'Full vault - 1,944 skills', included: true },
      { text: 'Monthly vault updates', included: true },
      { text: 'Full multi-agent support', included: true },
      { text: 'Skill enhancer', included: true },
      { text: 'Signal analytics', included: true },
      { text: 'sg sync --key', included: true },
      { text: 'Price locked forever', included: true },
    ],
    cta: 'Lock $7/mo Now',
    ctaHref: LEMON_URL,
    ctaStyle: 'primary',
  },
  {
    name: 'Pro',
    price: '$10',
    period: '/mo',
    note: 'After first 200 users',
    badge: null,
    featured: false,
    features: [
      { text: 'Everything in Free', included: true },
      { text: 'Full vault - 1,944 skills', included: true },
      { text: 'Monthly vault updates', included: true },
      { text: 'Full multi-agent support', included: true },
      { text: 'Skill enhancer', included: true },
      { text: 'Signal analytics', included: true },
      { text: 'sg sync --key', included: true },
      { text: 'Price not locked', included: false },
    ],
    cta: 'Get Pro',
    ctaHref: LEMON_URL,
    ctaStyle: 'secondary',
  },
]

export default function Pricing() {
  return (
    <section id="pricing" className="py-24 px-6">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-14">
          <h2 className="text-4xl font-syne font-extrabold tracking-tight uppercase mb-3 text-brut-ink">Pricing</h2>
          <p className="text-sm uppercase tracking-wide text-brut-muted">Free to install. Pay for the living vault.</p>
        </div>

        <div className="grid md:grid-cols-3 gap-2 items-start">
          {plans.map((plan) => (
            <div
              key={plan.name}
              className={`relative p-6 flex flex-col border-2 border-brut-border2 ${
                plan.featured ? 'bg-brut-bg2' : 'bg-brut-bg'
              }`}
            >
              {plan.badge && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-brut-ink text-brut-yellow text-[10px] font-bold tracking-widest uppercase px-3 py-1 whitespace-nowrap">
                  {plan.badge}
                </div>
              )}

              <div className="mb-5 border-b border-brut-border pb-4">
                <div className="text-xs uppercase tracking-wide mb-1 text-brut-muted">{plan.name}</div>
                <div className="flex items-baseline gap-1">
                  <span className="text-4xl font-syne font-extrabold text-brut-ink">{plan.price}</span>
                  <span className="text-xs text-brut-muted">{plan.period}</span>
                </div>
                <div className={`text-xs font-bold mt-1 uppercase ${plan.featured ? 'text-brut-accent' : 'text-brut-muted'}`}>
                  {plan.note}
                </div>
              </div>

              <ul className="space-y-2.5 mb-6 flex-1">
                {plan.features.map((f) => (
                  <li key={f.text} className="flex gap-2.5 text-sm text-brut-ink2">
                    <span className={`flex-shrink-0 font-bold mt-0.5 ${f.included ? 'text-[#1a6b3c]' : 'text-gray-300'}`}>
                      {f.included ? '+' : '-'}
                    </span>
                    <span className={f.included ? '' : 'text-brut-muted'}>{f.text}</span>
                  </li>
                ))}
              </ul>

              <a
                href={plan.ctaHref}
                target={plan.ctaHref.startsWith('http') ? '_blank' : undefined}
                rel="noopener noreferrer"
                className={`block text-center py-3 px-4 text-sm font-syne font-bold uppercase tracking-wide border-2 border-brut-ink transition-transform hover:translate-x-[2px] hover:translate-y-[2px] active:shadow-none ${
                  plan.ctaStyle === 'primary' ? 'bg-brut-yellow text-brut-ink' : 'bg-brut-bg'
                }`}
              >
                {plan.cta}
              </a>
            </div>
          ))}
        </div>

        <div className="mt-8 bg-brut-bg2 border-2 border-brut-border2 p-6 text-center">
          <h3 className="font-syne font-extrabold uppercase mb-2 text-brut-ink">Referral program</h3>
          <p className="text-sm leading-relaxed text-brut-ink2">
            Share your referral link - friend signs up at <strong className="text-brut-accent">$7/mo locked forever</strong>,
            even after the 200-user window closes.
            <br />
            Your friend converts to paid - you get <strong className="text-[#1a6b3c]">1 free month</strong> ($10 value)
            automatically.
          </p>
        </div>

        <p className="text-center text-xs uppercase tracking-wide mt-6 text-brut-muted">
          Licensed via LemonSqueezy - Offline grace period 30 days - Your workflow never breaks
        </p>
      </div>
    </section>
  )
}
