import re
import io
import os
import sys

from dotenv import load_dotenv

load_dotenv()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, io.UnsupportedOperation):
        pass

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ==================================================
# CONFIG
# ==================================================

# Prefer the environment variable; fall back to inline for quick local runs.
# Set it before running:  export BOT_TOKEN="123456:ABC..."
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")

# Only respond inside these groups (set to empty list to allow anywhere).
# Comma-separated list from GROUP_IDS env var, or inline fallback.
_group_env = os.environ.get("GROUP_IDS") or os.environ.get("GROUP_ID")
if _group_env:
    GROUP_IDS = []
    for g in _group_env.split(","):
        g = g.strip()
        if g:
            try:
                GROUP_IDS.append(int(g))
            except ValueError:
                print(f"⚠️  Skipping invalid GROUP_ID value: {g!r}")
else:
    # Empty allow-list means respond in all groups where the bot is present.
    # Set GROUP_IDS in Render to restrict responses to specific group IDs.
    GROUP_IDS = []


def _is_allowed_group(chat_id):
    if not GROUP_IDS:
        return True
    return chat_id in GROUP_IDS

# Fraction of each level that goes to the B/S bet (rest goes to Number).
# Tuned to match the reference plan (~0.82).
BS_RATIO = 0.82


# ==================================================
# LEVEL PATTERN
# ==================================================

# Reference pattern from your ₹2,500 example
REFERENCE_4 = [47, 127, 322, 804]


def generate_level_totals(amount, levels):

    if amount <= 0:
        raise ValueError("Amount must be greater than 0")

    if levels <= 0:
        raise ValueError("Levels must be greater than 0")

    if amount < levels:
        raise ValueError(
            "Amount must be at least equal to number of levels"
        )

    # ----------------------------------------------
    # 1 LEVEL
    # ----------------------------------------------
    if levels == 1:
        return [amount]

    # ----------------------------------------------
    # 4 LEVELS
    # Exact same pattern as your ₹2,500 example
    # ----------------------------------------------
    if levels == 4:

        reference_total = sum(REFERENCE_4)

        raw = [
            amount * x / reference_total
            for x in REFERENCE_4
        ]

        totals = [int(x) for x in raw]

        remainder = amount - sum(totals)

        # Give rounding difference to last level
        totals[-1] += remainder

        return totals

    # ----------------------------------------------
    # OTHER LEVEL COUNTS
    #
    # Use a progressive pattern.
    # Higher levels receive progressively more.
    # ----------------------------------------------

    # Approximate progression ratio
    ratio = 2.5

    weights = [
        ratio ** i
        for i in range(levels)
    ]

    weight_sum = sum(weights)

    totals = [
        int(amount * w / weight_sum)
        for w in weights
    ]

    # Ensure every level has at least ₹1
    for i in range(levels):
        if totals[i] < 1:
            totals[i] = 1

    # Fix rounding difference
    difference = amount - sum(totals)

    totals[-1] += difference

    return totals


# ==================================================
# B/S + NUMBER SPLIT
# ==================================================

def split_level(level_amount):

    # B/S share (tuned to ~0.82 to match the reference plan)
    bs = round(level_amount * BS_RATIO)

    # Remaining amount goes to Number
    number = level_amount - bs

    return bs, number


# ==================================================
# CREATE PLAN
# ==================================================

def create_plan(amount, levels):

    level_totals = generate_level_totals(
        amount,
        levels
    )

    plan = []

    for i, total in enumerate(level_totals, start=1):

        bs, number = split_level(total)

        plan.append({
            "level": i,
            "bs": bs,
            "number": number,
            "total": total
        })

    # Final safety check
    calculated_total = sum(
        x["total"] for x in plan
    )

    if calculated_total != amount:
        raise ValueError(
            f"Calculation error: "
            f"{calculated_total} != {amount}"
        )

    return plan


# ==================================================
# RENDER PLAN AS IMAGE (like the attached table)
# ==================================================

def render_plan_image(amount, levels, plan):
    """Render the plan as a clean table PNG and return it as bytes."""

    def rupee(value):
        return f"\u20b9{value:,}"

    columns = ["Level", "B/S Bet", "Number Bet", "Level Total"]

    rows = []
    for row in plan:
        rows.append([
            str(row["level"]),
            rupee(row["bs"]),
            rupee(row["number"]),
            rupee(row["total"]),
        ])

    total = sum(x["total"] for x in plan)

    # Total summary row (only Level column label + Level Total value)
    rows.append(["Total", "", "", rupee(total)])

    n_rows = len(rows)

    # Figure sizing scales with number of rows
    fig_height = 1.0 + 0.6 * (n_rows + 1)
    fig, ax = plt.subplots(figsize=(8, fig_height), dpi=200)
    ax.axis("off")

    table = ax.table(
        cellText=rows,
        colLabels=columns,
        cellLoc="left",
        colLoc="left",
        loc="center",
    )

    table.auto_set_font_size(False)
    table.set_fontsize(15)
    table.scale(1, 2.0)

    header_color = "#111111"
    line_color = "#e6e6e6"

    # Style every cell: remove vertical borders, keep light horizontal rules
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(line_color)
        cell.set_linewidth(0)
        cell.PAD = 0.04

        # Draw only bottom horizontal line
        cell.visible_edges = "B"

        # Header row
        if r == 0:
            cell.set_text_props(weight="bold", color=header_color)
            cell.set_linewidth(1.0)
        else:
            cell.set_text_props(color="#222222")
            cell.set_linewidth(0.8)

        # Total row (last row)
        if r == n_rows:
            cell.set_text_props(weight="bold", color=header_color)

    fig.suptitle(
        f"{rupee(amount)}  \u2014  {levels} Levels",
        x=0.12,
        y=0.98,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )

    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        bbox_inches="tight",
        facecolor="white",
        pad_inches=0.3,
    )
    plt.close(fig)
    buffer.seek(0)
    return buffer


