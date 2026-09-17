
import os
import re
import json
import math
import time
import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ============================================================
# ROBUX PLUS BOT
# English Discord ticket / customer bot
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

OWNER_ID = 1453135839688265974
STAFF_ROLE_ID = 1549541686030635058
TICKET_CATEGORY_ID = 1549782404863102986
VOUCH_CHANNEL_ID = 1549539937479688222

CUSTOMER_ROLE_ID = 1549541062194896926
ROLE_10K_ID = 1550169459950493916
ROLE_20K_ID = 1550168812182306886
ROLE_30K_ID = 1550168265169440949

# Public receiving addresses supplied by the server owner.
PAYMENT_ADDRESSES = {
    "Litecoin": "LaZBKdeTWC6kaGWDkM85rLhWamPr1qYTBA",
    "Ethereum": "0xe82DBE270F85E01a26C37805025167a98707bDCE",
    "Tether USD (BSC)": "0xe82DBE270F85E01a26C37805025167a98707bDCE",
    "Solana": "H4rZL84Pj458YbB4JSiF8WuFea4EwZ5DatiXPUYLMqhY",
    "Bitcoin": "bc1ql9avzr7ghrrh4w2a229yhde4e66wd4dun9rqnu",
}

COINGECKO_IDS = {
    "Litecoin": "litecoin",
    "Ethereum": "ethereum",
    "Tether USD (BSC)": "tether",
    "Solana": "solana",
    "Bitcoin": "bitcoin",
}

# For automatic explorer verification:
# ETHERSCAN_API_KEY and BSCSCAN_API_KEY are optional but recommended.
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")

DB_PATH = os.getenv("DB_PATH", "robux_plus.db")
LOGO_FILE = "profile_logo.png"

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.messages = True
INTENTS.message_content = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row


# ----------------------------- Database -----------------------------

