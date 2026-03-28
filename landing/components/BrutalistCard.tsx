import { ReactNode } from 'react'

type BrutalistCardProps = {
  title: string
  children: ReactNode
}

export default function BrutalistCard({ title, children }: BrutalistCardProps) {
  return (
    <div className="border-2 border-brut-border2 bg-brut-bg p-6 relative">
      <div className="absolute top-0 right-0 bg-brut-ink text-brut-bg px-2 py-1 text-[10px] uppercase font-bold">
        v1.0
      </div>
      <h3 className="font-syne font-extrabold text-xl mb-4 uppercase text-brut-ink">{title}</h3>
      <div className="border-t border-brut-border pt-4">{children}</div>
    </div>
  )
}
