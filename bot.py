import os
import discord
from discord.ext import commands
from discord import app_commands

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")

OWNER_ID = 1453135839688265974
STAFF_ROLE_ID = 1549541686030635058
TICKET_CATEGORY_ID = 1549782404863102986
VOUCH_CHANNEL_ID = 1549539937479688222

PAYMENT_ADDRESSES = {
    "Litecoin (LTC)": os.getenv("LTC_ADDRESS"),
    "Bitcoin (BTC)": os.getenv("BTC_ADDRESS"),
    "Ethereum (ETH)": os.getenv("ETH_ADDRESS"),
    "Tether USD (USDT - BSC)": os.getenv("USDT_ADDRESS"),
    "Solana (SOL)": os.getenv("SOL_ADDRESS"),
}

# =========================
# DISCORD SETUP
# =========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# PRICE CALCULATION
# =========================

def calculate_price(robux: int):

    if robux < 5000:
        return None

    if robux % 5000 != 0:
        return None

    thousands = robux // 1000

    if robux <= 10000:
        price = thousands * 9
    else:
        price = thousands * 8.8

    return price


# =========================
# TICKET PANEL
# =========================

class TicketPanel(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Create Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="create_ticket"
    )
    async def create_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = interaction.guild

        category = guild.get_channel(TICKET_CATEGORY_ID)

        if category is None:
            await interaction.response.send_message(
                "❌ Ticket category was not found.",
                ephemeral=True
            )
            return

        # Prevent multiple tickets
        for channel in category.text_channels:
            if channel.topic == f"ticket:{interaction.user.id}":
                await interaction.response.send_message(
                    f"❌ You already have a ticket: {channel.mention}",
                    ephemeral=True
                )
                return

        staff_role = guild.get_role(STAFF_ROLE_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        }

        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            topic=f"ticket:{interaction.user.id}",
            overwrites=overwrites
        )

        await interaction.response.send_message(
            f"✅ Your ticket has been created: {channel.mention}",
            ephemeral=True
        )

        embed = discord.Embed(
            title="🛒 Robux Plus Order",
            description=(
                "Thanks for your order! Complete the steps below "
                "and we'll get started right away.\n\n"
                "Click the button below to start your order."
            ),
            color=discord.Color.blurple()
        )

        await channel.send(
            content=interaction.user.mention,
            embed=embed,
            view=OrderStartView()
        )


# =========================
# ORDER START
# =========================

class OrderStartView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Start Order",
        emoji="🛒",
        style=discord.ButtonStyle.success,
        custom_id="start_order"
    )
    async def start_order(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            RobuxAmountModal()
        )


class RobuxAmountModal(discord.ui.Modal, title="Robux Order"):

    robux = discord.ui.TextInput(
        label="How many Robux do you want?",
        placeholder="Example: 5000",
        required=True,
        min_length=1,
        max_length=10
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        try:
            amount = int(self.robux.value.replace(",", ""))
        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a valid number.",
                ephemeral=True
            )
            return

        price = calculate_price(amount)

        if price is None:
            await interaction.response.send_message(
                "❌ Robux must be at least 5,000 and "
                "must be purchased in 5,000 Robux steps.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "💎 Select your payment method below.",
            view=PaymentMethodView(amount, price),
            ephemeral=True
        )


# =========================
# PAYMENT METHOD
# =========================

