# Getting Started with EchoNest

EchoNest is a shared music queue for your office, party, or listening group. Everyone adds songs, votes on what plays next, and listens together in real time.

## Signing In

1. Open the EchoNest link your host shared with you.
2. Click **Sign in with Google**.
3. After signing in, you'll be prompted to **Connect Spotify**. Click the green button to link your Spotify account.
   - **Spotify Premium is required** for playback.
   - Make sure the Spotify app is open on your device before connecting.
   - You can click "Skip for now" to browse the queue without playback, and connect Spotify later from the **Other** tab.

## The Queue

The right side of the screen shows the shared queue. The currently playing song appears at the top with album art and the profile picture of whoever added it.

Songs play in order, influenced by votes. When the queue runs low, EchoNest automatically fills it with recommendations based on what's been playing (that's **Bender** at work).

## Adding Songs

1. Click the **Search** tab on the left.
2. Type an artist, song, or album name into the search box.
3. Click a result to add it to the queue.

You can also paste a Spotify Playlist link, YouTube link, or SoundCloud URL directly into the search box.

## Voting

Each song in the queue has vote buttons:

- **Up** / **Down** -- moves the song higher or lower in the queue.
- **Jam** -- shows extra love for a song. Jam icons appear next to the track so everyone can see.
- **Remove** -- removes a song you added (or any song, if you're feeling bold).

## Comments

Click the comment icon on any song (in the queue or now playing) to leave a message. Comments show up next to the song for everyone to see.

## Airhorns

Click the **Airhorn** tab and hit the airhorn button. You know what it does.

## Nests

Nests are separate listening rooms with their own queues. Think of them as breakout sessions -- the main room keeps playing, and a Nest runs independently.

- **Build a Nest** -- creates a new room with a shareable 5-character code. You can optionally set a seed track to shape the auto-fill genre.
- **Join a Nest** -- enter a code to hop into someone else's Nest.
- **Back to The EchoNest** -- return to the main room.

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
| **Mute** | Mutes your local audio. |
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