def init_db():
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance REAL NOT NULL DEFAULT 0,
        total_spent REAL NOT NULL DEFAULT 0,
        total_robux INTEGER NOT NULL DEFAULT 0,
        orders INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tickets (
        channel_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        robux INTEGER NOT NULL,
        price REAL NOT NULL,
        payment_method TEXT NOT NULL,
        payment_address TEXT NOT NULL,
        required_coin_amount REAL,
        tx_hash TEXT,
        payment_status TEXT NOT NULL DEFAULT 'awaiting_hash',
        roblox_username TEXT,
        order_robux INTEGER,
        vouch_expected TEXT,
        vouch_sent INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS giveaways (
        message_id INTEGER PRIMARY KEY,
        channel_id INTEGER NOT NULL,
        prize TEXT NOT NULL,
        winners INTEGER NOT NULL,
        end_time TEXT NOT NULL,
        ended INTEGER NOT NULL DEFAULT 0
    );
    """)
    db.commit()


def ensure_user(user_id: int):
    db.execute(
        "INSERT OR IGNORE INTO users(user_id, created_at) VALUES(?, ?)",
        (user_id, datetime.now(timezone.utc).isoformat())
    )
    db.commit()


def get_user(user_id: int):
    ensure_user(user_id)
    return db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def get_ticket(channel_id: int):
    return db.execute("SELECT * FROM tickets WHERE channel_id=?", (channel_id,)).fetchone()


def set_ticket(channel_id: int, **values):
    if not values:
        return
    fields = ", ".join(f"{k}=?" for k in values)
    params = list(values.values()) + [channel_id]
    db.execute(f"UPDATE tickets SET {fields} WHERE channel_id=?", params)
    db.commit()


def add_purchase(user_id: int, price: float, robux: int):
    ensure_user(user_id)
    db.execute("""
        UPDATE users
        SET total_spent = total_spent + ?,
            total_robux = total_robux + ?,
            orders = orders + 1
        WHERE user_id=?
    """, (price, robux, user_id))
    db.commit()


# ----------------------------- Helpers -----------------------------

def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID


def is_staff(interaction: discord.Interaction) -> bool:
    if interaction.user.id == OWNER_ID:
        return True
    role = interaction.guild.get_role(STAFF_ROLE_ID) if interaction.guild else None
    return role is not None and role in getattr(interaction.user, "roles", [])


def money(value: float) -> str:
    return f"${value:,.2f}"


def validate_robux(amount: int) -> bool:
    return amount >= 5000 and amount % 5000 == 0


def robux_price(robux: int) -> float:
    if not validate_robux(robux):
        raise ValueError("Robux amount must be a 5,000 increment.")
    rate = 9.00 if robux < 15000 else 8.80
    return (robux / 1000) * rate


def rank_for_robux(total_robux: int):
    if total_robux >= 30000:
        return "30K+", ROLE_30K_ID
    if total_robux >= 20000:
        return "20K+", ROLE_20K_ID
    if total_robux >= 10000:
        return "10K+", ROLE_10K_ID
    return None, None


async def update_rank_role(member: discord.Member, total_robux: int):
    guild = member.guild
    rank_name, rank_id = rank_for_robux(total_robux)
    rank_ids = [ROLE_10K_ID, ROLE_20K_ID, ROLE_30K_ID]

    for rid in rank_ids:
        role = guild.get_role(rid)
        if role and role in member.roles and rid != rank_id:
            try:
                await member.remove_roles(role, reason="Automatic Robux rank update")
            except discord.Forbidden:
                pass

    if rank_id:
        role = guild.get_role(rank_id)
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason="Automatic Robux rank update")
            except discord.Forbidden:
                pass


async def add_customer_role(member: discord.Member):
    role = member.guild.get_role(CUSTOMER_ROLE_ID)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason="Successful customer vouch")
        except discord.Forbidden:
            pass


def parse_duration(value: str):
    match = re.fullmatch(r"\s*(\d+)\s*([smhdw])\s*", value.lower())
    if not match:
        return None
    n = int(match.group(1))
    unit = match.group(2)
    seconds = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
    }[unit]
    return timedelta(seconds=n * seconds)


async def get_coin_price_usd(method: str):
    coin_id = COINGECKO_IDS[method]
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": coin_id, "vs_currencies": "usd"}
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return float(data[coin_id]["usd"])


async def usd_to_coin(usd: float, method: str):
    if method == "Tether USD (BSC)":
        return usd
    price = await get_coin_price_usd(method)
    if not price or price <= 0:
        return None
    return usd / price


def format_coin(amount: float, method: str):
    if method == "Tether USD (BSC)":
        return f"{amount:.2f} USDT"
    if method == "Bitcoin":
        return f"{amount:.8f} BTC"
    if method == "Litecoin":
        return f"{amount:.8f} LTC"
    if method == "Ethereum":
        return f"{amount:.8f} ETH"
    if method == "Solana":
        return f"{amount:.6f} SOL"
    return f"{amount:.8f}"


# ----------------------------- Payment verification -----------------------------

async def verify_utxo_tx(method: str, tx_hash: str, expected_usd: float):
    """
    Uses BlockCypher public APIs for BTC/LTC.
    It verifies that the transaction contains an output to the configured address.
    Exact USD value is compared using a fresh coin price.
    """
    coin = {"Bitcoin": "btc/main", "Litecoin": "ltc/main"}[method]
    url = f"https://api.blockcypher.com/v1/{coin}/txs/{tx_hash}"
    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return False, "Transaction not found or explorer unavailable."
            data = await resp.json()

    address = PAYMENT_ADDRESSES[method]
    total_received = 0
    for output in data.get("outputs", []):
        if address in output.get("addresses", []):
            total_received += int(output.get("value", 0))

    if total_received <= 0:
        return False, "The transaction does not send funds to the configured address."

    coin_amount = total_received / 100_000_000
    price = await get_coin_price_usd(method)
    if not price:
        return False, "Could not obtain the current coin price."

    received_usd = coin_amount * price
    # Small tolerance for price movement / fees.
    if received_usd + 0.01 < expected_usd * 0.995:
        return False, f"Received value is below the required amount ({money(received_usd)})."

    confirmations = int(data.get("confirmations", 0))
    if confirmations < 1:
        return False, "Transaction exists but is not confirmed yet."

    return True, f"Payment confirmed: approximately {money(received_usd)} received."


async def verify_eth_tx(tx_hash: str, expected_usd: float):
    if not ETHERSCAN_API_KEY:
        return False, "ETHERSCAN_API_KEY is not configured on the host."

    base = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": "1",
        "module": "account",
        "action": "txlist",
        "address": PAYMENT_ADDRESSES["Ethereum"],
        "startblock": "0",
        "endblock": "99999999",
        "page": "1",
        "offset": "100",
        "sort": "desc",
        "apikey": ETHERSCAN_API_KEY,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(base, params=params) as resp:
            if resp.status != 200:
                return False, "Ethereum explorer unavailable."
            data = await resp.json()

    txs = data.get("result", [])
    target = PAYMENT_ADDRESSES["Ethereum"].lower()
    tx = next((x for x in txs if x.get("hash", "").lower() == tx_hash.lower()), None)
    if not tx:
        return False, "Transaction not found for the configured Ethereum address."

    if tx.get("to", "").lower() != target:
        return False, "Transaction recipient does not match the configured address."

    value_eth = int(tx.get("value", "0")) / 10**18
    price = await get_coin_price_usd("Ethereum")
    if not price:
        return False, "Could not obtain the current ETH price."

    received_usd = value_eth * price
    if received_usd + 0.01 < expected_usd * 0.995:
        return False, f"Received value is below the required amount ({money(received_usd)})."

    if int(tx.get("isError", "0")) != 0:
        return False, "The Ethereum transaction failed."

    return True, f"Payment confirmed: approximately {money(received_usd)} received."


async def verify_bsc_usdt_tx(tx_hash: str, expected_usd: float):
    if not BSCSCAN_API_KEY:
        return False, "BSCSCAN_API_KEY is not configured on the host."

    base = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": "56",
        "module": "account",
        "action": "tokentx",
        "contractaddress": "0x55d398326f99059fF775485246999027B3197955",
        "address": PAYMENT_ADDRESSES["Tether USD (BSC)"],
        "page": "1",
        "offset": "100",
        "sort": "desc",
        "apikey": BSCSCAN_API_KEY,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(base, params=params) as resp:
            if resp.status != 200:
                return False, "BSC explorer unavailable."
            data = await resp.json()

    txs = data.get("result", [])
    tx = next((x for x in txs if x.get("hash", "").lower() == tx_hash.lower()), None)
    if not tx:
        return False, "USDT transaction not found."

    target = PAYMENT_ADDRESSES["Tether USD (BSC)"].lower()
    if tx.get("to", "").lower() != target:
        return False, "Transaction recipient does not match the configured USDT address."

    decimals = int(tx.get("tokenDecimal", "18"))
    amount = int(tx.get("value", "0")) / (10 ** decimals)

    if amount + 0.01 < expected_usd * 0.995:
        return False, f"Received amount is below the required ${expected_usd:.2f} USDT."

    return True, f"Payment confirmed: {amount:.2f} USDT received."


async def verify_sol_tx(tx_hash: str, expected_usd: float):
    rpc = "https://api.mainnet-beta.solana.com"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            tx_hash,
            {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}
        ],
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(rpc, json=payload) as resp:
            if resp.status != 200:
                return False, "Solana RPC unavailable."
            data = await resp.json()

    result = data.get("result")
    if not result:
        return False, "Solana transaction not found or not confirmed."

    if result.get("meta", {}).get("err") is not None:
        return False, "Solana transaction failed."

    target = PAYMENT_ADDRESSES["Solana"]
    received_lamports = 0

    instructions = result.get("transaction", {}).get("message", {}).get("instructions", [])
    for ins in instructions:
        parsed = ins.get("parsed")
        if not parsed or parsed.get("type") != "transfer":
            continue
        info = parsed.get("info", {})
        if info.get("destination") == target:
            received_lamports += int(info.get("lamports", 0))

    if received_lamports <= 0:
        return False, "No SOL transfer to the configured address was found."

    sol_amount = received_lamports / 1_000_000_000
    price = await get_coin_price_usd("Solana")
    if not price:
        return False, "Could not obtain the current SOL price."

    received_usd = sol_amount * price
    if received_usd + 0.01 < expected_usd * 0.995:
        return False, f"Received value is below the required amount ({money(received_usd)})."

    return True, f"Payment confirmed: approximately {money(received_usd)} received."


async def verify_payment(method: str, tx_hash: str, expected_usd: float):
    tx_hash = tx_hash.strip()
    if method in ("Bitcoin", "Litecoin"):
        return await verify_utxo_tx(method, tx_hash, expected_usd)
    if method == "Ethereum":
        return await verify_eth_tx(tx_hash, expected_usd)
    if method == "Tether USD (BSC)":
        return await verify_bsc_usdt_tx(tx_hash, expected_usd)
    if method == "Solana":
        return await verify_sol_tx(tx_hash, expected_usd)
    return False, "Unsupported payment method."


# ----------------------------- Ticket UI -----------------------------

ROBux_OPTIONS = [
    discord.SelectOption(label=f"{n:,} Robux", value=str(n))
    for n in range(5000, 125001, 5000)
]

PAYMENT_OPTIONS = [
    discord.SelectOption(label="Litecoin", emoji="🪙", value="Litecoin"),
    discord.SelectOption(label="Ethereum", emoji="◆", value="Ethereum"),
    discord.SelectOption(label="Tether USD (BSC)", emoji="💵", value="Tether USD (BSC)"),
    discord.SelectOption(label="Solana", emoji="◎", value="Solana"),
    discord.SelectOption(label="Bitcoin", emoji="₿", value="Bitcoin"),
]


class TicketStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.robux = None
        self.payment = None

    @discord.ui.select(
        placeholder="Select the Robux amount",
        min_values=1,
        max_values=1,
        options=ROBux_OPTIONS
    )
    async def robux_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.robux = int(select.values[0])
        await interaction.response.edit_message(view=self)

    @discord.ui.select(
        placeholder="Select a payment method",
        min_values=1,
        max_values=1,
        options=PAYMENT_OPTIONS
    )
    async def payment_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.payment = select.values[0]
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.primary, emoji="➡️")
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.robux or not self.payment:
            await interaction.response.send_message(
                "Please select both the Robux amount and payment method first.",
                ephemeral=True
            )
            return

        await create_ticket(interaction, self.robux, self.payment)


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="open_robux_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Choose your Robux amount and payment method:",
            view=TicketStartView(),
            ephemeral=True
        )


class OrderDetailsModal(discord.ui.Modal, title="Order Details"):
    roblox_username = discord.ui.TextInput(
        label="Roblox username",
        placeholder="Enter your Roblox username",
        required=True,
        max_length=32
    )
    robux_amount = discord.ui.TextInput(
        label="Robux purchased",
        placeholder="Example: 10000",
        required=True,
        max_length=12
    )

    async def on_submit(self, interaction: discord.Interaction):
        ticket = get_ticket(interaction.channel.id)
        if not ticket or ticket["user_id"] != interaction.user.id:
            await interaction.response.send_message(
                "This button can only be used by the ticket owner.",
                ephemeral=True
            )
            return

        try:
            amount = int(str(self.robux_amount.value).replace(",", "").replace(" ", ""))
        except ValueError:
            await interaction.response.send_message("Please enter a valid Robux amount.", ephemeral=True)
            return

        if amount != ticket["robux"]:
            await interaction.response.send_message(
                f"The ticket was created for **{ticket['robux']:,} Robux**. Please enter that exact amount.",
                ephemeral=True
            )
            return

        set_ticket(
            interaction.channel.id,
            roblox_username=str(self.roblox_username.value),
            order_robux=amount
        )

        embed = discord.Embed(
            title="Order Ready",
            description="The customer has submitted their Roblox order details.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Customer", value=interaction.user.mention)
        embed.add_field(name="Roblox Username", value=str(self.roblox_username.value))
        embed.add_field(name="Robux", value=f"{amount:,}")
        embed.set_footer(text="Please send the Robux to the customer.")

        await interaction.response.send_message(embed=embed)
        await interaction.channel.send(f"<@{OWNER_ID}> Order details are ready. Please process this order.")


class OrderDetailsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Submit Order Details", style=discord.ButtonStyle.success, emoji="📋", custom_id="submit_order_details")
    async def submit_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(OrderDetailsModal())


class TxHashModal(discord.ui.Modal, title="Submit Transaction Hash"):
    tx_hash = discord.ui.TextInput(
        label="Transaction hash",
        placeholder="Paste the transaction hash here",
        required=True,
        max_length=160
    )

    async def on_submit(self, interaction: discord.Interaction):
        ticket = get_ticket(interaction.channel.id)
        if not ticket or ticket["user_id"] != interaction.user.id:
            await interaction.response.send_message(
                "Only the ticket owner can submit the transaction hash.",
                ephemeral=True
            )
            return

        if ticket["payment_status"] == "confirmed":
            await interaction.response.send_message("This payment is already confirmed.", ephemeral=True)
            return

        tx = str(self.tx_hash.value).strip()
        set_ticket(interaction.channel.id, tx_hash=tx, payment_status="checking")

        await interaction.response.send_message(
            "Transaction hash received. I am checking the blockchain now..."
        )

        ok, message = await verify_payment(ticket["payment_method"], tx, ticket["price"])

        if ok:
            set_ticket(interaction.channel.id, payment_status="confirmed")
            embed = discord.Embed(
                title="Payment Confirmed",
                description=f"✅ {message}",
                color=discord.Color.green()
            )
            embed.add_field(name="Robux", value=f"{ticket['robux']:,}")
            embed.add_field(name="Transaction Hash", value=f"`{tx}`", inline=False)
            embed.set_footer(text="You can now submit your Roblox order details.")
            await interaction.channel.send(embed=embed, view=OrderDetailsView())
        else:
            set_ticket(interaction.channel.id, payment_status="awaiting_hash")
            embed = discord.Embed(
                title="Payment Not Confirmed",
                description=f"❌ {message}\n\nPlease check the transaction hash and try again.",
                color=discord.Color.red()
            )
            await interaction.channel.send(embed=embed)


class TxHashView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Submit Transaction Hash", style=discord.ButtonStyle.primary, emoji="🔗", custom_id="submit_tx_hash")
    async def submit_hash(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TxHashModal())


async def create_ticket(interaction: discord.Interaction, robux: int, payment: str):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
        return

    category = guild.get_channel(TICKET_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        await interaction.response.send_message(
            "The configured ticket category could not be found.",
            ephemeral=True
        )
        return

    # Prevent duplicate open ticket for the same user.
    existing = db.execute(
        "SELECT channel_id FROM tickets WHERE user_id=?",
        (interaction.user.id,)
    ).fetchall()

    for row in existing:
        ch = guild.get_channel(row["channel_id"])
        if ch:
            await interaction.response.send_message(
                f"You already have an open ticket: {ch.mention}",
                ephemeral=True
            )
            return

    price = robux_price(robux)
    address = PAYMENT_ADDRESSES[payment]
    coin_amount = await usd_to_coin(price, payment)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True
        ),
    }

    staff_role = guild.get_role(STAFF_ROLE_ID)
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True
        )

    channel = await guild.create_text_channel(
        name=f"ticket-{interaction.user.name.lower()[:16]}",
        category=category,
        overwrites=overwrites,
        reason="Robux purchase ticket"
    )

    db.execute("""
        INSERT INTO tickets(
            channel_id,user_id,robux,price,payment_method,payment_address,
            required_coin_amount,payment_status,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        channel.id,
        interaction.user.id,
        robux,
        price,
        payment,
        address,
        coin_amount,
        "awaiting_hash",
        datetime.now(timezone.utc).isoformat()
    ))
    db.commit()

    embed = discord.Embed(
        title="Robux Plus Order",
        description="Thanks for your order! Complete payment below and we'll get started right away.",
        color=discord.Color.blue()
    )
    embed.add_field(name="💰 Payment", value=(
        f"**Product:** {robux:,} Robux\n"
        f"**Price:** {money(price)}\n"
        f"**Payment Method:** {payment}"
    ), inline=False)
    embed.add_field(name=f"{payment} Address", value=f"`{address}`", inline=False)

    if coin_amount:
        embed.add_field(
            name="Amount to Send",
            value=f"**{format_coin(coin_amount, payment)}**\n"
                  f"Send the equivalent of **{money(price)}**.",
            inline=False
        )
    else:
        embed.add_field(
            name="Amount to Send",
            value=f"Send exactly **{money(price)}** worth of {payment}.",
            inline=False
        )

    embed.add_field(
        name="Next Step",
        value="Send the payment, then click **Submit Transaction Hash** and paste the transaction hash.",
        inline=False
    )
    embed.set_footer(text="Payment is verified automatically when the transaction is confirmed.")

    await channel.send(
        content=f"{interaction.user.mention} <@&{STAFF_ROLE_ID}>",
        embed=embed,
        view=TxHashView()
    )

    await interaction.response.send_message(
        f"Your ticket has been created: {channel.mention}",
        ephemeral=True
    )


