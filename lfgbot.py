import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.voice_states = True  # det her er nødvendig for at vi kan monitor voice channel aktiviteter btw, som vi skal for at slette vc's efter 30 sek af inaktivitet ::)))))
intents.guilds = True

# prefix og intents skal defineres, vi skaber også bare bot variablen her, den kunne hedde whatever
bot = commands.Bot(command_prefix="/", intents=intents)

# vores file paths til data saving wup
TEMP_VC_FILE = "temp_vc.json"
LFG_EMBEDS_FILE = "lfg_embeds.json"

# initialize vores filer
for file in [TEMP_VC_FILE, LFG_EMBEDS_FILE]:
    try:
        with open(file, "r") as f:
            data = f.read().strip()
            if not data:  # If the file is empty
                raise ValueError("File is empty")
            json.loads(data)  # attempt to parse JSON
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        with open(file, "w") as f:
            json.dump({}, f)  # empty JSON object


# Role mapping
rank_roles = {
    "silver": 1320179163608649739,
    "bronze": 1320178964848840704,
    "gold": 1320179276951064648,
    "platinum": 1320179316251951197,
    "plat": 1320179316251951197,  # Alias for platinum
    "p": 1320179316251951197,  # Alias for platinum
    "diamond": 1320179379862507593,
    "dia": 1320179379862507593,  # Alias for diamond
    "d": 1320179379862507593,# Alias for diamond
    "grandmaster": 1320179440914796604,
    "gm": 1320179440914796604, #alias for grandmaster
    "master": 1320179440914796604, #alias for grandmaster
    "m": 1320179440914796604, #alias for grandmaster
    "champion": 1320179440914796604, #alias for champion
    "c": 1320179440914796604, #alias for champion
    "eternity": 1320179507319013539, 
    "one above all": 1320179601661497427,
    "oaa": 1320179601661497427  # Alias for one above all
}

# Channel restriction, this is for the /lfg command
allowed_channel_id = 1320121523675336726
# these are our dedicated text channels for the /create command
dedicated_channels = [
    1320206547502104698, 1320206559166333033, 1320206570008739892,
    1320206580901347349, 1320206592855244874, 1320206535787417703,
    1320121449444278413
]

# just some helper fucntions to read/write JSON
def read_json(file_path):
    with open(file_path, "r") as f:
        return json.load(f)

def write_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

@bot.event
async def on_ready():
    print(f"Bot is ready. Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands globally.")
        for command in synced:
            print(f"Command: {command.name} - {command.description}")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    if not cleanup_voice_channels.is_running():
        cleanup_voice_channels.start()
    if not cleanup_lfg_embeds.is_running():
        cleanup_lfg_embeds.start()

@bot.event
async def on_message(message):
    if message.channel.id == allowed_channel_id and not message.content.startswith("/lfg"):
        if message.author != bot.user:  # Prevent deletion of bot messages (e.g., embeds)
            await message.delete()

@bot.tree.command(name="create", description="Create a temporary voice channel.")
async def create(interaction: discord.Interaction):
    if interaction.channel.id not in dedicated_channels:
        await interaction.response.send_message("This command can only be used in dedicated channels.", ephemeral=True)
        return


    class CreateChannelModal(discord.ui.Modal, title="Create Temporary Voice Channel"):
        channel_name = discord.ui.TextInput(label="What do you want the channel to be named?", placeholder="Enter channel name")

        async def on_submit(self, interaction: discord.Interaction):
            guild = interaction.guild
            # Find the category of the text channel where the command was issued
            text_channel = interaction.channel
            category = text_channel.category

            if not category:
                await interaction.response.send_message("This text channel is not in a category, so a voice channel cannot be created.", ephemeral=True)
                return

            # Create the temporary voice channel within the same category
            voice_channel = await guild.create_voice_channel(name=self.channel_name.value, category=category)

            # Save to JSON
            temp_vc_data = read_json(TEMP_VC_FILE)
            temp_vc_data[str(voice_channel.id)] = {
                "name": self.channel_name.value,
                "category": category.name
            }
            write_json(TEMP_VC_FILE, temp_vc_data)

            embed = discord.Embed(title="Temporary Voice Channel Created", color=discord.Color.green())
            embed.add_field(name="Channel Name", value=self.channel_name.value, inline=False)
            embed.add_field(name="Category", value=category.name, inline=False)
            embed.set_footer(text="Channel will be deleted after 30 seconds of inactivity.")

            await interaction.response.send_message(embed=embed)

    await interaction.response.send_modal(CreateChannelModal())

