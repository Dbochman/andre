# Getting Started with EchoNest

**[echone.st](https://echone.st)**

EchoNest is a shared music queue for your office, party, or listening group. Everyone adds songs, votes on what plays next, and listens together in real time.

## Signing In

1. Open the EchoNest link your host shared with you.
2. Click **Sign in with Google**.
3. After signing in, you'll be prompted to **Connect Spotify**. Click the green button to link your Spotify account.
   - **Spotify Premium is required** for playback.
   - Make sure the Spotify app is open on your device before connecting.
   - You can click "Skip for now" to browse the queue without playback, and connect Spotify later from the **Other** tab.

## The EchoNest (Main Queue)

When you log in you land in the main queue -- "The EchoNest." This is the shared queue everyone sees by default. What makes it special is history: years of play logs from past sessions are stored on the server, and Bender draws on them.

The Throwback strategy (30% of auto-fills in the main queue) pulls songs that were played on the same day of the week from past sessions. If it's Wednesday, you get songs people queued on previous Wednesdays. They show up credited to whoever originally added them, with "(throwback)" next to their name -- so you'll see familiar faces resurfacing old picks.

The right side of the screen shows the queue. The currently playing song appears at the top with album art and the profile picture of whoever added it. Songs play in order, influenced by votes. When the queue runs low, Bender auto-fills it with recommendations.

### Preview Track

Below the now-playing area you'll see a preview of the next track Bender is considering. This is a low-effort way to shape the vibe without having to search for something specific. It has three buttons:

- **Spotify** -- opens the track in Spotify so you can give it a listen.
- **Queue** -- adds the track to the queue immediately.
- **Filter** -- skips this suggestion and shows you a different one. Tap through a few to browse what Bender has lined up.

## Adding Songs

There are a few ways to get music into the queue:

1. **Search** -- click the Search tab, type an artist or song name, and click a result to add it.
2. **Paste a link** -- paste a Spotify Playlist link, YouTube link, or SoundCloud URL directly into the search box.
3. **Queue from the preview** -- if Bender is showing a preview track below now-playing, click its **Queue** button to add it directly.

## Voting

Each song in the queue has vote buttons:

- **Up** / **Down** -- moves the song higher or lower in the queue.
- **Jam** -- shows extra love for a song. Jam icons appear next to the track so everyone can see.
- **Remove** -- removes a song you added (or any song, if you're feeling bold).

## Comments

Click the comment icon on any song (in the queue or now playing) to leave a message. Comments show up next to the song for everyone to see.

## Bender (Auto-fill)

When the queue runs low, Bender kicks in and adds songs automatically. It picks from several strategies, weighted so you get a good mix.

### Main room strategies

| Strategy | Weight | What it does |
|----------|--------|-------------|
| Genre | 35% | Searches Spotify for tracks matching the genre of what's been playing. |
| Throwback | 30% | Resurfaces songs from past sessions played on the same day of the week. Credited to whoever originally queued them. |
| Artist Search | 25% | Finds tracks by artists who've collaborated with the current seed artist. |
| Top Tracks | 5% | The seed artist's most popular songs on Spotify. |
| Album | 5% | Other tracks from the same album as the seed. |

### Nests (user-created rooms)

Nests don't have play history, so Throwback is unavailable. The remaining strategies split its weight. If the Nest has a genre (either from its name or a seed track), the Genre strategy gets a bonus (+20%), so most auto-fills match the room's vibe. Each Nest name maps to a genre and seed track -- for example, "FunkNest" seeds off Parliament and favors funk, "ChordNest" seeds off Bill Evans and favors jazz.

### How seeding works

Bender picks its seed from the most recent signal it can find: the last song a human queued, then the last song Bender added, then whatever's currently playing. You can browse what Bender has queued up by tapping **Filter** on the preview track to cycle through suggestions, and **Queue** anything that catches your ear.

## Airhorns

Click the **Airhorn** tab and hit the airhorn button. You know what it does.

## Nests

Nests are separate listening rooms with their own queues. Think of them as breakout sessions -- the main queue keeps playing, and a Nest runs independently.

- **Build a Nest** -- creates a new room with a shareable 5-character code. You can optionally set a seed track to shape the auto-fill genre.
- **Join a Nest** -- enter a code to hop into someone else's Nest.
- **Back to The EchoNest** -- return to the main queue.

Each Nest has its own queue, votes, and now-playing state. You can provide a seed track url with a name to influence bender's suggestions.

## Other Options

The **Other** tab has additional controls:

| Button | What it does |
|--------|-------------|
| **Sync Audio** | Plays the current song through your browser in sync with everyone else. |
| **Reconnect Spotify** | Re-links your Spotify account (useful if playback stops working). |
| **Change Colors** | Cycles through nine color themes. |
| **Hide Shame** | Replaces everyone's profile pictures (including yours) with anonymous avatars. |
| **Skip Playing Song** | Skips the currently playing track. |

| **Clear Queue** | Removes all songs from the queue. Use with caution. |
| **Pause/Unpause Everything** | Toggles paused state for everyone. |

## Troubleshooting

**Songs aren't playing automatically.**
Make sure you've connected Spotify (check the **Other** tab for "Reconnect Spotify"). Spotify Premium is required. The Spotify app must be open and music must be already playing on your device.

**The queue is paused and there is no audio.**
Unpause Playback Once something is in the queue, Bender will start auto-filling with related tracks to keep the music going.

**Queue elements are flickering or buttons aren't responding.**
Hard-refresh your browser (Cmd+Shift+R on Mac, Ctrl+Shift+R on Windows). This clears cached scripts and re-establishes the WebSocket connection.

**Playback is out of sync.**
Click **Sync Audio** on the EchoNest tab to re-sync your player with the server.