# ----------------------------- Events -----------------------------

@bot.event
async def on_ready():
    init_db()
    bot.add_view(TicketPanelView())
    bot.add_view(TxHashView())
    bot.add_view(OrderDetailsView())

    try:
        synced = await bot.tree.sync()
        print(f"Logged in as {bot.user}")
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Command sync error: {e}")

    if not giveaway_loop.is_running():
        giveaway_loop.start()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    ticket = get_ticket(message.channel.id)

    # Exact vouch format:
    # +vouch @agressiioncult 10000
    if (
        message.channel.id == VOUCH_CHANNEL_ID
        and ticket
        and ticket["user_id"] == message.author.id
        and ticket["order_robux"]
        and ticket["vouch_sent"] == 0
    ):
        expected = f"+vouch <@{OWNER_ID}> {ticket['order_robux']}"
        # Accept either mention or plain owner username/id mention form.
        pattern = rf"^\+vouch\s+<@!?{OWNER_ID}>\s+{ticket['order_robux']}\s*$"

        if re.fullmatch(pattern, message.content.strip(), flags=re.IGNORECASE):
            set_ticket(message.channel.id, vouch_sent=1)
            await message.add_reaction("❤️")

            member = message.guild.get_member(message.author.id)
            if member:
                await add_customer_role(member)

            user = get_user(message.author.id)
            add_purchase(message.author.id, ticket["price"], ticket["order_robux"])
            user = get_user(message.author.id)

            if member:
                await update_rank_role(member, user["total_robux"])

            await asyncio.sleep(2)
            try:
                await message.channel.delete(reason="Vouch completed - ticket closed")
            except discord.Forbidden:
                pass
            return

    await bot.process_commands(message)


