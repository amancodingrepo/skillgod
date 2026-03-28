import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'SkillGod — Claude Code on steroids',
  description: '1,944 skills, persistent memory, and multi-agent orchestration for any AI coding tool. Free to install.',
  openGraph: {
    title: 'SkillGod — Claude Code on steroids',
    description: '1,944 skills, persistent memory, and multi-agent orchestration. Free to install.',
    url: 'https://skillgod.dev',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'SkillGod — Claude Code on steroids',
    description: '1,944 skills, persistent memory, and multi-agent orchestration. Free to install.',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  )
}
