import discord
from discord.ext import commands, tasks
import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup
import libsql_client
import asyncio
import imaplib
import email
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
import re
import os
import logging
from dotenv import load_dotenv
from discord import Embed
from discord.ui import View

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('bot')

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.voice_states = True
intents.members = True
intents.message_content = True
invisible_char = "\u200b"

MODERN_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,es;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'max-age=0',
}

#698588699042119711 angela
#317425052083552257 sergio
#244466932718239744 sydney
#348929639944814592 leyre
#273427129813827584 nat

# A quién se le reenvían los códigos de inicio de sesión de Spotify
LEYRE_DISCORD_ID = 348929639944814592
SERGIO_DISCORD_ID = 317425052083552257
SPOTIFY_CODE_RECIPIENTS = [LEYRE_DISCORD_ID, SERGIO_DISCORD_ID]
GMAIL_IMAP_HOST = 'imap.gmail.com'

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
        log.info('Base de datos inicializada correctamente.')
        # Start health check HTTP server for Koyeb
        app = web.Application()
        app.router.add_get('/', self.health_check)
        app.router.add_get('/health', self.health_check)
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.environ.get('PORT', 8000))
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        log.info(f'Servidor health check iniciado en puerto {port}.')
        # Reenvío de códigos de Spotify (solo si hay credenciales de Gmail)
        if os.environ.get('GMAIL_ADDRESS') and os.environ.get('GMAIL_APP_PASSWORD'):
            self.check_spotify_emails.start()
            log.info('Reenvío de códigos de Spotify activado.')
        else:
            log.info('GMAIL_ADDRESS/GMAIL_APP_PASSWORD no configurados: reenvío de Spotify desactivado.')

    async def health_check(self, request):
        return web.Response(text='OK', status=200)

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
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS active_sessions (
                user_id TEXT PRIMARY KEY,
                user_name TEXT,
                join_time TEXT
            )
        ''')
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS processed_emails (
                message_id TEXT PRIMARY KEY,
                processed_at TEXT
            )
        ''')

    async def on_ready(self):
        log.info(f'Bot conectado como {self.user} (ID: {self.user.id})')
        log.info(f'Conectado a {len(self.guilds)} servidor(es).')
        await self.change_presence(activity=discord.Game(name="🤑buscar codiguitos🤑"))
        await self.restore_voice_sessions()
        self.check_websites.start()
        log.info('Task loop de check_websites iniciado (cada 10 min).')

    async def restore_voice_sessions(self):
        """Restaura sesiones activas tras un reinicio del bot."""
        log.info('Restaurando sesiones de voz...')
        # Recopilar usuarios que están AHORA en canales de voz
        current_voice_users = {}
        for guild in self.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if not member.bot:
                        current_voice_users[str(member.id)] = member

        # Leer sesiones activas guardadas en la BD
        result = await self.db.execute("SELECT user_id, user_name, join_time FROM active_sessions")
        saved_sessions = {row[0]: (row[1], row[2]) for row in result.rows}

        # Cerrar sesiones huérfanas (usuarios que ya no están en voz)
        for user_id, (user_name, join_time_str) in saved_sessions.items():
            if user_id not in current_voice_users:
                # El usuario ya no está en un canal: cerrar sesión con la hora actual
                join_time = datetime.strptime(join_time_str, "%Y-%m-%d %H:%M:%S")
                leave_time = datetime.now()
                duration = int((leave_time - join_time).total_seconds())
                await self.db.execute(
                    "INSERT INTO voice_sessions (user_id, user_name, join_time, leave_time, duration) VALUES (?, ?, ?, ?, ?)",
                    [user_id, user_name, join_time_str, leave_time.strftime("%Y-%m-%d %H:%M:%S"), duration]
                )
                await self.db.execute("DELETE FROM active_sessions WHERE user_id = ?", [user_id])
                log.info(f'Sesión huérfana cerrada para {user_name} (duración: {duration}s)')
            else:
                # El usuario sigue en voz: restaurar en memoria
                join_time = datetime.strptime(join_time_str, "%Y-%m-%d %H:%M:%S")
                self.active_voice_sessions[int(user_id)] = join_time
                log.info(f'Sesión restaurada para {user_name} (desde {join_time_str})')

        # Registrar usuarios en voz que NO tenían sesión guardada
        for user_id_str, member in current_voice_users.items():
            if user_id_str not in saved_sessions and int(user_id_str) not in self.active_voice_sessions:
                join_time = datetime.now()
                self.active_voice_sessions[member.id] = join_time
                await self.db.execute(
                    "INSERT OR REPLACE INTO active_sessions (user_id, user_name, join_time) VALUES (?, ?, ?)",
                    [user_id_str, member.name, join_time.strftime("%Y-%m-%d %H:%M:%S")]
                )
                log.info(f'Nueva sesión creada para {member.name} (detectado en canal al iniciar)')


    async def get_hsr_codes(self, url):
        log.info('Scrapeando códigos de HSR...')
        await self.db.execute("UPDATE hsr_codes SET active = 0")

        api_url = 'https://honkai-star-rail.fandom.com/api.php'
        params = {
            'action': 'parse',
            'page': 'Redemption_Code',
            'format': 'json',
            'prop': 'text',
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params, headers=MODERN_HEADERS) as response:
                if response.status == 200:
                    data = await response.json()
                    text = data.get('parse', {}).get('text', {}).get('*', '')
                else:
                    log.error(f'Error HTTP {response.status} al obtener códigos de HSR')
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

                    log.debug(f'HSR código encontrado: {code}')
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
                            log.info(f'¡NUEVO código HSR detectado y anunciado!: {code}')

                            user_ids = ['317425052083552257']
                            for user_id in user_ids:
                                user = await self.fetch_user(user_id)
                                try:
                                    await user.send(embed=embed)
                                except discord.Forbidden:
                                    log.warning(f'No se pudo enviar DM a {user.name} (HSR)')
                            codes.append((code, datetime.now(), 1))
                        else:
                            await self.db.execute("UPDATE hsr_codes SET active = 1 WHERE code = ?", [code])
                    elif 'bg-old' in cells[3].get('class', []):
                        # This is an old code, check if it exists in the database and mark it as inactive
                        await self.db.execute("UPDATE hsr_codes SET active = 0 WHERE code = ?", [code])

            return codes
        return []

    async def get_dbd_codes(self, url):
        log.info('Scrapeando códigos de DBD...')
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=MODERN_HEADERS) as response:
                if response.status == 200:
                    text = await response.text()
                else:
                    log.error(f'Error HTTP {response.status} al obtener códigos de DBD')
                    return []

        soup = BeautifulSoup(text, 'html.parser')
        uls = soup.find_all('ul')

        if uls:
            ul = uls[5]
            log.debug('Lista UL de DBD encontrada')
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
                        log.info(f'¡NUEVO código DBD detectado y anunciado!: {code}')
                        user_ids = ['317425052083552257']
                        for user_id in user_ids:
                            user = await self.fetch_user(user_id)
                            try:
                                await user.send(embed=embed)
                            except discord.Forbidden:
                                log.warning(f'No se pudo enviar DM a {user.name} (DBD)')
                    else:
                        await self.db.execute("UPDATE dbd_codes SET active = 1 WHERE code = ?", [code])
                        log.debug(f'DBD código {code} ya existe en la BD.')
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
        log.info('Scrapeando códigos de Genshin Impact...')
        api_url = 'https://genshin-impact.fandom.com/api.php'
        params = {
            'action': 'parse',
            'page': 'Promotional_Code',
            'format': 'json',
            'prop': 'text',
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params, headers=MODERN_HEADERS) as response:
                if response.status == 200:
                    data = await response.json()
                    text = data.get('parse', {}).get('text', {}).get('*', '')
                else:
                    log.error(f'Error HTTP {response.status} al obtener códigos de GI')
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
                            log.info(f'¡NUEVO código GI detectado y anunciado!: {code}')
                            user_ids = ['317425052083552257', '244466932718239744', '698588699042119711']
                            for user_id in user_ids:
                                user = await self.fetch_user(user_id)
                                try:
                                    await user.send(embed=embed)
                                except discord.Forbidden:
                                    log.warning(f'No se pudo enviar DM a {user.name} (GI)')
                            if not active:
                                await self.db.execute("UPDATE gi_codes SET active = 0 WHERE code = ?", [code])
                                log.info(f'GI código {code} marcado como inactivo.')
                        else:
                            await self.db.execute("UPDATE gi_codes SET active = 1 WHERE code = ?", [code])
                            log.debug(f'GI código {code} ya existe en la BD.')
                            date_added = existing.rows[0][0]
                        codes.append((code, date_added, 1))

            # Borrar de la base de datos los códigos que ya no aparecen en la web
            result = await self.db.execute("SELECT code FROM gi_codes")
            db_codes = {row[0] for row in result.rows}
            removed_codes = db_codes - scraped_codes
            for code in removed_codes:
                await self.db.execute("DELETE FROM gi_codes WHERE code = ?", [code])
                log.info(f'GI código {code} eliminado de la BD (ya no está en la web).')

            return codes
        return []

    async def get_poke_codes(self, url):
        log.info('Scrapeando códigos de Pokémon TCG Pocket...')
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=MODERN_HEADERS) as response:
                if response.status == 200:
                    text = await response.text()
                else:
                    log.error(f'Error HTTP {response.status} al obtener códigos de Pokémon')
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
                            log.info(f'¡NUEVO código Pokémon detectado y anunciado!: {code}')

                            user_ids = ['317425052083552257', '244466932718239744', '698588699042119711', '348929639944814592', '273427129813827584']
                            for user_id in user_ids:
                                user = await self.fetch_user(user_id)
                                try:
                                    await user.send(embed=embed)
                                except discord.Forbidden:
                                    log.warning(f'No se pudo enviar DM a {user.name} (Pokémon)')

                            codes.append((code, date_added, 1))
                        else:
                            await self.db.execute("UPDATE poke_codes SET active = 1 WHERE code = ?", [code])
                            log.debug(f'Pokémon código {code} ya existe en la BD.')
                            date_added = existing.rows[0][0]
                            codes.append((code, date_added, 1))

            # Borrar de la base de datos los códigos que ya no aparecen en la web
            result = await self.db.execute("SELECT code FROM poke_codes")
            db_codes = {row[0] for row in result.rows}
            removed_codes = db_codes - scraped_codes
            for code in removed_codes:
                await self.db.execute("DELETE FROM poke_codes WHERE code = ?", [code])
                log.info(f'Pokémon código {code} eliminado de la BD (ya no está en la web).')

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
        log.info('--- Inicio de ciclo de scraping de códigos ---')
        for game in games:
            try:
                await game['function'](game['url'])
            except Exception as e:
                log.error(f'Error scrapeando {game["name"]}: {e}')
        log.info('--- Fin de ciclo de scraping ---')

    @check_websites.before_loop
    async def before_check_websites(self):
        await self.wait_until_ready()  # Wait until the bot has connected to discord

    # --- Reenvío de códigos de inicio de sesión de Spotify al DM de Leyre ---
    # Solo se reenvían los correos recibidos en estos minutos: los códigos de
    # Spotify caducan enseguida y así no se reenvían los antiguos al arrancar
    SPOTIFY_RECENT_MINUTES = 15

    def fetch_recent_spotify_emails(self):
        """Lee el buzón por IMAP (bloqueante, se ejecuta en un hilo aparte).
        Devuelve los correos recientes de Spotify ya parseados.
        No marca los correos como leídos ni toca la base de datos."""
        address = os.environ.get('GMAIL_ADDRESS')
        password = os.environ.get('GMAIL_APP_PASSWORD')
        if not address or not password:
            return []

        since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%d-%b-%Y')
        emails = []
        with imaplib.IMAP4_SSL(GMAIL_IMAP_HOST) as imap:
            imap.login(address, password)
            imap.select('INBOX', readonly=True)  # readonly: no marca los correos como leídos
            status, data = imap.search(None, f'(FROM "spotify" SINCE {since})')
            if status != 'OK':
                return []
            for num in data[0].split():
                status, msg_data = imap.fetch(num, '(RFC822)')
                if status != 'OK' or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                message_id = msg.get('Message-ID') or f'num-{num.decode()}'

                date = msg.get('Date')
                try:
                    received = parsedate_to_datetime(date)
                    if received.tzinfo is None:
                        received = received.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    received = None
                if received is not None:
                    age = (datetime.now(timezone.utc) - received).total_seconds()
                    if age > self.SPOTIFY_RECENT_MINUTES * 60:
                        continue  # correo viejo: se ignora

                subject = self.decode_mail_header(msg.get('Subject'))
                body = self.extract_mail_body(msg)
                emails.append({
                    'message_id': message_id,
                    'code': self.extract_login_code(subject, body),
                    'link': self.extract_login_link(body),
                })
        return emails

    @staticmethod
    def decode_mail_header(value):
        if not value:
            return ''
        out = ''
        for text, enc in decode_header(value):
            if isinstance(text, bytes):
                out += text.decode(enc or 'utf-8', 'replace')
            else:
                out += text
        return out

    @staticmethod
    def extract_mail_body(msg):
        plain = html = ''
        if msg.is_multipart():
            for part in msg.walk():
                if 'attachment' in (part.get('Content-Disposition') or '').lower():
                    continue
                ctype = part.get_content_type()
                if ctype not in ('text/plain', 'text/html'):
                    continue
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                text = payload.decode(part.get_content_charset() or 'utf-8', 'replace')
                if ctype == 'text/plain' and not plain:
                    plain = text
                elif ctype == 'text/html' and not html:
                    html = text
        else:
            payload = msg.get_payload(decode=True)
            if payload is not None:
                text = payload.decode(msg.get_content_charset() or 'utf-8', 'replace')
                if msg.get_content_type() == 'text/html':
                    html = text
                else:
                    plain = text
        # Si solo hay versión HTML, se saca el texto plano de ella
        if html and not plain:
            plain = BeautifulSoup(html, 'html.parser').get_text(' ', strip=True)
        return plain

    @staticmethod
    def extract_login_code(subject, body):
        # Spotify manda un código numérico (normalmente de 6 dígitos)
        match = re.search(r'\b(\d{6})\b', f"{subject}\n{body}")
        return match.group(1) if match else None

    @staticmethod
    def extract_login_link(body):
        # Algunos correos traen un enlace de acceso en vez de un código
        for url in re.findall(r'https?://[^\s"\'<>]+', body):
            if 'spotify' in url.lower():
                return url
        return None

    @tasks.loop(seconds=20)
    async def check_spotify_emails(self):
        try:
            # imaplib es bloqueante: se lee en un hilo aparte para no congelar el bot
            loop = asyncio.get_running_loop()
            emails = await loop.run_in_executor(None, self.fetch_recent_spotify_emails)
        except Exception as e:
            log.error(f'Error leyendo el correo de Spotify: {e}')
            return

        for mail in emails:
            # Evita reenviar el mismo correo dos veces (también tras un reinicio)
            existing = await self.db.execute(
                "SELECT message_id FROM processed_emails WHERE message_id = ?", [mail['message_id']]
            )
            if existing.rows:
                continue
            await self.db.execute(
                "INSERT INTO processed_emails (message_id, processed_at) VALUES (?, ?)",
                [mail['message_id'], str(datetime.now())]
            )

            if mail['code']:
                content = f"🎵 Código de inicio de sesión de Spotify: `{mail['code']}`"
            elif mail['link']:
                content = f"🎵 Enlace de inicio de sesión de Spotify:\n{mail['link']}"
            else:
                content = "🎵 Ha llegado un correo de Spotify, pero no se pudo extraer el código."

            for recipient_id in SPOTIFY_CODE_RECIPIENTS:
                try:
                    user = await self.fetch_user(recipient_id)
                    await user.send(content)
                    log.info(f'Código de Spotify reenviado a {recipient_id}.')
                except discord.HTTPException:
                    log.warning(f'No se pudo enviar el código de Spotify a {recipient_id}')

    @check_spotify_emails.before_loop
    async def before_check_spotify_emails(self):
        await self.wait_until_ready()

