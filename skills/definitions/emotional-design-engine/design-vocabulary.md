# Design Vocabulary Reference

This document maps emotional qualities to professional design terminology. When decomposing an emotional anchor, use these exact industry terms in your reasoning and code comments. These terms trigger professional-grade design thinking and output.

## Typography Connotation Map

### Warmth / Comfort / Nostalgia
- **Serif families**: Freight Text, Lora, Merriweather, Playfair Display, DM Serif Display, Cormorant Garamond
- **Humanist sans**: Nunito, Quicksand, Comfortaa, Baloo 2
- **Handwritten-adjacent**: Caveat, Patrick Hand (use sparingly as accent only)
- **Design terms**: humanist axis, warm letterforms, calligraphic stress, generous x-height, round terminals, open counters, oldstyle figures

### Precision / Technology / Authority  
- **Geometric sans**: DM Sans, Outfit, Sora, Manrope, General Sans, Satoshi
- **Monospace for tech**: JetBrains Mono, Fira Code, IBM Plex Mono, Space Mono
- **Design terms**: geometric construction, uniform stroke width, rational proportions, tabular figures, tight letter-spacing, mechanical rhythm

### Luxury / Elegance / Refinement
- **High-contrast serif**: Cormorant, Bodoni Moda, Noto Serif Display, Libre Caslon Display
- **Refined sans**: Tenor Sans, Josefin Sans, Poiret One
- **Design terms**: high stroke contrast, hairline serifs, optical sizing, wide letter-spacing on uppercase, refined apertures, delicate terminals

### Energy / Playfulness / Youth
- **Display sans**: Righteous, Fredoka, Rubik, Lilita One, Bungee
- **Rounded families**: Varela Round, ABeeZee, Nunito
- **Design terms**: supple curves, bouncy baseline, generous counter space, rounded terminals, informal rhythm, variable weight for emphasis

### Industrial / Raw / Brutalist
- **Grotesk families**: Space Grotesk, Schibsted Grotesk, Familjen Grotesk, Darker Grotesque
- **Condensed/Extended**: Oswald, Barlow Condensed, Bebas Neue, Anton
- **Design terms**: blunt terminals, tight tracking, mechanical uniformity, high ink trap contrast, squared counters, utilitarian proportion

### Editorial / Literary / Intellectual
- **Transitional serif**: Libre Baskerville, EB Garamond, Spectral, Source Serif 4
- **Humanist sans for body**: Source Sans 3, Noto Sans, Atkinson Hyperlegible
- **Design terms**: classical axis, moderate contrast, bracketed serifs, proportional oldstyle figures, scholarly rhythm, generous leading

## Color Psychology in Design

### Temperature Mapping
| Emotion Category | Primary Hue Range | Neutrals Lean | Accent Strategy |
|---|---|---|---|
| Warm/Cozy | Amber (30°–50°), Ochre, Terracotta | Warm grays (undertone of yellow/pink) | Deep burgundy or forest green complement |
| Cool/Calm | Slate blue (200°–220°), Sage, Seafoam | Cool grays (undertone of blue) | Muted gold or warm coral for contrast |
| Energetic/Bold | Saturated primaries, Neon accents | Near-black with colored undertone | Complementary clash for tension |
| Mysterious/Dark | Deep indigo, Plum, Charcoal | Near-black neutrals | Single bright accent for focal point |
| Fresh/Natural | Green (120°–160°), Sky blue, Earth tones | Warm off-whites, cream, linen | Organic accent (berry, clay, moss) |
| Sophisticated/Luxury | Gold, Deep navy, Black, Ivory | Pure neutrals or very slight warm lean | Metallic or jewel-tone accent |

### Saturation as Emotional Volume
- **Whisper** (S: 5–15%): Contemplative, sophisticated, muted. Use for quiet/reflective emotions.
- **Conversational** (S: 20–40%): Approachable, grounded, natural. Use for warm/comfortable emotions.
- **Confident** (S: 50–70%): Clear, intentional, engaging. Use for professional/assured emotions.
- **Shouting** (S: 80–100%): Demanding attention, electric, overwhelming. Use for high-energy/urgent emotions.

## Spatial Design Vocabulary

### Negative Space (Whitespace)
- **Micro whitespace**: 4–8px. Padding within components, gaps between inline elements. Creates intimacy and density.
- **Meso whitespace**: 16–32px. Margins between related components, section padding. Creates grouping and rhythm.
- **Macro whitespace**: 48–128px+. Space between major sections, page margins. Creates breathing room and importance.
- **Design terms**: visual breathing room, compositional balance, figure-ground relationship, spatial hierarchy, content-to-chrome ratio

### Layout Composition
- **Modular grid**: Structured, predictable, authoritative. For precision/corporate/editorial emotions.
- **Column grid with baseline**: Classical, rhythmic, literary. For intellectual/elegant emotions.
- **Broken grid / asymmetric**: Dynamic, unexpected, artistic. For creative/energetic/rebellious emotions.
- **Organic flow**: Natural, conversational, casual. For warm/human/intimate emotions.
- **Single-column with generous margins**: Focused, contemplative, premium. For luxury/minimal/quiet emotions.

