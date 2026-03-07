import discord
from discord.ext import commands, tasks
import aiohttp
from bs4 import BeautifulSoup
import libsql_client
from datetime import datetime
import re
import os
from dotenv import load_dotenv
from discord import Embed
from discord.ui import View

load_dotenv()

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
invisible_char = "\u200b"

#698588699042119711 angela
#317425052083552257 sergio
#244466932718239744 sydney
#348929639944814592 leyre
#273427129813827584 nat

class MyBot(commands.Bot):
    def __init__(self, command_prefix, intents):
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.announcement_channel_id = 1240423591099502653  # Replace with your channel ID
        self.active_voice_sessions = {}
        self.db = None

    async def setup_hook(self):
        url = os.environ['TURSO_URL'].replace("libsql://", "https://")
        self.db = libsql_client.create_client(
            url=url,
            auth_token=os.environ['TURSO_TOKEN']
        )
        await self.init_db()

    async def init_db(self):
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS hsr_codes
            (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, description TEXT, date_added TEXT, active INTEGER DEFAULT 1)
        ''')
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS dbd_codes
            (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, description TEXT, date_added TEXT, active INTEGER DEFAULT 1)
        ''')
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS gi_codes
            (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, description TEXT, date_added TEXT, active INTEGER DEFAULT 1)
        ''')
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS poke_codes
            (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, description TEXT, date_added TEXT, active INTEGER DEFAULT 1)
        ''')
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS voice_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                user_name TEXT,
                join_time TEXT,
                leave_time TEXT,
                duration INTEGER
            )
        ''')

    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        await self.change_presence(activity=discord.Game(name="🤑buscar codiguitos🤑"))
        self.check_websites.start()  # Start the task loop


    async def get_hsr_codes(self, url):
        # Mark all codes as inactive
        await self.db.execute("UPDATE hsr_codes SET active = 0")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                else:
                    print(f"Error: {response.status}")
                    return []

        soup = BeautifulSoup(text, 'html.parser')
        table = soup.find('table')  # Find the table in the HTML
        if table:
            codes = []
            for row in table.find_all('tr'):  # Iterate over each row in the table
                cells = row.find_all('td')  # Find each cell in the row
                if cells:
                    raw_code = cells[0].text  # The code is in the first cell
                    description = cells[2].text  # The description is in the third cell
                    code = re.sub(r'Quick Redeem', '', raw_code)  # Remove 'Quick Redeem' from the code
                    code = re.sub(r'\[\w+\]', '', code)  # Remove '[word]' from the code
                    code = re.sub(r'\[\d+\]', '', code)  # Remove '[number]' from the code
                    code = re.sub(r'\[.*\]', '', code)  # Remove anything between brackets
                    code = code.strip()  # Remove any leading or trailing whitespace

                    print(code)
                    if 'bg-new' in cells[3].get('class', []):
                        # Check if code already exists
                        existing = await self.db.execute("SELECT code FROM hsr_codes WHERE code = ?", [code])
                        if not existing.rows:
                            await self.db.execute("INSERT INTO hsr_codes (code, description, date_added, active) VALUES (?, ?, ?, 1)", [code, description, str(datetime.now())])
                            date_added = datetime.now()
                            channel = self.get_channel(self.announcement_channel_id)
                            embed = Embed(title=":new: Nuevo código de Honkai Star Rail: :new:", color=0x00ff00)
                            embed.add_field(name=f"{code}", value=f"[Canjear](https://hsr.hoyoverse.com/gift?code={code}{invisible_char})", inline=False)
                            await channel.send(embed=embed)

                            user_ids = ['317425052083552257']
                            for user_id in user_ids:
                                user = await self.fetch_user(user_id)
                                try:
                                    await user.send(embed=embed)
                                except discord.Forbidden:
                                    print(f"No se pudo enviar un DM a {user.name}")
                            codes.append((code, datetime.now(), 1))
                        else:
                            await self.db.execute("UPDATE hsr_codes SET active = 1 WHERE code = ?", [code])
                    elif 'bg-old' in cells[3].get('class', []):
                        # This is an old code, check if it exists in the database and mark it as inactive
                        await self.db.execute("UPDATE hsr_codes SET active = 0 WHERE code = ?", [code])

            return codes
        return []

    async def get_dbd_codes(self, url):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                else:
                    print(f"Error: {response.status}")
                    return []

        soup = BeautifulSoup(text, 'html.parser')
        uls = soup.find_all('ul')

        if uls:
            ul = uls[5]
            print(ul)
            codes = []
            for li in ul.find_all('li'):
                if li.find('strong'):
                    code = li.find('strong').text.split(' ')[0]
                    existing = await self.db.execute("SELECT date_added FROM dbd_codes WHERE code = ?", [code])
                    if not existing.rows:
                        await self.db.execute("INSERT INTO dbd_codes (code, description, date_added, active) VALUES (?, ?, ?, 1)", [code, '', str(datetime.now())])
                        date_added = datetime.now()
                        channel = self.get_channel(self.announcement_channel_id)
                        embed = Embed(title=":new: Nuevo código de Dead By Daylight: :new:", color=0x00ff00)
                        embed.add_field(name=f"{code}", value="", inline=False)
                        await channel.send(embed=embed)
                        user_ids = ['317425052083552257']
                        for user_id in user_ids:
                            user = await self.fetch_user(user_id)
                            try:
                                await user.send(embed=embed)
                            except discord.Forbidden:
                                print(f"No se pudo enviar un DM a {user.name}")
                    else:
                        await self.db.execute("UPDATE dbd_codes SET active = 1 WHERE code = ?", [code])
                        print(f"El código {code} ya existe en la base de datos.")
                        date_added = existing.rows[0][0]
                    codes.append((code, date_added, 1))
            result = await self.db.execute("SELECT * FROM dbd_codes WHERE active = 0")
            inactive_codes = result.rows

            # Add the inactive codes to the codes list
            for code, _, date_added, _ in inactive_codes:
                codes.append((code, date_added, 0))

            return codes
        return []

    async def get_gi_codes(self, url):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                else:
                    print(f"Error: {response.status}")
                    return []

        soup = BeautifulSoup(text, 'html.parser')
        table = soup.find('table')  # Find the table

        scraped_codes = set()
        codes = []
        if table:
            for row in table.find_all('tr'):  # Iterate over each table row
                cols = row.find_all('td')  # Find all td elements in this row
                if cols and len(cols) >= 4:
                    code = cols[0].text.strip()  # Get the code
                    if re.match(r'^[A-Z0-9]{12}$', code):
                        scraped_codes.add(code)
                        description = cols[2].text.strip()  # Get the description
                        date_added = datetime.now()  # Get the current datetime
                        active = 'background-color:rgb(153,255,153,0.5)' in cols[3].get('style', '')
                        existing = await self.db.execute("SELECT date_added FROM gi_codes WHERE code = ?", [code])
                        if not existing.rows:
                            await self.db.execute(
                                "INSERT INTO gi_codes (code, description, date_added, active) VALUES (?, ?, ?, 1)",
                                [code, description, str(date_added)]
                            )
                            channel = self.get_channel(self.announcement_channel_id)
                            embed = Embed(title=":new: Nuevo código de Genshin Impact: :new:", color=0x00ff00)
                            embed.add_field(name=f"{code}", value=f"[Canjear](https://genshin.hoyoverse.com/es/gift?code={code})", inline=False)
                            await channel.send(embed=embed)
                            user_ids = ['317425052083552257', '244466932718239744', '698588699042119711']
                            for user_id in user_ids:
                                user = await self.fetch_user(user_id)
                                try:
                                    await user.send(embed=embed)
                                except discord.Forbidden:
                                    print(f"No se pudo enviar un DM a {user.name}")
                            if not active:
                                await self.db.execute("UPDATE gi_codes SET active = 0 WHERE code = ?", [code])
                                print(f"El código {code} ya no está activo.")
                        else:
                            await self.db.execute("UPDATE gi_codes SET active = 1 WHERE code = ?", [code])
                            print(f"El código {code} ya existe en la base de datos.")
                            date_added = existing.rows[0][0]
                        codes.append((code, date_added, 1))

            # Borrar de la base de datos los códigos que ya no aparecen en la web
            result = await self.db.execute("SELECT code FROM gi_codes")
            db_codes = {row[0] for row in result.rows}
            removed_codes = db_codes - scraped_codes
            for code in removed_codes:
                await self.db.execute("DELETE FROM gi_codes WHERE code = ?", [code])
                print(f"El código {code} fue eliminado de la base de datos por no estar presente en la web.")

            return codes
        return []

    async def get_poke_codes(self, url):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                else:
                    print(f"Error: {response.status}")
                    return []

        soup = BeautifulSoup(text, 'html.parser')
        table = soup.find('table')

        scraped_codes = set()
        codes = []
        if table:
            for row in table.find('tbody').find_all('tr'):  # Buscar filas en tbody
                cols = row.find_all('td')
                if cols and len(cols) >= 4:
                    code_element = cols[0].find('strong')
                    if code_element:
                        code = code_element.text.strip()
                        scraped_codes.add(code)
                        rewards = cols[2].text.strip()  # Las recompensas están en la tercera columna
                        date_added = datetime.now()

                        existing = await self.db.execute("SELECT date_added FROM poke_codes WHERE code = ?", [code])
                        if not existing.rows:
                            await self.db.execute(
                                "INSERT INTO poke_codes (code, description, date_added, active) VALUES (?, ?, ?, 1)",
                                [code, rewards, str(date_added)]
                            )

                            channel = self.get_channel(self.announcement_channel_id)
                            embed = Embed(title=":new: Nuevo código de Pokémon TCG Pocket: :new:", color=0x00ff00)
                            embed.add_field(name=f"{code}", value=f"[Canjear](https://gift.pokemontcgpocket.com/es/)", inline=False)
                            await channel.send(embed=embed)

                            user_ids = ['317425052083552257', '244466932718239744', '698588699042119711', '348929639944814592', '273427129813827584']
                            for user_id in user_ids:
                                user = await self.fetch_user(user_id)
                                try:
                                    await user.send(embed=embed)
                                except discord.Forbidden:
                                    print(f"No se pudo enviar un DM a {user.name}")

                            codes.append((code, date_added, 1))
                        else:
                            await self.db.execute("UPDATE poke_codes SET active = 1 WHERE code = ?", [code])
                            print(f"El código {code} ya existe en la base de datos.")
                            date_added = existing.rows[0][0]
                            codes.append((code, date_added, 1))

            # Borrar de la base de datos los códigos que ya no aparecen en la web
            result = await self.db.execute("SELECT code FROM poke_codes")
            db_codes = {row[0] for row in result.rows}
            removed_codes = db_codes - scraped_codes
            for code in removed_codes:
                await self.db.execute("DELETE FROM poke_codes WHERE code = ?", [code])
                print(f"El código {code} fue eliminado de la base de datos por no estar presente en la web.")

            return codes
        return []


    @tasks.loop(minutes=10)
    async def check_websites(self):
        games = [
            {
                'name': 'hsr',
                'url': 'https://honkai-star-rail.fandom.com/wiki/Redemption_Code',
                'function': self.get_hsr_codes
            },
            {
                'name': 'dbd',
                'url': 'https://www.rockpapershotgun.com/dead-by-daylight-codes-list',
                'function': self.get_dbd_codes
            },
            {
                'name': 'gi',
                'url': 'https://genshin-impact.fandom.com/wiki/Promotional_Code',
                'function': self.get_gi_codes
            },
            {
                'name': 'poke',
                'url': 'https://ptcgpocket.gg/codes/',
                'function': self.get_poke_codes
            }

        ]
        for game in games:
            await game['function'](game['url'])

    @check_websites.before_loop
    async def before_check_websites(self):
        await self.wait_until_ready()  # Wait until the bot has connected to discord

bot = MyBot(command_prefix='!', intents=intents)

@bot.command(name='hsr')
async def hsr(ctx):
    allowed_roles = [916018910904590447]
    allowed_users = [317425052083552257, 244466932718239744]

    if isinstance(ctx.channel, discord.DMChannel):
        if ctx.author.id not in allowed_users:
            await ctx.send('Creías que podías usar esto en privado? JAJA encima te doxeo y te hackeo 🥱')
            return
    elif not any(role.id in allowed_roles for role in ctx.author.roles):
        await ctx.send('Sorry pero tú no puedes usar esto 🥱')
        return
    # Retrieve codes from the database
    result = await bot.db.execute("SELECT code, description, date_added, active FROM hsr_codes")
    codes = result.rows
    if codes:
        formatted_codes = []
        for code, description, date, active in codes:
            if active:
                date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f')
                formatted_date = date_obj.strftime('%d/%m/%Y')
                formatted_codes.append(f"{code} - {description} - {formatted_date} - [Canjear](https://hsr.hoyoverse.com/gift?code={code}{invisible_char})")
        messages = [":star: Códigos de Honkai Star Rail: :star:"]
        current_message = ""
        for code in formatted_codes:
            if len(current_message) + len(code) > 2000:
                messages.append(current_message)
                current_message = code
            else:
                current_message += "\n" + code
        messages.append(current_message)
        for message in messages:
            await ctx.send(message)
    else:
        await ctx.send("No se encontraron códigos.")

@bot.command(name='dbd')
async def dbd(ctx):
    allowed_roles = [916018910904590447]
    allowed_users = [317425052083552257, 244466932718239744]

    if isinstance(ctx.channel, discord.DMChannel):
        if ctx.author.id not in allowed_users:
            await ctx.send('Creías que podías usar esto en privado? JAJA encima te doxeo y te hackeo 🥱')
            return
    elif not any(role.id in allowed_roles for role in ctx.author.roles):
        await ctx.send('Sorry pero tú no puedes usar esto 🥱')
        return
    url = 'https://www.rockpapershotgun.com/dead-by-daylight-codes-list'
    codes = await ctx.bot.get_dbd_codes(url)
    if codes:
        formatted_codes = []
        for code, date, active in codes:
            date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f')
            status = "Activo" if active else "Inactivo"
            formatted_codes.append(f"{code} - {date_obj.strftime('%d/%m/%Y %H:%M')}")
        message = ":star: Códigos de Dead By Daylight: :star: \n" + '\n'.join(formatted_codes)
        await ctx.send(message)
    else:
        await ctx.send("No se encontraron códigos.")

@bot.command(name='gi')
async def gi(ctx):
    allowed_roles = [916018910904590447]
    allowed_users = [317425052083552257, 244466932718239744]

    if isinstance(ctx.channel, discord.DMChannel):
        if ctx.author.id not in allowed_users:
            await ctx.send('Creías que podías usar esto en privado? JAJA encima te doxeo y te hackeo 🥱')
            return
    elif not any(role.id in allowed_roles for role in ctx.author.roles):
        await ctx.send('Sorry pero tú no puedes usar esto 🥱')
        return

    result = await bot.db.execute("SELECT code, description, date_added, active FROM gi_codes")
    codes = result.rows
    if codes:
        embed = Embed(title=":star: Códigos de Genshin Impact: :star:", color=0x00ff00)
        active_codes = [
            (code, description, date, active)
            for code, description, date, active in codes if active
        ]
        # Limita a 25 campos, o puedes optar por combinar si hay más:
        for code, description, date, active in active_codes[:25]:
            date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f')
            embed.add_field(name=code, value=f"[Canjear](https://genshin.hoyoverse.com/es/gift?code={code})", inline=False)
        if len(active_codes) > 25:
            embed.set_footer(text=f"Y {len(active_codes) - 25} código(s) más...")
        await ctx.send(embed=embed)
    else:
        await ctx.send("No se encontraron códigos.")

@bot.command(name='poke')
async def poke(ctx):
    allowed_roles = [916018910904590447]
    allowed_users = [317425052083552257, 244466932718239744, 273427129813827584]

    if isinstance(ctx.channel, discord.DMChannel):
        if ctx.author.id not in allowed_users:
            await ctx.send('Creías que podías usar esto en privado? JAJA encima te doxeo y te hackeo 🥱')
            return
    elif not any(role.id in allowed_roles for role in ctx.author.roles):
        await ctx.send('Sorry pero tú no puedes usar esto 🥱')
        return

    result = await bot.db.execute("SELECT code, description, date_added, active FROM poke_codes")
    codes = result.rows
    if codes:
        embed = Embed(title=":star: Códigos de Pokémon TCG Pocket: :star:", color=0x00ff00)
        active_codes = [
            (code, description, date, active)
            for code, description, date, active in codes if active
        ]
        # Limita a 25 campos
        for code, description, date, active in active_codes[:25]:
            date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f')
            embed.add_field(name=code, value=f"[Canjear](https://gift.pokemontcgpocket.com/es/)", inline=False)
        if len(active_codes) > 25:
            embed.set_footer(text=f"Y {len(active_codes) - 25} código(s) más...")
        await ctx.send(embed=embed)
    else:
        await ctx.send("No se encontraron códigos.")

bot.remove_command('help')
@commands.has_any_role(916018910904590447)
@bot.command(name='help')
async def help(ctx):
    embed = discord.Embed(title="Ayuda", description="Algunos comandos útiles son:", color=0xeee657)

    embed.add_field(name="!hsr", value="Muestra códigos de Honkai Star Rail.", inline=False)
    embed.add_field(name="!dbd", value="Muestra códigos de Dead By Daylight.", inline=False)
    embed.add_field(name="!gi", value="Muestra códigos de Genshin Impact.", inline=False)
    embed.add_field(name="!poke", value="Muestra códigos de Pokémon TCG Pocket.", inline=False)
    embed.add_field(name="", value="El bot detecta cuando existe un código nuevo y lo muestra en el chat.", inline=False)

    await ctx.send(embed=embed)

class RankingView(View):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def generate_ranking_embed(self):
        result = await self.bot.db.execute(
            "SELECT user_id, user_name, SUM(duration) AS total FROM voice_sessions GROUP BY user_id ORDER BY total DESC"
        )
        results = result.rows

        embed = discord.Embed(title="Ranking de Tiempo en el Servidor", color=0x00ff00)
        if results:
            description = ""
            for idx, (user_id, user_name, total) in enumerate(results, start=1):
                formatted_time = format_duration(total)
                description += f"**{idx}. {user_name}** - {formatted_time}\n"
            embed.description = description
        else:
            embed.description = "No se han registrado datos de tiempo de voz."
        return embed

    @discord.ui.button(label="Actualizar Ranking", style=discord.ButtonStyle.primary)
    async def update_ranking(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.generate_ranking_embed()
        await interaction.response.edit_message(embed=embed)

@bot.command(name='ranking')
async def ranking(ctx):
    allowed_roles = [916018910904590447]
    allowed_users = [317425052083552257]

    if isinstance(ctx.channel, discord.DMChannel):
        if ctx.author.id not in allowed_users:
            await ctx.send('No puedes usar este comando en privado.')
            return
    elif not any(role.id in allowed_roles for role in ctx.author.roles):
        await ctx.send('No tienes permiso para usar este comando.')
        return

    view = RankingView(bot)
    embed = await view.generate_ranking_embed()
    await ctx.send(embed=embed, view=view)

@bot.event
async def on_voice_state_update(member, before, after):
    # Si el usuario entra a un canal de voz
    if before.channel is None and after.channel is not None:
        join_time = datetime.now()
        bot.active_voice_sessions[member.id] = join_time
        join_str = join_time.strftime("%d/%m/%Y %H:%M:%S")
        notifier = await bot.fetch_user(317425052083552257)
        try:
            await notifier.send(f"{member} se ha unido al canal de voz: {after.channel.name} a las {join_str}.")
        except discord.Forbidden:
            print(f"No se pudo enviar un DM a {notifier.name}")
    # Si el usuario cambia de canal de voz
    elif before.channel is not None and after.channel is not None and before.channel != after.channel:
        if member.id in bot.active_voice_sessions:
            join_time = bot.active_voice_sessions.pop(member.id)
            leave_time = datetime.now()
            duration = int((leave_time - join_time).total_seconds())
            # Guardar en la BD
            await bot.db.execute(
                "INSERT INTO voice_sessions (user_id, user_name, join_time, leave_time, duration) VALUES (?, ?, ?, ?, ?)",
                [str(member.id), member.name, join_time.strftime("%Y-%m-%d %H:%M:%S"), leave_time.strftime("%Y-%m-%d %H:%M:%S"), duration]
            )
            formatted_duration = format_duration(duration)
            join_str = join_time.strftime("%d/%m/%Y %H:%M:%S")
            leave_str = leave_time.strftime("%d/%m/%Y %H:%M:%S")
            notifier = await bot.fetch_user(317425052083552257)
            try:
                await notifier.send(
                    f"{member} se ha cambiado de canal:\n"
                    f"• Salió de {before.channel.name} a las {join_str} tras estar {formatted_duration}.\n"
                    f"• Se unió a {after.channel.name} a las {leave_str}."
                )
            except discord.Forbidden:
                print(f"No se pudo enviar un DM a {notifier.name}")
        # Registra la hora de entrada en el nuevo canal
        bot.active_voice_sessions[member.id] = datetime.now()
    # Si el usuario abandona el canal de voz
    elif before.channel is not None and after.channel is None:
        if member.id in bot.active_voice_sessions:
            join_time = bot.active_voice_sessions.pop(member.id)
            leave_time = datetime.now()
            duration = int((leave_time - join_time).total_seconds())
            await bot.db.execute(
                "INSERT INTO voice_sessions (user_id, user_name, join_time, leave_time, duration) VALUES (?, ?, ?, ?, ?)",
                [str(member.id), member.name, join_time.strftime("%Y-%m-%d %H:%M:%S"), leave_time.strftime("%Y-%m-%d %H:%M:%S"), duration]
            )
            formatted_duration = format_duration(duration)
            join_str = join_time.strftime("%d/%m/%Y %H:%M:%S")
            leave_str = leave_time.strftime("%d/%m/%Y %H:%M:%S")
            notifier = await bot.fetch_user(317425052083552257)
            try:
                await notifier.send(
                    f"{member} se ha desconectado del canal de voz: {before.channel.name}.\n"
                    f"Entró a las {join_str} y salió a las {leave_str} (tiempo en canal: {formatted_duration})."
                )
            except discord.Forbidden:
                print(f"No se pudo enviar un DM a {notifier.name}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingAnyRole):
        await ctx.send('Sorry pero tú no puedes usar esto 🥱')
    else:
        raise error

def format_duration(seconds):
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    result = []
    if hours > 0:
        result.append(f"{hours} hora{'s' if hours != 1 else ''}")
    if minutes > 0:
        result.append(f"{minutes} minuto{'s' if minutes != 1 else ''}")
    if not result:  # menos de un minuto
        result.append(f"{sec} segundo{'s' if sec != 1 else ''}")
    return ', '.join(result)

bot.run(os.environ['DISCORD_TOKEN'])
