export default function Footer() {
  return (
    <footer className="border-t border-brut-border2 py-10 px-6 bg-brut-bg2">
      <div className="max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="text-xl font-syne font-extrabold tracking-tight uppercase text-brut-ink">
          Skill<span className="text-brut-accent">God</span>
        </div>
        <div className="flex gap-6 text-xs uppercase tracking-wide text-brut-muted">
          <a href="https://github.com/amancodingrepo/skillgod" target="_blank" rel="noopener noreferrer" className="hover:text-brut-ink transition-colors">GitHub</a>
          <a href="https://github.com/amancodingrepo/skillgod/blob/main/README.md" target="_blank" rel="noopener noreferrer" className="hover:text-brut-ink transition-colors">Docs</a>
          <a href="mailto:hello@skillgod.dev" className="hover:text-brut-ink transition-colors">hello@skillgod.dev</a>
        </div>
        <p className="text-xs uppercase tracking-wide text-brut-muted">Open source runtime. Vault is the product.</p>
      </div>
    </footer>
  )
}
