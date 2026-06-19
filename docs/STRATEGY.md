# GTA VI Shorts Channel Strategy (June → November 2026)

This document outlines the strategic playbook for managing the automated GTA VI Shorts pipeline from pre-release hype through launch window.

---

### 1. HYPE CYCLE MAP (June → November 2026)

The fundamental problem right now is that **real GTA VI gameplay does not exist yet**. The `is_gameplay` validation gate will reject pure news/talking head videos. Therefore, the pipeline must source *proxy* content until November.

**Phase 1: The Proxy & Engine Era (June – August)**
*   **The Meta:** Viewers are starved for visuals. They are watching GTA V modded with "ultra-realism ray tracing" meant to simulate GTA VI, or analyzing 2-second snippets of official trailers/leaks on a loop. 
*   **Prioritize:** Ultra-modded GTA V physics stunts, GTA VI trailer "hidden detail" zooms, and leaked RAGE engine physics tests (if visually clean). 
*   **Hook Tone:** Disbelief, visual simulation, curiosity. ("Wait... look at the water physics").
*   **Winning Signal:** High completion rate. Viewers loop the video to see if it's real GTA VI footage or modded GTA V.

**Phase 2: The Pre-Release Previews (September – October)**
*   **The Meta:** Rockstar lifts the embargo. IGN and major creators release heavily restricted preview footage. 
*   **Prioritize:** The "B-Roll" from major journalist previews. They will talk over it, but your pipeline extracts the visual, mutes their voice, and overlays your TTS hook.
*   **Hook Tone:** Feature confirmation, "They actually did it". ("Bro... they actually added dynamic mud").
*   **Winning Signal:** High share rate. People sending the confirmed feature to their friends.

**Phase 3: The Floodgates (November)**
*   **The Meta:** The game is out. The market is saturated with 10-hour let's plays. 
*   **Prioritize:** Bugs, physics glitches, NPC AI breaking, and accidental stunts. 
*   **Hook Tone:** Shock, humor, authenticity. ("Nobody told me the NPCs do THIS").
*   **Winning Signal:** Massive algorithmic scaling. The first channel to clip a hilarious launch-day bug gets 10M views.

---

### 2. WHITELIST CHANNEL STRATEGY

Your whitelist is the bottleneck. If you feed the pipeline garbage, Gemini will reject it, and nothing posts.

**Right Now (June - Oct):**
*   **Prioritize:** High-end GTA V modding channels, stunt communities (e.g., *Hazardous, Red Arcade, Prestige Clips*), and channels dedicated to recreating GTA VI trailer scenes in GTA V.
*   **Size:** Target mid-tier channels (50k - 500k subs). Massive channels over-edit with fast cuts that confuse the `clip_analyzer`. Mid-tier channels often upload raw, continuous 30-second clips of a stunt or mod, which gives the peak-finder the perfect runway.
*   **Avoid:** Speculation channels (MrBossFTW, etc.). They use talking heads and static background gameplay. Gemini will flag it, or worse, the gameplay won't match the hook.

**Launch Window (November):**
*   **Prioritize:** "Day One" speedrunners, raw gameplay dumpers, and meme channels. Look for channels that upload "GTA 6 Funny Moments" within 48 hours of launch. 
*   **The Shift:** Purge the whitelist of GTA V mod channels the day before launch. Only pure GTA VI metadata should flow into the pipeline.

---

### 3. HOOK LANGUAGE STRATEGY

The 3s blurred setup + TTS hook is the signature format. Because we only have ~3 seconds (about 5-7 words spoken comfortably), the AI must generate conversational fragments, not complete sentences.

