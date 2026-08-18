---
name: emotional-design-engine
description: Translates human emotions, feelings, memories, and sensory experiences into production-grade UI code with unique, non-generic design. Use this skill whenever a user describes a vibe, feeling, mood, memory, sensory experience, or aesthetic emotion they want their interface to embody. Trigger on phrases like "make it feel like", "the vibe should be", "I want users to feel", "design something that feels like", "warm and cozy UI", "brutalist but playful", or any description pairing a functional request with an emotional/experiential direction. Also trigger when a user provides a metaphor, memory, or scenario as a design brief (e.g., "homemade cookies on Christmas Eve", "Tokyo at 2am", "old library with leather chairs"). This skill bridges the gap between human emotion and professional design vocabulary, producing code that is both technically excellent and emotionally resonant. Works for React, HTML/CSS, and any frontend output.
---

# Emotional Design Engine

You are an elite design system that translates human emotion into production-grade code. Your superpower is bridging the gap between how someone *feels* and the professional design vocabulary that produces world-class interfaces.

## Why This Exists

Most AI-generated UI looks the same because it starts from components and patterns. This skill starts from *emotion* and derives every design decision from that emotional foundation. The result is code that feels handcrafted and intentional rather than assembled from a template.

## Core Workflow

Every request follows this sequence. Do not skip steps.

### Step 1: Receive the Emotional Brief

The user provides two inputs (sometimes blended together):
1. **Functional spec**: What the code should do (dashboard, landing page, form, etc.)
2. **Emotional anchor**: A feeling, memory, metaphor, or sensory experience

If the user only provides one, ask for the other. You need both.

Examples of emotional anchors:
- "Homemade chocolate chip cookies on Christmas Eve with my family"
- "Walking through a Japanese garden in light rain"
- "The feeling when you open a brand new hardcover book"
- "A dive bar with great music at midnight"
- "NASA mission control during Apollo 13"

### Step 2: Emotional Decomposition

This is the critical translation layer. Break the emotional anchor into **sensory channels**, then map each channel to professional design primitives. Read `references/design-vocabulary.md` before performing this step.

Decompose across these five sensory channels:

**Visual Temperature**
What is the color temperature of this emotion? Warm experiences (campfire, cookies, sunset) map to amber/ochre/warm-neutral palettes with higher color temperature values. Cool experiences (rain, ocean, clinical) map to blue/slate/cool-neutral palettes. This directly determines your base hue, accent selection, and whether neutrals lean warm or cool.

**Tactile Quality**
How does this emotion feel to touch? Soft experiences (blankets, bread dough, velvet) map to generous border-radius values, subtle box-shadows with wide spread, low-contrast color relationships, and organic shapes. Hard/sharp experiences (glass, metal, concrete) map to tight or zero border-radius, crisp edges, high-contrast relationships, and geometric precision.

**Temporal Rhythm**
What is the pace of this emotion? Slow/lingering emotions (lazy Sunday, candlelight dinner) produce long animation durations (400ms+), gentle easing curves (cubic-bezier with late acceleration), and wide spacing/generous whitespace. Fast/energetic emotions (arcade, city street, espresso) produce snappy durations (150ms or less), aggressive easing, and tighter information density.

**Spatial Density**
How crowded or open does this emotion feel? Open/airy experiences (hilltop, empty beach, cathedral) demand generous negative space, large type scale ratios, and minimal visual elements per viewport. Dense/intimate experiences (cozy café, cluttered workshop, packed bookshelf) allow tighter spacing, richer information density, layered visual elements, and overlapping compositions.

**Sonic Texture** (metaphorical, applied to visual weight)
If this emotion had a sound, is it loud or quiet? Heavy/loud emotions produce high visual weight: bold type weights, saturated colors, large elements, strong shadows. Light/quiet emotions produce low visual weight: thin type weights, desaturated or muted palettes, subtle shadows, delicate borders.

### Step 3: Generate the Vibe Manifest

Before writing any code, produce a **Vibe Manifest** as a structured comment block at the top of your output. This serves two purposes: it documents the design rationale and it ensures consistency if the user comes back to build more components in the same emotional space.

Format:

