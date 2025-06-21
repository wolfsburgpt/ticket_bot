import discord
from discord.ext import commands
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import gzip
import logging
import os
from dotenv import load_dotenv
import json
import pytz

# Setup logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler('ticket_bot.log'), logging.StreamHandler()]
)

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))

# Load configuration from config.json
with open('config.json') as f:
    config = json.load(f)
URL = config['url']
TARGET_DAY = config['target_day']
TARGET_MONTH = config['target_month']
CHECK_INTERVAL = config['check_interval_seconds']

# Setup Discord bot with command prefix '!'
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

class TicketBot:
    def __init__(self, client, channel_id, url, target_day, target_month, check_interval):
        self.client = client
        self.channel_id = channel_id
        self.url = url
        self.target_day = target_day.lower()
        self.target_month = target_month.lower()
        self.check_interval = check_interval
        self.already_announced = False
        self.check_count = 0
        self.previous_event_summaries = []
        self.start_time = datetime.now()
        self.timezone = pytz.timezone('Europe/Lisbon')  # Portugal timezone (WEST)

    def is_within_operating_hours(self):
        """Check if current time is between 8 AM and midnight WEST."""
        now = datetime.now(self.timezone)
        current_hour = now.hour
        return 8 <= current_hour < 24  # 8 AM to 11:59 PM

    async def check_ticket(self):
        await self.client.wait_until_ready()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
            'Accept': 'text/html,*/*;q=0.8',
            'Accept-Language': 'pt-PT,pt;q=0.9,en-US;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }

        while not self.client.is_closed():
            if self.is_within_operating_hours():
                self.check_count += 1
                logging.info(f"Check attempt #{self.check_count}")
                try:
                    # Make HTTP request
                    response = requests.get(self.url, headers=headers, timeout=30)
                    response.raise_for_status()

                    # Handle response content
                    content = gzip.decompress(response.content).decode('utf-8') if response.content.startswith(b'\x1f\x8b') else response.text
                    soup = BeautifulSoup(content, 'html.parser')

                    # Find date containers
                    date_containers = soup.find_all("div", class_=lambda x: x and 'date' in x)
                    events = []
                    event_summaries = []
                    found = False

                    for container in date_containers:
                        day_tag = container.find("p", class_=lambda x: x and 'day' in x)
                        month_tag = container.find("p", class_=lambda x: x and 'month' in x)
                        if day_tag and month_tag:
                            link_tag = container.find_parent("a", href=True)
                            day = day_tag.get_text(strip=True).lower()
                            month = month_tag.get_text(strip=True).lower()
                            url = f"https://ticketline.sapo.pt{link_tag['href']}" if link_tag else "No link"
                            event_summaries.append(f"📅 {day.upper()} {month.upper()} — {url}")
                            if day == self.target_day and month == self.target_month:
                                found = True
                                if not self.already_announced:
                                    channel = self.client.get_channel(self.channel_id)
                                    if channel:
                                        message = f"🚨 Tickets for **{self.target_month.upper()} {self.target_day}** are now available! @here\n{url}"
                                        await channel.send(message[:2000])
                                        logging.info("Alert sent to Discord")
                                        self.already_announced = True

                    if not event_summaries:
                        event_summaries.append("*(No ticket sessions found)*")

                    # Send summary if changed
                    if event_summaries != self.previous_event_summaries:
                        channel = self.client.get_channel(self.channel_id)
                        if channel:
                            message = "**Current Ticket Dates:**\n" + "\n".join(event_summaries)
                            await channel.send(message[:2000])
                            logging.info("Updated ticket dates sent to Discord")
                        self.previous_event_summaries = event_summaries.copy()

                    if not found:
                        logging.info(f"{self.target_month.upper()} {self.target_day} tickets not found yet")
                    else:
                        logging.info(f"{self.target_month.upper()} {self.target_day} tickets are available!")

                except Exception as e:
                    logging.error(f"Error during check: {e}")
            else:
                logging.info("Outside operating hours (8 AM - midnight WEST). Sleeping...")
            
            await asyncio.sleep(self.check_interval)

    def get_stats(self):
        uptime = datetime.now() - self.start_time
        return f"Bot Status:\nUptime: {uptime}\nChecks: {self.check_count}\nTarget Announced: {self.already_announced}"

# Discord commands
@bot.command()
async def status(ctx):
    await ctx.send(bot.ticket_bot.get_stats())

@bot.command()
async def reset(ctx):
    bot.ticket_bot.already_announced = False
    await ctx.send("Target announcement reset.")

# Bot event
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")
    bot.loop.create_task(bot.ticket_bot.check_ticket())

# Run bot
bot.ticket_bot = TicketBot(bot, CHANNEL_ID, URL, TARGET_DAY, TARGET_MONTH, CHECK_INTERVAL)
bot.run(TOKEN)