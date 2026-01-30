import asyncio
import random
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
from SANYAMUSIC import app, YouTube, LOGGER
from config import BANNED_USERS
from SANYAMUSIC.utils.database import is_active_chat
from SANYAMUSIC.utils.decorators.language import language, languageCB
from SANYAMUSIC.utils.exceptions import AssistantErr
from SANYAMUSIC.utils.database import get_cmode
from SANYAMUSIC.utils.formatters import time_to_seconds

RANDOM_HINDI_QUERIES = [
    "Insta tending", "Lofi songs", "Latest Hindi Songs", "Romantic Songs", 
    "Sad Songs", "Punjabi Hits", "Best of Arijit Singh", 
    "Atif Aslam Hits", "Old Hindi Songs", "90s Bollywood Songs",
    "Party Songs Hindi", "Indian Lo-fi"
]

async def show_suggestions(chat_id: int, last_played_title: str):
    """
    Shows song suggestions after 10 seconds if no song is playing.
    Call this function in your stream end handler.
    """
    # 1. Wait 20 seconds
    await asyncio.sleep(10)
    
    if await is_active_chat(chat_id):
        LOGGER(__name__).info(f"Chat {chat_id} is active, skipping suggestions.")
        return
    
    # 2. Fetch suggestions
    
    suggestions = []
    # Try to get suggestions based on the last played song
    if last_played_title:
        clean_title = last_played_title
        if "-" in clean_title:
            clean_title = clean_title.split("-")[0].strip()

        keyword = f"songs similar to {clean_title}"

        # Fetch a bit more to have a buffer for filtering
        initial_suggestions = await YouTube.suggestions(keyword, limit=5)

        # Filter out the last played song
        if initial_suggestions:
            suggestions = [
                s for s in initial_suggestions
                if last_played_title.lower() not in s['title'].lower()
            ]

    # If we don't have enough, get random ones
    if len(suggestions) < 3:
        keyword = random.choice(RANDOM_HINDI_QUERIES)
        needed = 3 - len(suggestions)
        new_suggestions = await YouTube.suggestions(keyword, limit=needed + 2)  # fetch extra for filtering
        if new_suggestions:
            filtered_new = [
                s for s in new_suggestions
                if not last_played_title or last_played_title.lower() not in s['title'].lower()
            ]
            suggestions.extend(filtered_new)

    # Ensure unique suggestions and limit to 3
    final_suggestions = []
    seen_ids = set()
    for s in suggestions:
        if len(final_suggestions) < 3 and s['id'] not in seen_ids:
            final_suggestions.append(s)
            seen_ids.add(s['id'])
    suggestions = final_suggestions

    if not suggestions:
        LOGGER(__name__).info(f"No suggestions found for chat {chat_id}.")
        return

    # 3. Build Buttons
    buttons = []
    for vid in suggestions:
        buttons.append([
            InlineKeyboardButton(
                text=f"🎧 {vid['title'][:30]}... - {vid['duration']}",
                callback_data=f"suggestion_play:{vid['id']}"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text="Refresh", callback_data="refresh_suggestions"),
        InlineKeyboardButton(text="Close", callback_data="close")
    ])

    # 4. Send Message
    try:
        msg = await app.send_message(
            chat_id,
            text=f"<b>💿 No music is playing! or queue is empty.</b>\n\n💡 <i>Use /suggest lofi songs or /suggest to search for song suggestions.</i>\n\nHere are some suggestions:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        # 5. Delete after 1 minute
        await asyncio.sleep(60)
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        LOGGER(__name__).error(f"Error sending suggestion message: {e}")

@app.on_message(filters.command("suggest") & ~BANNED_USERS)
@language
async def suggest_command(client, message, _):
    msg = await message.reply_text("🔎 Finding suggestions...")
    
    if len(message.command) > 1:
        keyword = message.text.split(None, 1)[1]
        refresh_data = f"refresh_suggestions:{keyword}"
        if len(refresh_data) > 64:
            refresh_data = "refresh_suggestions"
    else:
        keyword = random.choice(RANDOM_HINDI_QUERIES)
        refresh_data = "refresh_suggestions"

    suggestions = await YouTube.suggestions(keyword, limit=5)
    
    if not suggestions:
        return await msg.edit(f"Could not fetch suggestions for '{keyword}'. Please try again.")

    buttons = []
    for vid in suggestions:
        buttons.append([
            InlineKeyboardButton(
                text=f"🎧 {vid['title'][:30]}... - {vid['duration']}",
                callback_data=f"suggestion_play:{vid['id']}"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text="Refresh", callback_data=refresh_data),
        InlineKeyboardButton(text="Close", callback_data="close")
    ])

    await msg.edit_text(
        f"<b>🎼 Here are some suggestions for you:</b>\n\nBased on: <i>{keyword}</i>",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^refresh_suggestions") & ~BANNED_USERS)
@languageCB
async def refresh_suggestions_cb(client, cq, _):
    await cq.answer("Refreshing...", show_alert=False)
    
    if ":" in cq.data:
        keyword = cq.data.split(":", 1)[1]
        refresh_data = cq.data
    else:
        keyword = random.choice(RANDOM_HINDI_QUERIES)
        refresh_data = "refresh_suggestions"

    suggestions = await YouTube.suggestions(keyword, limit=3)
    
    if not suggestions:
        return await cq.answer("Could not fetch new suggestions. Please try again.", show_alert=True)

    buttons = []
    for vid in suggestions:
        buttons.append([
            InlineKeyboardButton(
                text=f"🎧 {vid['title'][:30]}... - {vid['duration']}",
                callback_data=f"suggestion_play:{vid['id']}"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text="Refresh", callback_data=refresh_data),
        InlineKeyboardButton(text="Close", callback_data="close")
    ])

    try:
        await cq.edit_message_text(
            f"<b>🎼 Here are some suggestions for you:</b>\n\nBased on: <i>{keyword}</i>",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception:
        pass

@app.on_callback_query(filters.regex(r"^suggestion_play:") & ~BANNED_USERS)
@languageCB
async def suggestion_play_cb(client, cq, _):
    vid_id = cq.data.split(":")[1]
    await cq.answer("Processing...", show_alert=False)

    # Determine the chat_id for the voice call
    chat_id_for_stream = cq.message.chat.id
    channel = await get_cmode(chat_id_for_stream)
    if channel:
        chat_id_for_stream = channel

    user_id = cq.from_user.id
    user_name = cq.from_user.first_name

    mystic = await cq.message.reply_text(_["play_1"])

    try:
        details, track_id = await YouTube.track(vid_id, True)
    except Exception as e:
        return await mystic.edit_text(_["play_3"] + f"\n\nError: {e}")

    if details.get("duration_min"):
        duration_sec = time_to_seconds(details["duration_min"])
        if duration_sec > config.DURATION_LIMIT:
            return await mystic.edit_text(
                _["play_6"].format(config.DURATION_LIMIT_MIN, client.me.mention)
            )
    else:
        # For simplicity, we won't handle live streams from suggestions.
        return await mystic.edit_text("Live streams are not supported for suggestions.")

    try:
        from SANYAMUSIC.utils.stream.stream import stream
        await stream(
            client,
            _,
            mystic,
            user_id,
            details,  # result
            chat_id_for_stream,  # voice chat id
            user_name,
            cq.message.chat.id,  # original_chat_id
            video=None,  # audio only for now
            streamtype="youtube",
            forceplay=None,  # Don't force play
        )
    except AssistantErr as e:
        await mystic.edit_text(str(e))
        return
    except Exception as e:
        ex_type = type(e).__name__
        err = _["general_2"].format(ex_type)
        await mystic.edit_text(err)
        return

    await mystic.delete()
    await cq.message.delete()
