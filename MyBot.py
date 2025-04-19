# Importation des bibliothèques
import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp
from collections import deque
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from keep_alive import keep_alive

# Chargement des variables d'environnement
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Configuration des intentions
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Authentification Spotify
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))

# File d'attente et volume
SONG_QUEUES = {}
VOLUME_LEVELS = {}

# yt-dlp options
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch1:",
    "nocheckcertificate": True,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
}

FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"


def format_duration(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02}"


def create_song_embed(title,
                      duration,
                      user,
                      uploader,
                      playing=False,
                      volume=1.0):
    status = "▶️ En lecture" if playing else "➕ Ajoutée à la file"
    embed = discord.Embed(
        title=status,
        description=f"**{title}**\n🎤 **{uploader}**\n👤 {user}",
        color=0xe74c3c)
    embed.add_field(name="⏱️ Durée", value=duration, inline=True)
    embed.add_field(name="🔊 Volume",
                    value=f"{int(volume * 100)}%",
                    inline=True)
    embed.set_footer(
        text=
        "🔥ALWAYS STRIVE AND PROSPER🔥\n                        🌟A$AP🌟          "
    )
    return embed


def create_playlist_embed(tracks, added_by, volume=1.0):
    embed = discord.Embed(title=f"📋 Playlist ajoutée ({len(tracks)} titres)",
                          color=0xe74c3c)
    for i, track in enumerate(tracks[:10]):
        title = track.get("title", "Sans titre")
        duration = format_duration(track.get("duration", 0))
        uploader = track.get("uploader", "Inconnu")
        embed.add_field(name=f"{i+1}. **{title}**",
                        value=f"🎤 **{uploader}** | ⏱️ Durée: {duration}",
                        inline=False)
    if len(tracks) > 10:
        embed.set_footer(text=f"...et {len(tracks) - 10} autres titres")
    else:
        embed.set_footer(
            text=
            "🔥ALWAYS STRIVE AND PROSPER🔥\n                        🌟A$AP🌟          "
        )
    return embed


async def search_ytdlp_url_only(query):
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None,
                                          lambda: _extract_url_only(query))
    except Exception as e:
        print(f"Erreur yt-dlp: {e}")
        return {}


def _extract_url_only(query):
    options = dict(YDL_OPTIONS)
    cookie_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    if os.path.exists(cookie_path):
        options["cookiefile"] = cookie_path
        options["http_headers"] = {
            "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

    with yt_dlp.YoutubeDL(options) as ydl:
        try:
            data = ydl.extract_info(query, download=False)
            if not data:
                print("yt-dlp n'a rien trouvé.")
                return {}

            if "entries" in data and isinstance(data["entries"],
                                                list) and data["entries"]:
                return data["entries"][0]

            return data
        except Exception as e:
            print("Erreur yt-dlp:", e)
            return {}


async def connect_to_voice_channel(voice_channel, guild_id):
    voice_client = voice_channel.guild.voice_client
    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_channel != voice_client.channel:
        await voice_client.move_to(voice_channel)
    return voice_client


async def play_next_song(voice_client, guild_id, channel):
    if not SONG_QUEUES[guild_id]:
        await voice_client.disconnect()
        SONG_QUEUES[guild_id] = deque()
        return

    audio_url, title, duration, user, uploader = SONG_QUEUES[guild_id].popleft(
    )
    volume = VOLUME_LEVELS.get(guild_id, 1.0)
    source = discord.FFmpegPCMAudio(audio_url,
                                    before_options=FFMPEG_BEFORE_OPTIONS,
                                    options="-vn")
    source = discord.PCMVolumeTransformer(source, volume)

    async def safe_play():
        embed = create_song_embed(title,
                                  format_duration(duration),
                                  user,
                                  uploader,
                                  playing=True,
                                  volume=volume)
        message = await channel.send(embed=embed)

        for emoji in ["⏯️", "⏩", "📛"]:
            await message.add_reaction(emoji)

        def check(reaction, user_):
            return user_ != bot.user and reaction.message.id == message.id and str(
                reaction.emoji) in ["⏯️", "⏩", "📛"]

        while True:
            if not voice_client.is_playing() and not voice_client.is_paused():
                break
            try:
                reaction, user_ = await bot.wait_for("reaction_add",
                                                     timeout=duration + 10,
                                                     check=check)
                emoji = str(reaction.emoji)
                await message.remove_reaction(emoji, user_)

                if emoji == "⏯️":
                    if voice_client.is_playing():
                        voice_client.pause()
                        await channel.send("⏸️ Pause demandée.")
                    elif voice_client.is_paused():
                        voice_client.resume()
                        await channel.send("▶️ Lecture reprise.")
                elif emoji == "⏩":
                    voice_client.stop()
                    await channel.send("⏩ Chanson sautée.")
                    return
                elif emoji == "📛":
                    SONG_QUEUES[guild_id].clear()
                    voice_client.stop()
                    await voice_client.disconnect()
                    await channel.send("📛 Musique arrêtée et bot déconnecté.")
                    return

                await asyncio.sleep(0.5)

            except asyncio.TimeoutError:
                break

    def after_play(error):
        if error:
            print(f"Erreur dans after_play: {error}")
        fut = asyncio.run_coroutine_threadsafe(
            play_next_song(voice_client, guild_id, channel), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"Erreur dans after_play (fut): {e}")

    voice_client.play(source, after=after_play)
    asyncio.create_task(safe_play())


def parse_spotify_url(url):
    if "track" in url:
        track_id = url.split("track/")[1].split("?")[0]
        track = sp.track(track_id)
        return [f"{track['name']} {track['artists'][0]['name']}"]
    elif "playlist" in url:
        playlist_id = url.split("playlist/")[1].split("?")[0]
        results = sp.playlist_tracks(playlist_id)
        return [
            f"{item['track']['name']} {item['track']['artists'][0]['name']}"
            for item in results['items']
        ]
    elif "album" in url:
        album_id = url.split("album/")[1].split("?")[0]
        results = sp.album_tracks(album_id)
        album = sp.album(album_id)
        return [
            f"{track['name']} {album['artists'][0]['name']}"
            for track in results['items']
        ]
    else:
        return []


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} est en ligne !")