# ----------------------------- Slash Commands -----------------------------

@bot.tree.command(name="setup-ticket", description="Post the Robux Plus ticket panel.")
async def setup_ticket(interaction: discord.Interaction):
    if not is_staff(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    embed = discord.Embed(
        title="Robux Plus",
        description=(
            "Want to purchase Robux?\n\n"
            "Click the button below to open a ticket.\n"
            "You will select your Robux amount and payment method before the ticket is created."
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Robux Plus • Fast & secure orders")
    await interaction.channel.send(embed=embed, view=TicketPanelView())
    await interaction.response.send_message("Ticket panel posted.", ephemeral=True)


@bot.tree.command(name="close-ticket", description="Close the current ticket.")
async def close_ticket(interaction: discord.Interaction):
    if not is_staff(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    ticket = get_ticket(interaction.channel.id)
    if not ticket:
        await interaction.response.send_message("This channel is not a registered ticket.", ephemeral=True)
        return

    await interaction.response.send_message("Closing ticket in 3 seconds...")
    await asyncio.sleep(3)
    try:
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
    except discord.Forbidden:
        pass


@bot.tree.command(name="calc", description="Calculate the price of a Robux amount.")
@app_commands.describe(robux="Robux amount in 5,000 increments")
async def calc(interaction: discord.Interaction, robux: int):
    if not validate_robux(robux):
        await interaction.response.send_message(
            "Robux amount must be at least **5,000** and use **5,000 Robux increments**.",
            ephemeral=True
        )
        return

    price = robux_price(robux)
    rate = 9.00 if robux < 15000 else 8.80

    embed = discord.Embed(title="Robux Price Calculator", color=discord.Color.blue())
    embed.add_field(name="Robux", value=f"{robux:,}")
    embed.add_field(name="Rate", value=f"${rate:.2f} per 1,000")
    embed.add_field(name="Total", value=f"**{money(price)}**")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="add-balance", description="Add USD balance to a user.")
@app_commands.describe(user="User to receive balance", amount="USD amount")
async def add_balance(interaction: discord.Interaction, user: discord.Member, amount: float):
    if not is_staff(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
        return

    ensure_user(user.id)
    db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user.id))
    db.commit()
    new_balance = get_user(user.id)["balance"]

    await interaction.response.send_message(
        f"Added **{money(amount)}** to {user.mention}'s balance.\n"
        f"New balance: **{money(new_balance)}**"
    )


@bot.tree.command(name="use-balance", description="Use USD balance from a user.")
@app_commands.describe(user="User whose balance will be used", amount="USD amount")
async def use_balance(interaction: discord.Interaction, user: discord.Member, amount: float):
    if not is_staff(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
        return

    current = get_user(user.id)["balance"]
    if current < amount:
        await interaction.response.send_message(
            f"{user.mention} only has **{money(current)}** balance.",
            ephemeral=True
        )
        return

    db.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user.id))
    db.commit()
    new_balance = get_user(user.id)["balance"]

    await interaction.response.send_message(
        f"Used **{money(amount)}** from {user.mention}'s balance.\n"
        f"Remaining balance: **{money(new_balance)}**"
    )


@bot.tree.command(name="ban", description="Ban a user.")
@app_commands.describe(user="User to ban", reason="Reason for the ban")
async def ban_cmd(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_staff(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    try:
        await user.ban(reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"🔨 Banned {user.mention}\n**Reason:** {reason}")
    except discord.Forbidden:
        await interaction.response.send_message(
            "I cannot ban that user. Check my role position and Ban Members permission.",
            ephemeral=True
        )


@bot.tree.command(name="timeout", description="Timeout a user.")
@app_commands.describe(user="User to timeout", duration="Example: 10m, 2h, 1d", reason="Reason")
async def timeout_cmd(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str):
    if not is_staff(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    delta = parse_duration(duration)
    if not delta:
        await interaction.response.send_message(
            "Invalid duration. Use formats such as `10m`, `2h`, `1d` or `1w`.",
            ephemeral=True
        )
        return

    if delta > timedelta(days=28):
        await interaction.response.send_message("Discord timeouts cannot exceed 28 days.", ephemeral=True)
        return

    try:
        await user.timeout(delta, reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(
            f"⏱️ Timed out {user.mention} for **{duration}**.\n**Reason:** {reason}"
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "I cannot timeout that user. Check my role position and Moderate Members permission.",
            ephemeral=True
        )


@bot.tree.command(name="vouch", description="Send the vouch instructions in the current ticket.")
async def vouch_cmd(interaction: discord.Interaction):
    if not is_staff(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    ticket = get_ticket(interaction.channel.id)
    if not ticket or ticket["payment_status"] != "confirmed":
        await interaction.response.send_message(
            "This command can only be used in a ticket with a confirmed payment.",
            ephemeral=True
        )
        return

    if not ticket["roblox_username"] or not ticket["order_robux"]:
        await interaction.response.send_message(
            "The customer has not submitted their Roblox order details yet.",
            ephemeral=True
        )
        return

    expected = f"+vouch <@{OWNER_ID}> {ticket['order_robux']}"
    set_ticket(interaction.channel.id, vouch_expected=expected)

    embed = discord.Embed(
        title="Vouch Required",
        description=(
            "Thank you for your purchase! ❤️\n\n"
            "Please go to the vouch channel and send the following exact message:"
        ),
        color=discord.Color.blue()
    )
    embed.add_field(name="Vouch Message", value=f"```{expected}```", inline=False)
    embed.add_field(
        name="After Vouching",
        value="Once the correct message is detected, you will receive the Customer role and this ticket will close automatically.",
        inline=False
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="profile", description="View a customer profile.")
@app_commands.describe(user="Optional user to view")
async def profile_cmd(interaction: discord.Interaction, user: discord.Member | None = None):
    member = user or interaction.user
    data = get_user(member.id)
    rank_name, _ = rank_for_robux(data["total_robux"])

    if rank_name is None:
        rank_display = "No Robux rank yet"
        progress = f"{data['total_robux']:,} / 10,000 Robux"
        next_target = 10000
    elif rank_name == "10K+":
        rank_display = "10K+"
        progress = f"{data['total_robux']:,} / 20,000 Robux"
        next_target = 20000
    elif rank_name == "20K+":
        rank_display = "20K+"
        progress = f"{data['total_robux']:,} / 30,000 Robux"
        next_target = 30000
    else:
        rank_display = "30K+"
        progress = f"{data['total_robux']:,} Robux"
        next_target = None

    embed = discord.Embed(
        title=f"{member.display_name}'s Profile",
        description=f"**{rank_display}**",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=f"attachment://{LOGO_FILE}")
    embed.add_field(name="💰 Balance", value=money(data["balance"]), inline=True)
    embed.add_field(name="💵 Total Spent", value=money(data["total_spent"]), inline=True)
    embed.add_field(name="🪙 Robux Purchased", value=f"{data['total_robux']:,}", inline=True)
    embed.add_field(name="📦 Orders", value=str(data["orders"]), inline=True)
    embed.add_field(name="🏆 Rank", value=rank_display, inline=True)
    embed.add_field(name="📈 Progress", value=progress, inline=True)

    if next_target:
        pct = min(100, int(data["total_robux"] / next_target * 100))
        filled = max(0, min(10, pct // 10))
        bar = "█" * filled + "░" * (10 - filled)
        embed.add_field(name="Progress Bar", value=f"`{bar}` {pct}%", inline=False)
    else:
        embed.add_field(name="Progress Bar", value="`██████████` 100%", inline=False)

    embed.set_footer(text="Robux Plus")
    file = None
    if os.path.exists(LOGO_FILE):
        file = discord.File(LOGO_FILE, filename=LOGO_FILE)

    await interaction.response.send_message(embed=embed, file=file)


@bot.tree.command(name="giveaway", description="Start a giveaway.")
@app_commands.describe(
    prize="Giveaway prize",
    duration="Example: 10m, 2h, 1d",
    winners="Number of winners"
)
async def giveaway_cmd(interaction: discord.Interaction, prize: str, duration: str, winners: int):
    if not is_staff(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    if winners < 1 or winners > 50:
        await interaction.response.send_message("Winners must be between 1 and 50.", ephemeral=True)
        return

    delta = parse_duration(duration)
    if not delta or delta < timedelta(seconds=10):
        await interaction.response.send_message(
            "Invalid duration. Use something like `10m`, `2h`, or `1d`.",
            ephemeral=True
        )
        return

    end = datetime.now(timezone.utc) + delta

    embed = discord.Embed(
        title="🎉 Giveaway",
        description=f"**Prize:** {prize}\n\nReact with 🎉 to enter!",
        color=discord.Color.blue()
    )
    embed.add_field(name="Winners", value=str(winners))
    embed.add_field(name="Ends", value=f"<t:{int(end.timestamp())}:R>")
    embed.set_footer(text=f"Started by {interaction.user}")

    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("🎉")

    db.execute(
        "INSERT OR REPLACE INTO giveaways(message_id,channel_id,prize,winners,end_time) VALUES(?,?,?,?,?)",
        (msg.id, msg.channel.id, prize, winners, end.isoformat())
    )
    db.commit()


# ----------------------------- Giveaway loop -----------------------------

@tasks.loop(seconds=30)
async def giveaway_loop():
    rows = db.execute("SELECT * FROM giveaways WHERE ended=0").fetchall()
    now = datetime.now(timezone.utc)

    for row in rows:
        try:
            end = datetime.fromisoformat(row["end_time"])
        except Exception:
            continue

        if now < end:
            continue

        channel = bot.get_channel(row["channel_id"])
        if not channel:
            db.execute("UPDATE giveaways SET ended=1 WHERE message_id=?", (row["message_id"],))
            db.commit()
            continue

        try:
            msg = await channel.fetch_message(row["message_id"])
            users = []
            for reaction in msg.reactions:
                if str(reaction.emoji) == "🎉":
                    async for member in reaction.users():
                        if not member.bot:
                            users.append(member)

            # Unique users.
            unique = {m.id: m for m in users}
            pool = list(unique.values())

            if not pool:
                await channel.send("🎉 Giveaway ended, but there were no valid entries.")
            else:
                import random
                count = min(row["winners"], len(pool))
                winners = random.sample(pool, count)
                mentions = ", ".join(w.mention for w in winners)
                await channel.send(
                    f"🎉 **Giveaway ended!**\n"
                    f"**Prize:** {row['prize']}\n"
                    f"**Winner(s):** {mentions}"
                )

        except Exception as e:
            print(f"Giveaway error: {e}")

        db.execute("UPDATE giveaways SET ended=1 WHERE message_id=?", (row["message_id"],))
        db.commit()


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN environment variable is missing.")
    init_db()
    bot.run(TOKEN)
