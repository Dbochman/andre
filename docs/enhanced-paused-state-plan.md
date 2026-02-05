# Enhanced Paused State Display

## Overview

When the player is paused, make it visually obvious to users by:
1. Displaying "PAUSED" title with Bender quote in the now-playing text area
2. Showing current song's album art with a pause icon overlay
3. Replacing Bender headshot in the person image area
4. Swapping airhorn buttons with an "unpause everything" button

## Visual Design

| Area | When Playing | When Paused |
|------|--------------|-------------|
| **Now-playing text** | Song title + Artist | "Bite my shiny metal pause button!" (Bender quote) |
| **Album art** | Current song's album | Current song's album with pause icon overlay |
| **Person image** | User who queued song | `theechonestcom.png` (Bender headshot) |
| **Airhorn buttons** | Visible | Hidden, replaced with "unpause everything" |
| **Browser tab** | "Song - Artist \| Andre" | "PAUSED \| Andre" |

## Implementation

### Part 1: CSS Changes (`static/css/app.css`)

Add at end of file - paused state styling for album art with pause icon overlay:

```css
/* Paused state - album art overlay */
/* Note: #now-playing-album already has position:absolute, keep it */

#now-playing-album.paused::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.3);
    z-index: 1001;
}

#now-playing-album.paused::after {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 100px;
    height: 100px;
    background-color: rgba(0, 0, 0, 0.8);
    border-radius: 50%;
    z-index: 1002;
    /* Pause icon bars using gradient */
    background-image: linear-gradient(to right,
        transparent 25%,
        #fff 25%,
        #fff 40%,
        transparent 40%,
        transparent 60%,
        #fff 60%,
        #fff 75%,
        transparent 75%
    );
    background-size: 50% 50%;
    background-position: center;
    background-repeat: no-repeat;
}
```

### Part 2: HTML Changes (`templates/main.html`)

Insert new unpause button immediately after `#do-airhorn` button, before `#do-free-airhorn`:

**Location**: Inside `#airhorn-tab` div, between the airhorn button and free airhorn button

```html
<div id="airhorn-tab" class="visible">
    <a href="javascript:void(0);" id="do-airhorn" class="left-button">airhorn</a>
    <a href="javascript:void(0);" id="airhorn-unpause-btn" class="left-button" style="display:none;">unpause everything</a>
    <a href="javascript:void(0);" id="do-free-airhorn" class="left-button">free airhorn</a>
    <div id="airhorn-history">
    </div>
</div>
```

### Part 3: JavaScript Changes (`static/js/app.js`)

#### Change 1: Modify `NowPlayingView.render()` method

**Location**: Inside the `NowPlayingView` Backbone view definition (around line 417)

**Why**: The view listens to model changes and re-renders automatically. We need to handle paused state in the view itself to prevent conflicts.

**Replace the existing render method with:**

```javascript
render: function(){
    // Handle paused state
    if (playerpaused) {
        // Render paused content (intentionally omits #playing-buttons and comment button)
        this.$el.html(
            '<div id="now-playing-person" style="background-image:url(/static/theechonestcom.png);"></div>' +
            '<div id="now-playing-text">' +
                '<h1>PAUSED</h1>' +
                '<h2>"Bite my shiny metal pause button!"</h2>' +
            '</div>' +
            '<div id="now-playing-jammers"></div>'
        );

        // Show next song's album art with pause overlay
        var nextSong = playlist.at(0);
        if (nextSong && nextSong.get('img')) {
            $('#now-playing-album').css('background-image', 'url(' + nextSong.get('img') + ')');
        } else {
            $('#now-playing-album').css('background-image', '');
        }

        $('#now-playing-album').addClass('paused');
        this.$el.removeClass("autoplay");
        _window_resize();
        return this.$el;
    }

    // Normal render when not paused
    if(!this.model || !this.model.get("title")){
        return;
    }
    this.$el.html(TEMPLATES.now_playing(this.model.toJSON()));
    $('#now-playing-album').css('background-image',
                                'url('+this.model.get("big_img")+')')
    $('#now-playing-album').removeClass('paused');
    this.$el.css({'background-color':
                    '#'+this.model.get("background_color"),
                    'color':'#'+this.model.get('foreground_color')});
    this.$el.toggleClass("autoplay", this.model.get("auto"))
    _window_resize();
    return this.$el;
}
```

#### Change 2: Simplify `now_playing_update` handler

**Location**: The `socket.on('now_playing_update', ...)` handler

**Replace the entire handler with:**