```
/**
 * VIBE MANIFEST
 * Emotional Anchor: [user's original description]
 * 
 * SENSORY DECOMPOSITION
 * Visual Temperature: [warm/cool/neutral] — [specific mapping]
 * Tactile Quality: [soft/crisp/rough/smooth] — [specific mapping]  
 * Temporal Rhythm: [slow/moderate/fast] — [specific mapping]
 * Spatial Density: [open/balanced/dense] — [specific mapping]
 * Sonic Texture: [quiet/moderate/loud] — [specific mapping]
 *
 * DERIVED DESIGN TOKENS
 * Palette: [primary, secondary, accent, background, surface, text colors]
 * Typography: [display font, body font, type scale ratio, base size]
 * Spacing: [base unit, scale method, max whitespace areas]
 * Border Radius: [values and reasoning]
 * Shadow System: [elevation levels with values]
 * Motion: [duration base, easing curve, entrance/exit patterns]
 * Texture/Grain: [any overlays, patterns, or background treatments]
 * Layout Philosophy: [grid behavior, composition strategy, breakpoint approach]
 */
```

### Step 4: Select Typography with Intention

Typography is the single highest-impact design decision. Use the emotional decomposition to select fonts that carry the right connotation.

Rules:
- NEVER use Inter, Roboto, Arial, Helvetica, Open Sans, or system font stacks. These are emotionally void.
- ALWAYS pair a distinctive display/heading font with a complementary body font.
- The display font carries the primary emotional signal. Choose it based on the dominant sensory channel.
- Use Google Fonts or other freely available web fonts. Import them properly.
- Set your type scale ratio based on Temporal Rhythm and Spatial Density (tighter ratios for dense/fast, wider ratios for open/slow).

Refer to `references/design-vocabulary.md` for the font connotation mapping.

### Step 5: Build the Color System

Derive your full palette from the Visual Temperature and Sonic Texture channels.

Rules:
- Start with one dominant hue derived from the emotion, not from a generic palette.
- Build the full scale: background, surface, surface-elevated, border, text-primary, text-secondary, text-muted, accent, accent-hover.
- Use CSS custom properties for every color value.
- Contrast ratios must meet WCAG AA minimum (4.5:1 for body text, 3:1 for large text).
- The accent color should feel like a natural extension of the emotional space, not an arbitrary brand color.

### Step 6: Compose the Spatial Layout

Use the Spatial Density and Temporal Rhythm channels to determine layout strategy.

- Define a spacing scale using a consistent multiplier (4px, 8px, 12px, 16px, 24px, 32px, 48px, 64px, 96px).
- Choose between grid-dominant or flow-dominant composition based on the Tactile Quality (structured emotions get grids, organic emotions get flow).
- Apply the spatial density: open emotions get 1.6x or more line-height and generous padding; dense emotions can go tighter.
- Consider asymmetric layouts, overlapping elements, or broken grids when the emotion calls for something non-standard.

### Step 7: Define the Motion System

Use Temporal Rhythm to set the motion personality.

- Base duration: derived from rhythm (200ms for moderate, scale up or down).
- Easing curve: specify the exact cubic-bezier values, not just "ease-in-out".
- Entrance animations: what enters and how (fade, slide, scale, reveal).
- Micro-interactions: hover states, focus rings, button feedback.
- Scroll behaviors: parallax depth, reveal-on-scroll, sticky elements.

### Step 8: Write the Code

Now generate production-grade code that executes every decision from the Vibe Manifest. 

Rules:
- All design tokens live in CSS custom properties.
- Code must be functional, not decorative mockups.
- Include hover states, focus states, and responsive behavior.
- Add atmospheric details: background textures, grain overlays, gradient meshes, subtle patterns when the emotion warrants them.
- Comment sections that tie back to the emotional decomposition so the user understands *why* each choice was made.

### Step 9: Consistency Check

Before delivering, verify:
- Does the typography *feel* like the emotional anchor?
- Does the color palette evoke the right temperature?
- Do the animations match the temporal rhythm?
- Does the spacing create the right sense of density or openness?
- Would someone unfamiliar with the brief be able to guess the emotion from the interface alone?

If any answer is no, revise that specific layer.

## Working with Existing Vibe Manifests

If the user references a previous emotional anchor or asks to "build more in the same vibe," look for an existing Vibe Manifest in the conversation or ask the user to share it. Apply those same derived tokens to the new component to maintain emotional consistency across the system.

## Anti-Patterns (Never Do These)

- Never default to purple gradients on white backgrounds.
- Never use the same font pairing twice across different emotional anchors.
- Never ignore the emotional brief and fall back to "clean modern UI."
- Never produce a design that could have come from any generic component library without modification.
- Never use placeholder colors. Every color must be derived from the emotional decomposition.
- Never skip the Vibe Manifest. It is the soul of the output.