class PaymentMethodSelect(discord.ui.Select):

    def __init__(self, amount, price):

        self.amount = amount
        self.price = price

        options = [
            discord.SelectOption(
                label="Litecoin",
                description="Pay with Litecoin",
                emoji="🪙",
                value="Litecoin (LTC)"
            ),
            discord.SelectOption(
                label="Bitcoin",
                description="Pay with Bitcoin",
                emoji="₿",
                value="Bitcoin (BTC)"
            ),
            discord.SelectOption(
                label="Ethereum",
                description="Pay with Ethereum",
                emoji="♦️",
                value="Ethereum (ETH)"
            ),
            discord.SelectOption(
                label="Tether USD - BSC",
                description="Pay with USDT on BNB Smart Chain",
                emoji="💵",
                value="Tether USD (USDT - BSC)"
            ),
            discord.SelectOption(
                label="Solana",
                description="Pay with Solana",
                emoji="🟣",
                value="Solana (SOL)"
            )
        ]

        super().__init__(
            placeholder="Select your payment method",
            options=options,
            custom_id="payment_method"
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        method = self.values[0]
        address = PAYMENT_ADDRESSES.get(method)

        if not address:
            address = "Payment address is not configured yet."

        embed = discord.Embed(
            title="💰 Payment",
            description=(
                "Thanks for your order! Complete payment below "
                "and we'll get started right away.\n\n"
                "**Robux Plus Order**\n\n"
                f"**Product:** {self.amount:,} Robux\n\n"
                f"**Price:** ${self.price:.2f}\n\n"
                f"**Payment Method:** {method}\n\n"
                f"**{method} Address:**\n"
                f"`{address}`\n\n"
                f"Send exactly **${self.price:.2f} USD worth of "
                f"{method.split('(')[0].strip()}** to this address.\n\n"
                "🔗 After sending the payment, click the button "
                "below and submit your transaction hash."
            ),
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=TransactionView(self.amount, self.price, method)
        )


class PaymentMethodView(discord.ui.View):

    def __init__(self, amount, price):
        super().__init__(timeout=300)
        self.add_item(
            PaymentMethodSelect(amount, price)
        )


# =========================
# TRANSACTION HASH
# =========================

class TransactionView(discord.ui.View):

    def __init__(self, amount, price, method):
        super().__init__(timeout=None)

        self.amount = amount
        self.price = price
        self.method = method

    @discord.ui.button(
        label="Submit Transaction Hash",
        emoji="🔗",
        style=discord.ButtonStyle.primary,
        custom_id="submit_transaction"
    )
    async def transaction(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            TransactionHashModal(
                self.amount,
                self.price,
                self.method
            )
        )


class TransactionHashModal(
    discord.ui.Modal,
    title="Transaction Verification"
):

    transaction_hash = discord.ui.TextInput(
        label="Transaction Hash",
        placeholder="Paste your transaction hash here",
        required=True,
        min_length=10,
        max_length=200
    )

    def __init__(self, amount, price, method):

        super().__init__()

        self.amount = amount
        self.price = price
        self.method = method

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        tx_hash = self.transaction_hash.value.strip()

        # Blockchain verification will be connected here.
        # For now we save the submitted hash in the ticket.

        embed = discord.Embed(
            title="🔎 Payment Verification",
            description=(
                "Your transaction hash has been submitted.\n\n"
                f"**Payment Method:** {self.method}\n"
                f"**Robux:** {self.amount:,}\n"
                f"**Price:** ${self.price:.2f}\n\n"
                f"**Transaction Hash:**\n`{tx_hash}`\n\n"
                "⏳ Your payment is being verified."
            ),
            color=discord.Color.orange()
        )

        await interaction.response.send_message(
            embed=embed
        )


# =========================
# ORDER DETAILS
# =========================

class OrderDetailsView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Enter Order Details",
        emoji="📝",
        style=discord.ButtonStyle.success,
        custom_id="order_details"
    )
    async def details(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            OrderDetailsModal()
        )


class OrderDetailsModal(
    discord.ui.Modal,
    title="Robux Delivery"
):

    username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Your Roblox username",
        required=True,
        max_length=50
    )

    robux = discord.ui.TextInput(
        label="Robux Purchased",
        placeholder="Example: 5000",
        required=True,
        max_length=10
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)

        ping = (
            f"<@{OWNER_ID}>"
            if staff_role is None
            else f"<@{OWNER_ID}> {staff_role.mention}"
        )

        embed = discord.Embed(
            title="📦 Order Ready for Delivery",
            description=(
                f"**Roblox Username:** `{self.username.value}`\n"
                f"**Robux Purchased:** `{self.robux.value}`\n\n"
                "Please deliver the Robux to the customer."
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(
            content=ping,
            embed=embed
        )


# =========================
# VOUCH COMMAND
# =========================

@bot.tree.command(
    name="vouch",
    description="Request a vouch from the customer."
)
async def vouch(interaction: discord.Interaction):

    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ You are not allowed to use this command.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="⭐ Leave a Vouch",
        description=(
            "Thank you for your purchase!\n\n"
            "Please leave a vouch in the designated vouch channel "
            "using the exact sentence below:\n\n"
            "**`Bought Robux from @YourName!`**\n\n"
            "❤️ Once your vouch is verified, this ticket will "
            "automatically close."
        ),
        color=discord.Color.pink()
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================
# SETUP TICKET PANEL
# =========================

@bot.tree.command(
    name="setup-ticket",
    description="Create the Robux ticket panel."
)
async def setup_ticket(
    interaction: discord.Interaction
):

    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ You are not allowed to use this command.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🛒 Robux Plus",
        description=(
            "Thanks for choosing Robux Plus!\n\n"
            "Click **Create Ticket** below to place an order.\n\n"
            "You will be asked for your Robux amount and "
            "preferred payment method."
        ),
        color=discord.Color.blurple()
    )

    await interaction.channel.send(
        embed=embed,
        view=TicketPanel()
    )

    await interaction.response.send_message(
        "✅ Ticket panel created.",
        ephemeral=True
    )


# =========================
# READY
# =========================

@bot.event
async def on_ready():

    print(f"Logged in as {bot.user}")

    bot.add_view(TicketPanel())
    bot.add_view(OrderStartView())

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as error:
        print(f"Slash command sync error: {error}")


# =========================
# START BOT
# =========================

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing."
    )

bot.run(TOKEN)