# ==================================================
# CAPTION (text summary under the photo)
# ==================================================

def format_caption(amount, levels, plan):

    total_bs = sum(x["bs"] for x in plan)
    total_number = sum(x["number"] for x in plan)
    total = sum(x["total"] for x in plan)

    progression = " \u2192 ".join(
        f"\u20b9{x['total']:,}" for x in plan
    )

    lines = [
        f"\U0001f4b0 \u20b9{amount:,} \u2014 {levels} Levels",
        f"Total B/S: \u20b9{total_bs:,}",
        f"Total Number: \u20b9{total_number:,}",
        f"Total: \u20b9{total:,}",
        f"\U0001f4c8 Progression: {progression}",
    ]

    return "\n".join(lines)


def render_plan_text(amount, levels, plan):
    """Render the plan as a monospace text table for Telegram Markdown code block."""

    def rupee(value):
        return f"\u20b9{value:,}"

    headers = ["Level", "B/S Bet", "Number Bet", "Level Total"]
    rows = [
        [
            str(row["level"]),
            rupee(row["bs"]),
            rupee(row["number"]),
            rupee(row["total"]),
        ]
        for row in plan
    ]

    total = sum(x["total"] for x in plan)
    rows.append(["Total", "", "", rupee(total)])

    widths = [
        max(len(headers[c]), max(len(r[c]) for r in rows))
        for c in range(len(headers))
    ]

    def fmt(cols):
        return "  ".join(
            cols[c].rjust(widths[c]) if c else cols[c].ljust(widths[c])
            for c in range(len(cols))
        )

    sep = "-+-".join("-" * w for w in widths)
    sep = "  ".join("-" * w for w in widths)

    lines = [fmt(headers), sep]
    for r in rows:
        lines.append(fmt(r))

    table = "\n".join(lines)
    caption = format_caption(amount, levels, plan)

    return (
        f"```\n{table}\n```\n\n{caption}"
    )


# ==================================================
# TELEGRAM COMMAND
# ==================================================

HELP_TEXT = (
    "\U0001f4b0 *Betting Plan Bot*\n\n"
    "Send a command in the format:\n"
    "`/<amount>,<levels>`\n\n"
    "Examples:\n"
    "`/1300,4`\n"
    "`/2500,4`\n"
    "`/1000,2`\n\n"
    "You can also use a space instead of a comma: `/1300 4`\n"
    "The bot replies with the plan as a table image."
)

async def handle_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if chat.type in {"group", "supergroup"} and not _is_allowed_group(chat.id):
        return
    await msg.reply_text(HELP_TEXT, parse_mode="Markdown")


async def handle_plan(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or not msg.text:
        return

    if chat.type in {"group", "supergroup"} and not _is_allowed_group(chat.id):
        return

    text = msg.text.strip()

    match = re.fullmatch(
        r"/(\d+)\s*[,\s]\s*(\d+)(?:@\w+)?",
        text
    )

    if not match:
        await msg.reply_text(
            "\u274c Invalid format. Use `/<amount>,<levels>` "
            "e.g. `/1300,4`",
            parse_mode="Markdown",
        )
        return

    amount = int(match.group(1))
    levels = int(match.group(2))

    try:

        plan = create_plan(amount, levels)

        image = render_plan_image(amount, levels, plan)
        caption = format_caption(amount, levels, plan)

        await msg.reply_photo(
            photo=image,
            caption=caption,
        )

    except Exception as e:

        await msg.reply_text(
            f"\u274c {str(e)}"
        )


# ==================================================
# BOT
# ==================================================

def main():

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help"], handle_start))

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^/\d+\s*[,\s]\s*\d+(?:@\w+)?$"),
            handle_plan,
        )
    )

    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        print(
            "\u26a0\ufe0f  BOT_TOKEN is not set or empty. "
            "Set it via `set BOT_TOKEN=...` (Windows) or edit the .env file."
        )
        sys.exit(1)

    print("\u2705 Plan Bot Running...")

    app.run_polling()


if __name__ == "__main__":
    main()