**Emotional Triggers:** The highest rewatch rates come from **cognitive dissonance** (seeing something that shouldn't happen in the game engine) and **absurdity**.

**Prompting the AI (The "Pattern"):**
Teach Groq to use specific opening fragments. Blacklist marketing speak.

*   *Blacklisted:* "In this video", "Watch this", "You won't believe", "Epic GTA moment", "Crazy stunt".
*   *Mandatory formatting:* No punctuation except an optional "..." for a pause. Lowercase preferred to feel like a real text message caption.

**15 Example Hooks (Train Groq on these):**

*For Physics/Glitches (High CTR):*
1. "bro really just defied gravity"
2. "wait... what happened to the car"
3. "the physics engine just broke"
4. "nobody told me NPCs do this"
5. "tell me why he flew perfectly"

*For Details/Graphics (Pre-release):*
6. "look at the water physics here"
7. "they actually added dynamic mud"
8. "wait... zoom in on the mirror"
9. "the details on this are insane"
10. "how is this even running"

*For Absurd Stunts/Outcomes:*
11. "see there's always a bigger fish"
12. "never trust the quiet player"
13. "sometimes the road fights back"
14. "bro picked the wrong ramp today"
15. "he actually landed that perfectly"

---

### 4. ALGORITHMIC ACCELERATION TACTICS

Starting at 0 subscribers means zero authority.

*   **Posting Time:** Schedule the pipeline to publish at **3:00 PM EST**. This hits the US East Coast as school/work ends, and scales into the West Coast evening—the prime gaming Shorts demographic.
*   **Metadata Strategy:** 
    *   *Title:* `[Hook Text] #GTA6 #Shorts` (e.g., `bro really just defied gravity #GTA6 #Shorts`). Keep it under 45 characters. The title must match the spoken hook to reinforce the curiosity gap.
    *   *Description:* Keep it exactly as the pipeline builds it. The creator credit is vital to avoid copyright strikes.
*   **Growth Milestones:**
    *   **0 - 100 Subs:** Expect wild variance. Do not touch the pipeline code. Let the algorithm figure out the audience cluster.
    *   **100 - 1,000 Subs:** The algorithm knows the audience. Review `performance_log.json`. Double the priority weight for whitelist channels generating the most views.
*   **External Signals:** Set up a secondary script to auto-post the YouTube Short link to specific gaming Discord servers in a "clips" channel. Do NOT spam Reddit; they hate automated self-promo.
*   **The "Dead" Signal:** If a Short hits 500 views and stops completely, it hit the Swipe-Away threshold (likely >50% swiped). It's dead. Move on.

---

### 5. LAUNCH WINDOW STRATEGY (November 2026)

This is the Super Bowl for the pipeline. 

*   **T-Minus 14 Days:** Shift the whitelist aggressively to channels getting early review copies (IGN, GameSpot, major creators). Adjust search logic to find "GTA 6 Preview".
*   **T-Minus 24 Hours:** Change `UPLOAD["limit_per_run"] = 1` to `3`. YouTube allows 3-5 Shorts a day without penalizing reach. For the launch week only, run the pipeline every 8 hours. 
*   **Launch + 48 Hours:** The most viral clips will NOT be story spoilers. The most viral clips will be **NPC interactions, car crashes, and funny bugs.** 
*   **Validation Adjustment:** Temporarily relax the `is_punchy` validation gate. At launch, people will watch a 15-second clip of a character walking down the street because the graphics are new. Don't over-filter the initial hype wave.

---

### 6. COMPETITIVE DIFFERENTIATION

In November, thousands of kids will be manually ripping clips. Why the automated bot wins:

**The Pacing Edge.** Manual creators get greedy and leave 5 seconds of boring setup before the stunt happens. The pipeline uses heatmaps to find the exact peak, and the `clip_analyzer` enforces strict boundaries. The 3s setup → hard cut to peak action is a dopamine slot machine. **Never compromise on the tight 10-14s total duration.**

**The Audio Signature.** Using a 5-stage humanized cloned voice separates this channel from raw ElevenLabs or TikTok voices. The slight breath injection and room tone makes the channel feel like a real person reacting, building parasocial loyalty.

---

### 7. 30-DAY LAUNCH REVIEW FRAMEWORK

After 30 days, query `performance_log.json` to answer these specific questions:

**1. The Peak Signal Audit:**
Compare the 7d view counts grouped by `peak_signal` (heatmap vs. comments vs. audio_energy). 
*   *Threshold Action:* If the `heatmap` signal correlates with videos that get >10k views, but the `comments` fallback averages 1k views, the `min_views` threshold for sourcing is too low. Raise the minimum view requirement to scrape videos big enough to generate a YouTube heatmap.

**2. The Whitelist Cull:**
Group AVD (Average View Duration) by `source_channel_title`. 
*   *Threshold Action:* If a specific creator's clips consistently result in <70% AVD, their pacing doesn't translate to short-form. Remove them from the whitelist entirely.

**3. The Hook Style Review:**
Group swipe-away rates or raw view volume by `hook_style`.
*   *Threshold Action:* If "deadpan" averages 5k views and "hype" averages 500 views, rewrite the Groq prompts to force all outputs into the deadpan format.
