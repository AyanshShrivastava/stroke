import type { MistProject } from '../types/mist';
import { createSafeId } from '../utils/projectOps';

export interface MistTemplate {
  id: string;
  name: string;
  category: string;
  description: string;
  prompt: string;
  previewImage: string;
  accentHex: string;
  files: Array<{
    path: string;
    language: 'tsx' | 'ts' | 'css' | 'html' | 'json';
    content: string;
  }>;
}

export const MIST_TEMPLATES: MistTemplate[] = [
  {
    id: 'kuro-coffee',
    name: 'Kuro Coffee Tokyo',
    category: 'Hospitality',
    description: 'Minimalist Tokyo specialty pour-over bar with single-origin menu, brew parameters, and reservation hours.',
    prompt: 'Minimalist Tokyo specialty coffee roastery landing page with single-origin menu, brew guide, and Kiyosumi location details.',
    previewImage: '/src/assets/images/template_coffee_roastery_1794659272127.jpg',
    accentHex: '#B45309',
    files: [
      {
        path: 'src/components/Navbar.tsx',
        language: 'tsx',
        content: `import React from 'react';

export default function Navbar() {
  return (
    <header className="sticky top-0 z-30 border-b border-stone-200 bg-stone-50/95 backdrop-blur-sm">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-8 px-6 py-4">
        <a href="#top" className="text-lg font-semibold tracking-tight text-stone-900 whitespace-nowrap shrink-0">
          Kuro Coffee
        </a>
        <nav className="hidden md:flex items-center gap-7 text-sm font-medium text-stone-600">
          <a href="#origins" className="hover:text-stone-900 transition-colors whitespace-nowrap shrink-0">Origins</a>
          <a href="#brew" className="hover:text-stone-900 transition-colors whitespace-nowrap shrink-0">Brew Guide</a>
          <a href="#roastery" className="hover:text-stone-900 transition-colors whitespace-nowrap shrink-0">Roastery</a>
          <a href="#visit" className="hover:text-stone-900 transition-colors whitespace-nowrap shrink-0">Visit</a>
        </nav>
        <a
          href="#visit"
          className="rounded-md bg-stone-900 px-4 py-2 text-xs font-medium text-stone-50 hover:bg-stone-800 transition-colors whitespace-nowrap shrink-0"
        >
          Reserve Bar Seat
        </a>
      </div>
    </header>
  );
}
`,
      },
      {
        path: 'src/App.tsx',
        language: 'tsx',
        content: `import React, { useState } from 'react';
import Navbar from './components/Navbar';

const ORIGINS = [
  { name: 'Kiyosumi House Blend', region: 'Ethiopia / Colombia', notes: 'Bergamot, toasted almond, cocoa', roast: 'Light-Medium', price: '$19 / 250g', category: 'filter' },
  { name: 'Guji Uraga Washed', region: 'Oromia, Ethiopia', notes: 'White peach, jasmine, Meyer lemon', roast: 'Light', price: '$24 / 250g', category: 'filter' },
  { name: 'Huila Pink Bourbon', region: 'San Agustin, Colombia', notes: 'Blood orange, cane sugar, cacao nib', roast: 'Medium', price: '$23 / 250g', category: 'espresso' },
  { name: 'Antigua El Injerto', region: 'Sacatepequez, Guatemala', notes: 'Roasted hazelnut, dark fig, caramel', roast: 'Medium-Dark', price: '$21 / 250g', category: 'espresso' },
];

export default function App() {
  const [filter, setFilter] = useState<'all' | 'filter' | 'espresso'>('all');
  const [booked, setBooked] = useState(false);

  const visibleOrigins = filter === 'all' ? ORIGINS : ORIGINS.filter((item) => item.category === filter);

  return (
    <div id="top" className="min-h-screen bg-stone-50 text-stone-900">
      <Navbar />

      <main>
        <section className="mx-auto max-w-6xl px-6 py-16 lg:py-24">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 items-stretch">
            <div className="lg:col-span-5 flex flex-col justify-between gap-8">
              <div className="space-y-6">
                <p className="text-xs font-medium tracking-wide text-stone-500">
                  Kiyosumi-Shirakawa · Tokyo · Est. 2019
                </p>
                <h1 className="text-4xl lg:text-5xl font-semibold tracking-tight leading-[1.08] text-stone-950">
                  Small-batch coffee roasted for quiet mornings.
                </h1>
                <p className="text-base leading-relaxed text-stone-600">
                  Every lot is roasted on a cast-iron 5kg Fuji Royal drum and brewed to order at our eight-seat concrete counter.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-4">
                <a
                  href="#origins"
                  className="rounded-md bg-amber-800 px-5 py-2.5 text-sm font-medium text-white hover:bg-amber-900 transition-colors"
                >
                  Explore Current Lots
                </a>
                <a
                  href="#brew"
                  className="rounded-md border border-stone-300 px-5 py-2.5 text-sm font-medium text-stone-800 hover:bg-stone-100 transition-colors"
                >
                  Read Pour-Over Specs
                </a>
              </div>
            </div>
            <div className="lg:col-span-7 overflow-hidden rounded-xl border border-stone-200 bg-stone-200">
              <img
                src="/src/assets/images/template_coffee_roastery_1794659272127.jpg"
                alt="Barista pouring filter coffee at the concrete counter in Kuro Coffee Tokyo"
                className="h-full w-full object-cover min-h-[320px]"
              />
            </div>
          </div>
        </section>

        <section id="origins" className="border-t border-stone-200 bg-white py-16 lg:py-20">
          <div className="mx-auto max-w-6xl px-6">
            <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6 mb-10">
              <div>
                <h2 className="text-2xl lg:text-3xl font-semibold tracking-tight text-stone-950">
                  Seasonal Roasting Menu
                </h2>
                <p className="mt-2 text-sm text-stone-600">
                  Roasted Mondays and Thursdays. Shipped whole bean within 24 hours.
                </p>
              </div>
              <div className="inline-flex items-center gap-1 rounded-lg bg-stone-100 p-1">
                {(['all', 'filter', 'espresso'] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setFilter(tab)}
                    className={\`rounded-md px-3.5 py-1.5 text-xs font-medium capitalize transition-colors \${
                      filter === tab
                        ? 'bg-white text-stone-950 shadow-sm'
                        : 'text-stone-600 hover:text-stone-900'
                    }\`}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            </div>

            <div className="divide-y divide-stone-200 border-y border-stone-200">
              {visibleOrigins.map((lot) => (
                <div key={lot.name} className="grid grid-cols-1 md:grid-cols-12 gap-4 py-5 items-center">
                  <div className="md:col-span-4">
                    <h3 className="text-base font-semibold text-stone-900">{lot.name}</h3>
                    <p className="text-xs text-stone-500 mt-0.5">{lot.region}</p>
                  </div>
                  <div className="md:col-span-5 text-sm text-stone-600">{lot.notes}</div>
                  <div className="md:col-span-2 text-xs font-medium text-stone-500">{lot.roast}</div>
                  <div className="md:col-span-1 text-sm font-semibold text-stone-900 md:text-right tabular-nums">
                    {lot.price}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="brew" className="border-t border-stone-200 py-16 lg:py-20">
          <div className="mx-auto max-w-6xl px-6 grid grid-cols-1 md:grid-cols-3 gap-10">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight text-stone-950">Counter Brew Ratio</h2>
              <p className="mt-3 text-sm leading-relaxed text-stone-600">
                Calibrated daily for soft Tokyo water filtered through activated carbon and mineral remineralization.
              </p>
            </div>
            <div className="space-y-4 border-t border-stone-200 pt-4 md:border-t-0 md:pt-0">
              <p className="text-xs font-medium text-stone-500">01. Dose & Water</p>
              <p className="text-2xl font-semibold text-stone-900 tabular-nums">16g : 255ml</p>
              <p className="text-sm text-stone-600">92°C soft water, medium-fine grind, flat-bottom ceramic dripper.</p>
            </div>
            <div className="space-y-4 border-t border-stone-200 pt-4 md:border-t-0 md:pt-0">
              <p className="text-xs font-medium text-stone-500">02. Total Drawdown</p>
              <p className="text-2xl font-semibold text-stone-900 tabular-nums">2m 35s</p>
              <p className="text-sm text-stone-600">45g bloom for 35 seconds followed by two concentric pours.</p>
            </div>
          </div>
        </section>

        <section id="visit" className="border-t border-stone-200 bg-stone-900 text-stone-100 py-16">
          <div className="mx-auto max-w-6xl px-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-8">
            <div className="space-y-2 max-w-xl">
              <h2 className="text-2xl font-semibold tracking-tight">Visit the Kiyosumi Counter</h2>
              <p className="text-sm text-stone-400">
                2-14-8 Shirakawa, Koto-ku, Tokyo · Open Tuesday–Sunday, 08:00–17:30.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setBooked(true)}
              className="rounded-md bg-amber-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-amber-500 transition-colors"
            >
              {booked ? 'Seat Request Confirmed' : 'Book Tasting Flight'}
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}
`,
      },
      {
        path: 'src/index.css',
        language: 'css',
        content: `@import "tailwindcss";\n`,
      },
      {
        path: 'src/styles/mist-overrides.css',
        language: 'css',
        content: `/* Visual editor overrides */\n`,
      },
    ],
  },
  {
    id: 'nordholm-architects',
    name: 'Nordholm Architects',
    category: 'Architecture',
    description: 'Copenhagen architectural practice showcase with selected works table, studio philosophy, and inquiry form.',
    prompt: 'Scandinavian architectural studio portfolio website with selected projects index, daylight studio imagery, and consultation form.',
    previewImage: '/src/assets/images/template_architect_studio_1794659273332.jpg',
    accentHex: '#1E293B',
    files: [
      {
        path: 'src/components/Navbar.tsx',
        language: 'tsx',
        content: `import React from 'react';

export default function Navbar() {
  return (
    <header className="border-b border-neutral-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-8 px-6 py-4">
        <a href="#top" className="text-base font-semibold tracking-tight text-neutral-900 whitespace-nowrap shrink-0">
          Nordholm Architects
        </a>
        <nav className="hidden md:flex items-center gap-7 text-sm text-neutral-600">
          <a href="#works" className="hover:text-neutral-950 transition-colors whitespace-nowrap shrink-0">Works</a>
          <a href="#practice" className="hover:text-neutral-950 transition-colors whitespace-nowrap shrink-0">Practice</a>
          <a href="#journal" className="hover:text-neutral-950 transition-colors whitespace-nowrap shrink-0">Monographs</a>
          <a href="#contact" className="hover:text-neutral-950 transition-colors whitespace-nowrap shrink-0">Contact</a>
        </nav>
        <a
          href="#contact"
          className="rounded-md bg-neutral-900 px-4 py-2 text-xs font-medium text-white hover:bg-neutral-800 transition-colors whitespace-nowrap shrink-0"
        >
          Inquire
        </a>
      </div>
    </header>
  );
}
`,
      },
      {
        path: 'src/App.tsx',
        language: 'tsx',
        content: `import React, { useState } from 'react';
import Navbar from './components/Navbar';

const WORKS = [
  { year: '2026', title: 'Aarhus Timber Pavilion', typology: 'Cultural', area: '1,420 m²', location: 'Aarhus, Denmark' },
  { year: '2025', title: 'Skagen Dune Residence', typology: 'Residential', area: '340 m²', location: 'North Jutland' },
  { year: '2024', title: 'Kastrup Maritime Library', typology: 'Public', area: '2,850 m²', location: 'Copenhagen' },
  { year: '2023', title: 'Vesterbro Courtyard Housing', typology: 'Adaptive Reuse', area: '4,100 m²', location: 'Copenhagen' },
];

export default function App() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitted(true);
  };

  return (
    <div id="top" className="min-h-screen bg-[#F9F9F7] text-neutral-900">
      <Navbar />
      <main>
        <section className="mx-auto max-w-6xl px-6 py-16 lg:py-24">
          <div className="max-w-3xl space-y-5 mb-12">
            <p className="text-xs font-medium text-neutral-500">Copenhagen · Timber & Daylight Architecture</p>
            <h1 className="text-4xl lg:text-5xl font-semibold tracking-tight leading-[1.08] text-neutral-950">
              Quiet civic and residential buildings shaped by Nordic light.
            </h1>
          </div>
          <div className="overflow-hidden rounded-xl border border-neutral-200 bg-neutral-100">
            <img
              src="/src/assets/images/template_architect_studio_1794659273332.jpg"
              alt="Architects examining timber scale models inside Nordholm Copenhagen studio"
              className="w-full h-[420px] object-cover"
            />
          </div>
        </section>

        <section id="works" className="border-t border-neutral-200 bg-white py-16">
          <div className="mx-auto max-w-6xl px-6">
            <h2 className="text-2xl font-semibold tracking-tight mb-8">Selected Works Index</h2>
            <div className="divide-y divide-neutral-200 border-y border-neutral-200">
              {WORKS.map((work) => (
                <div key={work.title} className="grid grid-cols-2 md:grid-cols-12 gap-4 py-4 items-center text-sm">
                  <span className="md:col-span-1 text-neutral-500 tabular-nums">{work.year}</span>
                  <span className="md:col-span-5 font-medium text-neutral-950">{work.title}</span>
                  <span className="md:col-span-2 text-neutral-600">{work.typology}</span>
                  <span className="md:col-span-2 text-neutral-500 tabular-nums">{work.area}</span>
                  <span className="md:col-span-2 text-neutral-600 md:text-right">{work.location}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="practice" className="border-t border-neutral-200 py-16">
          <div className="mx-auto max-w-6xl px-6 grid grid-cols-1 md:grid-cols-3 gap-10">
            <div>
              <h2 className="text-xl font-semibold">01. Material Longevity</h2>
              <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                Cross-laminated Nordic spruce, lime mortar, and untreated zinc selected to weather gracefully over centuries.
              </p>
            </div>
            <div>
              <h2 className="text-xl font-semibold">02. Passive Daylight</h2>
              <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                Physical scale modeling in our daylight studio informs every roof monitor, courtyard proportion, and deep window reveal.
              </p>
            </div>
            <div>
              <h2 className="text-xl font-semibold">03. Low-Carbon Craft</h2>
              <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                Full lifecycle carbon accounting from timber harvest to modular disassembly across all public commissions.
              </p>
            </div>
          </div>
        </section>

        <section id="contact" className="border-t border-neutral-200 bg-neutral-900 text-neutral-100 py-16">
          <div className="mx-auto max-w-6xl px-6 flex flex-col md:flex-row md:items-center justify-between gap-8">
            <div>
              <h2 className="text-2xl font-semibold">Commission & Studio Inquiries</h2>
              <p className="mt-2 text-sm text-neutral-400">Bredgade 45, 1260 København K · studio@nordholm.dk</p>
            </div>
            {submitted ? (
              <p className="text-sm font-medium text-emerald-400">Thank you. Our partners will respond within two business days.</p>
            ) : (
              <form onSubmit={handleSubmit} className="flex w-full max-w-md gap-3">
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@organization.com"
                  className="flex-1 rounded-md border border-neutral-700 bg-neutral-800 px-3.5 py-2 text-sm text-white placeholder:text-neutral-500"
                />
                <button
                  type="submit"
                  className="rounded-md bg-white px-4 py-2 text-sm font-medium text-neutral-950 hover:bg-neutral-200 transition-colors"
                >
                  Send Brief
                </button>
              </form>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
`,
      },
      {
        path: 'src/index.css',
        language: 'css',
        content: `@import "tailwindcss";\n`,
      },
      {
        path: 'src/styles/mist-overrides.css',
        language: 'css',
        content: `/* Visual editor overrides */\n`,
      },
    ],
  },
  {
    id: 'aether-audio',
    name: 'Aether Audio Labs',
    category: 'Hardware',
    description: 'Precision machined desktop audio interface product page with interactive gain staging preview and technical specs.',
    prompt: 'Precision desktop audio hardware product launch website with dark slate studio aesthetic, specs table, and pre-order selector.',
    previewImage: '/src/assets/images/template_audio_hardware_1794659272890.jpg',
    accentHex: '#D97706',
    files: [
      {
        path: 'src/components/Navbar.tsx',
        language: 'tsx',
        content: `import React from 'react';

export default function Navbar() {
  return (
    <header className="border-b border-zinc-800 bg-zinc-950">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-8 px-6 py-4">
        <a href="#top" className="text-base font-semibold tracking-tight text-zinc-100 whitespace-nowrap shrink-0">
          Aether Audio Labs
        </a>
        <nav className="hidden md:flex items-center gap-7 text-sm text-zinc-400">
          <a href="#architecture" className="hover:text-zinc-100 transition-colors whitespace-nowrap shrink-0">Architecture</a>
          <a href="#specs" className="hover:text-zinc-100 transition-colors whitespace-nowrap shrink-0">Specifications</a>
          <a href="#metering" className="hover:text-zinc-100 transition-colors whitespace-nowrap shrink-0">VU Metering</a>
        </nav>
        <a
          href="#order"
          className="rounded-md bg-amber-600 px-4 py-2 text-xs font-medium text-white hover:bg-amber-500 transition-colors whitespace-nowrap shrink-0"
        >
          Pre-Order M1
        </a>
      </div>
    </header>
  );
}
`,
      },
      {
        path: 'src/App.tsx',
        language: 'tsx',
        content: `import React, { useState } from 'react';
import Navbar from './components/Navbar';

export default function App() {
  const [edition, setEdition] = useState<'silver' | 'obsidian'>('silver');
  const [reserved, setReserved] = useState(false);

  return (
    <div id="top" className="min-h-screen bg-zinc-950 text-zinc-100">
      <Navbar />
      <main>
        <section className="mx-auto max-w-6xl px-6 py-16 lg:py-24 grid grid-cols-1 lg:grid-cols-12 gap-12 items-center">
          <div className="lg:col-span-5 space-y-6">
            <p className="text-xs font-medium text-amber-500">Model M1 · Reference Desktop Interface</p>
            <h1 className="text-4xl lg:text-5xl font-semibold tracking-tight leading-[1.08] text-white">
              CNC-milled analog transparency for mastering desks.
            </h1>
            <p className="text-base leading-relaxed text-zinc-400">
              Dual discrete Class-A preamps, stepped resistor monitor attenuation, and backlit mechanical VU meters in a solid 6061 aluminum chassis.
            </p>
            <div className="flex items-center gap-4 pt-2">
              <a
                href="#order"
                className="rounded-md bg-amber-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-amber-500 transition-colors"
              >
                Reserve Batch 04 — $1,290
              </a>
              <a
                href="#specs"
                className="rounded-md border border-zinc-700 px-5 py-2.5 text-sm font-medium text-zinc-200 hover:bg-zinc-900 transition-colors"
              >
                Audio Specs
              </a>
            </div>
          </div>
          <div className="lg:col-span-7 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900">
            <img
              src="/src/assets/images/template_audio_hardware_1794659272890.jpg"
              alt="Aether Audio M1 brushed aluminum desktop audio interface with illuminated VU meters"
              className="w-full h-full object-cover"
            />
          </div>
        </section>

        <section id="specs" className="border-t border-zinc-800 bg-zinc-900/50 py-16">
          <div className="mx-auto max-w-6xl px-6">
            <h2 className="text-2xl font-semibold tracking-tight mb-8">Measured Performance</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-8 border-y border-zinc-800 py-8">
              <div>
                <p className="text-xs text-zinc-400">Dynamic Range</p>
                <p className="mt-2 text-2xl font-semibold text-white tabular-nums">128 dB (A)</p>
              </div>
              <div>
                <p className="text-xs text-zinc-400">THD+N @ 1kHz</p>
                <p className="mt-2 text-2xl font-semibold text-white tabular-nums">-114 dB</p>
              </div>
              <div>
                <p className="text-xs text-zinc-400">Max Sample Rate</p>
                <p className="mt-2 text-2xl font-semibold text-white tabular-nums">384 kHz</p>
              </div>
              <div>
                <p className="text-xs text-zinc-400">Headphone Output</p>
                <p className="mt-2 text-2xl font-semibold text-white tabular-nums">2 × 650 mW</p>
              </div>
            </div>
          </div>
        </section>

        <section id="order" className="border-t border-zinc-800 py-16">
          <div className="mx-auto max-w-6xl px-6 flex flex-col md:flex-row md:items-center justify-between gap-8">
            <div className="space-y-2">
              <h2 className="text-2xl font-semibold">Select Anodized Finish</h2>
              <p className="text-sm text-zinc-400">Ships calibrated with individual APx555 test certificate.</p>
              <div className="flex items-center gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEdition('silver')}
                  className={\`rounded-md px-3.5 py-1.5 text-xs font-medium border transition-colors \${
                    edition === 'silver' ? 'border-amber-500 bg-zinc-800 text-white' : 'border-zinc-800 text-zinc-400'
                  }\`}
                >
                  Raw Brushed Aluminum
                </button>
                <button
                  type="button"
                  onClick={() => setEdition('obsidian')}
                  className={\`rounded-md px-3.5 py-1.5 text-xs font-medium border transition-colors \${
                    edition === 'obsidian' ? 'border-amber-500 bg-zinc-800 text-white' : 'border-zinc-800 text-zinc-400'
                  }\`}
                >
                  Bead-Blasted Obsidian
                </button>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setReserved(true)}
              className="rounded-md bg-amber-600 px-6 py-3 text-sm font-medium text-white hover:bg-amber-500 transition-colors"
            >
              {reserved ? \`Reserved (\${edition === 'silver' ? 'Brushed Aluminum' : 'Obsidian'})\` : 'Reserve Unit — $1,290'}
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}
`,
      },
      {
        path: 'src/index.css',
        language: 'css',
        content: `@import "tailwindcss";\n`,
      },
      {
        path: 'src/styles/mist-overrides.css',
        language: 'css',
        content: `/* Visual editor overrides */\n`,
      },
    ],
  },
  {
    id: 'lume-botanicals',
    name: 'Lume Botanicals',
    category: 'E-Commerce',
    description: 'Luxury botanical skincare storefront with formulation notes, interactive cart counter, and editorial hero.',
    prompt: 'Luxury botanical skincare e-commerce site with amber glass serum showcase, ingredient table, and interactive bag.',
    previewImage: '/src/assets/images/template_botanical_skincare_1794659273501.jpg',
    accentHex: '#78350F',
    files: [
      {
        path: 'src/components/Navbar.tsx',
        language: 'tsx',
        content: `import React from 'react';

export default function Navbar({ bagCount }: { bagCount: number }) {
  return (
    <header className="border-b border-stone-200 bg-[#FAF8F5]">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-8 px-6 py-4">
        <a href="#top" className="text-lg font-semibold tracking-tight text-stone-900 whitespace-nowrap shrink-0">
          Lume Botanicals
        </a>
        <nav className="hidden md:flex items-center gap-7 text-sm text-stone-600">
          <a href="#serums" className="hover:text-stone-900 transition-colors whitespace-nowrap shrink-0">Formulations</a>
          <a href="#ingredients" className="hover:text-stone-900 transition-colors whitespace-nowrap shrink-0">Ingredients</a>
          <a href="#ritual" className="hover:text-stone-900 transition-colors whitespace-nowrap shrink-0">Daily Ritual</a>
        </nav>
        <a
          href="#serums"
          className="rounded-md bg-stone-900 px-4 py-2 text-xs font-medium text-white hover:bg-stone-800 transition-colors whitespace-nowrap shrink-0 tabular-nums"
        >
          Bag ({bagCount})
        </a>
      </div>
    </header>
  );
}
`,
      },
      {
        path: 'src/App.tsx',
        language: 'tsx',
        content: `import React, { useState } from 'react';
import Navbar from './components/Navbar';

const PRODUCTS = [
  { id: 'ritual', name: 'The Ritual Serum', size: '30 ml · 1.0 fl oz', actives: 'Hyaluronic Acid + Copper Peptides', price: 84 },
  { id: 'barrier', name: 'Barrier Lipid Oil', size: '30 ml · 1.0 fl oz', actives: 'Squalane + Sea Buckthorn Seed', price: 72 },
  { id: 'mist', name: 'Neroli Hydrosol Tonic', size: '100 ml · 3.4 fl oz', actives: 'Steam-Distilled Bitter Orange', price: 48 },
];

export default function App() {
  const [bagCount, setBagCount] = useState(0);

  return (
    <div id="top" className="min-h-screen bg-[#FAF8F5] text-stone-900">
      <Navbar bagCount={bagCount} />
      <main>
        <section className="mx-auto max-w-6xl px-6 py-16 lg:py-24 grid grid-cols-1 lg:grid-cols-12 gap-12 items-center">
          <div className="lg:col-span-5 space-y-6">
            <p className="text-xs font-medium text-stone-500">Cold-Pressed Botanical Formulations</p>
            <h1 className="text-4xl lg:text-5xl font-semibold tracking-tight leading-[1.08] text-stone-950">
              Clinical peptides suspended in organic plant lipids.
            </h1>
            <p className="text-base leading-relaxed text-stone-600">
              Formulated without synthetic fragrance or silicones. Bottled in UV-filtering amber glass to preserve active potency.
            </p>
            <button
              type="button"
              onClick={() => setBagCount((c) => c + 1)}
              className="rounded-md bg-stone-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-stone-800 transition-colors"
            >
              Add Ritual Serum — $84
            </button>
          </div>
          <div className="lg:col-span-7 overflow-hidden rounded-xl border border-stone-200 bg-stone-100">
            <img
              src="/src/assets/images/template_botanical_skincare_1794659273501.jpg"
              alt="Frosted amber glass skincare serum bottles on travertine stone"
              className="w-full h-full object-cover"
            />
          </div>
        </section>

        <section id="serums" className="border-t border-stone-200 bg-white py-16">
          <div className="mx-auto max-w-6xl px-6">
            <h2 className="text-2xl font-semibold tracking-tight mb-8">Core Apothecary Collection</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              {PRODUCTS.map((item) => (
                <div key={item.id} className="flex flex-col justify-between rounded-xl border border-stone-200 p-6 bg-[#FAF8F5]">
                  <div>
                    <p className="text-xs text-stone-500">{item.size}</p>
                    <h3 className="mt-2 text-lg font-semibold text-stone-950">{item.name}</h3>
                    <p className="mt-2 text-sm text-stone-600">{item.actives}</p>
                  </div>
                  <div className="mt-6 flex items-center justify-between border-t border-stone-200 pt-4">
                    <span className="text-base font-semibold tabular-nums">\${item.price}</span>
                    <button
                      type="button"
                      onClick={() => setBagCount((c) => c + 1)}
                      className="rounded-md border border-stone-300 bg-white px-3.5 py-1.5 text-xs font-medium text-stone-900 hover:bg-stone-100 transition-colors"
                    >
                      Add to Bag
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
`,
      },
      {
        path: 'src/index.css',
        language: 'css',
        content: `@import "tailwindcss";\n`,
      },
      {
        path: 'src/styles/mist-overrides.css',
        language: 'css',
        content: `/* Visual editor overrides */\n`,
      },
    ],
  },
];

export function instantiateProjectFromTemplate(template: MistTemplate): MistProject {
  const now = new Date().toISOString();
  return {
    id: createSafeId('proj'),
    name: template.name,
    description: template.description,
    prompt: template.prompt,
    templateId: template.id,
    isPublished: false,
    createdAt: now,
    updatedAt: now,
    files: template.files.map((f) => ({
      id: createSafeId('file'),
      path: f.path,
      language: f.language,
      content: f.content,
    })),
    chatHistory: [
      {
        id: createSafeId('msg'),
        role: 'user',
        content: template.prompt,
        timestamp: now,
      },
      {
        id: createSafeId('msg'),
        role: 'assistant',
        content: `Generated ${template.name} with ${template.files.length} React, TypeScript, and Tailwind CSS files.`,
        timestamp: now,
        changedFiles: template.files.map((f) => f.path),
      },
    ],
  };
}