### Design terms for spatial relationships
- Proximity grouping, visual hierarchy, information density, content cadence, rhythm and repetition, alignment axes, optical weight distribution, focal point placement, rule of thirds, golden ratio proportions, modular scale

## Motion Design Vocabulary

### Easing Curves by Emotion
- **Gentle/Natural**: `cubic-bezier(0.25, 0.1, 0.25, 1.0)` — ease with soft deceleration
- **Snappy/Confident**: `cubic-bezier(0.4, 0.0, 0.2, 1.0)` — Material Design standard
- **Bouncy/Playful**: `cubic-bezier(0.34, 1.56, 0.64, 1.0)` — overshoot spring
- **Dramatic/Heavy**: `cubic-bezier(0.7, 0.0, 0.3, 1.0)` — slow start, decisive end
- **Mechanical/Precise**: `cubic-bezier(0.0, 0.0, 1.0, 1.0)` — linear, robotic
- **Luxurious/Slow**: `cubic-bezier(0.16, 1.0, 0.3, 1.0)` — fast start, long elegant tail

### Animation Duration Ranges
- **Micro-interactions** (hover, focus, toggle): 100–200ms
- **Element transitions** (appear, move, resize): 200–400ms
- **Page transitions** (route change, modal): 300–600ms
- **Atmospheric/ambient** (parallax, floating, pulsing): 1000ms–3000ms+
- **Orchestrated sequences** (staggered reveals, cascading): base + 50–100ms delay per item

### Motion Design Terms
- Choreography, stagger delay, entrance animation, exit animation, interruption handling, spring physics, velocity curve, motion path, keyframe interpolation, scroll-linked animation, intersection observer trigger, transform origin, will-change optimization, GPU-composited properties (transform, opacity)

## Shadow and Depth Vocabulary

### Elevation System by Emotion
- **Flat/Honest**: No shadows or 1px borders only. For brutalist/minimal/raw emotions.
- **Subtle/Refined**: `0 1px 3px rgba(0,0,0,0.08)` scale. For elegant/quiet/professional emotions.
- **Soft/Dreamy**: `0 8px 30px rgba(0,0,0,0.06)` with wide spread. For cozy/gentle/romantic emotions.
- **Bold/Dramatic**: `0 20px 60px rgba(0,0,0,0.15)` with tight spread. For intense/important/luxurious emotions.
- **Colored shadows**: Use tinted shadows (rgba of the element's color) for playful/creative/whimsical emotions.

### Design terms
- Elevation hierarchy, z-depth, shadow softness (penumbra), shadow crispness (umbra), ambient occlusion, layered depth, material metaphor, surface treatment, card elevation, floating elements, grounded elements

## Texture and Surface Vocabulary

### Background Treatments
- **Noise/Grain overlay**: Organic, analog, warm, vintage. Apply with CSS `filter` or SVG `feTurbulence`.
- **Gradient mesh**: Atmospheric, modern, ambient. Use radial gradients with multiple stops.
- **Geometric patterns**: Structured, architectural, rhythmic. Use CSS gradients or inline SVG.
- **Photographic blur**: Immersive, cinematic, atmospheric. Use backdrop-filter or positioned blurred elements.
- **Solid with subtle variation**: Clean but not sterile. Use very slight gradients or off-white tints.

### Design terms
- Surface treatment, material quality, visual texture, grain density, noise frequency, pattern rhythm, background depth, atmospheric perspective, foreground/background separation, glassmorphism, neumorphism, claymorphism, paper texture, fabric texture, screen-door effect

## Border Radius Emotional Mapping

| Radius Value | Emotional Quality | Use For |
|---|---|---|
| 0px | Sharp, authoritative, brutalist | Industrial, serious, editorial |
| 2–4px | Slightly softened, professional | Corporate, clean, trustworthy |
| 8–12px | Friendly, approachable, modern | SaaS, consumer apps, comfortable |
| 16–24px | Playful, soft, inviting | Creative, youth-oriented, cozy |
| 9999px (pill) | Whimsical, badge-like, contained | Tags, buttons for playful contexts |
| 50% (circle) | Complete, organic, infinite | Avatars, decorative, natural |
| Mixed (different per corner) | Unexpected, artistic, distinctive | Creative, editorial, breaking convention |

## Putting It All Together

When you receive an emotional anchor, run through each section of this document and make deliberate selections. The goal is not to match every single property to the emotion, but to create a *coherent system* where every decision reinforces the same feeling.

The Vibe Manifest should use these exact design terms. When Claude (or any model) sees terms like "generous negative space," "warm humanist letterforms," "soft penumbra shadows," and "gentle easing with late deceleration," it produces dramatically better design output than vague terms like "make it look nice" or "modern and clean."

The professional vocabulary is the bridge. The emotion is the compass. Together they produce design that is both technically excellent and emotionally authentic.