bot = MyBot(command_prefix='!', intents=intents)

@bot.command(name='hsr')
async def hsr(ctx):
    log.info(f'Comando !hsr usado por {ctx.author} (ID: {ctx.author.id})')
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
    log.info(f'Comando !dbd usado por {ctx.author} (ID: {ctx.author.id})')
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
    log.info(f'Comando !gi usado por {ctx.author} (ID: {ctx.author.id})')
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
    log.info(f'Comando !poke usado por {ctx.author} (ID: {ctx.author.id})')
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
    log.info(f'Comando !help usado por {ctx.author} (ID: {ctx.author.id})')
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
    log.info(f'Comando !ranking usado por {ctx.author} (ID: {ctx.author.id})')
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
        log.info(f'🔊 {member.name} se unió al canal de voz: {after.channel.name}')
        join_time = datetime.now()
        bot.active_voice_sessions[member.id] = join_time
        await bot.db.execute(
            "INSERT OR REPLACE INTO active_sessions (user_id, user_name, join_time) VALUES (?, ?, ?)",
            [str(member.id), member.name, join_time.strftime("%Y-%m-%d %H:%M:%S")]
        )
        join_str = join_time.strftime("%d/%m/%Y %H:%M:%S")
        notifier = await bot.fetch_user(317425052083552257)
        try:
            await notifier.send(f"{member} se ha unido al canal de voz: {after.channel.name} a las {join_str}.")
        except discord.Forbidden:
            log.warning(f'No se pudo enviar DM a {notifier.name} (voz join)')
    # Si el usuario cambia de canal de voz
    elif before.channel is not None and after.channel is not None and before.channel != after.channel:
        log.info(f'🔀 {member.name} cambió de canal: {before.channel.name} → {after.channel.name}')
        if member.id in bot.active_voice_sessions:
            join_time = bot.active_voice_sessions.pop(member.id)
            leave_time = datetime.now()
            duration = int((leave_time - join_time).total_seconds())
            # Guardar en la BD y limpiar sesión activa
            await bot.db.execute(
                "INSERT INTO voice_sessions (user_id, user_name, join_time, leave_time, duration) VALUES (?, ?, ?, ?, ?)",
                [str(member.id), member.name, join_time.strftime("%Y-%m-%d %H:%M:%S"), leave_time.strftime("%Y-%m-%d %H:%M:%S"), duration]
            )
            await bot.db.execute("DELETE FROM active_sessions WHERE user_id = ?", [str(member.id)])
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
                log.warning(f'No se pudo enviar DM a {notifier.name} (voz switch)')
        # Registra la hora de entrada en el nuevo canal
        new_join_time = datetime.now()
        bot.active_voice_sessions[member.id] = new_join_time
        await bot.db.execute(
            "INSERT OR REPLACE INTO active_sessions (user_id, user_name, join_time) VALUES (?, ?, ?)",
            [str(member.id), member.name, new_join_time.strftime("%Y-%m-%d %H:%M:%S")]
        )
    # Si el usuario abandona el canal de voz
    elif before.channel is not None and after.channel is None:
        log.info(f'🔇 {member.name} salió del canal de voz: {before.channel.name}')
        if member.id in bot.active_voice_sessions:
            join_time = bot.active_voice_sessions.pop(member.id)
            leave_time = datetime.now()
            duration = int((leave_time - join_time).total_seconds())
            await bot.db.execute(
                "INSERT INTO voice_sessions (user_id, user_name, join_time, leave_time, duration) VALUES (?, ?, ?, ?, ?)",
                [str(member.id), member.name, join_time.strftime("%Y-%m-%d %H:%M:%S"), leave_time.strftime("%Y-%m-%d %H:%M:%S"), duration]
            )
            await bot.db.execute("DELETE FROM active_sessions WHERE user_id = ?", [str(member.id)])
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
                log.warning(f'No se pudo enviar DM a {notifier.name} (voz leave)')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingAnyRole):
        log.warning(f'{ctx.author} intentó usar !{ctx.command} sin permisos.')
        await ctx.send('Sorry pero tú no puedes usar esto 🥱')
    else:
        log.error(f'Error en comando !{ctx.command} por {ctx.author}: {error}')
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

log.info('Iniciando bot...')
bot.run(os.environ['DISCORD_TOKEN'])
