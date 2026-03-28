import Navbar from '@/components/Navbar'
import Hero from '@/components/Hero'
import Stats from '@/components/Stats'
import BeforeAfter from '@/components/BeforeAfter'
import HowItWorks from '@/components/HowItWorks'
import Pricing from '@/components/Pricing'
import Footer from '@/components/Footer'

export default function Home() {
  return (
    <>
      <Navbar />
      <main>
        <Hero />
        <Stats />
        <BeforeAfter />
        <HowItWorks />
        <Pricing />
      </main>
      <Footer />
    </>
  )
}