@bot.tree.command(name="lfg", description="Find players with specific ranks and a voice channel.")
async def lfg(interaction: discord.Interaction):
    if interaction.channel.id != allowed_channel_id:
        await interaction.response.send_message("This command can only be used in the designated LFG channel.", ephemeral=True)
        return

    user_voice_state = interaction.user.voice
    user_voice_channel = user_voice_state.channel if user_voice_state and user_voice_state.channel else None

    # Create a modal for user input
    class LFGModal(discord.ui.Modal, title="LFG Setup"):
        user_rank = discord.ui.TextInput(label="What rank are YOU?", placeholder="e.g., Silver")
        rank_range = discord.ui.TextInput(label="What rank do you want people from?", placeholder="e.g., GM, Diamond")
        region = discord.ui.TextInput(label="Which region are you playing in?", placeholder="e.g., EU, NA")
        current_players = discord.ui.TextInput(label="Current players in team? (0-6)", placeholder="Enter number of players")

        async def on_submit(self, interaction: discord.Interaction):
            mentioned_roles = []
            for rank in self.rank_range.value.split(","):
                rank = rank.strip().lower()
                role_id = rank_roles.get(rank)
                if role_id:
                    mentioned_roles.append(f"<@&{role_id}>")

            if not mentioned_roles:
                await interaction.response.send_message("No valid ranks were provided.", ephemeral=True)
                return

            embed = discord.Embed(title="Looking for Group", color=discord.Color.blue())
            embed.add_field(name="User Rank", value=self.user_rank.value, inline=False)
            embed.add_field(name="Mentioned Roles", value=" ".join(mentioned_roles), inline=False)
            embed.add_field(name="Region", value=self.region.value, inline=False)
            embed.add_field(name="Current Players", value=self.current_players.value, inline=False)

            if user_voice_channel:
                embed.add_field(name="Voice Channel", 
                                value=f"[Join Voice Channel](https://discord.com/channels/{interaction.guild.id}/{user_voice_channel.id})", 
                                inline=False)
            else:
                embed.add_field(name="Voice Channel", value="Not in a voice channel", inline=False)

            embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url)

            message = await interaction.channel.send(embed=embed)

            # Save to JSON
            lfg_embeds_data = read_json(LFG_EMBEDS_FILE)
            lfg_embeds_data[str(message.id)] = {
                "timestamp": datetime.utcnow().isoformat()
            }
            write_json(LFG_EMBEDS_FILE, lfg_embeds_data)

    # Show the modal to the user
    await interaction.response.send_modal(LFGModal())

@tasks.loop(seconds=30)
async def cleanup_voice_channels():
    temp_vc_data = read_json(TEMP_VC_FILE)
    for channel_id in list(temp_vc_data.keys()):
        channel = bot.get_channel(int(channel_id))
        if channel and len(channel.members) == 0:
            await channel.delete()
            del temp_vc_data[channel_id]
            write_json(TEMP_VC_FILE, temp_vc_data)

@tasks.loop(seconds=30)
async def cleanup_lfg_embeds():
    lfg_embeds_data = read_json(LFG_EMBEDS_FILE)
    for message_id, details in list(lfg_embeds_data.items()):
        timestamp = datetime.fromisoformat(details["timestamp"])
        if datetime.utcnow() - timestamp > timedelta(minutes=10):
            channel = bot.get_channel(allowed_channel_id)
            try:
                message = await channel.fetch_message(int(message_id))
                await message.delete()
            except discord.NotFound:
                pass
            del lfg_embeds_data[message_id]
            write_json(LFG_EMBEDS_FILE, lfg_embeds_data)

@cleanup_voice_channels.before_loop
async def before_cleanup_voice_channels():
    await bot.wait_until_ready()

@cleanup_lfg_embeds.before_loop
async def before_cleanup_lfg_embeds():
    await bot.wait_until_ready()


TOKEN = 
bot.run(TOKEN)