@bot.tree.command(name="play",
                  description="Écoutez une chanson ou une playlist.")
@app_commands.describe(song_query="Recherche, lien YouTube ou Spotify")
async def play(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("Vous devez être dans un canal vocal.")
        return

    voice_channel = interaction.user.voice.channel
    voice_client = await connect_to_voice_channel(voice_channel,
                                                  str(interaction.guild_id))
    guild_id = str(interaction.guild_id)
    if SONG_QUEUES.get(guild_id) is None:
        SONG_QUEUES[guild_id] = deque()
    volume = VOLUME_LEVELS.get(guild_id, 1.0)

    queries = []
    if "spotify.com" in song_query:
        try:
            queries = parse_spotify_url(song_query)
        except Exception as e:
            print("Erreur Spotify:", e)
            await interaction.followup.send(
                "❌ Impossible de lire ce lien Spotify.")
            return
    else:
        queries = [song_query]

    new_tracks = []
    for query in queries:
        result = await search_ytdlp_url_only(query)
        if not result:
            continue

        audio_url = result.get("url")
        title = result.get("title", query)
        duration = result.get("duration", 0)
        uploader = result.get("uploader", "Inconnu")
        user = interaction.user.display_name

        SONG_QUEUES[guild_id].append(
            (audio_url, title, duration, user, uploader))
        new_tracks.append(result)

        if not (voice_client.is_playing() or voice_client.is_paused()):
            await play_next_song(voice_client, guild_id, interaction.channel)

    # 🔐 PROTECTION CONTRE VIDE
    if not new_tracks:
        await interaction.followup.send(
            "❌ Aucune chanson trouvée ou lien bloqué par YouTube (vérification anti-bot). Essaie avec un autre lien."
        )
        return

    embed = create_playlist_embed(
        new_tracks, interaction.user.display_name,
        volume) if len(new_tracks) > 1 else create_song_embed(
            new_tracks[0]["title"],
            format_duration(new_tracks[0].get("duration", 0)),
            interaction.user.display_name,
            new_tracks[0].get("uploader", "Inconnu"),
            volume=volume)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="volume",
                  description="Change le volume de la musique (0 à 200%)")
@app_commands.describe(volume="Volume souhaité (0-200)")
async def volume(interaction: discord.Interaction, volume: int):
    if volume < 0 or volume > 200:
        await interaction.response.send_message(
            "Veuillez indiquer un volume entre 0 et 200.")
        return
    VOLUME_LEVELS[str(interaction.guild_id)] = volume / 100
    await interaction.response.send_message(f"🔊 Volume défini à {volume}%")


@bot.tree.command(name="skip", description="Saute la chanson en cours")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await interaction.response.send_message("⏭️ Chanson sautée.")
    else:
        await interaction.response.send_message("Je ne joue rien à sauter.")


@bot.tree.command(name="pause", description="Met en pause la musique")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Lecture mise en pause.")
    else:
        await interaction.response.send_message("Rien n'est en lecture.")


@bot.tree.command(name="resume", description="Reprend la musique")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Lecture reprise.")
    else:
        await interaction.response.send_message("Je ne suis pas en pause.")


@bot.tree.command(name="stop", description="Arrête tout")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        guild_id = str(interaction.guild_id)
        SONG_QUEUES[guild_id].clear()
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        await vc.disconnect()
    try:
        await interaction.response.send_message(
            "📛 Lecture arrêtée et déconnectée.")
    except discord.errors.NotFound:
        await interaction.followup.send("📛 Lecture arrêtée et déconnectée.")


@bot.tree.command(name="queue", description="Affiche la file d'attente")
async def queue(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    queue = SONG_QUEUES.get(guild_id, deque())
    if not queue:
        await interaction.response.send_message("La file d'attente est vide.")
        return

    embed = discord.Embed(title="🎶 File d'attente", color=0xe74c3c)
    for i, (_, title, duration, user, uploader) in enumerate(queue):
        embed.add_field(
            name=f"{i+1}. **{title}**",
            value=
            f"🎤 **{uploader}** | ⏱️ Durée: {format_duration(duration)} | 👤 Ajoutée par {user}",
            inline=False)
    await interaction.response.send_message(embed=embed)


# Lancement du bot
keep_alive()
bot.run(TOKEN)
