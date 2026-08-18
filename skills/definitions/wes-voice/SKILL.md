---
name: wes-voice
description: Use when Wes asks to rewrite or translate pasted text into his own casual voice, especially with "/wes", "make this sound like me", "make this sound like Wes", "translate this into my voice", or drafting comments, posts, replies, and messages he will personally send.
---

# Wes Voice

Rewrite the user's draft so it sounds like Wes wrote it.

## Output

- Output only the rewritten text unless Wes asks for notes or options.
- Keep the meaning and factual claims intact.
- Do not add new claims, credentials, dates, or technical details unless Wes supplied them.
- Use first person when the text is meant to come from Wes.
- Match the requested surface: Hacker News comment, Telegram reply, email, tweet, Discord message, etc.
- If no length is specified, make it shorter than the input.

## Voice

- Direct, casual, and low fluff.
- Sound like a real person writing quickly, not polished marketing copy.
- Prefer short sentences.
- Use contractions naturally.
- Mildly imperfect grammar is okay when it sounds more like Wes.
- Wes starts sentences with capital letters. Always capitalize sentence starts, even in casual comments.
- Avoid semicolons.
- Never use em dashes.
- Avoid dash-heavy sentence punctuation in general.
- Avoid corporate words like "leveraging", "robust", "seamless", "delighted", "excited to announce", "game changer", or "value proposition" unless Wes explicitly asks for that style.
- Avoid making Wes sound too impressed with himself.
- Prefer concrete language over abstract framing.

## Rewrite Heuristics

- Compress the idea into the fewest clear sentences.
- Remove throat-clearing unless it makes the line sound more human.
- Use plain transitions like "but", "so", "the thing is", or "the hard part".
- Keep useful technical terms, but do not over-explain them.
- If the input is too polished, roughen it slightly without making it sloppy.
- If the input is too long, keep the sharpest point and drop supporting detail.
- For public forum comments, make it conversational and defensible. Do not overclaim.

## Guardrails

- Do not fabricate personal experience in Wes's voice.
- Do not make Wes sound more certain than the source supports.
- Do not soften important criticism into blandness.
- Do not turn casual text into influencer-style content.
- Draft only for public posts or external messages unless Wes explicitly asks to send/post through an approved workflow.

## Examples

Input:

This is interesting because it resembles a system I built around Claude Code and OpenClaw. It routes tasks between agents, assigns a lead, delegates bounded subtasks, stores events in a ledger, and reports back to the origin channel. The main challenge is ensuring bounded, auditable, permission-aware communication.

Output:

I had a similar itch and hacked together a rough version with Claude Code + OpenClaw. I use a `/team <task>` command from telegram that creates a shared task, picks which agent should lead, lets the other one handle one narrow delegated piece, logs the whole thing to a local ledger, then reports back in the original chat. Messaging between sessions is the easy part though, the hard part is keeping it bounded and auditable so two agents dont just spiral into nonsense

Input:

I would like to clarify that this project is experimental and currently optimized for my personal workflow rather than general public usage.

Output:

Just to be clear this is still pretty experimental and mostly built around how I work, not really packaged up as a general thing yet

Input:

The current implementation works, but I think the next step is improving reliability and making the setup easier to start.

Output:

It works now, the next thing I need to fix is reliability and making it easier to spin up without remembering a bunch of commands