```javascript
socket.on('now_playing_update', function(data){
    playerpaused = data.paused;

    // Update button states
    if (playerpaused) {
        $('#pause-button').text('unpause everything');
        $('#do-airhorn, #do-free-airhorn').hide();
        $('#airhorn-unpause-btn').show();
        document.title = "PAUSED | Andre";
    } else {
        $('#pause-button').text('pause everything');
        $('#do-airhorn, #do-free-airhorn').show();
        $('#airhorn-unpause-btn').hide();
    }

    // Always keep now_playing model in sync - this triggers view re-render
    if (data.title) {
        now_playing.clear({silent:true});
        now_playing.set(data);
        if (!playerpaused) {
            document.title = data.title + " - " + data.artist + " | Andre";
        }
    } else if (playerpaused) {
        // Paused with no title data - trigger render anyway
        now_playing.trigger('change');
    }

    // Notifications (only when playing)
    if (!playerpaused && data.title) {
        if(window.webkitNotifications
                && window.webkitNotifications.checkPermission() == 0
                && SHOW_NOTIFICATIONS){
            var note = window.webkitNotifications.createNotification(data.img,
                                                data.title, data.artist);
                note.show();
                setTimeout(function(){note.close();}, 7000);
        }
    }

    // Player sync logic
    if(is_player){
        fix_player(now_playing.get('src'), now_playing.get('trackid'), data.pos, playerpaused);
    }
});
```

#### Change 3: Add click handler for unpause button

**Location**: Inside the `window.addEventListener('load', ...)` block, after the `$('#do-free-airhorn').on('click', do_free_airhorn);` line

```javascript
$('#airhorn-unpause-btn').on('click', function(){
    console.log("unpause button (from airhorn area)");
    socket.emit("unpause");
});
```

## Files to Modify

| File | Changes |
|------|---------|
| `static/css/app.css` | Add `.paused` class for album art with pause icon overlay |
| `templates/main.html` | Add `#airhorn-unpause-btn` button inside `#airhorn-tab` |
| `static/js/app.js` | Modify `NowPlayingView.render()`, update `now_playing_update` handler, add click handler |

## Technical Notes

### Z-Index Hierarchy
- `#now-playing-album`: z-index 1000 (existing)
- `.paused::before` (dark overlay): z-index 1001
- `.paused::after` (pause icon): z-index 1002

### Socket Events
- `socket.emit("unpause")` - Confirmed correct event name (used in existing `pause_button` function)
- Server handler: `on_unpause` in `app.py`

### Assets Used
- `/static/theechonestcom.png` - Bender headshot for person image area

### Backbone View Integration
- `NowPlayingView` listens to `'all'` events on `now_playing` model
- Paused state rendering is handled in the view's `render()` method
- This prevents DOM conflicts from model updates overwriting paused content

### Edge Cases Handled
- **Empty queue**: If `playlist.at(0)` is undefined, album art is cleared
- **Page load while paused**: View render checks `playerpaused` first
- **Paused without title data**: Triggers view re-render manually
- **View re-render conflicts**: Paused rendering handled in view, not handler

### Intentional UI Changes When Paused
- **#playing-buttons removed**: Spotify/YouTube/Jam links hidden (nothing to interact with when paused)
- **Comment button removed**: No active song to comment on
- **ES5 syntax**: Using string concatenation instead of template literals for compatibility

## Verification Steps

1. Start the app or use live site
2. Play a song, verify normal display
3. Click "pause everything" (in Other tab)
4. Verify:
   - Subtitle shows "Bite my shiny metal pause button!"
   - Album area shows next song's art with pause icon overlay
   - Person image shows Bender headshot
   - Airhorn + free airhorn buttons hidden
   - "unpause everything" button visible
   - Browser tab title shows "PAUSED | Andre"
5. Click "unpause everything" button
6. Verify:
   - Normal now-playing display returns immediately
   - Correct song title/artist shown
   - Album art shows current song (no pause overlay)
   - Airhorn buttons visible again
7. Refresh page while paused - verify paused state displays correctly
8. Test with empty queue while paused - verify no errors
9. **New**: Verify that receiving a new `now_playing_update` while paused doesn't flicker or break the paused UI

## Review History

- **v1**: Initial plan with center overlay
- **v2**: Fixed z-index issues (1100-1102), added initial state handling
- **v3**: Removed center overlay, moved paused text to title/subtitle area, added Bender quote, added pause icon on album art
- **v4**: Fixed DOM replacement issue (update specific elements instead of replacing HTML), removed early return to keep model in sync, added empty queue handling
- **v5**: Fixed Backbone view conflict by moving paused rendering into `NowPlayingView.render()` method, simplified handler, improved element location references
- **v6**: Changed to ES5 string concatenation for compatibility, documented intentional removal of playing-buttons and comment button when paused
- **v7**: Fixed CSS layout bug - removed `position: relative` override that broke album positioning
