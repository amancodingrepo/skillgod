'use client'
import { useState } from 'react'

export default function Hero() {
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText('curl -fsSL skillgod.dev/install | sh')
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <section className="pt-32 pb-24 px-6 relative overflow-hidden bg-brut-hero text-brut-bg border-b-2 border-brut-ink">
      <div className="absolute inset-0 opacity-25 bg-[radial-gradient(ellipse_at_center,rgba(245,200,66,0.12),transparent_60%)]" />
      <div className="absolute inset-0 opacity-20 bg-[repeating-linear-gradient(90deg,transparent_0,transparent_26px,rgba(245,200,66,0.06)_27px,transparent_28px)]" />
      <div className="relative z-10 max-w-6xl mx-auto">
        <div className="inline-flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.22em] text-brut-muted mb-8">
          <span className="w-1.5 h-1.5 bg-brut-yellow animate-pulse" />
          SkillGod - Full Promotion Plan - $10/mo - Zero paid ads
        </div>

        <h1 className="text-5xl md:text-7xl font-syne font-extrabold tracking-tight leading-[0.96] mb-6">
          Every Channel.
          <br />
          Every <span className="text-brut-yellow">Angle.</span>
        </h1>

        <p className="text-lg text-[#c7c2b8] max-w-3xl mb-10 leading-relaxed">
          A complete promotion strategy for one solo founder - what to post, where to launch, how to go viral,
          and how to turn attention into $10/month subscribers.
        </p>

        <div className="inline-flex items-center gap-3 border border-[#3b3a36] bg-[#1a1917]/85 px-5 py-3.5 mb-3 max-w-full">
          <span className="text-brut-yellow text-sm font-code select-none">$</span>
          <code className="text-brut-yellow text-sm font-code whitespace-nowrap overflow-hidden text-ellipsis">
            curl -fsSL skillgod.dev/install | sh
          </code>
          <button
            onClick={copy}
            className={`ml-2 text-xs px-3 py-1 border border-brut-yellow transition-all flex-shrink-0 font-syne font-bold uppercase ${
              copied
                ? 'bg-brut-yellow text-brut-ink'
                : 'bg-transparent text-brut-yellow hover:translate-x-[2px] hover:translate-y-[2px]'
            }`}
          >
            {copied ? 'copied!' : 'copy'}
          </button>
        </div>
      </div>
      <div className="relative z-10 max-w-6xl mx-auto">
        <p className="text-xs mb-10 text-brut-muted">
          Windows:{' '}
          <code className="font-code bg-[#1a1917]/85 border border-[#3b3a36] px-1.5 py-0.5 text-[#d9d4cb]">
            irm skillgod.dev/install.ps1 | iex
          </code>
        </p>

        <div className="flex gap-3 flex-wrap">
          <a
            href="#pricing"
            className="border-2 border-brut-yellow bg-brut-yellow text-brut-ink px-6 py-3 font-syne font-bold text-sm uppercase tracking-wide hover:translate-x-[2px] hover:translate-y-[2px] active:shadow-none transition-transform"
          >
            Start Free
          </a>
          <a
            href="https://github.com/amancodingrepo/skillgod"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 border border-[#3b3a36] bg-[#1a1917]/85 text-[#d9d4cb] px-6 py-3 font-syne font-bold text-sm uppercase tracking-wide hover:translate-x-[2px] hover:translate-y-[2px] active:shadow-none transition-transform"
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
            </svg>
            View on GitHub
          </a>
        </div>

        <p className="mt-8 text-xs uppercase tracking-wide text-brut-muted">
          Open source runtime - 1,944 curated skills - Zero telemetry
        </p>
      </div>
    </section>
  )
}
