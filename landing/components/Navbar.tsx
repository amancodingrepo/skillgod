'use client'

import { useEffect, useRef, useState } from 'react'

export default function Navbar() {
  const [isHidden, setIsHidden] = useState(false)
  const lastScrollY = useRef(0)

  useEffect(() => {
    const onScroll = () => {
      const currentY = window.scrollY

      if (currentY < 12) {
        setIsHidden(false)
      } else if (currentY > lastScrollY.current + 8) {
        setIsHidden(true)
      } else if (currentY < lastScrollY.current - 8) {
        setIsHidden(false)
      }

      lastScrollY.current = currentY
    }

    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <nav
      className={`fixed top-0 left-0 right-0 z-50 bg-brut-bg2/95 backdrop-blur-sm text-brut-ink border-b border-brut-border transition-transform duration-300 ${
        isHidden ? '-translate-y-full' : 'translate-y-0'
      }`}
    >
      <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
        <a href="/" className="text-xl font-syne font-extrabold tracking-tight uppercase">
          Skill<span className="text-brut-accent">God</span>
        </a>
        <div className="hidden md:flex items-center gap-8 text-xs uppercase tracking-wide text-brut-muted">
          <a href="#how" className="hover:text-brut-ink transition-colors">How it works</a>
          <a href="#pricing" className="hover:text-brut-ink transition-colors">Pricing</a>
          <a href="https://github.com/amancodingrepo/skillgod" target="_blank" rel="noopener noreferrer" className="hover:text-brut-ink transition-colors">GitHub</a>
        </div>
        <a
          href="#pricing"
          className="border-2 border-brut-ink bg-brut-ink text-brut-yellow px-4 py-2 font-syne font-bold text-xs uppercase tracking-wide hover:translate-x-[2px] hover:translate-y-[2px] active:shadow-none transition-transform"
        >
          Get Early Access
        </a>
      </div>
    </nav>
  )
}
